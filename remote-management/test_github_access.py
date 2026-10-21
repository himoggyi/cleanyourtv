"""Permission evidence must never be promoted into device execution evidence."""
import json
import subprocess
import unittest
from github_access import probe_ci


class GitHubAccessTests(unittest.TestCase):
    def probe(self, responses):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertEqual(kwargs['timeout'], 20)
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return subprocess.CompletedProcess(args, value[0], json.dumps(value[1]), '')
        return probe_ci(run), calls

    def prefix(self):
        return [(0, {'id': 143339177}), (0, {'workflows': [
            {'path': '.github/workflows/ci.yml', 'state': 'active'}]})]

    def test_read_access_does_not_prove_write(self):
        report, calls = self.probe(self.prefix() + [(1, {'status': '403'})])
        self.assertEqual(report['dispatch'], 'rejected')
        self.assertEqual(report['http_status'], 403)
        self.assertEqual(calls[-1][2:4], ['--method', 'POST'])
        self.assertEqual(report['free_task_channel'], 'not_verified')

    def test_ci_acceptance_is_not_device_success(self):
        report, _ = self.probe(self.prefix() + [(0, {})])
        self.assertEqual(report['dispatch'], 'accepted')
        self.assertEqual(report['device_execution'], 'unverified')
        self.assertFalse(report['relay_deployed'])
        self.assertEqual(report['free_task_channel'], 'not_verified')

    def test_wrong_owner_never_dispatches(self):
        report, calls = self.probe([(0, {'id': 1})])
        self.assertEqual(report['dispatch'], 'not_attempted')
        self.assertEqual(len(calls), 1)

    def test_missing_workflow_never_dispatches(self):
        report, calls = self.probe([(0, {'id': 143339177}), (0, {'workflows': []})])
        self.assertEqual(report['dispatch'], 'not_attempted')
        self.assertEqual(len(calls), 2)

    def test_timeout_after_post_is_ambiguous_and_not_retried(self):
        report, calls = self.probe(self.prefix() + [subprocess.TimeoutExpired('gh', 20)])
        self.assertEqual(report['dispatch'], 'outcome_unknown')
        self.assertEqual(len(calls), 3)

    def test_server_error_is_not_definitive_rejection(self):
        report, calls = self.probe(self.prefix() + [(1, {'status': '503'})])
        self.assertEqual(report['dispatch'], 'outcome_unknown')
        self.assertEqual(len(calls), 3)

    def test_bad_metadata_never_dispatches(self):
        report, calls = self.probe([(0, [] )])
        self.assertEqual(report['dispatch'], 'not_attempted')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()

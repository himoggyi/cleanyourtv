import tempfile
from pathlib import Path
import unittest
from configure_github import prepare


class GitHubPreparationTests(unittest.TestCase):
    def test_no_token_is_explicitly_unpairable_and_existing_key_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "private"
            info = prepare(target, "x5pro")
            self.assertFalse(info["pairing_ready"])
            self.assertFalse(info["device_tasks_enabled"])
            self.assertTrue((target / "pairing-template.INVALID.json").exists())
            self.assertFalse((target / "pairing.json").exists())
            self.assertEqual((target / "task-private.pem").stat().st_mode & 0o777, 0o600)
            before = (target / "task-private.pem").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare(target, "x5pro")
            self.assertEqual((target / "task-private.pem").read_bytes(), before)

    def test_refuses_material_inside_git_and_test_device(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "repo"
            repo.mkdir(); (repo / ".git").mkdir(); (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            with self.assertRaises(ValueError):
                prepare(repo / "private", "x5pro")
            with self.assertRaises(ValueError):
                prepare(Path(folder) / "private", "cloud-probe")


if __name__ == "__main__":
    unittest.main()

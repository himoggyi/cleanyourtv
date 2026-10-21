# Current wallpaper rollout verification — 2026-10-21

Continued from the existing local prototype `00b5ec5`; it was not rewritten from scratch.

| Requested stage | Evidence | Actual status |
| --- | --- | --- |
| Installed APK signature compatibility | Actual projector base.apk is not available; no ADB/VPN/device session exists | **UNVERIFIED; do not install yet** |
| Local APK signing continuity | Android 9 apksigner verification + package/certificate/version gate, local release 6 → remote 7 → rescue 8 | Passed for LOCAL BUILD REFERENCES ONLY, not the installed projector |
| JPG/PNG upload | Normalize/strip metadata, bounded decode, immutable device-scoped storage, signed hash descriptor, native HTTPS downloader/private atomic files | Implemented and compiled; physical Android decoder/path still needs device acceptance |
| Persistent HTTPS queue | SQLite WAL queue, durable assets, WSGI/Gunicorn, systemd/Caddy | Code/config complete; **not publicly deployed** |
| Actions permission | Actual POST to existing CI workflow repeated in this turn | **403 Resource not accessible by integration**; no dispatch created; outside grant still required |
| Publish source branch | Actual push of the completed local prototype branch repeated in this turn | **403 permission denied**; no branch or PR was published |
| Android builds | release, remote, rescue compile + lint + APK assembly | Passed; no APK installed |
| End-to-end | Real TLS upload → simulated Actions signer → broker restart → verified asset download → simulated-device file/preferences → persistent receipt | Passed **with an explicitly simulated device**; not a real projector E2E result |

Automated checks:

- **27 remote Python tests passed** with pinned Pillow 13.0.0 / Gunicorn 26.2.0. Includes actual Gunicorn startup with two workers, independent upload/read/write/device permissions, MIME/corrupt/animated/bomb/size rejection, EXIF removal, transparent PNG handling, image descriptor binding, task IDs, delegated-environment rejection before accessing a key/network, TLS certificate rejection/trusted-test-CA success, queue restart, immutable receipts and update refusal on mismatched APK identities.
- Existing repository suite: **120 run, 119 passed, 1 skipped** by the original non-main rule.
- Each Android variant ran the same **124 existing JVM tests**, all passed. These do **not** exercise the new service on Android hardware and are not 372 distinct native-path tests.
- All three lint tasks: **0 errors**; release/rescue 62 warnings, remote 73. Additional prototype warnings include UI localization, package visibility and the frame evidence preferences write. No new lint baseline suppresses errors.
- Official Caddy 2.11.7 Linux archive verified against its published **SHA-512**, and `caddy adapt` accepted the supplied configuration. This did not obtain a certificate or start a public service.
- APK manifest inspection confirmed INTERNET and RemoteTaskService **only in remote**; release/rescue have neither. None requests REQUEST_INSTALL_PACKAGES.
- Default release is **416,067 bytes**, within the unchanged 430,080-byte limit; remote **460,119 bytes**, rescue **416,083 bytes**.
- `apk_guard.py` verified signatures for Android SDK 28. All local APKs share certificate SHA-256 `f746475e2a6e5fb26146ee00d03fd274591e190a81965ad16dbce29182debff4`; this is the local debug certificate, not a claimed projector certificate.

Current artifact SHA-256:

```text
release 164b76e07addfea9f7ed82a4208bfba6df129ab531b1022b147e8dc2dd5f0524
remote  4e4e6c50f1e5397f482e0ebe18f509dde7b0312dd3164a9be49d0ec7dcc1506f
rescue  7e519ae5c262968439b1a20893a7a477f82243e2e2cfdddfbdd22ebacb14a0e5
```

Remaining owner actions are consolidated in [DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md): actual APK extraction/key match, server/domain approval and deployment, single-repository Actions-write credential and reviewed workflow publication, then local update/pairing and real wallpaper verification.
No existing desktop was uninstalled, no data was cleared, no factory launcher/HOME changed, no public ADB enabled, and no credentials were committed.

---

# Historical phase-1 verification — local commit 00b5ec5

Base repository: `himoggyi/cleanyourtv`, commit `a6996036102f9c84f1f6e19ac51164fa1e83a30c`.
Work is on the **local** branch `codex/projector-remote-prototype`.

## Actual cloud interface checks

- Connected GitHub identity: `himoggyi`, numeric user ID `143339177`.
- Managed-environment HTTP policy file permits outbound HTTPS; network-enabled commands are needed for sockets in this workspace.
- `gh auth status`: authenticated successfully after giving the command network access. Initial sandbox failures were not evidence of an invalid credential.
- GitHub REST GET workflow list: succeeded, found active `.github/workflows/ci.yml`, workflow ID `391462210`.
- Actual `POST /repos/himoggyi/cleanyourtv/actions/workflows/ci.yml/dispatches`, ref `main`: **403, Resource not accessible by integration**. This was an attempt to run existing CI only, without any projector task. No workflow run was created by this request.
- Actual Git push of prototype branch: **403, permission denied**.
- Connected GitHub create-branch tool: **403, Resource not accessible by integration**.
- The repository metadata's reported owner/admin permissions did **not** prove that the integration token had the required write permissions.
- `dispatch.py --probe`: correctly stops without making a request when the separately configured `PROJECTOR_GITHUB_TOKEN` is absent.

Conclusion: this session has a real authenticated REST/CLI transport but **cannot currently dispatch Actions tasks or publish this branch**. No task relay is deployed. Future activation requires the GitHub integration's corresponding write grant or an appropriately scoped securely configured token, plus an HTTPS queue and device pairing. The connector's available Issue tools have not been validated as a task trigger and are not used to circumvent these restrictions.

## Tests performed locally

- New protocol/relay/broker tests: **10 passed** using Python 3.12 and OpenSSL. Includes owner ID/event/rerun checks, signature tampering, expiry/skew, strict schemas, path and command injection, device isolation, persistent queue reopen, ID collisions, immutable receipts, and a real loopback HTTP simulated-device round trip.
- Existing repository Python suite: **120 run, 119 passed, 1 skipped** by the repository's default non-main count-check rule. Tests that open loopback sockets needed the same per-command network access; their initial sandbox errors went away with that access.
- Python compilation and Android Manifest XML parsing: passed.
- Android source compilation: passed with the official Temurin JDK 17 (download SHA-256 verified), SDK 34 and build-tools 34.0.0 (Google archive checksums verified).
- Android JVM unit tests: **124 passed, 0 failures/errors/skips** across 16 suites. These are existing pure JVM tests, not on-device tests of the new service.
- Final build command succeeded: `testReleaseUnitTest lintRelease assembleRelease testRemoteUnitTest lintRemote assembleRemote`.
- Ordinary release: **415,555 bytes**, below the existing 430,080-byte (420 KiB) gate. APK permission inspection confirms **no INTERNET permission**.
- Opt-in remote prototype: **458,383 bytes**. Remote source/manifest live under `launcher/app/src/remote/`; only this variant has the remote screen, services, network and boot permissions. No default size limit was relaxed.
- Both variants ran **124 JVM tests each**, all passed. These overlap: they are not 248 distinct tests of the remote service.
- Both lint tasks passed with **0 errors**. Ordinary release has 61 warnings, remote has 72; additional prototype warnings concern UI localization and Android 11 package visibility (this task targets Android 9). They are not suppressed by a new lint baseline.
- Build setup required a writable Android user directory, a complete JDK and the environment's existing Java CA trust store; TLS verification stayed enabled throughout. Missing optional platform-tools/metrics produced environment warnings; no ADB was installed or used.

Build artifact SHA-256 values (existing debug signing mechanism; **not a trusted owner release**):

```text
release f3d7021e98a9ab9b3d1ae804cda2fb4ac9806022ccf7a77362311321d19d2f5b
remote  9e53ca00f5966e5fea1dfc03106d8567c1272ea42530c4804bff8d106ec1f0ae
```

## Not performed

- No projector/ADB connection; no network scan of the home; no public port or router changes.
- No APK install, uninstall, system package disable, HOME switch, device reset or reboot.
- No real Android 9 execution, pairing, reboot/force-stop/Doze, live wallpaper/layout redraw or process-interruption acceptance test.
- No public broker deployment, cloud resource purchase, GitHub Secrets/Environment/branch protection configuration, remote branch or PR creation.
- APK download, verification catalog and install approval are designed but deliberately **not implemented/enabled**. Both relay and Android allowlists reject `install_apk`.

The Android source implements an opt-in resident execution path; successful compilation alone would not prove X5 Pro firmware behavior. Python's simulated receipt is not an Android device receipt. Source/review artifacts must not be described as an already installed or operational system.

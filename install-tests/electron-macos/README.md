# macOS Electron installation testing (Tart VM)

This directory contains the current Tart tooling for testing the macOS Electron installation path. The full clean-room field-test procedure is owned by [the shared field-testing skill](../../.agents/skills/field-testing/SKILL.md); [NON_DEVELOPER_FIELD_TEST.md](NON_DEVELOPER_FIELD_TEST.md) adds only signed-DMG-specific entry and completion gates.

The retired in-guest standalone-Tailscale harness is intentionally gone. It exercised an obsolete onboarding contract and duplicated the shared field-test procedure.

## Why a VM

Desktop onboarding runs the real `openbase-coder setup --json-progress` without `--skip-services`. It registers fixed launchd labels, configures phone-access networking, and binds ports 7999 and 7880. A disposable macOS VM is the safe, production-faithful isolation boundary; changing only `$HOME` is not enough.

## Current paths

### Signed-DMG field test

Start a visible bare clone, then follow [NON_DEVELOPER_FIELD_TEST.md](NON_DEVELOPER_FIELD_TEST.md) and the shared field-testing skill:

```bash
./install-tests/electron-macos/manual-vm.sh \
  --source <maintained-sip-enabled-source> \
  --name <run-specific-name> \
  --display 1600x900pt
```

Use the public Openbase downloads page inside the guest and install the signed, notarized DMG through Finder and Gatekeeper. A signed build offers Openbase VPN and Openbase Direct; a standalone Tailscale choice is a release defect.

### Local developer build

For a developer-flow field test or a targeted diagnostic, build the real bundled app on the host and place it into a fresh bare clone:

```bash
./install-tests/electron-macos/build-app.sh
./install-tests/electron-macos/manual-vm.sh \
  --app desktop/release/mac-arm64/Openbase.app \
  --source <maintained-sip-enabled-source> \
  --name <run-specific-name> \
  --display 1600x900pt
```

`build-app.sh` needs the desktop/CLI toolchain: Xcode, Go, uv, pnpm, Node 20 or newer, and a local `livekit-server` binary. `manual-vm.sh` itself needs only Tart and `sshpass`.

## VM lifecycle

Keep the just-tested disposable VM after a traditional field test so immediate targeted follow-ups can reuse the exact observed state. A follow-up on that retained VM is debugging evidence, not a second clean-room field test. Immediately before a later request needs a new clone, run `tart list`, delete one or more stale disposable field-test clones, and preserve maintained golden/source images plus any VM still needed for active evidence. Then create the new clone. This keeps fast follow-ups possible without accumulating old VMs or hitting Tart's concurrent-VM limit.

## Semantic guest control

Images stay pure: automation is host-side or injected into the disposable clone. Install the host driver once with `npm install --no-audit` in `install-tests/electron-macos/driver`, then use:

```bash
./install-tests/electron-macos/guest-automate.sh pin-layout <vm>
./install-tests/electron-macos/guest-automate.sh enable-safaridriver <vm>
./install-tests/electron-macos/guest-automate.sh safari-tunnel <vm> 4444
node install-tests/electron-macos/driver/host-drive.mjs --wd http://127.0.0.1:4444 snapshot

./install-tests/electron-macos/guest-automate.sh app-cdp <vm>
node install-tests/electron-macos/driver/host-drive.mjs --cdp http://127.0.0.1:9222 snapshot
```

Do not paste text through the Tart window. Command-V can insert only a literal `v`, and shifted or option characters can be corrupted. Use the semantic endpoints for text and forms; use the visible Tart window for Finder, Gatekeeper, System Settings, and macOS permission dialogs.

Before bringing Tart to the foreground, follow the shared skill's audible foreground notice. Perform every disposable-VM confirmation yourself. As soon as foreground-only work is done, send the corresponding audible release notice.

## Files

```text
electron-macos/
  README.md
  NON_DEVELOPER_FIELD_TEST.md  # signed-DMG-specific field-test additions
  build-app.sh                 # build a bundled local developer app
  manual-vm.sh                 # clone and boot a visible bare VM
  guest-automate.sh            # host-side SSH, SafariDriver, and CDP helpers
  driver/
    host-drive.mjs             # semantic Safari/Electron driver
    package.json               # Playwright dependency for host-drive.mjs
  images/                      # screenshots used by the signed-DMG runbook
```

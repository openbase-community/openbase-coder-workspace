# macOS Electron installation tests (Tart VM)

There are two distinct tracks:

- This file documents the developer/local-build harness that automatically verifies Prerequisites → Setup in a disposable VM.
- [NON_DEVELOPER_FIELD_TEST.md](NON_DEVELOPER_FIELD_TEST.md) documents the signed-DMG, clean-room field test through OAuth, Openbase VPN, physical-iPhone pairing, acoustic dispatcher response, Desktop permission, and a real Super Agent.

Tests the **macOS Electron app installation flow** — build the real bundled
`Openbase Coder.app`, install it to `/Applications`, launch it, click through
onboarding to run setup, and verify the resulting install — inside a **disposable
macOS VM** ([Tart](https://tart.run)). Each run happens in a throwaway VM clone,
so your real machine's install, launchd services, Tailscale routes, and ports
7999/7880 are never touched.

## Why a VM (and not a sandboxed `$HOME` like the `install.sh` test)

The desktop onboarding runs the real `openbase-coder setup --json-progress`
(see `desktop/electron/installer-commands.json`) **without** `--skip-services`.
That always:

- registers launchd services under the fixed label `com.openbase.coder`
  (a per-user domain — `launchctl` ignores `$HOME`), and
- reconfigures machine-level Tailscale Serve, and
- binds ports 7999 (console) and 7880 (LiveKit).

All three collide with your live dev install no matter how `$HOME` is sandboxed.
A whole disposable OS is the only way to exercise this flow faithfully and
safely. Inside the VM we deliberately do **not** sandbox anything — the VM *is*
the sandbox, so the flow stays production-faithful.

## Scope

In scope (the install flow): Prerequisites → **Setup** (activates the bundled
CLI package into `~/.openbase/packages/standalone` and runs `openbase-coder
setup`), then verification of the resulting install.

Out of scope for this automated developer harness: **Login** (browser OAuth), **Pairing** (a physical phone), and the full acoustic loop. A full field test using either the developer-flow install or the signed-DMG install follows the shared `.agents/skills/field-testing/SKILL.md` procedure; [NON_DEVELOPER_FIELD_TEST.md](NON_DEVELOPER_FIELD_TEST.md) adds only the signed-DMG track details.

## Prerequisites

- **Apple Silicon Mac** — Tart virtualizes macOS on arm64 only (Intel can't run
  any of this); the build and DMGs are `-arm64`.
- **Homebrew** — `bootstrap-golden.sh` installs Tart + sshpass through it (and
  runs `brew trust cirruslabs/cli`, which current Homebrew requires before it
  will install from that tap).
- **Disk**: ~50 GB for the golden image (steady state ~31 GB). Apple caps **2**
  concurrently-running macOS VMs.
- **`run.sh` (Electron flow)** needs an **ephemeral Tailscale auth key**
  (onboarding gates setup on Tailscale being connected).
- **`run.sh`'s local build** (`build-app.sh`, only when you don't pass `--app`)
  needs the full desktop/CLI toolchain: **Xcode** (companion `xcodebuild`),
  **uv**, **pnpm**, **Node ≥ 20**, and a **`~/.openbase/bin/livekit-server`**
  binary — which only exists if you already have a local Openbase dev install
  (or pass `--livekit-bin`). This produces the **unsigned** field-test build
  (`build-app.sh` — not a new build pathway; it is this harness's local
  clean-room build for field testing, distinct from `dist:mac` /
  `dist:mac:publish`). See the `field-testing` skill.
- **`manual-vm.sh` needs none of the build toolchain** — it clones a bare macOS
  image and you download the real signed DMG inside the VM.

## One-time bootstrap (~50 GB, headless, do this once)

```bash
./install-tests/electron-macos/bootstrap-golden.sh
```

This installs Tart + sshpass (via Homebrew), pulls a macOS base image, and bakes
a **golden** VM named `openbase-golden`. The cirruslabs base images are
pre-provisioned for CI (user `admin` / password `admin`, Remote Login on,
auto-login to a GUI session), so this runs **fully headless** — no macOS Setup
Assistant clicking. It installs into the golden VM:

- **Node** (for the Playwright driver),
- the **Tailscale client** (`tailscaled` + `tailscale`),
- the driver's **Playwright** deps (prewarmed).

It is safe to re-run; it skips a golden VM that already exists. (The onboarding's
only external prerequisite is Tailscale — the bundled CLI covers the rest — so
`uv`/`multi`/`pnpm` are NOT needed in the VM.)

## Running a test (needs a Tailscale auth key)

The desktop onboarding won't run setup until **Tailscale is connected**, so the
throwaway VM must join a tailnet. Generate an **ephemeral + reusable** auth key
at https://login.tailscale.com/admin/settings/keys and pass it:

```bash
# Build the app on the host, then run the flow in a fresh VM clone
./install-tests/electron-macos/run.sh --tailscale-authkey tskey-auth-...

# Reuse an already-built app (skip the ~10 min host build)
./install-tests/electron-macos/run.sh --tailscale-authkey tskey-auth-... \
  --app desktop/release/mac-arm64/Openbase.app

# Keep the VM clone on failure for debugging (otherwise it is always deleted)
./install-tests/electron-macos/run.sh --tailscale-authkey tskey-auth-... --keep-on-fail
```

The key can also be supplied via the `TS_AUTHKEY` env var. Ephemeral nodes
auto-remove from your tailnet when the clone is deleted.

## Semantic guest control (pure images, runtime injection)

Images stay **pure** — nothing automation-related is baked into the bare base
image, and the long-term direction is to thin the golden VM the same way (the
Node/Playwright/Tailscale it currently carries exist only for `run.sh`'s
in-guest driver, which is being replaced by the host-side CDP driver below).
All automation lives on the **host** or is injected into the **disposable
clone** at run time:

```bash
# One-time on the host (installs the driver's playwright dep locally):
cd install-tests/electron-macos/driver && npm install --no-audit

# Pin the guest keyboard layout (hygiene; new processes/login pick it up)
./guest-automate.sh pin-layout openbase-manual

# Guest web forms: enable built-in safaridriver, tunnel it, drive semantically
./guest-automate.sh enable-safaridriver openbase-manual
./guest-automate.sh safari-tunnel openbase-manual &          # leaves a tunnel up
node driver/host-drive.mjs --wd http://127.0.0.1:4444 goto "https://example.com"
printf '%s' "user@example.com" | node driver/host-drive.mjs --wd http://127.0.0.1:4444 fill 'input[type=email]'

# Installed Electron app: launch with a CDP port, tunnel, drive semantically
./guest-automate.sh app-cdp openbase-manual &                # leaves a tunnel up
node driver/host-drive.mjs --cdp http://127.0.0.1:9222 snapshot
node driver/host-drive.mjs --cdp http://127.0.0.1:9222 click "Let's get you set up"
```

**Do not paste text through the Tart window.** Command-V can insert only a literal `v`, and shifted/option characters can be corrupted ([openai/tart#1167](https://github.com/openai/tart/issues/1167)). Use the semantic endpoints above. If a release build has CDP fused off and Tart text entry is unavoidable, clear or select all, then keystroke the complete value again and inspect it; never append a correction to malformed input. Window interaction remains appropriate for clicks on Gatekeeper and System Settings. The `--remote-debugging-port` launch is a debug-only deviation from a Finder double-click, so keep one pure launch in a run's smoke pass and record the flag in the field log.

## Clicking through it yourself (fresh bare Mac, choose the channel)

To get a completely fresh, **visible**, **bare** macOS VM and do the whole
install by hand — including choosing which channel to test:

```bash
./install-tests/electron-macos/manual-vm.sh \
  --source <sip-enabled-source> \
  --display 1600x900pt
```

For a full Openbase VPN field test, follow the signed-DMG track's [entry and artifact-acquisition rules](NON_DEVELOPER_FIELD_TEST.md#entry-and-completion-gates). The `manual-vm.sh` default is the SIP-disabled cirruslabs image and is suitable only for harness/debugging work that does not claim the VPN gate; always pass a maintained SIP-enabled source for the full flow.

This clones the selected **clean base macOS image** (NOT the provisioned golden VM): no
Tailscale, no Node, no Homebrew, and **no app**. It opens a macOS **window** on
your screen. Everything is yours to do. A complete field test downloads through the public Openbase downloads page as specified by the signed-DMG track. The direct URLs below are only a diagnostic fallback; using one leaves the public download surface untested and must be recorded that way:

```bash
# main / stable
curl -L -o ~/Downloads/Openbase.dmg "https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac/Openbase-Coder-latest-arm64.dmg"
# staging
curl -L -o ~/Downloads/Openbase.dmg "https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac-staging/Openbase-Coder-latest-arm64.dmg"
```

Those are signed + notarized, so Gatekeeper behaves normally: open the DMG, drag to `/Applications`, and run onboarding. A signed non-developer build offers Openbase VPN and Openbase Direct; seeing a standalone Tailscale option is a release defect. Log in as `admin` / `admin`; `tart delete openbase-manual` when done.

Options: `--app PATH` also drops a **local** unsigned dev build in `~/Downloads`
(for testing a local build instead of a channel; right-click → Open to bypass
Gatekeeper). `--source <ref>` clones a different image (e.g. a barer
`macos-sequoia-vanilla`). `--display <WxH>` controls the fixed guest resolution and defaults to `1600x900pt`, which fits inside a 1920x1200 host after Tart and macOS chrome. Use `1920x1200pt` only on a larger host; do not rely on Tart scrolling or window-resize tricks.

`run.sh` orchestrates, all on disposable state:

1. build the bundled dev app on the host (`build-app.sh`, mirrors the standard
   release packaging path — bundled CLI + companion, `openbaseDevBuild=true`, no
   notarize/publish; used by the `field-testing` skill for clean-room installs);
2. `tart clone openbase-golden` → a fresh instance; boot it, wait for SSH;
3. join the tailnet with the auth key (`vm/ts-connect.sh` — userspace
   `tailscaled` on its default socket, `chmod 666` so the non-root CLI can run
   `tailscale serve`);
4. copy in the `.app` + `driver/`, then `vm/run-driver.sh`: install to
   `/Applications`, strip quarantine, and launch the driver **inside the GUI
   (Aqua) session via `launchctl asuser`** so Electron can reach WindowServer;
5. `driver/onboard-and-verify.mjs`: Playwright launches the app, advances
   Overview → Prerequisites (waits for the bundled-CLI activation to finish via
   the filesystem, never racing concurrent copies) → clicks **Run setup** and
   confirms **"I understand, run setup"**, waits for the `setup` process to
   fully exit (so services install), then verifies;
6. copy `result.json` back and report; `tart delete` the clone (always, unless
   `--keep-on-fail` and it failed).

## What the driver verifies

Inside the VM, after setup fully completes:

- `~/.openbase/installation.json` exists and is `standalone: true` (the desktop
  flow activates the bundled package as a standalone install);
- `~/.openbase/packages/standalone/current` is populated with matching metadata;
- launchd services for `com.openbase.coder` are installed (the 5 plists:
  django-cli, livekit-server, livekit-agent, sync-workers, openbase-routines);
- the bundled `openbase-coder doctor` runs.

## Files

```
electron-macos/
  README.md
  NON_DEVELOPER_FIELD_TEST.md  # signed-DMG-specific additions to the shared field-test procedure
  bootstrap-golden.sh          # one-time: install Tart + bake the golden VM (headless)
  build-app.sh                 # host: build the bundled dev .app
  run.sh                       # orchestrator: clone -> tailnet -> install -> drive -> verify -> delete
  manual-vm.sh                 # fresh VISIBLE VM w/ app installed, for clicking through by hand
  guest-automate.sh            # host-side semantic control of any clone (tunnels, injection)
  driver/
    package.json               # playwright dependency (prewarmed in the golden VM)
    onboard-and-verify.mjs     # Playwright-Electron clickthrough + verification (in-guest; legacy)
    host-drive.mjs             # host-side semantic driver over forwarded CDP/WebDriver
  images/                      # screenshots used by the non-developer runbook
  vm/                          # scripts that run INSIDE the VM
    ts-connect.sh              # join the tailnet headlessly with an auth key
    run-driver.sh              # clean state, install app, launch driver in the GUI session
```

## Notes / caveats

- **Verified working** end-to-end (build → install → clickthrough → setup →
  services), driver exit 0.
- The clickthrough targets the onboarding UI by button text (the renderer has no
  `data-testid`s). If onboarding copy changes, update the patterns in
  `driver/onboard-and-verify.mjs` (`ADVANCE` / `SETUP_TRIGGER` / `CONFIRM`). The
  driver logs the visible buttons when it stalls, so mismatches are easy to spot.
- **Login**, **Pairing**, and acoustic validation are out of scope only for this automated developer harness; use [NON_DEVELOPER_FIELD_TEST.md](NON_DEVELOPER_FIELD_TEST.md) for the full signed-DMG path.
- tart's default DHCP-lease IP resolver can go stale mid-run; the harness uses
  `tart ip --resolver arp`.
- Apple allows at most **2** concurrently-running macOS VMs per host.

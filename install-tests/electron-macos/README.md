# Electron app install-flow test (macOS, Tart VM)

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

Out of scope: the **Login** (browser OAuth) and **Pairing** (a physical phone)
onboarding steps — they need a real cloud account and device and cannot be
automated. Those remain the domain of live no-mock E2E.

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

## Clicking through it yourself (fresh bare Mac, choose the channel)

To get a completely fresh, **visible**, **bare** macOS VM and do the whole
install by hand — including choosing which channel to test:

```bash
./install-tests/electron-macos/manual-vm.sh
```

This clones the **clean base macOS image** (NOT the provisioned golden VM): no
Tailscale, no Node, no Homebrew, and **no app**. It opens a macOS **window** on
your screen. Everything is yours to do. Inside the VM's Terminal, download the
real signed DMG for whichever channel you want:

```bash
# main / stable
curl -L -o ~/Downloads/Openbase.dmg "https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac/Openbase-Coder-latest-arm64.dmg"
# staging
curl -L -o ~/Downloads/Openbase.dmg "https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac-staging/Openbase-Coder-latest-arm64.dmg"
```

Those are signed + notarized, so Gatekeeper behaves normally: open the DMG, drag
to `/Applications`, run onboarding (it prompts you to install Tailscale
yourself). Log in as `admin` / `admin`; `tart delete openbase-manual` when done.

Options: `--app PATH` also drops a **local** unsigned dev build in `~/Downloads`
(for testing a local build instead of a channel; right-click → Open to bypass
Gatekeeper). `--source <ref>` clones a different image (e.g. a barer
`macos-sequoia-vanilla`).

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
  bootstrap-golden.sh          # one-time: install Tart + bake the golden VM (headless)
  build-app.sh                 # host: build the bundled dev .app
  run.sh                       # orchestrator: clone -> tailnet -> install -> drive -> verify -> delete
  manual-vm.sh                 # fresh VISIBLE VM w/ app installed, for clicking through by hand
  driver/
    package.json               # playwright dependency (prewarmed in the golden VM)
    onboard-and-verify.mjs     # Playwright-Electron clickthrough + verification
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
- **Login** (OAuth) and **Pairing** (a physical phone) onboarding steps are out
  of scope — they need a real account and device; this verifies the install, not
  a fully paired end state.
- tart's default DHCP-lease IP resolver can go stale mid-run; the harness uses
  `tart ip --resolver arp`.
- Apple allows at most **2** concurrently-running macOS VMs per host.

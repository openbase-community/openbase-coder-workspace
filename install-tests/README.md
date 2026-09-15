# Installation-flow tests (macOS)

Automated tests for the two macOS Openbase Coder installation flows, so you never have to uninstall/reinstall Openbase on your own machine to test them:

| Flow | Entrypoint under test | Test | Isolation |
| --- | --- | --- | --- |
| **Developer install** | `cli/scripts/install.sh` | `test-standalone-install.sh` | sandbox `$HOME` (no VM) |
| **Electron app** | the desktop app's onboarding → `openbase-coder setup` | shared field-testing skill + `electron-macos/manual-vm.sh` | disposable Tart VM |

> These are **not** in `e2e/`. Per the workspace hard rules, `e2e/` is reserved for Appium-driven iOS / Selenium-driven browser app tests. These tests drive the install entrypoints and assert on system state, so they live here.
>
> The dev-**workspace** setup (`scripts/setup`) is a Linux concern and is intentionally not tested here.

## Running

```bash
./install-tests/run-all.sh              # developer install flow (fast, sandboxed)
./install-tests/run-all.sh --full       # also runs the real setup against install.sh's package

# Electron flow starts a visible bare Tart clone; follow the shared field-testing skill:
./install-tests/electron-macos/manual-vm.sh --source <maintained-sip-enabled-source> --name <run-specific-name>
```

## Developer install flow (`test-standalone-install.sh`)

Runs the real `cli/scripts/install.sh` against a freshly-built package inside a sandbox `$HOME`, then asserts the installed layout: `packages/standalone/…`, the `current` symlink, the `~/.local/bin` launcher, `--version`, and the PATH block added to the shell profile. Safe because `install.sh` is `$HOME`-scoped and never starts services; a `sandbox_guard` interlock refuses to run if `$HOME` is not the sandbox. See `lib/common.sh`. `--full` additionally runs `openbase-coder setup --skip-services` against the installed package.

## Electron app flow (`electron-macos/`)

The desktop onboarding runs the real `openbase-coder setup` **without** `--skip-services` — it registers launchd services under the fixed label `com.openbase.coder`, configures machine-level phone access, and binds ports 7999/7880. Those collide with your live install regardless of `$HOME`, so this flow runs inside a **disposable macOS VM** (Tart). The shared field-testing skill owns the clean-room install, onboarding, physical-phone, acoustic, and Super Agent gates. See `electron-macos/README.md` for the Tart entrypoints.

## Layout

```
install-tests/
  README.md
  run-all.sh
  test-standalone-install.sh     # developer install (install.sh), sandboxed $HOME
  lib/common.sh                  # sandbox, tailscale stub, assertions
  electron-macos/                # Electron app flow, disposable Tart VM
    README.md  manual-vm.sh  build-app.sh  guest-automate.sh  driver/
```

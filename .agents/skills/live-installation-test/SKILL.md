---
name: live-installation-test
description: Use when preparing, running, debugging, or reporting an Openbase Coder installation test, especially an Electron app installed into /Applications with a bundled CLI before live no-mock iOS/Electron testing.
---

# Live Installation Test

This workspace-local skill is the installation-test runbook for Openbase Coder.
It applies when Gabe asks for an installation test, local install test, bundled
Electron install test, or to prepare the desktop app for a live no-mock E2E run.

## Start Here

Always start by telling Gabe that the installation test begins by uninstalling
the existing local installation state, because uninstall/reset is the first step
to testing install.

After uninstall/reset, build the **full bundled** Electron app, install it to
`/Applications`, and on macOS open the installed app for Gabe:

```bash
open "/Applications/Openbase Coder.app"
```

Always use `open` on the `.app` bundle. Do not launch the executable inside
`Contents/MacOS` directly; that bypasses normal macOS app launch behavior.

A production-configured build's first launch from `/Applications` shows a
one-time installer-cleanup dialog (eject the install DMG / trash the download).
When Gabe is driving the app this is part of the product surface — leave it on
and let him answer it. For unattended or scripted launches where a native modal
would stall the run, suppress it with
`OPENBASE_DESKTOP_DISABLE_INSTALLER_CLEANUP=1` in the launch environment.

Do not use a thin Electron-only local build for this skill. In particular,
`pnpm --dir desktop install:local` and any `electron-builder` invocation with
`-c.extraResources=[]` are acceptable only for fast renderer/UI smoke tests;
they are **not** installation tests because they omit the bundled CLI and
companion resources. If the task is an installation test or setup behavior test,
the app under `/Applications` must contain bundled resources and exercise them.

Do not start the live test itself unless Gabe explicitly asks to run it. Building
and installing the app is preparation; the live no-mock test still requires the
RMOT and preflight flow from `.agents/skills/live-no-mock-e2e/SKILL.md`.

## Branch And Provenance Rules

- Prominent disclaimer: an installation test of the local Electron app does not
  prove that the iOS app or `../openbase-cloud-workspace` are on the same branch
  or built from the same code. Treat iOS and cloud as separate deployment
  surfaces whose provenance must be checked and reported independently.
- Work from the active workspace branch Gabe requested, usually `staging`.
- Check the branch and dirty state for the multi workspace before building.
- Be explicit when related workspaces are not fully on the same branch. In
  particular, iOS or `../openbase-cloud-workspace` may not be on `staging` for
  the installation test; call that out instead of silently assuming parity.
- For bundled Electron tests, the installed app should contain a standalone CLI
  package built from the current local workspace snapshot unless Gabe asks for a
  released CLI seed.
- Verify and report the bundled CLI package metadata, especially `version`,
  `target`, `channel`, and `repo_shas`. The bundled CLI should match the local
  branch snapshot used to build it, not necessarily `origin/staging`.
- If a repo is ahead or behind origin, include that caveat in the report.

## Build Preparation

Before building, confirm these local inputs:

```bash
multi git -- status --short --branch
git -C ../openbase-cloud-workspace status --short --branch
git -C ../openbase-cloud-workspace/api status --short --branch
```

Use focused status checks for any repos whose branch matters to the requested
test, such as `desktop`, `cli`, `console`, `ios`, and cloud `api`.

## Reset Existing Installation State

This is the first active step of every installation test. Always start by
uninstalling/resetting existing local installation state with the workspace
script:

```bash
./scripts/uninstall-openbase-coder-installation-test --yes
```

The script archives `~/.openbase` by default, removes desktop/Electron state,
uninstalls managed services, removes common persistent CLI installs, removes
only Openbase's managed Claude Code keychain credential, and leaves the normal
Claude Code login alone. It also wipes the signed-in test account's Openbase
Cloud device registry before local auth is removed and verifies that the
onboarding state returns zero desktops and zero mobiles.

If the script does not work, debug and fix `scripts/uninstall-openbase-coder-installation-test`
directly, then rerun it. Do not replace it with copied manual uninstall steps
in this skill; the script is the maintained source of the installation-test
reset behavior.

If there is no usable existing Openbase login, the script exits before removing
local auth. Pause and have Gabe sign in or clear the cloud registry through an
authenticated backend/admin path; do not call the test a clean installation
test while stale cloud devices may remain.

The script does not run `pip uninstall` by default, because that can mutate the
active Python environment. Pass `--pip-uninstall` only when the persistent CLI
was installed with pip. Pass `--tailscale-serve-reset` only when Gabe confirms
this machine used Tailscale Serve only for Openbase. If the backend does not
support `devices/deregister/` yet, report that limitation explicitly and use a
backend-side admin cleanup for the same signed-in account before rerunning the
script with `--skip-cloud-device-deregister`.

## Build The Bundled CLI

For an Electron-bundled installation test, build a standalone package from the
local `cli` checkout. If the workspace lockfile blocks the package script's
console build step, build the console first and rerun the package build with
`--skip-console-build`; do not update the lockfile just to get through a local
installation test.

The package must be validated by running:

```bash
cli/dist/openbase-coder-package/bin/openbase-coder --version
cat cli/dist/openbase-coder-package/openbase-coder-package.json
```

## Build And Install Electron

Install a local app into `/Applications/Openbase Coder.app`.

For Gabe-only local testing, notarization is not required. Prefer a local
unsigned or ad-hoc app when Developer ID signing the bundled Python tree is too
slow. The installed app must still be a dev build so it does not self-update
during the test.

The local packaged app must be production-like with respect to bundled
resources. It may skip notarization and publishing, but it must not skip
`extraResources`.

Do **not** use:

```bash
pnpm --dir desktop install:local
electron-builder ... -c.extraResources=[]
```

Those commands build a thin Electron shell that is useful for UI smoke testing
only. They do not test installation, bundled CLI provenance, system
configuration, or whether setup uses the resources shipped inside the app.

The local packaged app must:

- stage `desktop/bundled/OpenbaseCoderCLI` from the built standalone package;
- include the macOS companion app when the test target needs it, and include it
  for full installation tests unless Gabe explicitly scopes the test to CLI-only
  installation behavior;
- set `openbaseDevBuild=true`;
- avoid notarization for local-only testing unless Gabe explicitly asks for it;
- avoid publishing artifacts.

Prefer the release packaging path, or an equivalent local command that preserves
the normal `build.extraResources` entries:

```bash
pnpm --dir desktop run companion:stage:mac
pnpm --dir desktop run cli:stage:mac
pnpm --dir desktop run icons:generate
pnpm --dir desktop run build
pnpm --dir desktop exec electron-builder --mac --arm64 --publish never -c.extraMetadata.openbaseDevBuild=true
node desktop/scripts/install-local.mjs
```

If using a one-command release path, ensure it does not publish or notarize
unless Gabe asked for that. If the command mutates `desktop/package.json`, restore
the tracked metadata immediately and do not commit the mutation.

After install, verify:

```bash
defaults read /Applications/'Openbase Coder.app'/Contents/Info CFBundleShortVersionString
/Applications/'Openbase Coder.app'/Contents/Resources/OpenbaseCoderCLI/bin/openbase-coder --version
cat /Applications/'Openbase Coder.app'/Contents/Resources/OpenbaseCoderCLI/openbase-coder-package.json
test -d /Applications/'Openbase Coder.app'/Contents/Resources/OpenbaseCoderCLI
test -d /Applications/'Openbase Coder.app'/Contents/Resources/OpenbaseScreenShareCompanion.app
```

Also inspect the packaged `app.asar` package metadata and confirm
`openbaseDevBuild` is true.

Treat missing `OpenbaseCoderCLI`, missing package metadata, or an installed app
that is dramatically smaller than the production bundle as a failed
installation-test preparation, not as a successful install.

After verification, open the installed app for Gabe on macOS:

```bash
open "/Applications/Openbase Coder.app"
```

Use the `.app` bundle path exactly as shown, not the executable inside the app
bundle.

## Live Test Handoff

If Gabe asks to proceed from installation preparation into a live no-mock test,
switch to `.agents/skills/live-no-mock-e2e/SKILL.md` before running any live
command.

That handoff requires:

- writing an RMOT plan under `/tmp`;
- opening the RMOT in Typora;
- confirming production cloud targeting unless Gabe requested otherwise;
- confirming the physical iPhone/Appium target when relevant;
- avoiding incidental `tts` while the iOS app may be listening.

## Reporting

Report the installation result with:

- installed Electron app version;
- whether `openbaseDevBuild` is true;
- whether the app is signed, unsigned, ad-hoc signed, or notarized;
- where `~/.openbase` was archived, or that no existing state directory was
  present;
- which uninstall cleanup steps were run and which were intentionally skipped;
- whether `/Applications/Openbase Coder.app` was opened for Gabe after install;
- bundled CLI version and package target;
- relevant repo SHAs from bundled package metadata;
- installed app size and whether the expected bundled resources are present;
- branch/dirty/ahead/behind caveats for `desktop`, `cli`, `ios`, and cloud
  repos involved in the test;
- a clear disclaimer when iOS or cloud provenance differs from the Electron
  bundle being tested;
- whether the live no-mock test was started or intentionally left unstarted.

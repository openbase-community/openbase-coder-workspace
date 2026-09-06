---
name: deploy
description: Run a full Openbase deployment — promote both openbase-cloud and openbase-coder develop to main, then run the dependent CLI/desktop release and Cloud deploy checks. Use when asked to deploy, release, or ship Openbase.
---

# Openbase Deployment

This runbook coordinates a production deploy across both sibling multi workspaces:

- `../openbase-cloud-workspace`: Cloud API/web/PaaS/dev-ami targets.
- `openbase-coder-workspace`: local Coder CLI/React console/apps/desktop targets.

Promote the Cloud workspace before the Coder workspace. Each workspace's `scripts/promote` command owns its internal repository ordering, branch/ref safety checks, pre-release gates, and promotion side effects; follow the script's plan and failure output rather than documenting those rules in this skill.

The Cloud promotion script owns Cloud release and live-rollout monitoring. The coordination this skill adds is monitoring the Coder CLI release and, when a freshly seeded desktop installer matters, holding desktop until that release exists. `dev-docs/AUTO_UPDATE.md` owns the Coder release and update mechanics.

## Branch model

Two promotion paths are both valid, and we use each at different times:

- **`develop` → `main` directly** — the common path. One promote per workspace.
- **`develop` → `staging` → `main`** — when we want an integration/soak step, promote `develop` → `staging` first, verify, then `staging` → `main`.

Pick one per deploy and apply it consistently across both workspaces. The commands below use `develop main` as the example (the direct path); if you're going through `staging`, substitute the branch pair for the step you're on (`develop staging`, then later `staging main`) — the surrounding gates and ordering are identical either way.

## 0. Preconditions

- Both workspaces committed and pushed on the FROM branch you're promoting (usually `develop`); no parallel agent mid-commit in these repos.
- Run both promotion scripts with their default checks. Do not use `--skip-checks` unless intentionally overriding a diagnosed failure.
- Run any Cloud-specific tests required by the Cloud workspace before its promotion.

A coordinated deploy does not require or wait for a PyPI release. If the standalone Super Agents package should also be released, use the PyPI instructions in `dev-docs/AUTO_UPDATE.md` rather than copying those instructions into this runbook.

## 1. Promote openbase-cloud-workspace → main first

Promote the Cloud workspace before Coder so production Cloud serves any API contract the Coder release expects:

```bash
cd ../openbase-cloud-workspace
./scripts/promote develop main
```

When Cloud API or web inputs change, `scripts/promote` waits for the final PaaS releases and verifies the backend's live ECS rollout before returning. Treat a successful script exit as the Cloud deployment gate; do not duplicate its monitoring procedure here in this skill.

## 2. Promote openbase-coder-workspace → main

Promote the whole Coder workspace in one shot. `desktop` is one of the repos in the batch, so this cuts the CLI release (step 3) and triggers the desktop DMG rebuild (step 4) together:

```bash
# From the workspace root:
./scripts/promote develop main
```

Pushing cli main auto-cuts the CLI release (step 3). Expect this command to take 30+ minutes — the pre-release gates dominate (full cli test suite plus the committed-assembly pnpm install and console/desktop typechecks run before any push); see Timing expectations below. It is not hung.

Mobile artifacts ride this same promote: the ios push triggers the App Store upload CI, and when `android` actually moves, the script runs `scripts/publish-android-apk` (S3 upload + marketing label bump) as its **final** step. That step runs after every push has already succeeded — so a non-zero exit here can mean the promotions all landed and only the Android publish failed. Read the script's closing error summary before assuming the promotion failed or re-running it.

## 3. CLI auto-release

Pushing cli main runs `auto-release.yml` (minor bump by default; `[release patch]`/`[release major]`/`[skip release]` head-commit overrides).

```bash
gh run list --repo openbase-community/openbase --workflow auto-release.yml --limit 1
gh run watch <id> --repo openbase-community/openbase --exit-status
```

Verify the published release: assets include the tarball, SHA256SUMS, `update-manifest.json` **and `.sig`**; then prove the client path end-to-end:

```bash
cd cli && uv run python -c "from openbase_coder_cli.self_update import _fetch_manifest; m=_fetch_manifest('stable'); print(m['version'], m['channel'], list(m['repo_shas']))"
```

(That verifies the Ed25519 signature with the embedded key — it raises on any mismatch.)

### Cloud DevSpace AMI relationship

A normal CLI GitHub Release plus desktop publish does **not** rebuild the Cloud DevSpace AMI. Rebuild the AMI only when the change must be baked into newly created DevSpaces (for example AMI helper scripts, OS packages, GUI/Tailscale image setup, pre-baked workspace contents, or a baseline CLI version required before `openbase-coder provision` can self-heal).

The AMI is built by GitHub Actions in the private `openbase-community/openbase-dev-ami` repo (`.github/workflows/build-devspace-ami.yml`). That repo is checked out as the `dev-ami/` subrepo of `../openbase-cloud-workspace` (see its `multi.json`), so the `dev-ami/setup.sh` and Packer files you edit locally are the very files the workflow runs — promoting the cloud workspace pushes them. The workflow's **own branch** selects what gets baked (not the branch of any dev checkout, and there is no auto-discovery — the mapping is hardcoded in the workflow):

- Push to `openbase-dev-ami`'s **`main`** → default AMI. Packer's `workspace_branch` var is empty, so `setup.sh` installs the CLI from `git@main` and leaves the pre-baked workspace subrepos on their default branches. Named `openbase-devspace-ami-*`, which is what prod's newest-AMI launch lookup matches.
- Push to `openbase-dev-ami`'s **`staging`** → staging AMI. The workflow passes `-var workspace_branch=staging`, so `setup.sh` installs the CLI from `git@staging` and switches each pre-baked workspace subrepo to `staging` (subrepos without that branch stay on their default). Named `openbase-devspace-staging-ami` so prod never picks it up.

Either way the CLI comes from git at that branch's HEAD (a rebake picks up new commits directly; `openbase-coder` is no longer published to PyPI). The staging AMI only matters when you're deploying through the `staging` path (see Branch model above); a direct `develop` → `main` deploy exercises just the `main`/default AMI.

## 4. Desktop DMG publish

**CI is the publisher.** Pushing desktop `main` (done by step 2's promote) runs `electron-rebuild.yml`, which builds, signs, notarizes, and publishes the DMG/zip/feed to S3 (~30 min), seeding the app with the **latest released** CLI package (downloaded, never rebuilt). If publishing fails, fix or rerun CI; do not publish from a developer workstation.

`scripts/promote` now does this itself on main and staging: it defers the desktop push until the cli auto-release run succeeds and the release's `update-manifest.json` asset is live, then pushes desktop, watches the electron rebuild to completion, and fails loudly if the log's `Staged Openbase Coder CLI <version>` does not match the release it waited for. A stale seed is not benign: a fresh install runs its entire setup flow on the bundled seed before any self-update, so a contract-changing CLI release with an unsequenced desktop push breaks every fresh install until the feeds converge. (Bump `desktop/package.json` on develop before promoting when you want installed apps to auto-update — electron-updater only moves to *higher* versions.)

**Escape hatch:** `--no-wait-ci` restores the old fire-and-forget pushes (desktop alongside cli, no rebuild watch) when you deliberately do not care about the seed — expect the bundled CLI to be one release behind in that mode.

The same principle applies across workspaces: cloud, coder, multi, and boilersync each run their **own deploy lifecycle** from their own `scripts/promote`, and nothing synchronizes them. A Cloud DevSpace AMI bake snapshots this workspace's branches whenever it happens to run; multi-react/boilersync-react enter builds at whatever their trunk `main` holds. Cross-workspace freshness is eventually consistent by design — do not add cross-workspace waits.

Known CI behaviors: the `rebuild linux` and `rebuild macOS` jobs publish independently, so diagnose the failed job without assuming the other artifact failed too. If BOTH jobs fail instantly with zero steps, the org has exhausted its GitHub Actions spending limit — fix in org billing settings, then `gh run rerun`. A `workflow_dispatch`ed release shares the concurrency group with push runs and gets cancelled by any release-worthy push to main mid-build; `[skip release]` pushes are the exception — they never cancel (conditional `cancel-in-progress`, see dev-docs/AUTO_UPDATE.md).

If the macOS job fails late with `Electron failed to install correctly`, the workflow's pnpm postinstall config has regressed — see the `pnpm.onlyBuiltDependencies` rule in `dev-docs/AUTO_UPDATE.md` (Desktop app updates). Fix the workflow, then rerun after the CLI release asset exists so the desktop seed is the current CLI version.

## Timing expectations (2026-07 baselines)

| Deploy | Typical duration |
|---|---|
| Coder workspace `scripts/promote` (prechecks dominate: cli pytest suite, assembly pnpm install, typechecks) | 30+ min |
| CLI auto-release (GHA) | ~3 min |
| Desktop CI build+notarize+publish | ~30 min |
| openbase-cloud API (`openbase-deploy`, warm cache) | ~7 min (build ~4, rollout ~3.5) |
| Static sites (web/marketing) | ~20 s after local build |

## 5. Post-deploy checks

- `openbase-coder self-update --check` on a standalone install reports the new version.
- An installed desktop app (lower version) offers "Restart to update".
- Device registration still green: `cd cli && uv run python -c "from openbase_coder_cli.services.cloud_registration import register_and_report; print(register_and_report().ok)"`.

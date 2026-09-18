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
- **Deploy attribution:** PaaS Slack notifications attribute a deploy from the `Agent-Thread-Id` trailer on the pushed head commit. Both promote scripts stamp their synthesized exact-tree commits from `$AGENT_SESSION_ID`, the vendor-neutral session variable agent runtimes export into agent shells (Claude Code via the inject-session-id hook, Codex via super-agents' per-thread `shell_environment_policy`), with codex's native `$CODEX_THREAD_ID` as a backwards-compat fallback. If neither is in your environment, pass `--agent-thread-id <your-thread-id>` explicitly or the deploy shows up as `Agent: human`.
- **SSH-blocked networks:** some networks block outbound SSH to github.com on ports 22 AND 443 while HTTPS works, which hangs the SSH-remote subrepos (console, allauth-client-swift, multi-react). Run the promote with a per-process, **org-scoped** rewrite — `GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=url.https://github.com/openbase-community/.insteadOf GIT_CONFIG_VALUE_0=git@github.com:openbase-community/ GIT_CONFIG_KEY_1=url.https://github.com/montaguegabe/.insteadOf GIT_CONFIG_VALUE_1=git@github.com:montaguegabe/` — and never a blanket `github.com` rewrite: that leaks into the cli pytest gate the promote runs and fails tests that assert literal `git@github.com:` fixture URLs. Do not rewrite the shared checkouts' remotes.

A coordinated deploy does not require or wait for a PyPI release. If the standalone Super Agents package should also be released, use the PyPI instructions in `dev-docs/AUTO_UPDATE.md` rather than copying those instructions into this runbook.

## 1. Promote openbase-cloud-workspace → main first

Promote the Cloud workspace before Coder so production Cloud serves any API contract the Coder release expects:

```bash
cd ../openbase-cloud-workspace
./scripts/promote develop main
```

When Cloud API or web inputs change, `scripts/promote` waits for the final PaaS releases and verifies the backend's live ECS rollout before returning. Treat a successful script exit as the Cloud deployment gate; do not duplicate its monitoring procedure here in this skill.

**Known false failure — the release watcher can lose a supersession race.** A multi-repo burst cuts one PaaS release per pushed repo on "Openbase Cloud API", and the platform supersedes them by *creation order*, which does not always match which release actually rolls out. The script's watcher (and `openbase releases wait` on the survivor) can then report "rolled back"/"superseded"/"overtaken" even though the burst deployed fine. Before re-running anything after a non-zero exit where every push already landed: `openbase releases -a "Openbase Cloud API" --json`, find the release whose `commit_sha` is the promoted **api** repo's new main sha, poll it to `succeeded`, and confirm `https://app.openbase.cloud/api/csrf/` returns HTTP 200 with a JSON object containing `csrfToken` (retain only the shape, not the token). Use the matching staging origin for a staging rollout. Do not use an arbitrary `/api/health` 200 as API-health evidence: the SPA catch-all can return HTML with that status. A "failed" badge left on the app by a losing release clears on the next deploy. (Both false-failure shapes occurred on 2026-09-08.)

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

If the release build fails with `ERR_PNPM_OUTDATED_LOCKFILE`, a frontend member repo changed npm deps without regenerating both the root and the pinned release-workspace lockfiles — see the lockfile bullet under "Auto-release from main and staging" in `dev-docs/AUTO_UPDATE.md`.

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

`scripts/promote` now does this itself on main and staging: it defers the desktop push until the cli auto-release run succeeds and the release's `update-manifest.json` asset is live, then pushes desktop, watches the electron rebuild to completion, and fails loudly if the log's `Staged Openbase Coder CLI <version>` does not match the release it waited for. A stale seed is not benign, and fresh installs are the majority case, not an edge case: a fresh install runs its entire setup flow on the bundled seed before any self-update, so a contract-changing CLI release with an unsequenced desktop push ships a broken product to most new users until the feeds converge. (Bump `desktop/package.json` on develop before promoting when you want installed apps to auto-update — electron-updater only moves to *higher* versions.)

**Escape hatch:** `--no-wait-ci` restores the old fire-and-forget pushes (desktop alongside cli, no rebuild watch) when you deliberately do not care about the seed — expect the bundled CLI to be one release behind in that mode.

### Netmesh companion prebuilt (macOS) — refresh prod before it bites

The macOS DMG build stages the private Netmesh apps (headless `OpenbaseNetmeshCompanion.app` + status menu-bar `OpenbaseNetmesh.app`) as **signed prebuilts downloaded from the release S3 bucket** — public/CI desktop checkouts have no `netmesh-macos` source, so they can only download, never build or publish, these artifacts. The prefix is channel-local: `mac/` for `main`, `mac-staging/` for `staging` (see `desktop/scripts/stage-netmesh-companion.mjs` / `stage-netmesh-menubar.mjs`).

`desktop/scripts/netmesh-prebuilt-contract.mjs` pins `MINIMUM_NETMESH_BUILD`. The macOS job **fails at the stage step** (`build N is too old; build M or newer is required`) if the downloaded artifact's `CFBundleVersion` is below it. Because CI never refreshes the prod artifact, bumping `MINIMUM_NETMESH_BUILD` (or shipping a netmesh-macos build the desktop runtime now relies on) **will fail the prod macOS DMG until the `mac/` artifact is refreshed** — even though every git push and the CLI release succeeded. This is a pre-desktop-push gate, not a post-hoc check: verify it *before* promoting a desktop change that touches the contract.

`netmesh-macos` is pinned `@main`, so the staging and prod companion are the same build — the fast, low-risk refresh is to promote the already-signed artifact from `mac-staging/` to `mac/`:

```bash
BUCKET=openbase-coder-desktop-releases-632795836081-us-east-1
# 1. Confirm the desktop contract's required build and that netmesh-macos@main matches:
grep MINIMUM_NETMESH_BUILD desktop/scripts/netmesh-prebuilt-contract.mjs
grep CURRENT_PROJECT_VERSION netmesh-macos/project.yml
# 2. For each of OpenbaseNetmeshCompanion-latest-arm64.zip and OpenbaseNetmesh-latest-arm64.zip:
#    download the mac-staging artifact, verify CFBundleVersion >= minimum and
#    `codesign --verify --deep --strict` (Developer ID Application), back up the
#    current mac/ object, then copy staging -> prod:
aws s3 cp "s3://$BUCKET/mac-staging/<zip>" "s3://$BUCKET/mac/<zip>"
```

Both artifacts are contract-gated, so refresh both. (These prebuilts are unnotarized-but-signed by design — the outer DMG notarization covers the nested apps; do not expect a stapled ticket on the companion itself.) If `mac-staging/` does not yet carry the required build, run a staging desktop build first (or build from the `netmesh-macos` source checkout so `publish-s3.mjs` publishes it).

The same principle applies across workspaces: cloud, coder, multi, and boilersync each run their **own deploy lifecycle** from their own `scripts/promote`, and nothing synchronizes them. A Cloud DevSpace AMI bake snapshots this workspace's branches whenever it happens to run; multi-react/boilersync-react enter builds at whatever their trunk `main` holds. Cross-workspace freshness is eventually consistent by design — do not add cross-workspace waits.

Known CI behaviors: the `rebuild linux` and `rebuild macOS` jobs publish independently, so diagnose the failed job without assuming the other artifact failed too. If BOTH jobs fail instantly with zero steps, the org has exhausted its GitHub Actions spending limit — fix in org billing settings, then `gh run rerun`. A `403 Forbidden` / `Failed to FinalizeArtifact` on the `Upload macOS DMG` step is a **transient GitHub artifact-storage flake**, not a build problem — build+sign+notarize already passed, but because that step precedes `Publish macOS DMG to S3`, its failure leaves the S3 feed un-updated; just `gh run rerun --failed` (build+notarize re-run, ~20 min) and it publishes cleanly. A `workflow_dispatch`ed release shares the concurrency group with push runs and gets cancelled by any release-worthy push to main mid-build; `[skip release]` pushes are the exception — they never cancel (conditional `cancel-in-progress`, see dev-docs/AUTO_UPDATE.md).

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

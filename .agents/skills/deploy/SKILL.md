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

## Staging promotions: one command

A `develop` → `staging` promotion is one script, run from the Cloud workspace trunk (it drives the sibling Coder workspace too):

```bash
cd ../openbase-cloud-workspace
scripts/promote-staging --dry-run --upgrade <devspace pks>   # print the plan only
scripts/promote-staging --upgrade <devspace pks> --log <file> --summary-json <file>
```

It prints the plan first ("WILL rebuild X", "skip Y: unchanged"), from both workspaces' own `scripts/promote --dry-run` content comparison, and rebuilds only what depends on a changed tree: the Cloud API/web releases when api, api-core, deploy, the cloud root or web changed; the CLI release and the cloud workspace image when cli or a bundled sibling (super-agents, skills, console, coder-react, the root's `instructions/`) changed; desktop when desktop or its bundled CLI changed; Android when android changed. Then it runs everything in parallel: both promotions at once (Coder holds desktop back until the CLI release it must seed exists), the image build (amd64 only, dispatched right after the push instead of after the CLI release), the CLI, Android and desktop CI, and, once the image is built and the staging API is live, the `MARITIME_IMAGE` pin (its ~10 min config release rolls out in the background), the in-place upgrade of each `--upgrade` workspace and the fresh-workspace check, all at once. Remote steps run as short `openbase run` tasks (each under the ~120 s proxy cutoff) with `MARITIME_IMAGE` set to the new digest in the task environment, which is why they need not wait for the config release.

It upgrades only the listed workspaces that are running, with the image-upgrade procedure's guarded path below (quiescence check, both Super Agents stores already linked into `/data`, guard, `redeploy_container_workspace`, post-boot verification that every thread id and agent name survived). It skips stopped workspaces and refuses, without copying anything, a workspace whose stores are not linked (a suspected image revert); handle those by hand with the full procedure. The fresh-workspace check creates a workspace as `--fresh-user` (a field-test account), runs the post-boot checks and the BUG 7 stop/wake canary, and terminates it unless `--keep-fresh`. `--wait-desktop` also waits for the ~25 min desktop rebuild and verifies its CLI seed; by default the script reports the run and returns. It exits non-zero and lists every failure if any step failed; read the milestones it prints for the timeline.

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

### Cloud workspace image upgrades (staging and production)

Cloud workspaces (DevSpace kind `container`) run the CLI baked into the image pinned by the Cloud app's `MARITIME_IMAGE`; a CLI release does not reach them until that image is rebuilt, re-pinned and each existing workspace is redeployed in place. Maritime keeps only `/data` across a redeploy: the image layer, `$HOME` included, is replaced. Images built before cli `docker/persist-home-state.sh` (landed 2026-10-09) kept the Super Agents registry (thread ids, the Dispatcher's thread, Super Agent names) in `$HOME`, and the first staging redeploy lost it. Every existing workspace on such an image needs a one-time copy before its first redeploy; skipping it loses that user's threads irrecoverably.

**Runtime recovery workaround.** Some existing workspaces have reverted after a successful image deploy and stop/wake; isolated Redis image experiments retained upgrades, so this is not a proven universal Maritime limitation or a proven derived-image cause. Cloud now offers opt-in recovery through `openbase_api.devspaces.runtime_recovery.upgrade_container_runtime`. Deploy the Cloud API migration `devspaces.0013_maritimeruntimepin` first. Build the replacement image with the already-landed never-regress home-state fix. An old image entrypoint is unchanged: the minute Cloud sweep detects a wrong CLI version after it boots and makes at most one guarded repair, rather than storing another runtime on the user's volume. This does not prevent the old runtime from starting briefly, and a failing health probe or active work can require operator intervention.

For each existing workspace, staging and production alike:

1. Quiesce it: no active turn or call (check its threads through the local API over exec), and keep it quiescent through the redeploy so the snapshot is not overtaken by later writes. Record the thread ids, Dispatcher thread and Super Agent names for the post-boot comparison.
2. Copy the registry onto the volume, and redeploy in the same breath: the live store keeps changing while the workspace runs (every Super Agents event rewrites `~/.super-agents/state.json`, and the guard in step 3 refuses a copy more than 300 seconds older than the store), so make the copy immediately before the redeploy and never leave minutes between them. Run cli `docker/pre-upgrade-copy-home-state.sh` inside the workspace through the Maritime exec API with the paths spelled out: `bash -c <script text> x --refresh /home/openbase /data/openbase` (from the Cloud shell: `MaritimeClient().exec_command(d.maritime_agent_id, "bash -c " + shlex.quote(script_text) + " x --refresh /home/openbase /data/openbase", timeout=60)`). The exec runs as **root**: the script therefore never reads `$HOME` (root's is `/root`), and it hands everything it writes to the home directory's owner; a copy made by hand as root leaves a root-owned `state.sqlite3` that is read-only for the workspace user after the redeploy, which breaks the thread API and the LiveKit agent. Require successful completion. Expect `copied …` for each real source directory; with `--refresh` an existing volume copy that is older than the `$HOME` store is first reported as `set aside …` (parked as `<dest>.replaced-<stamp>`, never deleted). `skip … (not a real directory)` also covers missing sources and arbitrary symlinks: verify that any skipped source is either absent as expected or already points at its durable directory. Without `--refresh` an existing copy is never replaced (`skip … already exists`, or `kept …`), which is only right when nothing has changed since it was made.
   **Freshness rule (2026-10-10): a volume copy is never replaced by an older store.** With or without `--refresh`, the script compares the newest modification time anywhere in each tree (`state.json`, `state.sqlite3`, thread logs, the directories themselves) and keeps the volume copy when it is at least as new as the `$HOME` store, printing `kept <dest> (volume copy is newer than <src>)`; only a strictly newer `$HOME` store is copied, and only with `--refresh`. This matters because a workspace that wakes on an older image than the one last deployed (finding 1 of the 2026-10-10 staging promotion) brings that image layer's `$HOME` stores back as real directories, older than the `/data` stores the workspace has been writing since: on staging workspace 374 the old `--refresh` copied such a stale store over the newer `/data/openbase/super-agents-claude-code` and parked a thread with its turns. Treat `kept …` on such a workspace as the correct outcome and move on to step 3; the entrypoint's boot-time adoption applies the same rule, so the next boot keeps the volume copy and retires the layer's store (logged as `[persist-home-state] kept … at least as new as …`). `--force` restores the unconditional replacement (loud warning on stderr; the replaced copy is still parked) and is for a deliberate operator decision only, never part of this procedure.
3. Redeploy and enroll immediately with `upgrade_container_runtime(d, version="<expected CLI release>", image="openbaseai/openbase@sha256:<digest>")` from `openbase_api.devspaces.runtime_recovery`, never a bare `deploy_image`. The explicit version must match the image build; do not infer it from the possibly reverted workspace. Use a distinct CLI release per runtime upgrade, because the probe compares CLI versions, not whole-image digests. The helper requires successful API/worker health probes, no active runs/calls, the existing persistence guard, and a confirmed filesystem flush. It records a per-agent image/version target after the deploy is accepted; later global `MARITIME_IMAGE` changes do not alter that target. First confirm the target Cloud backend includes the persistence guard and the replacement image includes `persist-home-state.sh`. The guard re-checks through exec and refuses when the registry is still only in the image layer, when `$HOME` holds the live store and the volume copy is more than 300 seconds older than it, or when the check cannot run (an asleep workspace: start it first; a transient exec 503 `guest_command_unavailable`: retry from step 2). A volume copy newer than the `$HOME` store counts as persisted (the stale-layer case above: the guard neither blocks on files the newer copy lacks nor asks for a refresh over it). A refusal for staleness means the store changed after the copy: repeat step 2 with `--refresh` and redeploy again at once. Its five-minute staleness tolerance does not prove that all writes were captured; keep the workspace quiescent even if the guard passes. The low-level `redeploy_container_workspace` has an `allow_unpersisted_state=True` escape hatch that accepts losing threads and requires Gabe's explicit go; the runtime recovery helper never exposes or uses it.
4. Verify after boot: `/home/openbase/.super-agents` and `/home/openbase/.local/share/super-agents-claude-code` are symlinks into `/data/openbase`, every file under them belongs to the workspace user, and the workspace's `/api/threads/` still lists its `s_` thread ids, the Dispatcher's thread and the Super Agent names it had before. Give the services a minute: the LiveKit worker (`127.0.0.1:18081`) comes up after the API. Keep the workspace quiescent for step 5. The Maritime plan caps the number of awake machines, and the product start call can exceed the Cloud client's timeout while the VM still starts, so reconcile a minute later rather than retrying the start.

5. Verify durability before declaring the upgrade complete: once the initial boot has the expected CLI version and healthy API/worker, run `reconcile_runtime_pin(d)` from the same module and require `MaritimeRuntimePin.objects.get(devspace=d)` to have `repair_pending=False` and `blocked=False`. Stop and start through the product, then read the CLI version again after wake. Repeat the state/thread checks from step 4. If it first wakes old, allow the minute sweep and its five-minute verification window to finish; distinguish an immediately durable wake from a repaired wake in the deployment record. Any wrong version, blocked pin, or unresolved pending repair fails the deployment gate. Restore the original running/stopped state only after this check. Do not run this lifecycle validation on an in-use demo workspace without authorization.

**Failure and rollback.** `MaritimeRuntimePin` is operator state; the provider's running/stopped status remains truthful for billing and spend limits. Inspect `version`, `image`, `repair_pending`, `blocked`, and `verify_by`; logs emit `maritime_runtime_probe_failed` or `maritime_runtime_recovery_blocked` without command output. A blocked pin never retries automatically. Resolve unsafe/missing persistent state or active work first. To retry or deliberately roll back, use `upgrade_container_runtime(d, version="<known-good release>", image="<known-good immutable digest>")`, then repeat boot and stop/wake verification. The rollback image must also contain the never-regress fix and be compatible with current persistent data. A refused deployment leaves the prior pin intact. A request timeout is ambiguous: inspect provider deployment and live version before retrying; the old pin remains the recovery target. Never roll back data, delete parked stores, or use `allow_unpersisted_state` for runtime recovery.

Fresh workspaces need no pre-upgrade copy and are not enrolled automatically. Workspaces already on a safe image pass the persistence check without copying. `scripts/promote-staging` still uses the legacy guarded redeploy helper and does **not** enroll or update a runtime pin or prove durable wake. Never include an already-enrolled workspace in its `--upgrade` list: the old pin remains the recovery target, so the minute sweep can undo the new deployment. Use this full manual procedure for initial enrollment and every subsequent upgrade or rollback of an enrolled workspace. Do not treat staging-helper success as the durability gate.

## 4. Desktop DMG publish

**CI is the publisher.** Pushing desktop `main` (done by step 2's promote) runs `electron-rebuild.yml`, which builds, signs, notarizes, and publishes the DMG/zip/feed to S3 (~30 min), seeding the app with the **latest released** CLI package (downloaded, never rebuilt). If publishing fails, fix or rerun CI; do not publish from a developer workstation.

`scripts/promote` now does this itself on main and staging: it defers the desktop push until the cli auto-release run succeeds and the release's `update-manifest.json` asset is live, then pushes desktop, watches the electron rebuild to completion, and fails loudly if the log's `Staged Openbase Coder CLI <version>` does not match the release it waited for. A stale seed is not benign, and fresh installs are the majority case, not an edge case: a fresh install runs its entire setup flow on the bundled seed before any self-update, so a contract-changing CLI release with an unsequenced desktop push ships a broken product to most new users until the feeds converge. (Bump `desktop/package.json` on develop before promoting when you want installed apps to auto-update — electron-updater only moves to *higher* versions.)

**Escape hatch:** `--no-wait-ci` restores the old fire-and-forget pushes (desktop alongside cli, no rebuild watch) when you deliberately do not care about the seed — expect the bundled CLI to be one release behind in that mode.

### Netmesh companion prebuilt (macOS) — refresh prod before it bites

The macOS DMG build stages the private Netmesh apps (headless `OpenbaseNetmeshCompanion.app` + status menu-bar `OpenbaseNetmesh.app`) as **signed prebuilts downloaded from the release S3 bucket** — public/CI desktop checkouts have no `netmesh-macos` source, so they can only download, never build or publish, these artifacts. The prefix is channel-local: `mac/` for `main`, `mac-staging/` for `staging` (see `desktop/scripts/stage-netmesh-companion.mjs` / `stage-netmesh-menubar.mjs`).

`desktop/scripts/netmesh-prebuilt-contract.mjs` pins `MINIMUM_NETMESH_BUILD`. The macOS job **fails at the stage step** (`build N is too old; build M or newer is required`) if the downloaded artifact's `CFBundleVersion` is below it. For prod builds, `desktop/.github/workflows/electron-rebuild.yml` now runs `desktop/scripts/ensure-prod-netmesh-companion.mjs` before packaging: it checks both `mac/` artifacts, verifies the corresponding `mac-staging/` artifact's build number and Developer ID signature when prod is stale, and copies `mac-staging/` to `mac/` automatically. This is still a pre-desktop-push gate: if `mac-staging/` does not yet carry the required build, the prod DMG fails before packaging and you must publish a current netmesh-macos build first.

`netmesh-macos` is pinned `@main`, so the staging and prod companion are the same build. If the automatic prod refresh fails or you need to check the contract before promoting, use the same low-risk path manually: promote the already-signed artifact from `mac-staging/` to `mac/`:

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
| Coder workspace `scripts/promote` to main (prechecks dominate: cli pytest suite, assembly pnpm install, typechecks) | 30+ min |
| Coder or Cloud `scripts/promote` to staging (no prechecks; pushes only) | < 1 min |
| CLI auto-release (GHA, measured 2026-10-09) | 4–6 min |
| Cloud workspace image (`docker-image.yml`, both arches; amd64 alone is the same wall clock) | ~4–5 min |
| Android release (GHA) | 12–17 min, ~8 min less with the netmesh AAR cached |
| Desktop CI build+notarize+publish | ~24–30 min |
| openbase-cloud API (staging or prod webhook deploy) | 6–7.5 min |
| `MARITIME_IMAGE` config change (two config_sync releases) | 5 and 9–10 min |
| Cloud workspace in-place upgrade (redeploy + boot + verify) | ~3–5 min each, in parallel |
| Static sites (web/marketing) | ~20 s after local build |

## 5. Post-deploy checks

- `openbase-coder self-update --check` on a standalone install reports the new version.
- An installed desktop app (lower version) offers "Restart to update".
- Device registration still green: `cd cli && uv run python -c "from openbase_coder_cli.services.cloud_registration import register_and_report; print(register_and_report().ok)"`.

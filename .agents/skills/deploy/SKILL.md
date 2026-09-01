---
name: deploy
description: Run a full Openbase deployment — promote both openbase-cloud and openbase-coder staging to main, then run the dependent CLI/desktop release and Cloud deploy checks. Use when asked to deploy, release, or ship Openbase.
---

# Openbase Deployment

Full production deploy, in dependency order. This workflow covers both sibling
multi workspaces:

- `../openbase-cloud-workspace`: Cloud API/web/PaaS/dev-ami inputs.
- `openbase-coder-workspace`: local Coder CLI/console/apps/desktop release
  inputs.

The contract behind the Coder release side is the workspace `AUTO_UPDATE.md`;
this skill is the operational runbook.

Dependency graph: openbase-cloud API contract → super-agents (PyPI, only when
changed) → CLI standalone package (GitHub Releases, via auto-release) →
desktop DMG (S3, bundles the released CLI as its first-install seed). Sibling
JS repos (console, coder-react, multi-react, boilersync-react, skills) are
baked into the CLI package from their main branches.

## 0. Preconditions

- Both workspaces committed and pushed on `staging`; no parallel agent
  mid-commit in these repos.
- **`scripts/promote` enforces the code-quality preconditions automatically**
  when promoting into `main`: it runs the cli test suite and the
  console/desktop typechecks as **fatal** gates (a failure aborts before any
  push) and the desktop mac-release prereqs as a **non-blocking warning**.
  `--skip-checks` overrides. Cloud API tests are not covered — run them before
  promoting the Cloud workspace if its API changed.
- For the manual desktop fallback only (step 5), this Mac needs the
  `openbase-coder-desktop` notarytool keychain profile, a Developer ID
  identity in the keychain, and default AWS credentials for the releases
  bucket.

## 1. Promote openbase-cloud-workspace → main first

Promote the Cloud workspace before Coder's CLI release so production Cloud
serves any API contract the release expects. Use that workspace's own
`scripts/promote` — it fast-forwards every Cloud repo provider-first, skips
repos with no delta, and aborts all-or-nothing if any repo cannot
fast-forward:

```bash
cd ../openbase-cloud-workspace
./scripts/promote staging main
```

If a repo reports `diverged — cannot fast-forward`, linearize it (rebase its
staging onto main) and re-run; promote never creates merge commits.

If Cloud API or web changed, run the appropriate PaaS deploy/release monitor
from the `openbase-deploy` skill after `main` moves. Do not assume GitHub ref
promotion alone means ECS/static deployment finished.

## 2. super-agents first (only when it changed)

The release build resolves super-agents **from PyPI** via the cli pin —
workspace path sources are dev-only. Shipping new super-agents code requires
publishing before the CLI release starts:

1. Bump `version` in `super-agents/pyproject.toml` (PyPI rejects reused
   versions) and bump the cli pin in `cli/pyproject.toml`
   (`super-agents[claude]>=<new>`) so the release cannot silently take an
   older wheel.
2. Commit → push staging → merge to main → **push the tag directly**
   (`git tag v<new> && git push origin v<new>`). Tags created by workflows
   don't trigger publishing; direct pushes do.
3. Watch `publish-pypi.yml` succeed, then confirm:
   `curl -s https://pypi.org/pypi/super-agents/json | jq .info.version`.
   **Do not push cli main until PyPI serves the new version.**

Because step 3's `promote` pushes cli in the same burst as super-agents,
finish this step fully — PyPI serving the new version **and** super-agents
main advanced — before running the step-3 promotion. promote then skips
super-agents (already even).

If the repo rejects merge commits on main, linearize first and tag the final
main commit, not the staging merge commit. A tag pushed before main is fixed
can publish content from the staging DAG even if the later main tree is
equivalent.

## 3. Promote openbase-coder-workspace → main

Promote every Coder workspace repo's staging to main with `scripts/promote`,
**holding desktop back** — its electron build (~30 min) should seed the CLI
release this step produces, so it is promoted alone in step 5 to build once.
(The hold-back is a freshness optimization, not a safety requirement — see
"Not waiting is also fine" in step 5.)
promote pushes provider-first (cli ahead of the rest), skips repos with no
staging delta so they trigger no rebuild/release, and **aborts before pushing
anything** if any repo cannot fast-forward or if promoted content would pin a
sibling to a less-stable branch ref ("main must point to main"). The step-0
pre-release checks run automatically first; the console/desktop typechecks
run against the committed origin/FROM refs in a throwaway worktree assembly,
so another agent's dirty or untracked working-tree files can never fail (or
force `--skip-checks` on) a promotion.

```bash
# From the workspace root:
./scripts/promote staging main --exclude desktop
```

Pushing cli main auto-cuts the CLI release (step 4). Preview first with
`--dry-run` if you want to see the plan without running the checks or pushing.

- **Android APK is published automatically.** When this step promotes the
  `android` repo into main, `scripts/promote` runs `scripts/publish-android-apk`
  as its final action: it builds the debug APK, uploads versioned + latest
  keys to S3 (`android/scripts/build-and-upload-apk.sh`), and bumps the
  "Test build · vX.Y.Z" downloads-card label in the marketing repo's
  `site-content/install.html`, committing that one file and pushing
  `origin main` (which triggers the site deploy). It runs **after** all repo
  pushes, so an APK/upload/marketing failure never unwinds the promotions —
  it surfaces as a loud error summary and a non-zero exit at the very end; fix
  the cause and re-run `scripts/publish-android-apk` standalone. It skips (with
  a loud warning, not a failure) if the marketing checkout is missing or its
  `install.html` has uncommitted local changes.
- **Every** repo except desktop moves in this step, not just the ones you
  remember touching: a repo left on staging is silently baked into the release
  at its older main and nothing fails (the release's sibling-move guard only
  catches mains moving *during* the build, never a forgotten merge). promote
  handles this by promoting the whole set at once.
- If promote reports `diverged — cannot fast-forward` (protected mains reject
  merge commits — observed on cli, desktop, workspace, and super-agents),
  linearize that repo: rebase/cherry-pick its staging onto main and
  fast-forward, then re-run. `git cherry origin/main origin/staging` shows
  what still differs — `-` entries are patch-equivalent, only `+` entries need
  attention.
- Use a `[skip release]` head commit on cli if you are moving cli main without
  intending a release. Safe even while a release builds: since cli `e832c23`,
  `cancel-in-progress` is conditional on the head commit message, so a
  `[skip release]` push never cancels an in-flight release run (its own run
  skips itself, so cancelling would silently drop the predecessor's release —
  see AUTO_UPDATE.md's concurrency contract).

## 4. CLI auto-release

Pushing cli main runs `auto-release.yml` (minor bump by default;
`[release patch]`/`[release major]`/`[skip release]` head-commit overrides).

```bash
gh run list --repo openbase-community/openbase --workflow auto-release.yml --limit 1
gh run watch <id> --repo openbase-community/openbase --exit-status
```

Verify the published release: assets include the tarball, SHA256SUMS,
`update-manifest.json` **and `.sig`**; then prove the client path end-to-end:

```bash
cd cli && uv run python -c "from openbase_coder_cli.self_update import _fetch_manifest; m=_fetch_manifest('stable'); print(m['version'], m['channel'], list(m['repo_shas']))"
```

(That verifies the Ed25519 signature with the embedded key — it raises on any
mismatch.)

### Cloud DevSpace AMI relationship

A normal CLI GitHub Release plus desktop publish does **not** rebuild the Cloud
DevSpace AMI. Rebuild the AMI only when the change must be baked into newly
created DevSpaces (for example AMI helper scripts, OS packages, GUI/Tailscale
image setup, pre-baked workspace contents, or a baseline CLI version required
before `openbase-coder provision` can self-heal). `dev-ami/setup.sh` installs
the CLI from git — `main` for default AMIs, the workspace branch for staging
AMIs — so a rebake picks up the branch HEAD directly; `openbase-coder` is no
longer published to PyPI.

## 5. Desktop DMG publish

**CI is the publisher.** Pushing desktop `main` runs `electron-rebuild.yml`,
which builds, signs, notarizes, and publishes the DMG/zip/feed to S3
(~30 min), seeding the app with the **latest released** CLI package
(downloaded, never rebuilt). The manual flow below is the **fallback** for CI
outages.

Desktop was held back in step 3, so promote it **now** — only after step 4
proves the CLI GitHub Release exists and its package asset downloads — so the
single electron build seeds the just-released CLI. Everything else is already
even, so this promotes desktop alone:

```bash
# From the workspace root. --skip-checks is safe: the suite already passed in
# step 3 and cli is unchanged here (only desktop is pushed).
./scripts/promote staging main --skip-checks
```

Watch the run and confirm the macOS log shows `Staged Openbase Coder CLI
<version>` at the released version. (Bump `desktop/package.json` on staging
before step 3 when you want installed apps to auto-update — electron-updater
only moves to *higher* versions.)

**Not waiting is also fine.** `scripts/promote` never waits for the CI it
triggers; a one-shot `./scripts/promote staging main` (no `--exclude`) is
safe. The electron rebuild then starts before the CLI release finishes and
seeds the **previous** CLI release — installed apps still converge to the new
CLI through the update feed on next launch. Use the two-step hold-back when
you want the DMG pre-seeded with the just-released CLI (and one electron
build instead of two); use the one-shot when eventual freshness is enough.

The same principle applies across workspaces: cloud, coder, multi, and
boilersync each run their **own deploy lifecycle** from their own
`scripts/promote`, and nothing synchronizes them. A Cloud DevSpace AMI bake
snapshots this workspace's branches whenever it happens to run;
multi-react/boilersync-react enter builds at whatever their trunk `main`
holds. Cross-workspace freshness is eventually consistent by design — do not
add cross-workspace waits.

Known CI behaviors: the `rebuild linux` and `rebuild macOS` jobs publish
independently, so diagnose the failed job without assuming the other artifact
failed too. If BOTH jobs fail instantly with zero steps, the org has
exhausted its GitHub Actions spending limit — fix in org billing settings,
then `gh run rerun`. A `workflow_dispatch`ed release shares the concurrency
group with push runs and gets cancelled by any release-worthy push to main
mid-build; `[skip release]` pushes are the exception — they never cancel
(conditional `cancel-in-progress`, see AUTO_UPDATE.md).

When touching `desktop/.github/workflows/electron-rebuild.yml`, keep the
temporary CI root `package.json` entries in both jobs configured with
`pnpm.onlyBuiltDependencies: ["electron"]`. pnpm 10 otherwise skips
Electron's postinstall binary setup; electron-builder may still package from
its own cache, but the custom DMG background script calls `require("electron")`
and macOS fails late with `Electron failed to install correctly`. If you see
that error, fix the workflow approval first, then rerun after the CLI release
asset exists so the desktop seed is the current CLI version.

### Manual fallback

1. Bump `version` in `desktop/package.json` when you want installed apps to
   auto-update (electron-updater only updates to *higher* versions). Commit
   via staging → main as usual (`[skip release]` not needed — desktop main
   has no release workflow).
2. Stage the **released** CLI package (never a local build) and keep the
   seed dir free of stray archives — Apple's notary scanner inspects inside
   tarballs and fails the whole submission on their unsigned contents:

```bash
rm -rf /tmp/cli-seed && mkdir /tmp/cli-seed && cd /tmp/cli-seed
gh release download v<CLI_VERSION> --repo openbase-community/openbase \
  --pattern "openbase-coder-package-aarch64-apple-darwin.tar.gz"
tar xzf openbase-coder-package-*.tar.gz && rm openbase-coder-package-*.tar.gz
```

3. Publish (DMG is built by `scripts/build-dmg.mjs` via hdiutil — dmgbuild
   undersizes its volume for the ~1.7GB seeded app):

```bash
cd <workspace>/desktop
export APPLE_KEYCHAIN_PROFILE=openbase-coder-desktop \
       OPENBASE_CODER_DESKTOP_CLI_PACKAGE_DIR=/tmp/cli-seed
pnpm run dist:mac:publish
```

4. Verify S3: `latest-mac.yml` shows the new version and the DMG/zip return
   HTTP 200 under
   `https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac/`.

## Timing expectations (2026-07 baselines)

| Deploy | Typical duration |
|---|---|
| CLI auto-release (GHA) | ~3 min |
| Desktop CI build+notarize+publish | ~30 min |
| openbase-cloud API (`openbase-deploy`, warm cache) | ~7 min (build ~4, rollout ~3.5) |
| Static sites (web/marketing) | ~20 s after local build |

## 6. Post-deploy checks

- `openbase-coder self-update --check` on a standalone install reports the
  new version.
- An installed desktop app (lower version) offers "Restart to update".
- Cloud health endpoint responds, and any Cloud deploy run that was triggered
  from `openbase-cloud-workspace` finished successfully.
- Device registration still green:
  `uv run python -c "from openbase_coder_cli.services.cloud_registration import register_and_report; print(register_and_report().ok)"`.

## Known hazards

- **Syncthing** syncs `~/Projects` (including `.git`) with the mini: files
  can flap mid-commit/mid-build on this Mac. Build outputs are stignore'd;
  if a commit or copy fails mysteriously, suspect a sync flap first.
- The release workspace npm deps are pinned by
  `cli/scripts/release-workspace/pnpm-lock.yaml`; regenerate it with
  `cli/scripts/update-release-lockfile.sh` after changing frontend deps, or
  the release build fails on a frozen-lockfile mismatch.
- PyPI publishing of `openbase-coder` itself (dev channel) only happens on a
  directly pushed tag; auto-release tags don't trigger it. Optional.
- Version stamping: hatch-vcs only honors the unsuffixed
  `SETUPTOOLS_SCM_PRETEND_VERSION`; the `_FOR_<dist>` variant is silently
  ignored (the release build has a guard that fails on a bad stamp).
- Marketing pickup is automatic: openbase-landing's "Download for Mac"
  points at the S3 `Openbase-Coder-latest-arm64.dmg` alias (refreshed by
  every publish), and `openbase.cloud/ios` is a forwarder page in
  openbase-voice-marketing `public/ios/index.html` — the single place the
  TestFlight/App Store destination is defined.

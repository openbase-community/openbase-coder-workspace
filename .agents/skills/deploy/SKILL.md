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

- All repos in both workspaces committed and pushed on `staging`; cli suite
  green (`cd cli && uv run pytest`), console/desktop typechecks clean, and
  Cloud API tests green for any API changes.
- No parallel agent mid-commit in these repos.
- This Mac has: the `openbase-coder-desktop` notarytool keychain profile, a
  Developer ID identity in the keychain, default AWS credentials for the
  releases bucket.

## 1. Promote openbase-cloud-workspace → main first

Promote every Cloud workspace repo's `staging` to `main` before Coder's CLI
release. This ensures production Cloud serves any API contract that the Coder
release expects.

Use remote fast-forwards when possible so local unrelated dirty files do not
block the deploy. If `origin/main` is not an ancestor of `origin/staging`, stop
and linearize that repo intentionally.

```bash
cd ../openbase-cloud-workspace
for r in . api auth-client api-core dev-ami web; do
  git -C "$r" fetch origin --quiet
  git -C "$r" rev-parse --verify --quiet origin/staging >/dev/null || continue
  [ -z "$(git -C "$r" log --oneline origin/main..origin/staging)" ] && continue
  git -C "$r" merge-base --is-ancestor origin/main origin/staging
  git -C "$r" push origin origin/staging:main
done
```

Gate before moving on — this must print nothing:

```bash
for r in . api auth-client api-core dev-ami web; do
  git -C "$r" fetch origin --quiet
  git -C "$r" rev-parse --verify --quiet origin/staging >/dev/null || continue
  git -C "$r" log --oneline origin/main..origin/staging |
    sed "s|^|UNMERGED cloud $r: |"
done
```

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

If the repo rejects merge commits on main, linearize first and tag the final
main commit, not the staging merge commit. A tag pushed before main is fixed
can publish content from the staging DAG even if the later main tree is
equivalent.

## 3. Promote openbase-coder-workspace → main — cli last, desktop after cli

**Every** Coder workspace repo's staging moves to main in this step, in one
sitting — not just the repos you remember touching. A repo left on staging is
silently baked into the release at its older main and nothing fails: the
release's sibling-move guard only catches mains moving *during* the build,
never a forgotten merge.

Merge every non-cli/non-desktop repo first (repos without a staging branch or
with no delta are skipped). Hold desktop until step 4: pushing desktop main
starts its publisher immediately, and it seeds from the latest already
published CLI release.

```bash
# From the workspace root:
for r in . console coder-react multi-react boilersync-react skills \
         super-agents ios android allauth-client-swift \
         allauth-client-kotlin agent-work-scheduler; do
  git -C "$r" fetch origin --quiet
  git -C "$r" rev-parse --verify --quiet origin/staging >/dev/null || continue
  [ -z "$(git -C "$r" log --oneline origin/main..origin/staging)" ] && continue
  echo "== $r"
  git -C "$r" checkout main && git -C "$r" pull --ff-only &&
    git -C "$r" merge --no-edit staging && git -C "$r" push origin main &&
    git -C "$r" checkout staging
done
```

Then gate before touching cli — this must print nothing:

```bash
for r in . console coder-react multi-react boilersync-react skills \
         super-agents ios android allauth-client-swift \
         allauth-client-kotlin agent-work-scheduler; do
  git -C "$r" rev-parse --verify --quiet origin/staging >/dev/null || continue
  git -C "$r" log --oneline origin/main..origin/staging |
    sed "s|^|UNMERGED $r: |"
done
```

Only when the gate is clean, merge cli the same way. cli goes **last**
because its main push triggers auto-release, and the release's sibling-move
guard fails if sibling mains move mid-build. Use a `[skip release]` head
commit if you are moving cli main without intending a release.

- The workspace repo requires **linear history**: rebase staging onto main if
  they diverged, then fast-forward.
- Some protected mains reject merge commits even for admins (observed on cli,
  desktop, workspace, and super-agents). If a push is rejected for linear
  history, rebase/cherry-pick staging onto main and fast-forward main. When
  staging and main end up with different SHAs for the same patches, use
  `git cherry origin/main origin/staging`; `-` entries are patch-equivalent
  and only `+` entries still need attention.
- Do not push desktop main here. Desktop publishes after the CLI release has
  completed and its assets are downloadable.

## 4. CLI auto-release

Pushing cli main runs `auto-release.yml` (minor bump by default;
`[release patch]`/`[release major]`/`[skip release]` head-commit overrides).

```bash
gh run list --repo openbase-community/openbase-coder --workflow auto-release.yml --limit 1
gh run watch <id> --repo openbase-community/openbase-coder --exit-status
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
before `openbase-coder provision` can self-heal). If you are rebuilding the AMI
to pick up a new `openbase-coder` baseline, publish `openbase-coder` to PyPI via
a directly pushed tag first; auto-release-created tags do not trigger PyPI, and
`dev-ami/setup.sh` installs the CLI with `uv tool install openbase-coder`.

## 5. Desktop DMG publish

**CI is the publisher.** Pushing desktop `main` runs `electron-rebuild.yml`,
which builds, signs, notarizes, and publishes the DMG/zip/feed to S3
(~30 min), seeding the app with the **latest released** CLI package
(downloaded, never rebuilt). Normally the whole step is: bump
`desktop/package.json` version, push main, watch the run. The manual flow
below is the **fallback** for CI outages.

Only push desktop main after step 3 proves the CLI GitHub Release exists and
the package asset downloads. If desktop main was pushed early, the run can
seed the previous CLI version without failing; rerun it after the CLI release
and inspect the macOS log for `Staged Openbase Coder CLI <version>`.

Known CI behaviors: the `rebuild linux` and `rebuild macOS` jobs publish
independently, so diagnose the failed job without assuming the other artifact
failed too. If BOTH jobs fail instantly with zero steps, the org has
exhausted its GitHub Actions spending limit — fix in org billing settings,
then `gh run rerun`. A `workflow_dispatch`ed release shares the concurrency
group with push runs and gets cancelled by any push to main mid-build.

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
gh release download v<CLI_VERSION> --repo openbase-community/openbase-coder \
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
- Sourcing all of `~/Developer/.env` replaces AWS credentials with a
  restricted user — export only the specific vars you need.
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

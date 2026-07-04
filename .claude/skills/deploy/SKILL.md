---
name: deploy
description: Run a full Openbase Coder deployment — super-agents to PyPI when changed, CLI auto-release from main, desktop DMG publish with the released CLI seed. Use when asked to deploy, release, or ship Openbase Coder.
---

# Openbase Coder Deployment

Full production deploy, in dependency order. The contract behind each step is
the workspace `AUTO_UPDATE.md`; this skill is the operational runbook.

Dependency graph: super-agents (PyPI) → CLI standalone package (GitHub
Releases, via auto-release) → desktop DMG (S3, bundles the released CLI as
its first-install seed). Sibling JS repos (console, coder-react, multi-react,
boilersync-react, skills) are baked into the CLI package from their main
branches. The cloud backbone (openbase-cloud) deploys independently via
`openbase-deploy` and must already serve any API contract the release needs.

## 0. Preconditions

- All repos committed and pushed on `staging`; cli suite green
  (`cd cli && uv run pytest`), console/desktop typechecks clean.
- No parallel agent mid-commit in these repos.
- This Mac has: the `openbase-coder-desktop` notarytool keychain profile, a
  Developer ID identity in the keychain, default AWS credentials for the
  releases bucket.

## 1. super-agents first (only when it changed)

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

## 2. Merge to main — siblings first, cli last

```bash
# per repo: console coder-react multi-react boilersync-react skills super-agents (and . / ios / allauth-* as relevant)
git checkout main && git pull --ff-only && git merge --no-edit staging && git push && git checkout staging
```

- The workspace repo requires **linear history**: rebase staging onto main if
  they diverged, then fast-forward.
- cli goes **last**: its main push triggers auto-release, and the release's
  sibling-move guard fails if sibling mains move mid-build.

## 3. CLI auto-release

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

## 4. Desktop DMG publish

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

## 5. Post-deploy checks

- `openbase-coder self-update --check` on a standalone install reports the
  new version.
- An installed desktop app (lower version) offers "Restart to update".
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

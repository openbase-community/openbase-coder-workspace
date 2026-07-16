# Auto-Update Guide

How Openbase components are released, distributed, and updated. This is
the durable contract: consult it before touching release workflows, the
updater, state-file schemas, or version handshakes — and keep it current when
they change.

## Update topology

Each component owns its own update; nothing installs into another component.

| Component | Distribution | Updated by |
|---|---|---|
| Desktop app (macOS DMG) | S3 (`publish-s3.mjs`) with an electron-updater generic feed (`latest-mac.yml` + zip) | electron-updater in the app itself |
| CLI runtime package (standalone) | GitHub Releases on `openbase-community/openbase-coder` | `openbase-coder self-update` |
| Backend CLIs (`~/.openbase/bin/codex`) | GitHub release binaries | refreshed during `self-update` (`claude` self-updates on its own) |
| PyPI (`openbase-coder`, `super-agents`, `open-approvals`) | PyPI via GitHub Actions trusted publishing on tags | `uv tool upgrade` — **dev channel only**, never an auto-update path |
| iOS app | App Store/TestFlight (future) | out of scope here |

Rules that must not regress:

- The CLI package bundled inside the desktop DMG is a **first-install seed
  only**. After activation, the GitHub release feed is the sole authority; the
  desktop app triggers CLI updates through the local API
  (`POST /api/update/apply`), it never installs the CLI itself.
- **Dev-workspace installs never auto-update.** `self-update` refuses when the
  CLI is not running from a standalone runtime package; dev checkouts are
  git-managed.
- Headless installs (e.g. a Mac mini with no desktop app) rely solely on
  `openbase-coder self-update`; every update capability must work without the
  desktop app.

## Release artifacts and the update manifest

`cli/.github/workflows/release-standalone.yml` produces, per tag:

- `openbase-coder-package-<target>.tar.gz` — the runtime package
- `openbase-coder-package_SHA256SUMS`
- `update-manifest.json` (+ `update-manifest.json.sig` when signing is
  configured) — built by `cli/scripts/build_update_manifest.py`
- `install.sh`

Manifest schema (`manifest_schema` 1):

```json
{
  "manifest_schema": 1,
  "channel": "stable",
  "version": "0.2.0",
  "layout_version": 1,
  "min_supported_version": "0.1.0",
  "python_version": "3.12.8",
  "targets": {
    "aarch64-apple-darwin": {"url": "...", "sha256": "...", "size": 123}
  },
  "repo_shas": {"cli": "...", "console": "...", "skills": "..."}
}
```

- The **stable** channel resolves via
  `releases/latest/download/update-manifest.json`; the **beta** channel
  resolves the newest release including prereleases via the GitHub API.
- `repo_shas` pins the exact sibling-repo commits baked into the package
  (also stamped into `openbase-coder-package.json`) so releases are
  reproducible and diagnosable.
- The manifest is signed with an Ed25519 key (`OPENBASE_UPDATE_SIGNING_KEY`
  repo secret); the client embeds the public key in
  `openbase_coder_cli/self_update.py`, and signature verification is
  mandatory — never ship a client that downgrades this.
- Key custody: GitHub secrets are write-only, so the private key is also kept
  outside any git repo under `~/Projects/openbase/secure/`. Rotating the key
  is a client-release-first operation: ship a client embedding the new public
  key before signing manifests with the new private key.

## Release-time race protections

Multi workspaces push all subrepos together, and the release workflow checks
sibling repos out at their branch HEADs, so two protections apply:

- **Sibling-move guard**: before publishing, the workflow re-fetches every
  sibling repo and fails the release if any HEAD moved during the build — a
  moved HEAD means the packaged snapshot may be incoherent. Re-tag after the
  push settles. (The cli repo itself is pinned by the tag and cannot race.)
- **Draft-then-publish**: the GitHub release is created as a draft, all assets
  upload, and only then is it published — `releases/latest` and the update
  manifest never point at a release whose artifacts are still uploading.

Release ordering discipline: push all subrepos first, then push the tag.

## Auto-release from main

Every push to `main` in the cli repo cuts a stable release automatically
(`auto-release.yml`): the next version is computed from the highest stable
tag (**minor bump by default**) and the release build runs in the same
workflow run (tags pushed with `GITHUB_TOKEN` cannot trigger workflows, so
tag-triggering is not used). `concurrency: cancel-in-progress` makes a burst
of pushes release once, from the final state.

- Commit-message overrides on the pushed head commit: `[skip release]`,
  `[release patch]`, `[release major]`.
- Manual releases: `workflow_dispatch` on auto-release (bump choice) or on
  release-standalone directly (exact version, draft option).
- `staging` and all other branches never release — pushes to `main` are
  production. Sibling-only changes (console, skills, …) need a manual
  dispatch since only cli pushes trigger auto-release.
- The release build stamps the release version into the packaged CLI
  (`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENBASE_CODER`) so
  `openbase-coder --version` matches the package version.

## Dormant Intel (x86_64) pathway

Two manual-only (`workflow_dispatch`) workflows exist so Intel Macs *could*
be supported someday; neither runs automatically and nothing serves their
output to users yet:

- `cli/.github/workflows/release-standalone-intel.yml` — given an existing
  release tag, rebuilds the standalone package on the `macos-15-intel`
  runner (GitHub's last Intel image, supported through August 2027) at the
  exact `repo_shas` snapshot from that release's update manifest, then
  attaches `openbase-coder-package-x86_64-apple-darwin.tar.gz` (+ its own
  `_SHA256SUMS`) to the release. It never creates releases and never touches
  `update-manifest.json`, `install.sh`, or the arm64 sums file — the update
  feed gains no x86_64 target.
- `desktop/.github/workflows/electron-intel-installer.yml` — builds a
  signed, notarized x64 DMG (`pnpm run dist:mac:x64`;
  `OPENBASE_CODER_MAC_ARCH=x64` steers `build-dmg.mjs`) seeded with the
  release's Intel CLI package, and uploads it only as a workflow artifact —
  no S3 publish, no update feed, no marketing-site wiring.

Bringing Intel online later means: merging an `x86_64-apple-darwin` target
into the update manifest (`build_update_manifest.py --merge-existing`),
adding a desktop S3 publish step, and wiring downloads — all deliberate,
separate work.

## Inspecting versions

Every versioned piece is inspectable without MCP:

| Piece | How to inspect |
|---|---|
| CLI + package + channel + update flags | `openbase-coder version` (`--json` for machine use) |
| CLI (bare) | `openbase-coder --version` |
| Server/API | `GET /api/update/status/` or the `versions` block of `GET /api/onboarding/status/` |
| Standalone package | `openbase-coder-package.json` in the package root |
| super-agents | `super-agents-mcp --version` / `super-agents-backend --version` |
| Desktop app | shown in the app UI (and macOS About menu) |
| Console | shows the CLI/package version it is served by (they version together) |
| livekit-server / codex / claude | each binary's own `--version` |
| syncthing (optional, downloaded on `sync enable`) | pinned in `code_sync/install.py`; `syncthing --version` |
| Plugins | `openbase-coder plugins list` |

## The CLI self-update sequence

`openbase-coder self-update` (all steps in `openbase_coder_cli/self_update.py`):

1. **Refuse in dev mode** (no runtime package detected).
2. **Take the update lock** (`packages/standalone/.self-update.lock`,
   non-blocking flock) so concurrent invocations — desktop-triggered, manual,
   scripted — defer instead of racing the extract/flip.
3. Fetch the manifest for the install's channel (from
   `openbase-coder-package.json`); verify signature when the key is set.
4. Compare versions; honor `min_supported_version` and any cloud-reported
   minimum; stop if `layout_version` is newer than the updater understands.
5. **Quiesce**: if a voice session is active, defer (override with `--force`).
6. Download the target tarball, verify SHA-256, extract to
   `~/.openbase/packages/standalone/releases/<version>-<target>/`, validate the
   package (metadata, launcher, livekit-server), smoke-run
   `bin/openbase-coder --version`.
7. **Atomic flip**: repoint the `current` symlink (temp symlink + rename);
   keep the outgoing release behind a `previous` symlink; prune older releases
   (keep 2).
8. **Post-flip via the NEW launcher**: regenerate + restart services
   (`services install`), rebuild the plugin site when the bundled Python
   minor version changed (`plugins rebuild-site`), refresh
   `~/.openbase/bin/codex` when it was installed by us.
9. **Health gate**: services installed + `--version` sane. On failure, flip
   back to `previous`, reinstall services, and report the rollback.

The user-facing shim (`~/.local/bin/openbase-coder`) and service wrappers
point through `current`, so a flip atomically retargets everything — but
service wrappers embed resolved paths, which is why step 8's regeneration is
mandatory after every flip.

## State-file schema versions

Every Openbase-owned state file carries a `schema_version` (all currently 1):

- `~/.openbase/installation.json`
- `~/.openbase/dispatcher-config.json`
- `~/.openbase/plugins/plugins.json`

The rules (this is the lesson of the pre-1.0 legacy purge — no silent
fallback reads, ever):

- Readers **refuse** files with a `schema_version` greater than they
  understand ("written by a newer version — update the CLI").
- Schema changes ship a forward-only migration that runs once at read time,
  bumps the version, and can be deleted after a deprecation window.
- Never add "read the old key as a fallback" code paths.

## Version handshake and kill switch

- `GET /api/onboarding/status/` includes a `versions` block: CLI version,
  package target, channel, layout version, and `update_available` /
  `update_required` flags.
- The CLI's cloud registration report includes its version; the cloud response
  may carry `minimum_cli_version`, cached locally and surfaced as
  `update_required` (the remote kill switch for bad releases). Clients (iOS,
  console, desktop) render "update your Mac" from these flags rather than
  guessing.

## Desktop app updates

electron-updater with the `generic` provider pointed at the S3 prefix that
`publish-s3.mjs` uploads to. Publishing must upload the DMG, the **zip**
target (electron-updater on macOS updates from the zip), and `latest-mac.yml`.
Signing identity must remain the same Developer ID across releases or the
updater rejects the download.

For local packaged testing, `pnpm run install:local` in the desktop repo
builds without the CLI seed/companion, stamps `openbaseDevBuild: true`
(which disables auto-update for that build), and copies the app to
`/Applications`.

The DMG itself is a styled drag-to-install image (branded Retina background,
app + Applications layout) built by `desktop/scripts/build-dmg.mjs`; see the
desktop `RELEASE.md`. On the first packaged launch from `/Applications`, the
app offers to eject the mounted install DMG and move the downloaded `.dmg`
to the Trash, listing the exact volumes and files in the dialog
(`desktop/electron/installer-cleanup.cjs`). A packaged launch from anywhere
else offers to move the app to `/Applications` (the only supported install
location) and relaunch. Responses are remembered in the app's userData
directory, so each prompt appears at most once per installation and never
for `openbaseDevBuild` installs; automation can suppress both prompts with
`OPENBASE_DESKTOP_DISABLE_INSTALLER_CLEANUP=1`.

## Channels

`channel` is stamped into `openbase-coder-package.json` at build time
(default `stable`). Tags containing a prerelease suffix (e.g. `v0.2.0b1`)
publish as GitHub prereleases and serve the `beta` channel. An install stays
on its channel until reinstalled.

## PyPI (dev channel)

`cli` and `super-agents` publish to PyPI on tag pushes via GitHub Actions
**trusted publishing** (OIDC — no tokens or credentials stored anywhere).
The PyPI projects must have the corresponding workflow registered as a
trusted publisher (Manage → Publishing on pypi.org). These packages exist for
`uv tool install` developer convenience; user-facing updates never flow
through PyPI.

Gotcha: tags created *by* the release workflow (via `GITHUB_TOKEN`) do not
trigger `publish-pypi.yml` — GitHub suppresses token-initiated events. Push
tags directly to publish to PyPI.

## Invariants checklist for changes in this area

- [ ] Updates remain atomic (flip a symlink; never mutate a release in place)
- [ ] Rollback path exists and is tested (`previous` symlink + health gate)
- [ ] Services are regenerated after every flip
- [ ] Dev-workspace installs are excluded
- [ ] State files carry `schema_version`; no fallback reads of old keys
- [ ] Manifest/signature verification is never weakened in shipped clients
- [ ] Headless (no-desktop) installs can complete the whole flow
- [ ] Concurrent self-updates are serialized by the update lock
- [ ] Releases are draft-first and fail on mid-build sibling pushes

# Auto-Update Guide

How Openbase Coder components are released, distributed, and updated. This is
the durable contract: consult it before touching release workflows, the
updater, state-file schemas, or version handshakes — and keep it current when
they change.

## Update topology

Each component owns its own update; nothing installs into another component.

| Component | Distribution | Updated by |
|---|---|---|
| Desktop app (macOS DMG) | S3 (`publish-s3.mjs`) with an electron-updater generic feed (`latest-mac.yml` + zip) | electron-updater in the app itself |
| CLI runtime package (standalone) | GitHub Releases on `openbase-community/openbase` | `openbase-coder self-update` |
| Backend CLIs (`~/.openbase/bin/codex`) | GitHub release binaries | refreshed during `self-update` (`claude` self-updates on its own) |
| PyPI (`openbase-coder`, `super-agents`) | PyPI via GitHub Actions trusted publishing on tags | `uv tool upgrade` — **dev channel only**, never an auto-update path |
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
  "repo_shas": {
    "cli": "...", "console": "...", "coder-react": "...",
    "multi-react": "...", "boilersync-react": "...", "super-agents": "...",
    "skills": "...", "workspace": "..."
  }
}
```

- The **stable** channel resolves via
  `releases/latest/download/update-manifest.json`; the **beta** channel
  resolves the newest release including prereleases via the GitHub API.
- `repo_shas` pins the exact sibling-repo commits baked into the package
  (also stamped into `openbase-coder-package.json`) so releases are
  reproducible and diagnosable.
- **super-agents is built from its sibling checkout, not PyPI.** The package
  build installs the `super-agents` checkout from source (and fails if the
  checkout is missing or if the cli's version floor would pull a PyPI wheel
  over it), so the runtime package rides branch HEADs exactly like the JS
  siblings. The `super-agents[claude]>=x.y.z` floor in `cli/pyproject.toml`
  only governs dev-channel installs that resolve from PyPI.
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

## Auto-release from main and staging

Every push to `main` in the cli repo cuts a stable release automatically
(`auto-release.yml`): the next version is computed from the highest stable
tag (**minor bump by default**) and the release build runs in the same
workflow run (tags pushed with `GITHUB_TOKEN` cannot trigger workflows, so
tag-triggering is not used). Per-branch `concurrency` groups make a burst of
pushes release once, from the final state, without staging and main builds
cancelling each other.

Every push to `staging` cuts a **staging-channel release** the same way:
the version is the next stable version with a `.dev<UTC timestamp>` suffix
(PEP 440 — sorts below the stable it precedes), published as a GitHub
prerelease, with every sibling repo checked out at its **staging** HEAD
(`sibling_ref` input). The `.dev` marker in the tag is what routes the
release to the staging channel; `releases/latest` and beta resolution both
exclude it.

- Commit-message overrides on the pushed head commit: `[skip release]`,
  `[release patch]`, `[release major]`.
- Manual releases: `workflow_dispatch` on auto-release (bump choice) or on
  release-standalone directly (exact version, draft option, sibling branch).
- Pushes to `main` are production; pushes to `staging` serve only
  staging-channel installs. Sibling-only changes (console, skills, …) need
  a manual dispatch since only cli pushes trigger auto-release.
- The release build stamps the release version into the packaged CLI
  (`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OPENBASE_CODER`) so
  `openbase-coder --version` matches the package version.

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

Updates apply through three triggers, all funneling into the same locked
sequence below:

- **Automatic (default)**: the `openbase-routines` service checks the feed
  every 6 hours on standalone installs and, when an update is available,
  spawns `openbase-coder self-update` as a detached process (detached because
  applying an update reinstalls services, including the routines service
  itself). Required updates (below `min_supported_version` or the
  cloud-reported minimum) are spawned with `--force`; merely-available
  updates are attempted once per version per runner process so a release
  that rolls back on health checks does not churn service restarts every
  cycle. Opt out with `OPENBASE_CODER_AUTO_UPDATE=0` (environment or
  `~/.openbase/.env`). Detached-run output lands in
  `~/.openbase/logs/self-update.log`.
- **Manual**: `openbase-coder self-update` (`--check`, `--force`, `--json`).
- **UI-driven**: the console/desktop update button hits the update API.

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
point through `current`, so a flip atomically retargets everything. Service
wrappers embed package paths routed through the `current` alias, derived from
the runtime package at generation time — `installation.json` deliberately
records no package paths (the `current` symlink is the single source of
truth), so a stale config can never strand services on a pruned release.
Step 8's regeneration is still mandatory after every flip (templates, backend
binaries, and the bundled Python can change between releases).

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

**Linux (Cloud DevSpace) does not self-update.** The DevSpace AMI installs
the AppImage into root-owned `/opt/openbase-coder-desktop/`, where
electron-updater's in-place replace fails with `EACCES` (it unlinks and
rewrites the file next to itself, which needs directory write access). The
AMI's `/usr/local/bin/openbase-coder-desktop` launcher therefore exports
`OPENBASE_DESKTOP_DISABLE_AUTOUPDATE=1`; DevSpaces receive new desktop builds
through AMI rebakes (see the deploy skill's "Cloud DevSpace AMI
relationship"), which fetch the `Openbase-Coder-latest-x86_64.AppImage`
object from the release bucket.

The visible desktop product and artifacts are named **Openbase**
(`Openbase.app`, `Openbase-<version>-<arch>.*`). Compatibility identifiers do
not change: the bundle ID remains `tech.openbase.coder.desktop`, the update
feed remains at the existing S3 prefix, and the deep-link scheme remains
`openbase-coder://`. The first renamed build keeps the legacy Electron
user-data directory and migrates `/Applications/Openbase Coder.app` to
`/Applications/Openbase.app` before opening the main window.

During the naming transition, desktop publishing also refreshes the legacy
`Openbase-Coder-latest-*` S3 aliases used by existing landing and Cloud
download links. Those aliases point at the new Openbase artifacts and can be
removed only after every consumer has moved to `Openbase-latest-*`.

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
(default `stable`). An install stays on its channel until reinstalled. The
version suffix partitions the channels:

| Channel | Version shape | Resolution |
|---|---|---|
| `stable` | `X.Y.Z` | `releases/latest` (GitHub excludes prereleases) |
| `beta` | `X.Y.Zb1` / `a`/`rc` suffix | newest non-`.dev` release with a manifest |
| `staging` | `X.Y.Z.dev<timestamp>` | newest `.dev` release with a manifest |

The staging channel is the CLI half of the full staging chain: staging
desktop builds (see below) seed and update from staging CLI releases, which
embed every sibling repo's staging HEAD — staging Electron depends on
staging cli depends on staging super-agents, exactly as main does with
main. Exception: multi-react and boilersync-react are external trunk-based
projects and are always built from **main** on both channels (`multi.json`
pins them via `fixedBranch`, and the release/rebuild workflows and the
moved-HEAD guard hardcode `main` for them). `.dev` releases publish as
GitHub prereleases, so they are invisible to `releases/latest`, and
`_prerelease_manifest_urls` filters them out of beta resolution
(`cli/openbase_coder_cli/self_update.py`).

**Staging desktop builds** (`desktop/.github/workflows/electron-rebuild.yml`
on staging pushes): internal siblings check out at staging HEADs (the two
external repos stay on main, as above), the app version is
stamped `X.Y.Z-staging.<timestamp>` (each staging push is an update; the
next stable sorts above all of them), the electron-updater feed URL is
rewritten to the `mac-staging`/`linux-staging` S3 prefixes, the CLI seed is
the newest staging-channel CLI release, and the app icon is generated with
an amber tile (`OPENBASE_DESKTOP_ICON_VARIANT=staging`) so staging installs
are visually unmistakable. The app identity (bundle ID, product name, deep
link scheme) is unchanged: a machine installs either the production or the
staging desktop app, and each updates only from its own feed.

## PyPI (dev channel)

`cli` and `super-agents` publish to PyPI on tag pushes via GitHub Actions
**trusted publishing** (OIDC — no tokens or credentials stored anywhere).
The PyPI projects must have the corresponding workflow registered as a
trusted publisher (Manage → Publishing on pypi.org). These packages exist for
`uv tool install` developer convenience and as the default-channel mechanism
the Openbase Cloud DevSpace AMI uses to bake in the CLI (`dev-ami/setup.sh`
runs `uv tool install openbase-coder`; staging AMIs instead install the coder
repo's staging branch from git with `--no-sources`, which still resolves
super-agents from PyPI). User-facing updates never flow through PyPI, and
PyPI is not an advertised installation pathway (see `GLOSSARY.md` →
Installation pathways). Note the released runtime package does **not** take
super-agents from PyPI (see the manifest section); PyPI-resolved super-agents
is a dev/AMI-channel behavior only.

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

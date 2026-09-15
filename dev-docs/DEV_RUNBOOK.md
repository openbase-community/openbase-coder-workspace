# Dev Runbook

The recommended path for developing and testing Openbase Coder starts at the GitHub workspace and runs `./scripts/setup`. This is the dev counterpart to the standalone/production install (see `AUTO_UPDATE.md` for how that side ships). Follow it top to bottom for a fresh machine; jump to [Iterating](#5-iterating) day to day.

## 1. One-time prerequisites

- `uv`, Node + pnpm (via nvm), and the current Go toolchain from [go.dev/dl](https://go.dev/dl/). The source-workspace path builds the Openbase Direct transport from `cli/tunneld`, so Go is required even when the current test selects another transport. (`livekit-server` is downloaded at the release-pinned version by setup into `~/.openbase/bin`; a Homebrew `livekit-server` is only a fallback and will warn if its version skews.)
- `multi` (`uv tool install multi-workspace`)
- A tailnet transport for phone access. Interactive developer setup offers the expert Tailscale transport, Openbase VPN, and Openbase Direct. Electron production onboarding is different: it offers only Openbase VPN or Direct.
- Coding-backend login: `codex login` for the codex backend, and/or your normal Claude Code login (setup bridges it into Openbase's managed config automatically on macOS)
- Only if you pick **Openbase VPN**, and only on macOS: the hardened VPN companion is closed-source, but a public checkout downloads its signed prebuilt and needs no extra build tools. An internal checkout with the private `netmesh-macos` source builds the companion with Xcode, `xcodegen`, and Go. Openbase Direct and the expert standalone-Tailscale transport do not use this companion; Linux and Windows use the official Tailscale client instead of the macOS companion.

Setup fails fast with the fix command if `uv`, `multi`, Go, Node, or pnpm is missing; the selected networking transport reports its other prerequisites. Picking the netmesh VPN likewise fails fast listing exactly which build tools are missing and how to install each (the authoritative list lives in that check, not here, so it can't drift). A missing `codex login` only warns (threads fail later until you log in).

## 2. Install

```bash
git clone https://github.com/openbase-community/openbase-coder-workspace
cd openbase-coder-workspace
./scripts/setup            # no flags = interactive pickers; or pass --backend codex
```

Setup puts `openbase-coder` on PATH via a shim at `~/.local/bin` that runs the workspace venv — the same interpreter the services use, so the terminal CLI and the services can never disagree about dependencies. (If a `uv tool install openbase-coder` shim exists, setup replaces it and tells you; run `uv tool uninstall openbase-coder` to drop the orphaned venv.)

With no flags, setup runs the interactive first-run pickers (coding backend and voice audio provider), then offers `openbase-coder login`, verifies cloud device registration and Tailscale Serve health, and prints a phone-downloads QR code. Any flag makes the run non-interactive (a fresh install then requires `--backend`). The picker/flag semantics are owned by [`cli/docs/commands/setup.md`](../cli/docs/commands/setup.md) — don't restate them here.

`scripts/setup` preserves the checkout's Multi install set: if any internal-only repo is already checked out it syncs `internal`; otherwise it syncs `default` so a public clone never requires private repo access. Multi clones any missing repositories in that selected set. Setup then creates the CLI venv, downloads LiveKit model files, builds the console, generates `~/.openbase` (environment, agent homes, and dispatcher config), installs the launchd services, and configures the selected private network. If a standalone install or another development workspace install already exists, it stops and points to https://docs.openbase.cloud/uninstall/ before making changes.

Branch selection is explicit. If the workspace root is on `develop`, `multi sync` clones missing unlocked repositories on `develop`, and setup verifies the selected install set to refuse any existing unlocked repository still on another branch. Four repositories are intentional trunk dependencies and remain on their `multi.json` `fixedBranch` of `main`: `netmesh-go`, `netmesh-macos`, `multi-react`, and `boilersync-react`. Everything else in the selected install set must match the workspace branch. Run `node scripts/check-workspace-branches.mjs . default` for a public checkout or replace `default` with `internal` for the full workspace. Use `multi set-branch develop` from a completely clean workspace to correct a mismatch.

A source-workspace install targets production Openbase Cloud by default even when the workspace branch is `develop`; the local CLI, console, desktop launcher, skills, and Super Agents still come from the checked-out branches described above. This is not a third develop environment: only production and staging Cloud deployments exist. When local develop code depends on a Cloud change not yet in production, choose staging before setup and before login so the endpoint is persisted into `~/.openbase/.env`:

```bash
OPENBASE_CODER_CLI_WEB_BACKEND_URL=https://app-staging.openbase.cloud ./scripts/setup
```

Do not reuse production login tokens after changing the endpoint; run `openbase-coder login` against the selected Cloud. Verify the installed mix with the install-set-aware branch checker above, `openbase-coder version`, and the `OPENBASE_CODER_CLI_WEB_BACKEND_URL` entry in `~/.openbase/.env` (absence means the production default).

The **Openbase VPN companion** is a separate axis from the workspace branch. Its prebuilt channel is resolved in this order: an explicit `OPENBASE_CODER_RELEASE_PREFIX`, the staging Cloud endpoint (`OPENBASE_CODER_CLI_WEB_BACKEND_URL=https://app-staging.openbase.cloud` selects `mac-staging`), a package version containing `-staging.`, then production `mac`. The companion remains control-plane-agnostic at runtime — it joins whichever Headscale URL accompanies the enrollment key — but staging setup deliberately downloads the staging prebuilt so an unreleased companion dependency can be tested without crossing release channels. Set a full `OPENBASE_NETMESH_COMPANION_URL` only when intentionally sampling a specific artifact.

## 3. Authenticate

```bash
openbase-coder login
```

Browser OAuth against app.openbase.cloud; tokens land in `~/.openbase/auth.json`. Required for iOS pairing and cloud onboarding.

If setup selected Openbase VPN or Openbase Direct before an Openbase login existed, setup prepares that transport without treating its expected `NeedsLogin` state as a failure. A successful `openbase-coder login` then records the configured transport as the account-level choice, mints an enrollment key, connects the selected transport, restarts the transport-dependent services, and re-registers the computer automatically; Direct also saves the matching staging or production control URL. If login already exists, setup performs the same reconciliation itself after its routes are ready, so the phone should never retain Cloud's previous/default transport while the computer silently uses another one. No second transport command should be necessary. A later setup rerun reuses an already-connected VPN or persisted Direct node instead of demanding another single-use key, then re-reports the final private address to Cloud after route health is known. If automatic reconciliation warns, repeat the supported transport action with `openbase-coder tailnet set-provider netmesh` for Openbase VPN or `openbase-coder tailnet set-provider netmesh-tsnet` for Direct; do not use the low-level `tailnet enroll` command as the normal recovery path. An `invalid pre auth key` error on Direct means the installed `OPENBASE_TSNET_CONTROL_URL` does not match the Cloud environment that minted the key, not that the account password is wrong.

> Quirk to expect: the login-success page deep-links
> `openbase-coder://…`, so if a desktop app is installed, macOS focuses it.
> That page is shared with desktop onboarding — ignore it; the terminal's
> "Logged in successfully" is the source of truth for CLI login.

### Physical-iPhone field-test ordering

When this developer install is sampled in a field test, use this runbook only for the developer-workspace setup mechanics. The [`field-testing` skill's documentation-ownership section](../.agents/skills/field-testing/SKILL.md#documentation-ownership-keep-the-install-tracks-dry) identifies and owns all behavior shared with the signed-DMG track; do not restate those procedures here. In particular, its [blocking early iPhone VPN passcode gate](../.agents/skills/field-testing/SKILL.md#blocking-early-iphone-vpn-passcode-gate) overrides the normal verify-first order below.

## 4. Verify, then exercise the product

```bash
openbase-coder version          # dev install, channel, update flags
openbase-coder doctor           # services, ports, selected phone-access network, credentials, auth
openbase-coder services status
```

Then pick the surface you're testing:

- **iOS app (the primary product surface).** Phone signed into the same Openbase Cloud account and on the same tailnet. The Mac appears via the cloud device registration that setup/login reported; start a voice session. If it sticks at "waiting for agent", see the LiveKit note in `AGENTS.md` (stale ICE state — restarting Mac + phone resolves it). The Xcode project is Tuist-generated and gitignored: after pulling or editing `ios/Project.swift`, run `tuist generate --no-open` in `ios/` before building, or the build silently uses stale Info.plist config (e.g. missing ATS exception domains → NSURLError -1022 on every plain-HTTP tailnet request). During a field test, follow the shared [Appium call procedure](../.agents/skills/field-testing/SKILL.md#driving-the-call-through-appium-do-this-before-you-speak) for first-call microphone permission, mic state, screenshot-proven speaker mode, Cartesia stimulus, and audible-response capture.
- **Android app.** The Kotlin/Compose peer of the iOS app. Sign the phone into the same Openbase Cloud account, choose the computer during onboarding, and let the selected Openbase-managed transport supply the private backend address. Android currently uses its bundled Openbase VPN client for both Openbase VPN and for computers running Openbase Direct; it does not require the Tailscale app or a Tailscale account. A source field-test build must stage the real netmesh AAR before Gradle runs, as specified once in the shared field-testing skill. Settings → Backend Host is an Advanced recovery/diagnostic control, not a normal onboarding step (see `android/README.md`).
- **Web console.** `http://localhost:7999` — served by the django-cli service from `console/dist`. Threads, skills, settings, versions footer.
- **Desktop app (optional — NOT needed for CLI/voice dev).** Offered at the end of `./scripts/setup`, or any time later via `./scripts/dev-launch --electron`. It builds the renderer once (skipped when unchanged), installs a thin launcher bundle at `/Applications/Openbase.app` (name + icon + Spotlight; no bundled runtime — it execs the workspace Electron, and it never replaces a real packaged install unless `OPENBASE_DEV_DASHBOARD_REPLACE_APP=1`), and runs Electron alone — no vite dev server or watchers; use `--electron-dev` only when working on the dashboard UI itself. It sets an explicit development dashboard-only mode; Electron also detects the active development `installation.json`. Its installer bridge and onboarding/setup wizard are unavailable, because `./scripts/setup` is the sole dev setup authority. Use `pnpm run install:local` only when intentionally testing a packaged app.
- **Swift networking menu bar (optional).** Run `./scripts/dev-launch --menu-bar` for native connection/status feedback, or `./scripts/dev-launch --all` for it plus Electron. Both have matching VS Code tasks; the Electron/React surface launches from `tasks.json`.

## 5. Iterating

- **cli (Python):** the workspace venv's editable install picks changes up immediately for new invocations; running services need `openbase-coder restart` (or `services restart <name>` — `livekit-agent` for voice-session code, `django-cli` for API/console-serving code).
- **LiveKit engine:** after pulling a change to `livekit_version.py`, a full `openbase-coder restart` or `openbase-coder restart --service livekit-server` downloads and verifies the pinned engine before scheduling the restart. If preparation fails, services remain running and the command reports the error. Setup also downloads the engine, but warns and permits a fallback if that download fails. Restarting only the agent or launching the developer dashboard does not refresh the engine.
- **console / coder-react:** `cd console && pnpm run build` — django serves `console/dist` directly, so a rebuild + browser refresh is enough. For hot reload use `pnpm dev` in `console/` (Vite dev server).
- **desktop:** `./scripts/dev-launch --electron` from the workspace root.
- **Tests:** `cd cli && uv sync --extra dev && uv run pytest` (the venv lives at the workspace root — uv workspace); `cd super-agents && uv run pytest`; frontend typechecks via `npx tsc -p tsconfig.app.json --noEmit` in `console/` and `desktop/`.
- **Agent profiles:** Openbase shares authentication and history with the normal agent homes, but applies its settings and MCP servers through session profiles. Codex clients load `~/.codex/openbase.config.toml` through per-thread API config; Claude uses the settings and MCP files under `~/.openbase/profiles/claude/`. Codex file hooks are for native `codex -p openbase` commands; app-server sessions receive identity from the client. The shared Codex daemon has no global Openbase model/provider overrides. Existing installs can run `openbase-coder profiles install` and restart services. Openbase instruction files render into `~/.openbase/instructions/` from the workspace `instructions/` templates.
- **Paid profile verification:** From `cli/`, run `uv run python scripts/test-agent-profiles.py --paid` against a running installed daemon and authenticated Codex/Claude CLIs. This spends credits on real Openbase-profile and ordinary sessions, checks Codex model/reasoning and MCP separation on the same daemon, and exercises Claude's actual SDK settings layer followed by the normal CLI. Threads are ephemeral or non-persistent. Unit tests alone do not establish vendor profile behavior.

## 6. Resetting

Syncthing policy: `.git` (and all VCS metadata) is **never synced** — the `~/Projects/.stglobalignore` patterns enforce this and `openbase-coder doctor` checks it. If a file mysteriously changes or vanishes mid-operation, suspect a working-tree sync race from the other machine and check `~/.openbase/sync-versions/` (code-sync history) before assuming data loss.

To test first-run behavior from scratch: stop services (`openbase-coder services stop`), archive `~/.openbase` (move it aside), and re-run `./scripts/setup`. You lose cloud login (re-run `openbase-coder login`), dispatcher settings (e.g. the skills auto-link toggle), and the Syncthing thread-sync folder identity.

To exercise the macOS install flows **without** disturbing your real install, use the installation-flow tests instead of archiving `~/.openbase`:

```bash
./install-tests/run-all.sh # developer install (install.sh), sandbox $HOME
./install-tests/electron-macos/manual-vm.sh --source <maintained-sip-enabled-source> --name <run-specific-name>
```

The developer-install check runs `cli/scripts/install.sh` in a throwaway sandbox `$HOME` with services skipped and networking stubbed, so your install, PATH, and launchd services are untouched. A full Electron field test starts with `manual-vm.sh`, installs either the signed DMG or an explicitly sampled local developer build, selects Openbase VPN or Openbase Direct through the real onboarding UI, and follows the shared field-testing skill. Retain the just-tested VM for immediate targeted follow-ups; before a later request needs a new clone, delete stale disposable field-test clones while preserving maintained source images and any VM still needed for active evidence. The dev-**workspace** flow (`scripts/setup`) is separate. See `install-tests/README.md` and `install-tests/electron-macos/README.md`.

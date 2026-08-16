# Dev Runbook

The direct path for developing and testing Openbase Coder from this
workspace. This is the dev counterpart to the standalone/production install
(see `AUTO_UPDATE.md` for how that side ships). Follow it top to bottom for a
fresh machine; jump to [Iterating](#5-iterating) day to day.

## 1. One-time prerequisites

- `uv`, Node + pnpm (via nvm). (`livekit-server` is downloaded at the
  release-pinned version by setup into `~/.openbase/bin`; a Homebrew
  `livekit-server` is only a fallback and will warn if its version skews.)
- `multi` (`uv tool install multi-workspace`)
- Tailscale installed, signed in, connected (the iOS app reaches this Mac
  over the tailnet)
- Coding-backend login: `codex login` for the codex backend, and/or your
  normal Claude Code login (setup bridges it into Openbase's managed config
  automatically on macOS)

Setup fails fast with the fix command if `uv`, `multi`, pnpm, or Tailscale is
missing; a missing `codex login` only warns (threads fail later until you log
in).

## 2. Install

```bash
git clone https://github.com/openbase-community/openbase-coder-workspace
cd openbase-coder-workspace
./scripts/setup            # no flags = interactive pickers; or pass --backend codex
```

Setup puts `openbase-coder` on PATH via a shim at `~/.local/bin` that runs
the workspace venv — the same interpreter the services use, so the terminal
CLI and the services can never disagree about dependencies. (If a
`uv tool install openbase-coder` shim exists, setup replaces it and tells
you; run `uv tool uninstall openbase-coder` to drop the orphaned venv.)

With no flags, setup runs interactively on a fresh install: numbered pickers
choose the coding backend (codex, claude-code, or openbase-cloud) and the
voice audio provider — Cloud TTS/STT (default), bring-your-own-keys
(AssemblyAI + Cartesia, prompts for the keys), or local models (not
recommended). The interactive run finishes by offering `openbase-coder
login`, verifying cloud device registration and Tailscale Serve health, and
printing a QR code for the phone app downloads page. Passing any flag makes
the run fully non-interactive (safe for scripts, AI agents, and the Electron
onboarding flow): a fresh install then requires `--backend` and defaults the
audio provider to openbase-cloud. `openbase-coder setup --interactive`
combines flags with the pickers. Prerequisites checked up front: `uv`,
`multi`, `pnpm`, and Node >= 20.

`scripts/setup` syncs the sub-repos with `multi`, creates the cli venv,
downloads LiveKit model files, builds the console, generates
`~/.openbase` (env, agent homes, dispatcher config), installs the launchd
services, and configures Tailscale Serve. It never clones anything itself.
If a standalone install or another development workspace install already
exists, it stops and points to https://docs.openbase.cloud/uninstall/ before
making changes.

## 3. Authenticate

```bash
openbase-coder login
```

Browser OAuth against app.openbase.cloud; tokens land in
`~/.openbase/auth.json`. Required for iOS pairing and cloud onboarding.

> Quirk to expect: the login-success page deep-links
> `openbase-coder://…`, so if a desktop app is installed, macOS focuses it.
> That page is shared with desktop onboarding — ignore it; the terminal's
> "Logged in successfully" is the source of truth for CLI login.

## 4. Verify, then exercise the product

```bash
openbase-coder version          # dev install, channel, update flags
openbase-coder doctor           # services, ports, Tailscale, credentials, auth
openbase-coder services status
```

Then pick the surface you're testing:

- **iOS app (the primary product surface).** Phone signed into the same
  Openbase Cloud account and on the same tailnet. The Mac appears via the
  cloud device registration that setup/login reported; start a voice
  session. If it sticks at "waiting for agent", see the LiveKit note in
  `AGENTS.md` (stale ICE state — restarting Mac + phone resolves it).
- **Web console.** `http://localhost:7999` — served by the django-cli
  service from `console/dist`. Threads, skills, settings, versions footer.
- **Desktop app (optional — NOT needed for CLI/voice dev).** In `desktop/`:
  `pnpm dev` for hot-reload iteration, or `pnpm run install:local` to build
  a packaged copy into `/Applications` (auto-update disabled for that
  build). The desktop app talks to the same local server and PATH CLI.

## 5. Iterating

- **cli (Python):** the workspace venv's editable install picks changes up
  immediately for new invocations; running services need `openbase-coder
  restart` (or
  `services restart <name>` — `livekit-agent` for voice-session code,
  `django-cli` for API/console-serving code).
- **console / coder-react:** `cd console && pnpm run build` — django serves
  `console/dist` directly, so a rebuild + browser refresh is enough. For hot
  reload use `pnpm dev` in `console/` (Vite dev server).
- **desktop:** `pnpm dev` in `desktop/`.
- **Tests:** `cd cli && uv sync --extra dev && uv run pytest` (the venv lives
  at the workspace root — uv workspace); `cd super-agents && uv run pytest`;
  frontend typechecks via `npx tsc -p tsconfig.app.json --noEmit` in
  `console/` and `desktop/`.
- **Agent homes:** `~/.openbase/codex_home` and `~/.openbase/claude_config`
  are generated by setup; instructions render from `instructions/`
  templates — edit the templates, not the generated files, then re-run
  setup or `openbase-coder restart`.

## 6. Resetting

Syncthing policy: `.git` (and all VCS metadata) is **never synced** — the
`~/Projects/.stglobalignore` patterns enforce this and `openbase-coder doctor`
checks it. If a file mysteriously changes or vanishes mid-operation, suspect
a working-tree sync race from the other machine and check
`~/.openbase/sync-versions/` (code-sync history) before assuming data loss.

To test first-run behavior from scratch: stop services
(`openbase-coder services stop`), archive `~/.openbase` (move it aside), and
re-run `./scripts/setup`. You lose cloud login (re-run `openbase-coder
login`), dispatcher settings (e.g. the skills auto-link toggle), and the
Syncthing thread-sync folder identity.

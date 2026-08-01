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

## 2. Install

```bash
git clone https://github.com/openbase-community/openbase-coder-workspace
cd openbase-coder-workspace
./scripts/setup            # prompts for a backend; or pass --backend codex
```

The development wrapper defaults to free local audio. On the first run it
installs Kokoro + MLX Whisper into the workspace venv, downloads all 30 Kokoro
model/voice files, installs `en_core_web_sm`, downloads the MLX Whisper model,
and verifies the same runtime the services will use. Expect the first model
download to take several minutes. Override only when intentional:

```bash
./scripts/setup --backend codex --audio-provider openbase-cloud  # subscription required
./scripts/setup --backend codex --audio-provider cartesia        # provider keys required
```

Setup puts `openbase-coder` on PATH via a shim at `~/.local/bin` that runs
the workspace venv — the same interpreter the services use, so the terminal
CLI and the services can never disagree about dependencies. (If a
`uv tool install openbase-coder` shim exists, setup replaces it and tells
you; run `uv tool uninstall openbase-coder` to drop the orphaned venv.)

`scripts/setup` syncs the sub-repos with `multi`, creates the cli venv,
downloads and verifies LiveKit and local-audio model files, builds the console, generates
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

Do not continue to phone testing unless `doctor` shows Tailscale Serve and the
required services healthy. A setup failure is actionable and non-successful;
rerun the same `./scripts/setup` command after fixing the reported prerequisite.

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
- **Tests:** `cd cli && uv sync --extra dev --extra local-audio && uv run pytest` (the venv lives
  at the workspace root — uv workspace); `cd super-agents && uv run pytest`;
  frontend typechecks via `npx tsc -p tsconfig.app.json --noEmit` in
  `console/` and `desktop/`.
- **Dependency syncs:** keep `--extra local-audio` on CLI `uv sync` commands.
  A plain sync intentionally removes optional packages and is not the supported
  voice-development environment.
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

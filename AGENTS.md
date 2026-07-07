# Openbase Coder Workspace — Agent Guide

## What This Product Is

Openbase Coder is a voice IDE — "write code from voice." The user speaks a
task and keeps a live coding call open: a dispatcher agent answers, starts
and steers coding sessions (threads) on the user's Mac or cloud DevSpace,
and hands the call to Super Agents; the user approves sensitive actions and
reviews diffs from the same control surface. Product surfaces: the iOS app,
the macOS Electron desktop app, the shared web console, and Openbase Cloud
(app.openbase.cloud) — all backed by the local `openbase-coder` CLI runtime.
Openbase Cloud is also a PaaS.

Product behavior and user-facing docs are in `cli/docs/`, published at
https://docs.openbase.cloud — use the `openbase-product-knowledge` skill to
route product questions to the right page. Workspace terms are defined in
`GLOSSARY.md`; keep it maintained when introducing recurring
Openbase-specific terms rather than redefining them across repos.

The sibling workspace `../openbase-cloud-workspace` contains the cloud
product (auth, remote workspaces, and the PaaS backend).

## Repositories

- `cli`: the Openbase Coder runtime (`openbase-coder`): local Django API +
  WebSocket server, LiveKit voice services, launchd/systemd service
  management, plugins, self-update, and the product docs (`cli/docs/`)
- `console`: React frontend console for Openbase Coder
- `coder-react`: shared React UI package used by the console and desktop
- `desktop`: Electron desktop app for Openbase Coder
- `ios`: main Openbase iOS application using Tuist
- `android`: main Openbase Android application (Kotlin, Jetpack Compose)
- `skills`: shared agent skills bundled with Openbase Coder
- `super-agents`: Python MCP wrapper for Codex app-server threads, turns,
  and Super Agents coordination
- `agent-work-scheduler`: deterministic Notion dependency scheduler for
  launching Super Agents work in isolated git worktrees
- `multi-react`: shared React diff viewer used by Multi and Openbase Coder
- `boilersync-react`: shared React components for BoilerSync workflows
- `allauth-client-swift` / `allauth-client-kotlin`: SwiftUI / Kotlin clients
  for Django AllAuth headless authentication

## Working In This Workspace

- Branches: do day-to-day work on `staging`. Deploys merge **every** repo's
  staging to main in one batch, cli last (see the `deploy` skill). The
  workspace AND desktop repos require **linear history** on main (no merge
  commits) — integrate feature branches by cherry-pick/rebase, never
  `merge --no-edit`, or the push is rejected.
- Parallel agents: multiple agents work these checkouts concurrently. Never
  commit, stash, or checkout over another agent's dirty files. To merge or
  branch-switch when a checkout is dirty with someone else's work, use a
  temporary worktree (`git worktree add /tmp/x <ref>`, operate, push,
  remove). If files mysteriously contain stale (months-old) content,
  suspect a Syncthing working-tree echo from another machine — park the
  evidence in a stash and restore from HEAD; never commit resurrections.
- Developer install/test flow: `DEV_RUNBOOK.md` — keep it accurate when
  setup, auth, or service behavior changes.
- Cross-repo feature specs: `specs/` — consult before implementing features
  that span repos; usage policy in `specs/README.md` (public-audience docs
  only — planning scratch stays in gitignored `.local/`).
- Releases, distribution, and update behavior: `AUTO_UPDATE.md` — consult
  before touching release workflows, the self-updater, state-file schemas,
  version handshakes, or update feeds, and keep it current.
- Debugging a running install (logs, ports, LiveKit, Tailscale):
  `TROUBLESHOOTING.md` is the agent-facing guide (for example, iOS calls
  stuck on "connecting" or "waiting for agent"). User-facing troubleshooting
  belongs in `cli/docs/troubleshooting.md` instead.
- Task tracking: https://app.notion.com/p/38a7b5b1c1d680bfa25bc2ca41718c95?v=38a7b5b1c1d680948e35000c5aa0133b

## Hard Rules

- `AGENTS.md` and `.agents/` are the source of truth for agent instructions
  and repo-local skills; `CLAUDE.md` and `.claude/skills` entries are
  symlinks to them. Edit the AGENTS/.agents side and keep the symlinks
  intact. Do not add duplicate workspace rules under `.cursor/rules`.
- Licensing: public AGPL-3.0-only — `cli`, `console`, `coder-react`,
  `skills`, `multi-react`, `boilersync-react`. Public MIT exceptions —
  `allauth-client-swift`, `allauth-client-kotlin`, `super-agents`. Dev-only
  pending publication — `agent-work-scheduler`. Private/proprietary —
  `android`, `desktop`, `ios`. Never add MIT licensing to any other repo,
  and never add an open-source license to the private apps.
- Tests under `e2e/` must be true app end-to-end tests (Appium-driven iOS or
  Selenium-driven browser). Direct API, app-server, or service-client
  integration tests do not belong there.
- This machine may sync `~/Projects` with another Mac via Syncthing. `.git`
  must never sync (see `~/Projects/.stglobalignore`); if a commit or build
  fails mysteriously, suspect a sync flap and verify `HEAD` matches
  `origin/<branch>` before committing.

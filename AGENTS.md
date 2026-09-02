# Openbase Coder Workspace — Agent Guide

## What This Product Is

Openbase Coder is a voice IDE — "write code from voice." The user speaks a task and keeps a live coding call open: a dispatcher agent answers, starts and steers coding sessions (threads) on the user's Mac or cloud DevSpace, and hands the call to Super Agents; the user approves sensitive actions and reviews diffs from the same control surface. Product surfaces: the iOS app, the Android app, the macOS Electron desktop app, the shared web console, and Openbase Cloud (app.openbase.cloud) — all backed by the local `openbase-coder` CLI runtime. Openbase Cloud is also a PaaS.

Product behavior and user-facing docs are in `cli/docs/`, published at https://docs.openbase.cloud — use the `openbase-product-knowledge` skill to route product questions to the right page. Workspace terms are defined in `dev-docs/GLOSSARY.md`; keep it maintained when introducing recurring Openbase-specific terms rather than redefining them across repos.

The sibling workspace `../openbase-cloud-workspace` contains the cloud product (auth, remote workspaces, and the PaaS backend).

## Repositories

- `cli`: the Openbase Coder runtime (`openbase-coder`): local Django API + WebSocket server, LiveKit voice services, launchd/systemd service management, plugins, self-update, and the product docs (`cli/docs/`)
- `console`: React frontend console for Openbase Coder
- `coder-react`: shared React UI package used by the console and desktop
- `desktop`: Electron desktop app for Openbase Coder
- `ios`: main Openbase iOS application using Tuist
- `android`: main Openbase Android application (Kotlin, Jetpack Compose)
- `skills`: shared agent skills bundled with Openbase Coder
- `super-agents`: standalone MIT Python MCP server/library for Codex app-server threads, turns, and Super Agents coordination. Keep it usable outside Openbase Coder: generic coordination primitives may live there; Openbase product-domain features belong in Openbase Coder repos or an adapter layer.
- `netmesh-go`: shared gomobile Tailscale-engine bridge (NetmeshGo) consumed by the iOS packet-tunnel extension and the Android VpnService (private, fixed to `main`, dev install set only)
- `multi-react`: shared React diff viewer used by Multi and Openbase Coder
- `boilersync-react`: shared React components for BoilerSync workflows
- `allauth-client-swift` / `allauth-client-kotlin`: SwiftUI / Kotlin clients for Django AllAuth headless authentication

## Working In This Workspace

Engineering docs for contributors and agents live in `dev-docs/` (glossary, runbook, release/update mechanics, troubleshooting, testing tiers). This is distinct from `cli/docs/`, which is the user-facing product documentation published to docs.openbase.cloud.

- Branches: do day-to-day work on `develop`. Deploys promote `develop` → `main` in one batch across **every** repo, cli last — either directly or through a `staging` soak step (both paths are valid; see the `deploy` skill for the branch model). The workspace AND desktop repos require **linear history** on main (no merge commits) — integrate feature branches by cherry-pick/rebase, never `merge --no-edit`, or the push is rejected.
- Parallel agents: multiple agents work these checkouts concurrently. Never commit, stash, or checkout over another agent's dirty files. To merge or branch-switch when a checkout is dirty with someone else's work, use a temporary worktree (`git worktree add /tmp/x <ref>`, operate, push, remove). If files mysteriously contain stale (months-old) content, suspect a Syncthing working-tree echo from another machine — park the evidence in a stash and restore from HEAD; never commit resurrections.
- Developer install/test flow: `dev-docs/DEV_RUNBOOK.md` — keep it accurate when setup, auth, or service behavior changes.
- Installation pathways are strict and few (dev workspace setup, the macOS Electron app, the Cloud DevSpace AMI, the Docker image — `openbaseai/openbase` — and native Windows (beta); definitions in `dev-docs/GLOSSARY.md`). Windows hosts run the **native** Windows install, not the Docker image. Never document or build a new install entry point without updating that glossary entry; `install.sh`, release tarballs, and PyPI are internal mechanisms, not user-facing pathways.
- Testing taxonomy: `dev-docs/testing-tiers.md` defines the three tiers — unit tests (tier 1), scripted E2E (tier 2, regression pinning), and field tests (tier 3, agent-driven clean-room full-acoustic-loop). Consult it before writing or classifying any full-system test.
- Scripted E2E (tier 2): `e2e-scripted/README.md` — consult before running the manual physical-phone regression suite in `e2e-scripted/`; those runs use real services and must not be mocked. The `field-testing` skill is the operational annex for those runs.
- Field testing (tier 3): the workspace-local `field-testing` skill (`.agents/skills/field-testing/SKILL.md`) — use it before planning or running any field test. Field tests run clean-room in a disposable Tart macOS VM (or Windows VM) under a dedicated field-test account, never the developer's own install; the skill requires a pre-run RMOT opened in Typora and production Openbase Cloud targeting.
- Live share-readiness gate: `manual:e2e:ios:parallel-agents-truth` launches parallel Super Agents from a prepared briefing, verifies their Markdown reports, tests transfer to the Bill Gates report agent, asks what happened, and exits back to dispatch. Keep exact paths/names/topics out of spoken prompts and in the briefing file.
- Cross-repo features: the code across repos is the source of truth — there is no standing design-spec directory. Keep planning scratch and post-mortems in the gitignored `.local/` directory, and never reference `.local/` files from committed docs. Durable cross-repo contracts belong with the code that owns them (or the relevant repo's docs), not in a separate spec that drifts.
- Releases, distribution, and update behavior: `dev-docs/AUTO_UPDATE.md` — consult before touching release workflows, the self-updater, state-file schemas, version handshakes, or update feeds, and keep it current.
- Debugging a running install (logs, ports, LiveKit, Tailscale): `dev-docs/TROUBLESHOOTING.md` is the agent-facing guide (for example, iOS calls stuck on "connecting" or "waiting for agent"). User-facing troubleshooting belongs in `cli/docs/troubleshooting.md` instead.
- Task tracking: https://app.notion.com/p/38a7b5b1c1d680bfa25bc2ca41718c95?v=38a7b5b1c1d680948e35000c5aa0133b

## Hard Rules

- `.reports/` is workspace-local and must never be committed to this public repository. Keep operational reports in a private project workspace when they need to be shared or versioned.
- `AGENTS.md` and `.agents/` are the source of truth for agent instructions and repo-local skills; `CLAUDE.md` and `.claude/skills` entries are symlinks to them. Edit the AGENTS/.agents side and keep the symlinks intact. Do not add duplicate workspace rules under `.cursor/rules`.
- Licensing: public AGPL-3.0-only — `cli`, `console`, `coder-react`, `skills`, `multi-react`. Public MIT exceptions — `allauth-client-swift`, `allauth-client-kotlin`, `super-agents`, `boilersync-react`. Private/proprietary — `android`, `desktop`, `ios`, `netmesh-go`. Never add MIT licensing to any other repo, and never add an open-source license to the private apps.
- Super Agents boundary: this root-level workspace rule applies whenever working on `super-agents`, because subrepo `AGENTS.md` files may not be loaded by default. `super-agents` must remain a standalone MCP product that can be installed and used without Openbase Coder. Do not add product domain features such as Openbase teams, team activity feeds, reports, Cloud account state, billing, onboarding, or app-specific UX flows directly to `super-agents`; put those in `cli`, `skills`, `console`, the apps, or a narrow adapter that calls generic Super Agents primitives.
- Tests under `e2e-scripted/` (tier-2 scripted E2E) must be true app end-to-end tests (Appium-driven iOS/Android or Selenium-driven browser). Direct API, app-server, or service-client integration tests do not belong there. Tier-2 exists for regression pinning — add a spec when a field test finds a bug worth freezing, not for speculative coverage. Agent-driven, unscripted testing is tier 3 (field tests), not a package under `e2e-scripted/`.
- When an agent interacts with Appium directly (ad-hoc device driving, debugging, screen inspection, or driving a tier-3 field test — anything outside the wdio spec runner), it must go through the `appium` MCP server tools (`mcp__appium__*`), not a hand-started Appium server, raw WebDriver calls, or one-off WebdriverIO scripts. See `e2e-scripted/README.md`.
- This machine may sync `~/Projects` with another Mac via Syncthing. `.git` must never sync (see `~/Projects/.stglobalignore`); if a commit or build fails mysteriously, suspect a sync flap and verify `HEAD` matches `origin/<branch>` before committing.

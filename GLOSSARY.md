# Openbase Glossary

This glossary defines Openbase Coder workspace terms as they appear in docs,
instructions, issues, reports, and agent handoffs. Add terms here when a new
concept becomes part of the shared Openbase vocabulary.

## Product Surfaces

**Product surface**: One of the user-facing faces of Openbase Coder: the
desktop app, the iOS app, the web console, and app.openbase.cloud, all backed
by the local CLI runtime. The product docs (`cli/docs/`, published at
docs.openbase.cloud) cover every surface and carry "In the apps" / "On
iPhone" cross-references between them.

**Live E2E test**: A manual full-system test that drives real product surfaces
and real services rather than mocks or test doubles. In Openbase Coder, the
most sensitive live E2E path is the physical iPhone voice suite because it uses
the installed iOS app, Appium/WebDriverAgent, LiveKit, Cartesia audio, and real
agent backends.

**Physical iPhone E2E**: The `e2e/ios-physical` suite that drives Gabe's real
iPhone through Appium/XCUITest against the modern Openbase iOS app bundle. It
is manual-only and requires explicit permission before running because it can
spend API credits and produce audible speech.

**Desktop app**: The macOS Electron app. It bundles and activates the
standalone CLI runtime, runs guided first-time setup, and hosts the dashboard
UI plus Electron-only features (auto-update, LiveKit companion screen
sharing, deep links).

**Installation pathways**: The only sanctioned ways to install Openbase
Coder, kept deliberately few and strict. (1) **Dev setup** — clone
`openbase-coder-workspace` and run `./scripts/setup`; `installation.json`
gets `workspace_path` set and `standalone: false`, and localhost:7999 serves
the checkout. (2) **Production setup** — download the macOS Electron app and
complete its onboarding; the app activates its bundled CLI package
(`standalone: true`, empty `workspace_path`). (2.5) For fast debugging of
the production flow it is permissible to build the Electron app **without
notarization** (`pnpm dist:mac`, or `install:local` for the seedless dev-app
variant) — see the `live-installation-test` skill. (3) **Openbase Cloud
workspace AMI** — the dev-ami bake installs the CLI via `uv tool install
openbase-coder` (PyPI) plus a pre-baked workspace clone, and instances
finish with `openbase-coder provision`. Everything else — the standalone
`install.sh` script, the release tarballs, PyPI — is an internal mechanism
that supports these pathways (desktop seed, self-update, AMI bake, manual
desktop setup), never a separately advertised way to install.

**Console**: The shared dashboard UI (from `coder-react`, built in
`console`). The desktop app embeds it, the local runtime serves it in a
browser, and the iOS app opens it in its Console and Diff tabs.

**iOS app**: The phone client: voice calls with the dispatcher and Super
Agents, threads, approvals, reports, diffs, and phone-side settings,
connected to a Mac or DevSpace over Tailscale.

**Openbase Cloud**: The account service at app.openbase.cloud: OAuth
sign-in, device onboarding for iPhone pairing, subscription, the
Openbase Cloud coding backend, and Cloud DevSpace launch. (Its deployment
tooling is separate from the Openbase Coder product surfaces.)

## Agent Identity

**Dispatcher**: The LiveKit voice-session agent that receives normal user speech
first and routes work to Super Agents or other targets. The dispatcher owns
delegation and routing decisions for the private voice room.

**Super Agent**: An Openbase-managed coding agent attached to a durable thread,
usually used for implementation, investigations, reports, or longer-running
work. A Super Agent has a thread name and may also have a separate speaking
agent name for voice.

**Speaking agent name**: The name used by voice commands such as
`openbase-coder user say` and `openbase-coder user transfer-to-agent`. It is
derived from a Super Agent thread name with `openbase-coder super-agent-name`.

**Thread**: A durable conversation or coding session in a backend such as Codex
app-server or Claude Code. Threads carry messages, turns, working directory
context, and local metadata.

**Turn**: One unit of work submitted to a thread. A turn may be a normal
implementation request, a plan-mode request, a follow-up, or steering input.

## Voice

**Voice route**: The active target for user speech in a private LiveKit room. It
is normally the dispatcher, but can be transferred to a Super Agent/thread and
then returned to the dispatcher.

**LiveKit room**: The private real-time voice room used by Openbase Coder for
user speech, agent audio, route-control data messages, and related voice events.

**Announcer message**: A short spoken message sent into the active voice session
with `openbase-coder user say AGENT_NAME MESSAGE`, commonly used for Super
Agent introductions, plan questions, and completion notices.

**Agent status packet**: A reliable LiveKit data packet on topic
`openbase.agent.status` that the voice agent publishes when it joins a room but
cannot operate (for example `subscription_required`, `login_required`,
`cloud_unavailable`, or `agent_start_failed`). Payload: JSON with `type`
(`agent_error`), `code`, `detail`, and `message_id`; clients show `detail` to
the user instead of leaving a silent call.

## Work Products

**Report**: A Markdown or other generated artifact written under a project
`.reports` directory by default. Reports capture investigations, proposals,
reviews, and other durable summaries.

**Reports CLI**: The `openbase-coder reports` command surface for listing,
filtering, showing metadata for, and reading reports through the same discovery
and metadata layer used by the console Reports page.

**Tags**: Local Openbase Coder labels applied to threads or reports to organize
work across the console and Super Agents tooling.

## Agent Capabilities

**MCP**: Model Context Protocol, the mechanism Openbase Coder uses to expose
tools and resources to agents, including Super Agents coordination tools.

**MCP elicitation**: A structured request from an MCP tool or backend asking the
agent to collect user input before continuing, such as a plan-mode question.

**open-approvals**: The standalone MIT-licensed package (with an
`open-approvals-react` companion for approver UIs) that provides Openbase
Coder's human-in-the-loop approvals: a shared JSON-file approval queue, an
agent-side client, and a documented protocol. The cli serves the approval REST
endpoints and super-agents mirrors Codex permission requests into the same
queue; approver surfaces (console, desktop, iOS) list and answer requests.

**Approval request**: One entry in the open-approvals queue — an action an
agent, skill, or Codex turn wants a human to accept or decline before it
proceeds. Pending requests appear in the console/desktop Approval requests
page and the iOS app; answering records an `accept`/`decline`/`cancel`
decision that the requester consumes.

**Permission guard**: The generic super-agents primitive behind locked-down
mode: a supervisor-controlled JSON file (default
`~/.super-agents/permission-guard.json`) whose `restricted: true` state makes
every Super Agents launch downgrade permission bypasses (`approvalPolicy:
never`, full-access sandboxes, Claude `bypassPermissions`) to gated
equivalents. Agents cannot edit their way past it because the file is owned
by the supervising process, not the calling agent.

**Locked-down mode**: The off-by-default Openbase Coder setting (final
onboarding-skill step; `openbase-coder lockdown`) that keeps the permission
guard restricted so coding launches always run gated — unless the user's
safe phrase is heard in the direct transcript of the live voice session,
which unlocks bypasses for that session only. Every new voice session
re-arms the guard.

**Safe phrase**: The user-chosen spoken phrase that unlocks locked-down mode
for one voice session. Matching is casing- and punctuation-insensitive and
runs only on verbatim STT transcripts, never on agent-produced text.

**Skill**: A local instruction bundle that teaches an agent a specialized
workflow, tool integration, or domain convention. Skills are loaded when a task
matches their trigger.

**Skills auto-link**: An off-by-default setting, toggled from the console
skills settings, that symlinks every personal skill under `~/.agents/skills`
into both Openbase agent homes: `~/.openbase/codex_home/skills` and
`~/.openbase/claude_config/skills`. Auto-linked skills share one source copy;
the `openbase-routines` service re-syncs the links roughly every five minutes,
so newly added personal skills appear without a restart.

**Plugin**: A local Python package that can contribute bootstrappers, stacks,
skills, Django URL modules, and iframe console pages to Openbase Coder.

**Plugin console page (iframe)**: The only supported form of plugin console UI:
a plugin declares `console_pages` entries with an `asset_dir` of prebuilt
static assets, which the CLI copies to `~/.openbase/plugins/console-assets/`
and serves at `/openbase-plugin-assets/...`. The console and desktop discover
pages at runtime via `/api/plugins/console-registry/`, so no console rebuild or
Node/npm is needed. React component pages and project views were removed.

**Plugin site directory**: The stable directory `~/.openbase/plugins/site`
where plugin Python packages install in standalone mode, outside the versioned
runtime package so upgrades do not lose plugins. The CLI adds it to `sys.path`
at startup. Development installs use the workspace CLI venv instead.

## Onboarding

**Onboarding state**: The first-run setup state formed from cloud rendezvous
facts and live desktop checks. Openbase-cloud records registered devices and
fresh Tailscale addresses; clients verify desktop readiness over Tailscale.
Defined in `specs/onboarding/`.

**Device registration**: A device (desktop or mobile) upserting itself with
openbase-cloud by stable `device_id`, including kind, hostname/display name,
version, capabilities, freshness, and its Tailscale identity (MagicDNS name,
tailnet, IPs) once available. The backend is a rendezvous registry, not durable
pairing or install-readiness truth.

**Setup progress protocol**: The NDJSON step events emitted by
`openbase-coder setup --json-progress` so the desktop app can render setup as
a live checklist. Step IDs and event shapes are defined in
`specs/onboarding/README.md`.

**Onboarding skill**: The bundled `openbase-onboarding` skill (in `skills`)
that walks a user through connecting recommended integrations — email,
meeting notes, shared documents, calendar, optional personal messaging,
computer control, and the GitHub CLI — preferring official CLIs and skills
over MCP servers. Its final step offers to enable locked-down mode with a
safe phrase.

**Onboarding-read marker**: `~/.openbase/onboarding-skill-read`, created by
an agent as soon as it reads the onboarding skill (even if onboarding is not
completed). Until it exists, the CLI appends a note to dispatcher-bound user
messages prompting the agent to offer the onboarding skill.

## Code Sync

**Code sync**: Openbase Coder's managed Syncthing file sync between a user's
non-phone devices (Macs, cloud workspaces) over their tailnet. Syncs selected
home-relative directories continuously — including uncommitted changes and
gitignored secrets — with VCS metadata (`.git`) categorically excluded.
Optional; arms only when the device registry shows two or more non-phone
devices with Tailscale identities. Plan and rationale in
`specs/code-sync/PLAN.md`.

**Sync folder**: One user-selected directory under `~`, identified across
devices by its home-relative path (deterministic folder ID = hash of the
relpath); each device mounts it at its own `$HOME/<relpath>`.

**Repo reconciler**: The code-sync service that keeps git branch pointers in
step across devices after files have already synced: fetches from the peer
over the local API's read-only git endpoint and fast-forwards only when the
local branch is an ancestor and the working tree already matches; anything
else becomes a repo sync conflict surfaced in the console and iOS app.

**Active-device lease**: Code-sync marks the non-active device's folders
receive-only (via the Syncthing REST API) so a stale peer can never echo old
state over live work; the lease follows agent/voice activity.

**Sync history**: Staggered Syncthing versioning (~30-day max age) kept under
`~/.openbase/sync-versions/`, storing old copies only of files replaced by
incoming syncs — the undo net for uncommitted work.

## Local Configuration

**Standalone runtime package**: The bundled production runtime for Openbase
Coder — Python, the CLI, livekit-server, a prebuilt console, instructions, and
skills — shipped inside the desktop app or installed via `install.sh` and
detected via `openbase-coder-package.json`. One of the two deployment modes.

**Development workspace mode**: The other deployment mode: a developer clones
the `openbase-coder-workspace` repo and runs `./scripts/setup` from its root,
with the CLI installed editable (`uv tool install -e ./cli`) or run via
`uv run`. `openbase-coder setup` never clones a workspace; without
`--workspace-dir` it discovers the checkout from `~/.openbase/installation.json`
or the editable CLI install.

**Coding backend**: Where Super Agents threads execute: `codex` (local Codex
app-server), `openbase_cloud` (Codex-compatible sessions through Openbase
Cloud), or `claude_code` (Claude Agent SDK). The configured backend
(`OPENBASE_CODING_BACKEND`) is only the default — each `super_agents_start`
launch may pick its own backend, and threads on different backends run side
by side under one MCP server. In Openbase Coder each agent home's
super-agents MCP registration pins `SUPER_AGENTS_DEFAULT_BACKEND` to that
home's own backend type, so a spawning session defaults new Super Agents to
its own kind (Claude Code sessions spawn Claude Code, Codex sessions spawn
Codex) unless the launch passes an explicit `backend`.

**Backend binary on-demand install**: Setup behavior that installs the selected
coding backend's CLI only if it is missing: codex from GitHub release binaries
into `~/.openbase/bin`, claude via Anthropic's official installer. Neither CLI
ships inside the standalone runtime package, and backend-specific services are
only installed for backends that use them.

**Session-ID hook**: The `inject-session-id.sh` SessionStart hook that
`openbase-coder setup` installs into `~/.openbase/hooks` and registers in both
Openbase agent homes (Claude `settings.json` hooks and a trusted codex
`[[hooks.SessionStart]]` entry). It injects the session's thread/session ID
into the conversation along with the instructions for using it, so agents
stamp commits with the `Agent-Thread-Id` trailer without a standing
`AGENTS.md` rule; the instructions ride in the hook so they ship, update, and
uninstall with it.

**Codex home**: The Openbase-specific Codex configuration directory, usually
`~/.openbase/codex_home`, that stores Codex instructions, skills, and related
runtime configuration.

**Thread sync conflict**: A local coding-thread sync state — for a Codex
thread or a Claude Code session — that needs human review because both synced
homes changed the same thread or a remote device snapshot diverged from the
local copy. Both backends resolve device conflicts the same way: accept the
local copy or accept the latest remote snapshot. Device conflicts only stand
while transcripts genuinely diverge: snapshots whose content is identical to
or an append-only extension of the local copy sync without conflict, and an
existing conflict auto-clears once the two sides converge.

**Claude config**: The Openbase-specific Claude Code configuration directory,
usually `~/.openbase/claude_config`, that stores Claude instructions and related
runtime configuration. Its `.claude.json` is the merged Claude Code user state
Claude reads under Openbase's `CLAUDE_CONFIG_DIR`.

**Claude auth bridge (keychain)**: The setup/sync behavior that lets Openbase's
managed Claude config inherit the user's normal Claude Code login. It merges
normal `~/.claude.json` state into `~/.openbase/claude_config/.claude.json`
(existing Openbase values win, `mcpServers` are unioned) and, on macOS, copies
the normal "Claude Code-credentials" keychain item to Openbase's
config-dir-specific keychain service, avoiding a second browser OAuth. The
fallback is `openbase-coder claude login`.

**Multi-root workspace**: This checkout, which groups multiple Openbase Coder
repositories under one `multi.json` so agents and developers can coordinate
changes across related repos.

**Openbase Coder CLI**: The `openbase-coder` command and local runtime that
provide the Django API, WebSocket endpoints, service management, plugin
management, LiveKit voice services, and Super Agents coordination.

**Routine**: A persisted Openbase Coder schedule run through the local
`openbase-coder routines` command surface. Agent routines start or queue a Super
Agents turn; command routines run a normal local command without launching an AI
agent. Routines are stored in local Super Agents state and run by the
`openbase-routines` scheduler service.

**Cloud idle heartbeat**: The `openbase-cloud-heartbeat` service (cloud
DevSpaces only, installed by `openbase-coder provision`) that runs
`openbase-coder cloud heartbeat`. It samples the local server's
`/api/threads/activity/` endpoint between beats and posts to the cloud API
whether any agent runs were running or launched during the window; Openbase
Cloud stops DevSpaces with no run activity. DCV connections and console
browsing intentionally do not count.
**Routines Marketplace**: The browse-and-install catalog of curated routine
templates, hosted anonymously on Openbase Cloud
(`/api/openbase/marketplace/routines/`) and surfaced in the console Routines page
(and the marketing site for SEO). Installing a marketplace routine creates a
local routine and co-installs any `required_skills` it declares. The local proxy
lives at `/api/marketplace/routines/...`. (Replaces the removed third-party
"Printing Press" skills catalog.)

**Official Skills Catalog**: The companion catalog of official skills, MCPs, and
CLIs (`/api/openbase/marketplace/skills/`), surfaced in the console Skills page.
Only `skill` entries are one-click installable — cloned into `~/.agents/skills`
and always co-installed for Claude Code and Codex together (symlinked into both
Openbase agent homes). `mcp`/`cli` entries are documentation-only. `featured`
entries drive the console's first-run recommended-skills prompt. Local proxy at
`/api/marketplace/skills/...`.

## Releases & Updates

**Update manifest**: `update-manifest.json` published with each CLI release:
version, channel, layout version, minimum supported version, per-target
artifact URLs/checksums, and pinned sibling-repo SHAs. Consumed by
`openbase-coder self-update`; optionally Ed25519-signed. See `AUTO_UPDATE.md`.

**Release channel**: `stable` or `beta`, stamped into a standalone package's
metadata at build time; prerelease tags publish to the beta channel. An
install updates within its channel.

**State schema version**: The `schema_version` field carried by Openbase-owned
state files (`installation.json`, `dispatcher-config.json`, `plugins.json`).
Readers refuse files written by newer versions; changes ship forward-only
migrations (see `AUTO_UPDATE.md`).

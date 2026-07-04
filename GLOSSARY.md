# Openbase Glossary

This glossary defines Openbase Coder workspace terms as they appear in docs,
instructions, issues, reports, and agent handoffs. Add terms here when a new
concept becomes part of the shared Openbase vocabulary.

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

**Backend binary on-demand install**: Setup behavior that installs the selected
coding backend's CLI only if it is missing: codex from GitHub release binaries
into `~/.openbase/bin`, claude via Anthropic's official installer. Neither CLI
ships inside the standalone runtime package, and backend-specific services are
only installed for backends that use them.

**Codex home**: The Openbase-specific Codex configuration directory, usually
`~/.openbase/codex_home`, that stores Codex instructions, skills, and related
runtime configuration.

**Thread sync conflict**: A local Codex thread sync state that needs human
review because both synced homes changed the same thread or a remote device
snapshot diverged from the local thread.

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

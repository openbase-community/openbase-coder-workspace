# Openbase Glossary

This glossary defines Openbase Coder workspace terms as they appear in docs,
instructions, issues, reports, and agent handoffs. Add terms here when a new
concept becomes part of the shared Openbase vocabulary.

## Product Surfaces

**Product surface**: One of the user-facing faces of Openbase Coder: the
desktop app, the iOS app, the Android app, the web console, and
app.openbase.cloud, all backed by the local CLI runtime. The product docs (`cli/docs/`, published at
docs.openbase.cloud) cover every surface and carry "In the apps" / "On
iPhone" cross-references between them.

**Testing tiers**: Openbase Coder's three complementary levels of testing:
(1) **unit tests** (per-repo, mocked, fast), (2) **scripted E2E** (deterministic
real-service/real-phone regression pinning), and (3) **field tests**
(agent-driven, clean-room, full acoustic loop). Defined in
`specs/testing-tiers.md`.

**Live E2E test**: A manual full-system test that drives real product surfaces
and real services rather than mocks or test doubles. It spans the scripted-E2E
and field-test tiers; the most sensitive live path is the physical-phone voice
loop because it uses the installed app, Appium/WebDriverAgent, LiveKit, Cartesia
audio, and real agent backends.

**Scripted E2E**: Tier 2 of the testing tiers — the `e2e-scripted/` package
(formerly `e2e/ios-physical`). Deterministic WebdriverIO/Appium specs that drive
a real iPhone against real services. Its role is **regression pinning**: when a
field test finds a bug, the reproduction is frozen here as a spec so it cannot
silently return. Expected to stay small and grow one spec per real defect.
Manual-only because it spends API credits and produces audible speech. See
`e2e-scripted/README.md` and `LIVE_E2E_TESTING.md`.

**Field test**: Tier 3 of the testing tiers, and the top tier — an
**agent-driven** (unscripted) test where an AI agent installs the product into a
clean-room, isolated environment and exercises it like a user. Three properties
define it: the agent drives the phone via the `appium` MCP server (iOS XCUITest
or Android UiAutomator2); installation is clean-room in a disposable Tart macOS
VM (or Windows VM) under a dedicated field-test account, never the developer's
real machine/user/install; and it closes the **full acoustic loop** — Cartesia
TTS through speakers into the phone mic, and the phone's spoken reply captured
by microphone and transcribed with local STT to assert on meaning. Every failure
it finds is logged, sent to Slack, and fixed as a READY PR against `develop`,
and reproducible regressions are pinned as new scripted-E2E specs. Operating
procedure: the `field-testing` skill.

**Field-test user**: The real, designated account a field test runs as — never a
developer's real Openbase account. Its email must be listed in the cloud API's
`FIELD_TEST_ALLOWED_EMAILS` allowlist (comma-separated); use plus-addressing
(`you+<run-slug>@gmail.com`) to mint unlimited distinct real signup addresses
that all land in one controlled inbox. Because the account is real, the field
test exercises the **real signup and real email-verification** flow: the
verification email actually arrives in the controlled inbox and the testing
agent reads it (via the `gmail-cli` skill) to complete verification. Only two
lifecycle steps are done out-of-band, by the `field_test_account` Django
management command (openbase-drf-api-core PR
[#13](https://github.com/openbase-community/openbase-drf-api-core/pull/13)):
`--destroy EMAIL` (pre-test — delete the prior account via the canonical
account-deletion cascade) and `--mock-payment EMAIL` (post-signup — grant paid
entitlement as a local `payment.Subscription` row at the normal default-tier cap,
no Stripe charge). It **never creates users and never mocks verification**,
guards hard against any email not on the allowlist (empty/unset ⇒ refuses
everything), and emits one line of JSON per operation for the harness. Invoke in
production via `openbase run -a <app> python manage.py field_test_account …`.

**Desktop app**: The macOS Electron app. It bundles and activates the
standalone CLI runtime, runs guided first-time setup, and hosts the dashboard
UI plus Electron-only features (auto-update, LiveKit companion screen
sharing, deep links). Its visible app name is **Openbase**; compatibility
identifiers and the underlying `openbase-coder` CLI keep their technical names.

**Installation pathways**: The only sanctioned ways to install Openbase
Coder, kept deliberately few and strict. (1) **Dev setup** — clone
`openbase-coder-workspace` and run `./scripts/setup`; `installation.json`
gets `workspace_path` set and `standalone: false`, and localhost:7999 serves
the checkout. (2) **Production setup** — download the macOS Electron app and
complete its onboarding; the app activates its bundled CLI package
(`standalone: true`, empty `workspace_path`). (2.5) For fast debugging of
the production flow it is permissible to build the Electron app **without
notarization** (`pnpm dist:mac`, or `install:local` for the seedless dev-app
variant) — see the `field-testing` skill and
`install-tests/electron-macos/`. (3) **Openbase Cloud
workspace AMI** — the dev-ami bake installs the CLI via `uv tool install
openbase-coder` (PyPI) plus a pre-baked workspace clone, and instances
finish with `openbase-coder provision`. (4) **Docker image** —
`openbaseai/openbase` on Docker Hub, built from `cli/Dockerfile` +
`cli/docker/`; runs the full runtime in a Linux container with Tailscale as
the networking layer, on any Docker engine (macOS, Windows, or Linux). User
docs in `cli/docs/docker.md`; deeper image/dev docs in `cli/docker/README.md`.
(5) **Native Windows (beta)** — Openbase Coder runs natively on Windows:
`openbase-coder setup` supports Windows directly, on a cross-platform service
backend with cross-platform file locking and the official Tailscale client for
networking (foundation from the Peruvian hackathon fork; see `cli/README.md`).
This — not the Docker image — is the supported way to run Openbase on a Windows
host. Installer/packaging details are still firming up and are not documented
here yet. Everything else — the standalone `install.sh`
script, the release tarballs, PyPI — is an internal mechanism that supports
these pathways (desktop seed, self-update, AMI bake, manual desktop setup),
never a separately advertised way to install.

**Console**: The shared dashboard UI (from `coder-react`, built in
`console`). The desktop app embeds it, the local runtime serves it in a
browser, and the iOS app opens it in its Console and Diff tabs.

**iOS app**: The phone client: voice calls with the dispatcher and Super
Agents, threads, approvals, reports, diffs, and phone-side settings,
connected to a Mac or DevSpace over Tailscale.

**Android app**: The Android phone client (Kotlin/Jetpack Compose), mirroring
the iOS app: voice calls, threads, approvals, reports, diffs, sync-conflict
resolution, and screen-share viewing, connected to a Mac or DevSpace over
Tailscale. Distributed as an APK from the Openbase downloads bucket.

**Openbase Cloud**: The account service at app.openbase.cloud: OAuth
sign-in, device onboarding for iPhone pairing, subscription, the
Openbase Cloud coding backend, and Cloud DevSpace launch. (Its deployment
tooling is separate from the Openbase Coder product surfaces.)

**Openbase Cloud coding backend**: The user-facing Coder backend option
`openbase_cloud`. It runs Claude Code through Openbase Cloud's Anthropic proxy,
authenticated with the user's Openbase login and a local Openbase machine token,
so users do not need a personal Anthropic account for this backend.

**Openbase Cloud Codex compatibility backend**: The hidden internal backend
value `openbase_cloud_codex`. It preserves the older Codex app-server path
through Openbase Cloud's OpenAI/Responses-compatible proxy, but is not listed as
a normal setup or settings choice.

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

**Voice lifecycle packet**: A reliable LiveKit data packet on topic
`openbase.voice.lifecycle` that the voice agent publishes from the voice
delivery ledger for explicit conversation milestones such as
`utterance_accepted`, `agent_audio_started`, `agent_audio_finished`, and
`safe_to_unmute`. Each event is also mirrored onto the agent's LiveKit
participant attribute of the same name, because data packets can be silently
lost in transit while attributes are state-synced; clients process whichever
transport arrives first and deduplicate by packet id. Clients use these
events for voice diagnostics and, when available, for microphone timing
instead of inferring every transition from broad remote agent states.

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
into both shared agent homes: `~/.codex/skills` and `~/.claude/skills`.
Auto-linked skills share one source copy; the `openbase-routines` service
re-syncs the links roughly every five minutes, so newly added personal skills
appear without a restart.

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
over MCP servers.

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

**Backend binary on-demand install**: Setup behavior that installs the selected
coding backend's CLI only if it is missing: codex from GitHub release binaries
into `~/.openbase/bin`, claude via Anthropic's official installer. Neither CLI
ships inside the standalone runtime package, and backend-specific services are
only installed for backends that use them.

**Session-ID hook**: The `inject-session-id.sh` SessionStart hook that
`openbase-coder setup` installs into `~/.openbase/hooks` and registers in both
shared agent homes (`~/.claude/settings.json` hooks and a trusted codex
`[[hooks.SessionStart]]` entry in `~/.codex/config.toml`). It injects the session's thread/session ID
into the conversation along with the instructions for using it, so agents
stamp commits with the `Agent-Thread-Id` trailer without a standing
`AGENTS.md` rule; the instructions ride in the hook so they ship, update, and
uninstall with it.

**Shared agent homes**: The user's own `~/.codex` and `~/.claude`, which
Openbase Coder uses directly for every session — one thread/session store per
backend shared with the terminal CLIs, IDE extensions, and desktop apps.
Setup registers only the super-agents MCP server and the session-ID hook
there; Openbase's full-permission posture and base instructions are passed
per session (super-agents `SUPER_AGENTS_CODEX_APPROVAL_POLICY`,
`SUPER_AGENTS_CODEX_SANDBOX_POLICY`, and `SUPER_AGENTS_BASE_INSTRUCTIONS_PATH`
env), never written into the homes' own defaults.

**Thread sync conflict**: A cross-device coding-thread sync state — for a
Codex thread or a Claude Code session — that needs human review because a
remote device snapshot diverged from the local copy. (Local sessions live in
one shared home per backend, so there is no local home-pair conflict.) Both
backends resolve device conflicts the same way: accept the local copy or
accept the latest remote snapshot. Device conflicts only stand while
transcripts genuinely diverge: snapshots whose content is identical to or an
append-only extension of the local copy sync without conflict, and an
existing conflict auto-clears once the two sides converge.

**Claude app index sync**: A best-effort `sync-workers` job (macOS only) that
injects Openbase Claude sessions into the Claude desktop app's private
session index (`~/Library/Application Support/Claude/claude-code-sessions`),
so sessions started by voice or the CLI appear in the app. Injected entries
are tracked in `~/.openbase/claude-app-index-ledger.json`; the app's own
entries are never modified.

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

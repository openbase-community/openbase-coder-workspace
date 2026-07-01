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

**Plugin**: A local bundle that can contribute skills, MCP servers, apps, and
runtime extensions to Openbase Coder.

## Local Configuration

**Codex home**: The Openbase-specific Codex configuration directory, usually
`~/.openbase/codex_home`, that stores Codex instructions, skills, and related
runtime configuration.

**Claude config**: The Openbase-specific Claude Code configuration directory,
usually `~/.openbase/claude_config`, that stores Claude instructions and related
runtime configuration.

**Multi-root workspace**: This checkout, which groups multiple Openbase Coder
repositories under one `multi.json` so agents and developers can coordinate
changes across related repos.

**Openbase Coder CLI**: The `openbase-coder` command and local runtime that
provide the Django API, WebSocket endpoints, service management, plugin
management, LiveKit voice services, and Super Agents coordination.

**Routine**: A persisted Openbase Coder schedule that periodically starts or
queues a Super Agents turn through the local `openbase-coder routines` command
surface. Routines are stored in local Super Agents state and run by the
`openbase-routines` scheduler service.

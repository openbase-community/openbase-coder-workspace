# openbase-coder-workspace

[Openbase Coder](https://openbase.cloud) is a voice IDE — speak the task,
keep a live coding call open, approve sensitive actions, and review the diff
from the same control surface. Product docs: https://docs.openbase.cloud.
Agent guidance for working in this workspace is in [AGENTS.md](AGENTS.md).

## Getting started

This repo is a [multi](https://github.com/montaguegabe/multi) workspace to manage multiple sub-repositories:

- [allauth-client-swift](https://github.com/openbase-community/allauth-client-swift) - SwiftUI client and views for Django AllAuth headless authentication
- [allauth-client-kotlin](https://github.com/openbase-community/allauth-client-kotlin) - Kotlin client and views for Django AllAuth headless authentication
- [cli](https://github.com/openbase-community/openbase-coder) - The Openbase Coder runtime (`openbase-coder`): local Django API + WebSocket server, LiveKit voice services, service management, plugins, and the product docs
- [console](https://github.com/openbase-community/openbase-coder-console) - React frontend console for Openbase Coder
- [coder-react](https://github.com/openbase-community/openbase-coder-react) - Shared React UI package for Openbase Coder components used by the console and desktop clients
- [desktop](https://github.com/openbase-community/openbase-coder-desktop) - Electron desktop app for Openbase Coder
- [ios](https://github.com/openbase-community/openbase-ios) - Main Openbase iOS application using Tuist
- [android](https://github.com/openbase-community/openbase-android) - Main Openbase Android application using Kotlin and Jetpack Compose
- [skills](https://github.com/openbase-community/openbase-coder-skills) - Shared agent skills for Openbase Coder workflows
- [super-agents](https://github.com/montaguegabe/super-agents) - Python MCP wrapper for controlling Codex app-server threads and Claude Code sessions
- [multi-react](https://github.com/montaguegabe/multi-react) - Shared React diff viewer and related UI utilities used by Multi and Openbase Coder
- [boilersync-react](https://github.com/montaguegabe/boilersync-react) - Shared React components and utilities for BoilerSync template workflows

To get started as a developer, install multi with
`uv tool install multi-workspace`, clone this workspace repo, and run
`./scripts/setup` from the workspace root. The script syncs the sub-repos with
`multi sync --install-set default`, then runs `openbase-coder setup
--workspace-dir <workspace-root>` against this checkout. Setup never clones or
git-updates a workspace itself; the CLI is typically installed editable
(`uv tool install -e ./cli`) or run via `uv run` from `cli/`.

The full development flow — install, authenticate, verify, exercise the iOS
app / console / desktop app, and iterate — is in the workspace
[`DEV_RUNBOOK.md`](DEV_RUNBOOK.md).

End users should not clone this repo: they install the standalone runtime
package via the Openbase Coder desktop app or the CLI's `install.sh`.

Openbase instruction files are rendered from [`instructions/`](instructions/)
into `~/.openbase/codex_home` and `~/.openbase/instructions`, with generated
files recording their source template path.
Workspace skills under [`skills/skills/`](skills/skills/) are symlink-installed
into `~/.openbase/codex_home/skills`.

Shared Openbase terms are defined in the workspace [glossary](GLOSSARY.md).
Update it when documenting or introducing terms that will recur across repos,
agent instructions, reports, or user-facing docs.

Cross-repo engineering specs live in [`specs/`](specs/) — see
[`specs/README.md`](specs/README.md) for what belongs there (public-audience
architecture and contracts) and what stays local. Current specs:
[`specs/onboarding/`](specs/onboarding/) (cross-device onboarding) and
[`specs/code-sync/`](specs/code-sync/) (managed file sync between machines).

## Coding Backends

Openbase Coder setup supports Codex, Openbase Cloud, and Claude Code as coding
backends:

```bash
openbase-coder setup --backend codex
openbase-coder setup --backend openbase-cloud
openbase-coder setup --backend claude-code
```

Switch later with:

```bash
openbase-coder backend use openbase-cloud
```

Restart the Openbase services and the MCP host that runs `super-agents-mcp`
after switching.

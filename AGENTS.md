This workspace contains multiple repositories:

- `allauth-client-swift`: SwiftUI client and views for Django AllAuth headless authentication
- `allauth-client-kotlin`: Kotlin client and views for Django AllAuth headless authentication
- `cli`: CLI for Openbase Coder. This runs a Django server that provides git diffs for repos across the file system.
- `console`: React frontend console for Openbase Coder
- `coder-react`: Shared React UI package for Openbase Coder components used by the console and desktop clients
- `desktop`: Electron desktop app for Openbase Coder
- `ios`: Main Openbase iOS application using Tuist
- `android`: Main Openbase Android application using Kotlin and Jetpack Compose
- `skills`: Shared agent skills for Openbase Coder workflows.
- `super-agents`: Python MCP wrapper for controlling Codex app-server threads, turns, compact status checks, and Super Agents coordination.
- `agent-work-scheduler`: Deterministic Notion dependency scheduler for launching Super Agents work in isolated git worktrees.
- `multi-react`: Shared React diff viewer and related UI utilities used by Multi and Openbase Coder.
- `boilersync-react`: Shared React components and utilities for BoilerSync template workflows.

This workspace is for voice-coding with an iOS app. `openbase-coder-cli` is run on the client computer, and runs a local Django server + MCP server for coding with Claude code and managing sessions.

Repository visibility and licensing:

- Public, AGPL-3.0-only: `cli`, `console`, `coder-react`, `skills`, `multi-react`, and `boilersync-react`.
- Public, MIT exceptions: `allauth-client-swift`, `allauth-client-kotlin`, and `super-agents`.
- Dev-only pending publication: `agent-work-scheduler`.
- Private/proprietary: `android`, `desktop`, and `ios`.

Do not add MIT licensing to any Openbase Coder repo other than `allauth-client-swift`, `allauth-client-kotlin`, and `super-agents`. The Android app, desktop app, and iOS app must remain private/proprietary for now and should not contain an open-source project license.

Tests under `e2e/` should be true app end-to-end tests: they must drive the iOS app with Appium or drive the browser with Selenium. Do not put direct API, app-server, or service-client integration tests in `e2e/`.

When the iOS app is stuck at "waiting for agent", check `~/.openbase/logs` to confirm whether the LiveKit agent job was dispatched. If the worker logs show `received job request` and then stall in `ctx.connect()` with `wait_pc_connection timed out`, treat it as a stale local/iPhone LiveKit ICE/network state before assuming dispatch logic is broken. Restarting both the Mac and iPhone has resolved this state.

Task tracking is in https://app.notion.com/p/38a7b5b1c1d680bfa25bc2ca41718c95?v=38a7b5b1c1d680948e35000c5aa0133b.

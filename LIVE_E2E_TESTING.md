# Live E2E Testing

This is the durable workspace reference for live Openbase E2E suites.
It documents what the suites are, where they live, and which local
configuration knobs they use.

For live no-mock execution procedure, use the workspace-local
`.agents/skills/live-no-mock-e2e` skill. That skill is the source of truth for
operational gates such as RMOT planning, production-cloud confirmation,
preflight sequencing, audio handling, human prompts, and post-run reporting.

## Source Of Truth Split

- `LIVE_E2E_TESTING.md`: stable suite map, environment reference, runtime target
  meanings, and package script inventory.
- `.agents/skills/live-no-mock-e2e/SKILL.md`: agent instructions for planning,
  running, debugging, or reporting a live no-mock run.

When these documents appear to conflict, follow the skill before running any
live command and update this reference afterward if the suite shape changed.

## iOS Physical Voice Suite

The physical iPhone suite lives in `e2e/ios-physical`. It drives the installed
modern iOS app (`com.openbase.coder`) through Appium/XCUITest on a real iPhone.
The suite talks to the normal local Openbase runtime and real services:
Openbase Cloud, LiveKit voice services, Cartesia-generated Mac speaker audio,
the phone microphone, Codex/Openbase agent homes, the dispatcher, and Super
Agents.

The suite is manual-only because it can spend real API credits, speak audio into
Gabe's phone, and create real agent work. Do not run live specs unless Gabe
explicitly asks for live full-system testing, and load the live E2E skill first.

## Runtime Targets

The tests drive whichever Openbase services are active. Use
`OPENBASE_E2E_EXPECT_RUNTIME` to fail fast when the wrong runtime is active.

- `electron-bundled`: require the active standalone runtime to match the
  installed desktop app's bundled CLI package.
- `standalone`: allow any active standalone runtime.
- `workspace`: require a development workspace runtime.
- `any`: report the runtime without enforcing a mode.

Live E2E normally targets production Openbase Cloud. The expected target guards
are:

```bash
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud
```

## Local Environment

Copy `e2e/ios-physical/env.example` to `e2e/ios-physical/.env` and fill in the
physical iPhone values. Keep secrets out of this file when possible; provide
credentials through the current shell or a narrowly extracted value instead of
sourcing broad private env files.

Common values:

```bash
OPENBASE_IOS_UDID=...
OPENBASE_IOS_DEVICE_NAME=Gabe's iPhone
OPENBASE_IOS_PLATFORM_VERSION=...
OPENBASE_IOS_BUNDLE_ID=com.openbase.coder
OPENBASE_IOS_XCODE_ORG_ID=...
OPENBASE_IOS_WDA_BUNDLE_ID=com.openbase.coder.WebDriverAgentRunner
OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud
```

Leave `OPENBASE_IOS_APP_PATH` empty when the modern app is already installed on
the phone. Set it only when Appium should install a specific `.app` or `.ipa`.

## Package Scripts

Safe local checks:

```bash
pnpm --dir e2e/ios-physical test
pnpm --dir e2e/ios-physical typecheck
pnpm --dir e2e/ios-physical e2e:ios:doctor
```

Live manual specs:

```bash
pnpm --dir e2e/ios-physical manual:e2e:ios:basic-call-response
pnpm --dir e2e/ios-physical manual:e2e:ios:superagent-own-name
pnpm --dir e2e/ios-physical manual:e2e:ios:parallel-agents-truth
```

The package scripts set the real-Codex guard variables, but the operational
skill still owns when these commands may be run.

## Share-Readiness Gate

`manual:e2e:ios:parallel-agents-truth` is the live share-readiness gate. It
drives the physical iPhone, asks the dispatcher to launch two Super Agents from
a prepared briefing, waits for both Markdown reports, verifies that the voice
route transfers to the Bill Gates report agent, asks what happened, and verifies
exit back to dispatch.

Keep brittle details in the briefing file, not in spoken prompts. Spoken audio
should be a short natural pointer to the briefing, because the beginning of
Mac-speaker audio can be clipped, mistranscribed, or split into partial turns.

## Human Actions

Live runs may require Gabe to:

- plug in or unlock the iPhone;
- tap Trust This Computer;
- grant microphone or local-network permissions;
- move the phone near the Mac speaker;
- provide or enable a missing Cartesia credential;
- confirm that a real live test may spend credits.

Use the live E2E skill for the exact `tts` rules before asking for these
actions.

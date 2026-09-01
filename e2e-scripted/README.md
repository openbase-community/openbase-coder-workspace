# Openbase Coder Scripted E2E (tier 2)

This is the **scripted E2E** package — tier 2 of the [testing
taxonomy](../specs/testing-tiers.md). Its role is **regression pinning**: when a
field test (tier 3) finds a bug, the reproduction is frozen here as a
deterministic wdio/Appium spec so the bug cannot silently return. It is expected
to stay small and grow one spec at a time, driven by real defects rather than
speculative coverage.

Manual-only: these specs drive a physical iPhone and use real Openbase Coder,
Codex, LiveKit, and Cartesia services. Do not run them unless explicitly
instructed. Agent-driven, unscripted testing belongs in tier 3 — see the
`field-testing` skill (`.agents/skills/field-testing/SKILL.md`).

This package contains scripted physical iPhone E2E specs for Openbase Coder:

- `specs/basic-call-response.real-codex.spec.ts`
- `specs/superagent-own-name.real-codex.spec.ts`
- `specs/parallel-agents-truth.real-codex.spec.ts`
- `specs/orphaned-answer-recovery.real-codex.spec.ts`

It intentionally uses the normal Codex/Openbase configuration from the current shell and installed launchctl services.
Dedicated field-test mobile variants use staging Openbase Cloud by default. Set `OPENBASE_E2E_EXPECT_WEB_BACKEND` and
`OPENBASE_E2E_EXPECT_CODING_BACKEND` so the runner fails before using the wrong
cloud/backend.
Set `OPENBASE_E2E_EXPECT_RUNTIME` to make the target explicit:

- `electron-bundled`: the active standalone runtime must match the installed
  desktop app's bundled CLI package.
- `standalone`: any active standalone runtime is acceptable.
- `workspace`: the active runtime must be a development workspace checkout.
- `any`: report the active runtime without enforcing a mode.

## Setup

```bash
cp e2e-scripted/env.example e2e-scripted/.env
pnpm install
pnpm e2e:ios:install-driver
```

Fill in `.env` with the physical device UDID, the field-test app bundle id, and WebDriverAgent signing values:

```bash
OPENBASE_IOS_UDID=...
OPENBASE_IOS_DEVICE_NAME=Gabe's iPhone
OPENBASE_IOS_PLATFORM_VERSION=18.x
OPENBASE_IOS_BUNDLE_ID=com.openbase.coder.field-test
OPENBASE_IOS_XCODE_ORG_ID=...
OPENBASE_IOS_WDA_BUNDLE_ID=com.openbase.coder.WebDriverAgentRunner
```

Always use the isolated `OpenbaseFieldTest` iOS scheme and `com.openbase.coder.field-test` bundle for live specs. The normal Openbase app must remain installed, signed in, and untouched. If the field-test app is already installed, keep `OPENBASE_IOS_APP_PATH` empty; otherwise point it at the field-test `.app` or `.ipa`. Android field testing likewise requires the Android project's distinct field-test build variant and application id; if that variant is unavailable, do not substitute or reset the normal app.

The account-creation spec uses real signup and email verification with Resend's official testing recipient. Generate a fresh opaque address in the reserved Openbase namespace for each run; no deployment allowlist change is required:

```bash
OPENBASE_E2E_SIGNUP_EMAIL=delivered+openbase-field-<opaque-run-slug>@resend.dev
```

After the spec reaches "Verify Your Email", use the dedicated secure Resend CLI field-test profile to list messages, select only the exact recipient created after the run began, retrieve it by id, and follow its confirmation URL through the tested phone/browser surface. Never pass a Resend API key on the command line or put the confirmation URL in a report, log, Slack message, or shell command. Full procedure: `.agents/skills/field-testing/SKILL.md`.

## Safe Checks

These commands do not start real Codex flows:

```bash
pnpm e2e:ios:doctor
pnpm --dir e2e-scripted test
pnpm --dir e2e-scripted typecheck
```

`e2e:ios:doctor` validates local prerequisites, confirms the configured iOS UDID is a physical device rather than a simulator, and confirms the normal dispatcher reasoning setting is `low`. Audio stimulus checks only require Cartesia credentials when `OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1`.
It also reports the active Openbase runtime target and fails if
`OPENBASE_E2E_EXPECT_RUNTIME` is set to a mode that does not match.

The helpers use stable accessibility identifiers when the app exposes them and fall back to visible labels where possible. Future iOS app changes should add identifiers such as `nav.call`, `settings.backend.host`, `settings.backend.add`, `call.start`, and `call.end`.

## Agent Interaction via Appium MCP

The `manual:e2e:ios:*` specs manage their own Appium through the wdio runner
(`@wdio/appium-service`), and that stays unchanged. But any time an **agent**
interacts with Appium directly — driving the phone ad hoc, debugging a failing
spec step, reading page source, taking screenshots, handling alerts — it must
go through the `appium` MCP server (`mcp__appium__*` tools; registered as
`appium`, command `npx -y appium-mcp`), never a hand-started `appium` server,
raw WebDriver HTTP calls, or one-off WebdriverIO scripts. The flow
(`select_device` → `appium_prepare_ios_real_device` →
`appium_session_management` → interaction tools) is documented in
`.agents/skills/field-testing/SKILL.md`. Do not create an MCP session while
a wdio spec is mid-run; it can steal WebDriverAgent from the run.

## Voice Assertion Policy

Voice E2E tests should default to cheap, deterministic evidence:

1. Assert the app or local CLI requested TTS with the expected text.
2. Assert LiveKit/agent logs show which voice was selected and what was fed into TTS, routed to the voice agent, or emitted as transcript-like internal state.
3. Use STT only when the test is specifically about what the physical iPhone heard, such as pronunciation of difficult names, acronyms, code words, or model/voice regressions.

Helpers:

- `support/voice/ttsTool.ts`: wraps `openbase-coder user say ...`, with `OPENBASE_E2E_TTS_COMMAND` override.
- `support/voice/livekitLogs.ts`: reads recent LiveKit logs and asserts text/regex evidence without invoking STT.
- `support/voice/sttAssertions.ts`: keeps STT assertions fail-closed unless `OPENBASE_E2E_ENABLE_STT_ASSERTIONS=1`.
- `support/audio/speakText.ts`: synthesizes Mac speaker prompts with Cartesia and plays them through `afplay`.

Check local voice-tool configuration:

```bash
pnpm e2e:voice:check
```

STT is intentionally opt-in:

```bash
OPENBASE_E2E_ENABLE_STT_ASSERTIONS=1 pnpm manual:e2e:ios:basic-call-response
```

That mode should be reserved for pronunciation/audio-quality cases, not ordinary TTS or routing assertions.

LiveKit TTS logs should include `stage=tts_stream_flush` or `stage=tts_synthesize_start`, `voice_id`, `voice_name`, `text_len`, and `text_excerpt`. This lets near-E2E tests verify the selected voice without spending on STT.

Turn-start logs should include `stage=turn_start_request`, `model`, `service_tier`, and `reasoning_effort` when that evidence is useful, but the basic call-response test does not require those fields to come from LiveKit logs.

The real voice smoke test opens the call surface, requires a successful click on `call.start`, speaks its hard-coded prompt through Cartesia-generated Mac audio, waits for a matching TTS response in LiveKit logs, asserts the normal dispatcher setting is `low`, and hangs up. It uses `OPENBASE_E2E_LIVEKIT_LOG_PATH` without STT.

The parallel-agent truth test is the live share-readiness gate. It asks the
dispatcher to follow a prepared `briefing.md` under `~/openbase-live-test`,
start two Super Agents in separate folders, wait for Elon Musk and Bill Gates
Markdown reports, verify the voice route moves to the Bill report agent, ask
what happened, and verify exit back to dispatch. The spoken prompt intentionally
does not carry exact paths, filenames, report topics, or names.

The orphaned-answer recovery test reproduces the July 2026 voice-delivery
incidents. Its first case asks a deliberately slow dispatcher question, speaks
a short interruption while the dispatcher is still thinking (cancelling the
voice generation that was waiting to speak the answer), then asserts from
LiveKit logs that the finished answer is still delivered
(`stage=orphaned_result_spoken` or a completed-turn rejoin) and audibly
synthesized (`stage=tts_stream_first_audio`). If the interruption never lands
(`stage=voice_turn_cancelled` missing), the test fails as a stimulus-tuning
problem, not a product regression. With `OPENBASE_E2E_EXPECT_AUTO_MUTE=1` and
Auto-mute/Auto-unmute enabled on the phone, it also asserts the mic stays
muted while the answer is owed instead of auto-unmuting into silence. Its
second case answers once, idles silently for 75 seconds, asks again, and
requires a clean reply with no `Cartesia connection error` /
`failed to synthesize` after the idle gap.

## Real Codex Guardrail

The test refuses to start unless:

- `OPENBASE_E2E_ALLOW_REAL_CODEX=1`
- `OPENBASE_E2E_CONFIRM_REAL_CODEX=1`
- dispatcher config at `~/.openbase/dispatcher-config.json` has `"dispatcher_reasoning_effort": "low"`

Run it manually:

```bash
OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 CARTESIA_API_KEY=... pnpm --dir e2e-scripted manual:e2e:ios:basic-call-response
OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 CARTESIA_API_KEY=... pnpm --dir e2e-scripted manual:e2e:ios:parallel-agents-truth
```

It uses the normal Codex/Openbase home configuration from the current shell and installed services. Do not run it unless you intend to use Gabe's real Openbase Coder, Codex, LiveKit, and Cartesia setup.

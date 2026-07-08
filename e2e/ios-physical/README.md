# Openbase Coder iOS Physical E2E

Manual-only: this test drives Gabe's physical iPhone and uses real Openbase Coder, Codex, LiveKit, and Cartesia services. Do not run it unless explicitly instructed.

This package contains physical iPhone E2E tests for Openbase Coder:

- `specs/basic-call-response.real-codex.spec.ts`
- `specs/superagent-own-name.real-codex.spec.ts`
- `specs/parallel-agents-truth.real-codex.spec.ts`

It intentionally uses the normal Codex/Openbase configuration from the current shell and installed launchctl services.
Live no-mock runs should use production Openbase Cloud unless Gabe explicitly
asks for another target. Set `OPENBASE_E2E_EXPECT_WEB_BACKEND` and
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
cp e2e/ios-physical/env.example e2e/ios-physical/.env
pnpm install
pnpm e2e:ios:install-driver
```

Fill in `.env` with the physical device UDID and WebDriverAgent signing values:

```bash
OPENBASE_IOS_UDID=...
OPENBASE_IOS_DEVICE_NAME=Gabe's iPhone
OPENBASE_IOS_PLATFORM_VERSION=18.x
OPENBASE_IOS_XCODE_ORG_ID=...
OPENBASE_IOS_WDA_BUNDLE_ID=com.openbase.coder.WebDriverAgentRunner
```

If the app is already installed on the phone, keep `OPENBASE_IOS_APP_PATH` empty and Appium will activate `com.openbase.coder`. If Appium should install a build artifact, point `OPENBASE_IOS_APP_PATH` at an `.app` or `.ipa`.

## Safe Checks

These commands do not start real Codex flows:

```bash
pnpm e2e:ios:doctor
pnpm --dir e2e/ios-physical test
pnpm --dir e2e/ios-physical typecheck
```

`e2e:ios:doctor` validates local prerequisites, confirms the configured iOS UDID is a physical device rather than a simulator, and confirms the normal dispatcher reasoning setting is `low`. Audio stimulus checks only require Cartesia credentials when `OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1`.
It also reports the active Openbase runtime target and fails if
`OPENBASE_E2E_EXPECT_RUNTIME` is set to a mode that does not match.

The helpers use stable accessibility identifiers when the app exposes them and fall back to visible labels where possible. Future iOS app changes should add identifiers such as `nav.call`, `settings.backend.host`, `settings.backend.add`, `call.start`, and `call.end`.

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

## Real Codex Guardrail

The test refuses to start unless:

- `OPENBASE_E2E_ALLOW_REAL_CODEX=1`
- `OPENBASE_E2E_CONFIRM_REAL_CODEX=1`
- dispatcher config at `~/.openbase/dispatcher-config.json` has `"dispatcher_reasoning_effort": "low"`

Run it manually:

```bash
OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 CARTESIA_API_KEY=... pnpm --dir e2e/ios-physical manual:e2e:ios:basic-call-response
OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 CARTESIA_API_KEY=... pnpm --dir e2e/ios-physical manual:e2e:ios:parallel-agents-truth
```

It uses the normal Codex/Openbase home configuration from the current shell and installed services. Do not run it unless you intend to use Gabe's real Openbase Coder, Codex, LiveKit, and Cartesia setup.

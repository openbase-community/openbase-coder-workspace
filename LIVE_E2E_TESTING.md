# Live E2E Testing

This is the agent-facing runbook for live Openbase Coder E2E tests. These
tests drive real product surfaces and real services. Do not replace service
calls, phone interaction, voice transport, speech synthesis, or agent backends
with mocks when Gabe asks for live E2E coverage.

Before running any live no-mock E2E command, use the workspace-local
`.agents/skills/live-no-mock-e2e` skill. That skill requires writing an RMOT
plan to `/tmp` and opening it in Typora before the live test starts.

## iOS Physical Voice E2E

The physical iPhone suite lives in `e2e/ios-physical`. It drives the installed
modern iOS app (`com.openbase.coder`) through Appium/XCUITest on a real iPhone.
It uses the normal local Openbase Coder runtime, normal Codex/Openbase agent
homes, LiveKit voice services, Cartesia-generated Mac speaker audio, and the
phone microphone.

The suite can target either the installed Electron-bundled runtime or a
workspace/dev runtime. The tests drive whichever Openbase services are active;
use `OPENBASE_E2E_EXPECT_RUNTIME` to make the intended target explicit.

Live E2E should use production Openbase Cloud unless Gabe explicitly asks for a
different target. Set `OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud`
and `OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud` so the doctor and test
runner fail before exercising the wrong cloud/backend.

This suite is manual-only because it can spend real API credits and speak audio
into Gabe's phone. Run it only when Gabe explicitly asks for live full-system
testing.

When the iOS app may be listening, do not use incidental agent `tts` for status
updates or completion messages. Only produce audio that is the intended test
stimulus, unless Gabe explicitly asks for an audible prompt.

## No-Mock Rule

For live E2E requests:

- Do not mock Codex, Super Agents, the dispatcher, LiveKit, Cartesia, Tailscale,
  Appium, WebDriverAgent, the iOS app, or phone interaction.
- Do not switch the runner to a simulator unless Gabe explicitly asks for a
  simulator check. The physical E2E doctor should reject simulator UDIDs.
- Do not point tests at test doubles or synthetic local services.
- Safe preflight commands such as typecheck, helper unit tests, and the E2E
  doctor are fine because they do not exercise the product flow.

## Preflight

From the workspace root:

```bash
pnpm --dir e2e/ios-physical test
pnpm --dir e2e/ios-physical typecheck
pnpm --dir e2e/ios-physical e2e:ios:doctor
```

`e2e:ios:doctor` must pass before a full live run. It checks that:

- the configured UDID is a physical iOS device;
- Appium, Xcode, Tailscale, and the workspace are available;
- the installed app or app artifact can be addressed by bundle ID/path;
- dispatcher and Super Agents reasoning are set to the expected low-cost
  values for live E2E;
- the active Openbase runtime matches `OPENBASE_E2E_EXPECT_RUNTIME` when set;
- Cartesia credentials are present when audio stimulus is enabled.

Use `xcrun xctrace list devices` to find the physical iPhone UDID. If the phone
is offline, locked, asking to trust the Mac, or otherwise needs attention, use
`tts` to ask Gabe for the action before waiting.

## Local Environment

Copy `e2e/ios-physical/env.example` to `e2e/ios-physical/.env` and fill in the
physical iPhone values. Keep secrets out of this file when possible; source
credentials from `~/.openbase/.env` or the current shell instead.

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

Runtime target values:

- `electron-bundled`: require the active standalone runtime to match the
  installed desktop app's bundled CLI package.
- `standalone`: allow any active standalone runtime.
- `workspace`: require a development workspace runtime.
- `any`: report the runtime without enforcing a mode.

For spoken prompts, assume the beginning of the Mac-speaker audio may be
clipped, mistranscribed, or split into partial turns. Do not put exact paths,
filenames, people's names, or acceptance criteria in TTS. Put brittle details
in a prepared `briefing.md` file and make the spoken prompt a short natural
pointer, such as "In my home folder, open the folder named openbase live test
and follow the briefing markdown file." Do not use meta-instructions like "the
real instruction starts after this sentence." During long physical-phone runs,
the iPhone display may dim; keep it awake or set Auto-Lock to Never if dimming
turns into locking.

Prefer voice-friendly filenames and exact text for file-completion assertions,
but keep those details in the briefing file rather than relying on speech.
Hyphens, punctuation, names, and Latin filler text can turn the test into a
speech-recognition edge case instead of an agent-completion test.

## Live Commands

Run the live specs from the package directory or with `--dir`:

```bash
pnpm --dir e2e/ios-physical manual:e2e:ios:basic-call-response
pnpm --dir e2e/ios-physical manual:e2e:ios:superagent-own-name
pnpm --dir e2e/ios-physical manual:e2e:ios:parallel-agents-truth
```

`parallel-agents-truth` is the share-readiness gate from the Testing + Demoing
note. It drives the physical iPhone, asks the dispatcher to launch two Super
Agents from the prepared briefing under `~/openbase-live-test`, waits for the
Elon Musk and Bill Gates Markdown reports, verifies the voice route transfers
to the Bill report agent, asks what happened, and verifies exit back to
dispatch. The spoken prompt is only a pointer to the briefing.

The package scripts set the real-Codex guard variables. If Cartesia credentials
live in a shell env file, extract only the specific key needed by the run
rather than sourcing the entire file:

```bash
CARTESIA_KEY="$(awk '/^CARTESIA_API_KEY=/{sub(/^[^=]*=/, ""); gsub(/^\"|\"$/, ""); print; exit}' ~/Developer/.env)"
pnpm --dir e2e/ios-physical manual:e2e:ios:basic-call-response
```

## Expected Human Actions

Use `tts` when Gabe needs to do something off-chat, such as:

- plug in or unlock the iPhone;
- tap Trust This Computer;
- grant microphone or local-network permissions;
- move the phone near the Mac speaker;
- provide or enable a missing Cartesia credential;
- confirm that a real live test may spend credits.

## After A Run

Report which specs ran, whether the phone was driven through Appium, whether
real audio stimulus was used, and the first real failure if anything fails.
Avoid pasting secrets or long logs. If reasoning settings were changed only to
satisfy the safety gate, say so explicitly.

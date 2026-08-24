---
name: live-no-mock-e2e
description: Use when asked to plan, run, debug, or report on live no-mock Openbase Coder E2E testing, especially physical iPhone/Appium voice tests against real Openbase services.
---

# Live No-Mock E2E

This workspace-local skill is the operational runbook for live Openbase Coder
E2E testing. It applies when Gabe asks for live, full-system, no-mock, human,
physical-phone, Appium, voice, or production-cloud E2E runs.

## Non-Negotiables

- Do not mock Codex, Super Agents, the dispatcher, LiveKit, Cartesia, Tailscale,
  Openbase Cloud, Appium, WebDriverAgent, the iOS app, the desktop app, or
  phone interaction.
- Live E2E uses production Openbase Cloud by default:
  `https://app.openbase.cloud` for cloud/account APIs and `openbase_cloud` for
  the coding backend unless Gabe explicitly asks for another backend.
- Before running a live test, write an RMOT plan to `/tmp` and open it in
  Typora. Do not skip this even if the command seems obvious.
- Use `tts` whenever Gabe needs to do something off-chat, such as unlocking the
  phone, trusting the Mac, moving the phone near the speaker, or providing a
  missing credential.
- When the iOS app may be listening, do not use incidental agent `tts` for
  status updates or completion messages. Only speak when the audio is an
  intentional test stimulus or Gabe explicitly asks for an audible prompt.
- Any time the agent interacts with Appium directly — ad-hoc taps, screenshots,
  page source, alerts, app lifecycle, or debugging outside the wdio spec
  runner — it must go through the `appium` MCP server (`mcp__appium__*` tools;
  registered as `appium`, command `npx -y appium-mcp`). Do not hand-start an
  `appium` CLI server, curl WebDriver endpoints, or write one-off
  WebdriverIO scripts. The pnpm `manual:e2e:ios:*` specs keep using their own
  wdio-managed Appium; the MCP is for agent-driven interaction. See "Direct
  Appium Interaction" below.
- Do not source broad env files for the test process. Cherry-pick only the
  specific credentials or variables required for the command.
- Treat Mac-speaker prompt audio as a real but lossy test dependency. Do not put
  exact paths, filenames, people's names, or acceptance criteria in TTS. Put
  brittle details in a prepared `briefing.md` file and make the spoken prompt a
  short natural pointer, such as "In my home folder, open the folder named
  openbase live test and follow the briefing markdown file." Do not use
  meta-instructions like "the real instruction starts after this sentence." If
  the phone display dims or locks during a long run, pause and ask Gabe to keep
  the phone awake or set Auto-Lock to Never for the test.

## Required RMOT

Before any live command, create a Markdown RMOT under `/tmp` and open it in
Typora. The RMOT must include:

- exact date/time and the requested test scope;
- planned commands and specs;
- whether the run is safe preflight or live no-mock;
- iOS target: device name, UDID, iOS version, app bundle ID, app path/installed
  app status, and whether the iOS app provenance is known;
- local runtime target: `electron-bundled`, `standalone`, or `workspace`;
- Electron details when relevant: installed app version and bundled CLI package
  version;
- CLI/service details: active runtime mode, package version, service status,
  selected coding backend, and cloud web backend;
- production-cloud confirmation;
- audio path: Cartesia model/voice, Mac speaker audio, and phone microphone;
- audio prompt reliability notes: prepared briefing file, minimal spoken
  pointer, and whether Gabe should keep the phone awake / disable Auto-Lock;
- expected human actions and when `tts` will be used;
- no-mock statement listing the real systems involved;
- rollback/cleanup notes, including any temporary reasoning or backend changes.

Use repo-relative or `~`-relative paths in the RMOT.

## Preflight Sequence

1. Confirm the physical iPhone is visible:

   ```bash
   xcrun xctrace list devices
   ```

2. Confirm the intended local runtime. For Electron-bundled tests, the active
   standalone package should match the installed desktop app's bundled CLI.

3. Confirm production cloud targeting:

   ```bash
   openbase-coder backend status
   ```

   If the backend is not `openbase_cloud`, switch with the packaged CLI and
   restart services before the live run.

4. Run safe checks:

   ```bash
   pnpm --dir e2e/ios-physical test
   pnpm --dir e2e/ios-physical typecheck
   OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
   OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
   OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
     pnpm --dir e2e/ios-physical e2e:ios:doctor
   ```

5. If audio stimulus is enabled, provide only the Cartesia key needed by the
   child process, for example by extracting one variable from a private env
   file. Do not source the whole file.

## Direct Appium Interaction

When you need to drive or inspect the phone yourself (reproduce a failing spec
step, check what is on screen, dismiss an alert, take a screenshot, relaunch
the app), use only the `appium` MCP server tools. If the `mcp__appium__*` tools
are deferred, load them via ToolSearch first. Typical flow:

1. `select_device` — pick the physical iPhone (matches `OPENBASE_IOS_UDID`).
2. `appium_prepare_ios_real_device` — call once without
   `provisioningProfileUuid` to list profiles, then again with the chosen UUID;
   this readies WebDriverAgent on the device.
3. `appium_session_management` `action=create` against `com.openbase.coder`
   (or `action=attach` to inspect an existing session instead of creating one).
4. Interact with `appium_find_element`, `appium_gesture`, `appium_set_value`,
   `appium_get_text`, `appium_get_page_source`, `appium_screenshot`,
   `appium_alert`, `appium_app_lifecycle`.
5. `appium_session_management` `action=delete` (or `detach`) when done.

Do not create an MCP session while a live wdio spec is mid-run — a second
XCUITest session can steal WebDriverAgent from the run. Interact between runs,
or attach rather than create.

## Live Commands

Run live specs only after the RMOT is open and the doctor passes:

```bash
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_E2E_CARTESIA_API_KEY="$CARTESIA_KEY" \
  pnpm --dir e2e/ios-physical manual:e2e:ios:basic-call-response
```

Then, if requested and the first run is clean:

```bash
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_E2E_CARTESIA_API_KEY="$CARTESIA_KEY" \
  pnpm --dir e2e/ios-physical manual:e2e:ios:superagent-own-name
```

The share-readiness truth test from the Testing + Demoing note is:

```bash
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_E2E_CARTESIA_API_KEY="$CARTESIA_KEY" \
  pnpm --dir e2e/ios-physical manual:e2e:ios:parallel-agents-truth
```

That spec must use a prepared `briefing.md`, launch two real Super Agents in
separate folders, verify both Markdown reports exist, verify the Bill Gates
agent receives the voice route, ask what happened, and return the route to
dispatch. The spoken prompt should only point to the briefing.

## Reporting

After the run, report:

- which target was tested: iOS app, Electron app, CLI runtime, cloud backend;
- which specs ran and whether they were live no-mock;
- whether production cloud was confirmed;
- whether the phone was driven by Appium on a physical device;
- first failure with concise evidence, not long logs;
- any local settings changed and whether they were restored.

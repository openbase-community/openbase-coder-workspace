---
name: field-testing
description: Use when planning, running, debugging, or reporting an Openbase Coder field test — the tier-3, agent-driven, clean-room, full-acoustic-loop test where an agent installs the product into a disposable VM under a dedicated field-test account and exercises it like a real user. Also the operational annex for running the tier-2 scripted-E2E regression suite.
---

# Field Testing (tier 3)

This workspace-local skill is the operating procedure for **field tests** — tier 3 of the testing taxonomy (`dev-docs/testing-tiers.md`). A field test is agent-driven: no script. An agent installs Openbase Coder from scratch into a disposable, isolated environment, exercises it like a real user (driving the phone through the `appium` MCP server), notices what breaks, and turns every failure into a logged, Slack-reported, READY-PR fix.

It applies whenever the user asks for a field test, live/full-system/no-mock test, or to install-and-exercise the product end to end. For the **tier-2 scripted-E2E regression suite** (deterministic wdio/Appium specs in `e2e-scripted/`), see the [Scripted-E2E annex](#scripted-e2e-annex-tier-2) at the bottom — it is the same live-run gates, applied to frozen specs instead of agent-driven exploration.

## Documentation Ownership (keep the install tracks DRY)

This skill is the **single source of truth for every rule shared by developer-install and signed-DMG field tests**: Appium-first ordering, transport selection and the conditional VPN-passcode gate, field-test accounts and `--mock-payment`, disposable-VM control, Cloud/model checks, phone permissions, acoustic setup, speaker verification, the Super Agent/Desktop-permission gate, failure handling, logging, reporting, and teardown. If a new lesson applies to both installation pathways, update this skill only.

- `dev-docs/DEV_RUNBOOK.md` owns only developer-workspace installation and iteration mechanics. Its field-test notes link here.
- `install-tests/electron-macos/NON_DEVELOPER_FIELD_TEST.md` owns only signed-DMG acquisition, verification, onboarding, and upgrade/reboot mechanics. It returns here for every shared gate.
- `install-tests/electron-macos/README.md` owns only the Tart/Electron harness and its automation commands; it is not a second field-test procedure.

### Stumbling-block index

Use this index to jump to the authoritative recovery instead of adding another copy to an install-track document:

- Automation is not visibly running on the phone: [Preflight Sequence step 0](#preflight-sequence).
- An iPhone passcode, saved-password, or AutoFill prompt is ambiguous: [Blocking early iPhone VPN passcode gate](#blocking-early-iphone-vpn-passcode-gate) and [iOS passcode prompts and app relaunches](#ios-passcode-prompts-and-app-relaunches-hard-won-2026-09-12).
- Openbase VPN will not connect in Tart, or setup waits for its helper: [clean-room VM constraints](#the-one-hard-boundary-never-touch-the-developers-state) and [disposable-VM approval rules](#non-negotiables).
- Browser OAuth opens outside automation control or Tart corrupts text: [clean-room VM constraints](#the-one-hard-boundary-never-touch-the-developers-state) and [desktop onboarding](#driving-the-desktop-onboarding-in-the-tart-vm-verified-2026-09-04).
- A call connects but the phone hears nothing, no reply is audible, or host recording is silent: [Full Acoustic Loop](#full-acoustic-loop) and [Driving the call through Appium](#driving-the-call-through-appium-do-this-before-you-speak).
- A new account runs out of credit or an agent/model request is rejected: [Field-Test Account Lifecycle](#field-test-account-lifecycle) and [Preflight Sequence](#preflight-sequence).
- A spawned coding task hangs or claims it cannot act: [Mandatory Super Agent and Desktop-permission gate](#mandatory-super-agent-and-desktop-permission-gate).
- A build, notarization, or deployment wait may outlive the session: the durable-resume rule under [Non-Negotiables](#non-negotiables).

### Conditional desktop onboarding stages

The managed Openbase Cloud path is Overview → Prerequisites → Setup → Sign in → Phone → Pairing → Verify. It has one desktop authentication stage: the Openbase account sign-in also activates managed coding and managed voice. Choosing BYO Codex or Claude Code adds exactly one Agent sign-in stage. Choosing Cartesia adds Voice Keys; managed Cloud and local audio do not. The phone still signs in to the same Openbase account on that separate device, but it is not another desktop provider-auth stage. The transport choice does not add an authentication stage: Openbase VPN may add macOS helper approval and an iOS VPN-configuration passcode prompt, while Openbase Direct adds neither.

## Hard Boundary Zero: A Field Test Starts From A Fresh Clone, Every Time

**A run only counts as a field test if it begins with `tart clone` of a golden image in that same run.** A VM that already exists — left over from a prior session, already provisioned, already signed in, already paired — is **contaminated evidence**. Continuing on one and reporting the results as a "field test" is a process failure, not a judgment call (real incident, 2026-09-13: an agent resumed a warm previous-session VM whose checkout was on `staging` with hand-copied patches, ran the acoustic loop on it, and reported the developer-install "field test" phase complete — it had tested nothing about installation, setup, onboarding, or first-run state, which is most of what field tests exist to catch).

- **Fresh clone or it isn't a field test.** Before claiming any field-test result, verify the VM was created by this run (`tart list` timestamps; the run plan in the daily log must name the newly cloned VM). If you inherit a session mid-run (compaction, resume, model handoff), re-verify the provenance of the VM you're driving instead of trusting the prior transcript's framing.
- **Warm VMs are for debugging only.** Reusing an existing VM to reproduce a bug, iterate on a fix, or inspect state is fine and often right — but the output of that work is labeled *debugging / fix verification*, never *field test passed*. The fix's validation is a **new clean-room run from a fresh clone** that receives the fixed build through the real pathway (new staging release, or the real setup flow pulling the updated branch).
- **No hand-deployed patches in a run you'll report on.** `scp`-ing edited files into an install and bouncing services is a debugging technique; it turns the install into something no user ever has. Any run containing a hand-patch is disqualified as a field test from that point on.
- **One run, one fresh VM, one account, one log entry.** The daily-log run plan records the freshly cloned VM name, the field-test account (fresh, or reuse explicitly justified), the branch/channel under test, and the install pathway — before the run starts. If the answer to any of those is "whatever was already there," stop and re-plan.

## The One Hard Boundary: Never Touch The Developer's State

**A field test never touches the developer's active user, machine, or local installation.** There is no "uninstall your active install first" step — that old flow is gone. Field tests are clean-room by construction:

- **Host OS runs in a disposable VM.** On macOS, use a [Tart](https://tart.run) macOS VM exclusively — the harness in `install-tests/electron-macos/` clones a throwaway VM so the real machine's install, launchd services, Tailscale routes, and ports 7999/7880 are never touched. The native-Windows pathway uses a Windows VM (later). Never install a field-test build onto the developer's own macOS session.
  - **The macOS Openbase VPN companion does not connect on the cirruslabs (SIP-disabled) base image — very likely a SIP issue, NOT a Tart/virtualization limit.** The privileged `NetmeshHelper`↔`OpenbaseNetmeshCompanion` XPC handshake fails with `-67065 errSecCSGuestInvalid`, so `tailscaled` never starts and the Mac never joins the tailnet — even though both binaries pass `codesign --verify --deep --strict`. Root cause (strong hypothesis, confirmed diagnostics): the cirruslabs CI images ship with **SIP disabled** (`csrutil status: disabled`, `security.mac.amfi.launch_constraints_enforced: 0`), and the helper enforces peer identity with `NSXPCListener.setConnectionCodeSigningRequirement` (an Apple-anchored team+bundle requirement), whose strict audit-token validation depends on normal code-signing enforcement. Tell-tale: `codesign -d +<pid>` on the running companion resolves its identity fine (PID path works), but the strict audit-token XPC path fails — exactly what relaxed enforcement breaks. Virtualization.framework guests have **SIP enabled by default**; the CI image deliberately turns it off. **To exercise the VPN companion in a VM, use a SIP-enabled guest** — a Tart VM built from a vanilla macOS IPSW (`tart create` from IPSW keeps SIP on), or re-enable SIP in the golden image via Recovery → Startup Security → `csrutil enable`. Openbase Direct does not use that companion, but a signed standalone/desktop run must still verify that its runtime package includes and starts `openbase-tunneld`; an older release-package omission made Direct unusable.
- **Test the real user installation path.** For a full staging or production macOS field test, start from a bare VM and install the signed, notarized channel DMG through the normal download, Gatekeeper, Applications, prerequisite, and onboarding flow. Open `https://openbase.cloud/downloads?staging=true` in the VM for a staging build (omit `?staging=true` for production) and use the page's download control; do not start with the raw S3 release-bucket URL, because that bypasses the public CDN-backed download pathway under test and is not the user-facing installation flow. If Tart keyboard or clipboard forwarding prevents reliable navigation, or the user explicitly opts out of testing the marketing download page, stop fighting the guest UI: use SSH and the bare macOS VM's built-in `curl -fL` to download the exact signed channel DMG into `~/Downloads`, then resume the normal Finder, Gatekeeper, Applications, prerequisite, and onboarding flow. Bare macOS does not include `wget`; do not install it just for this fallback. Record the SSH download as an explicit exception and leave the marketing-download surface unclaimed. Tart supplies disposable hardware isolation; Tart-only provisioning is not the installation under test. Use the pre-provisioned golden image, `run.sh`, or a local unsigned app only when the harness or a local build is explicitly the subject, or as a secondary diagnostic after the public path has been tested. Record every prerequisite encountered and whether the user-facing product or public documentation disclosed it before it was needed.
- **Do not paste text through the Tart window.** Host Command-V can time out and insert only a literal `v`; shifted and option characters can also be corrupted even with matching layouts (upstream [openai/tart#1167](https://github.com/openai/tart/issues/1167)). Use the semantic endpoints in `install-tests/electron-macos/`: `guest-automate.sh safari-tunnel` plus `driver/host-drive.mjs --wd` for Safari, and `guest-automate.sh app-cdp` plus `driver/host-drive.mjs --cdp` for a debuggable Electron build. When a release Electron build has CDP fused off and text must go through Tart, select all or clear the field, then keystroke the entire value again and inspect it before submitting; never append a correction to a malformed value. Generate long alphanumeric-only field-test passwords so punctuation forwarding cannot corrupt credentials. The Tart window remains appropriate for clicks and drags on large static targets.
- **Start Safari computer control before opening OAuth.** On a fresh VM, run `guest-automate.sh enable-safaridriver <vm>` once, start `guest-automate.sh safari-tunnel <vm> 4444`, and prime the host WebDriver session with `host-drive.mjs --wd http://127.0.0.1:4444 snapshot` before clicking the desktop app's login action. Safari can still open OAuth in a second ordinary window while SafariDriver stays on its blank automation window; when the page is visibly loaded but `snapshot` returns `[]`, run `guest-automate.sh safari-adopt <vm> 4444` to move that exact visible URL into the controlled window. Do not stop the automation session or type through Tart. Trying to attach only after OAuth has opened is unreliable and led to an avoidable control dead end. Verify the address-bar origin is the expected staging or production origin before entering credentials; for a staging run, `app.openbase.cloud` is a hard stop.
  OAuth confirmation URLs, callback codes, state, and PKCE values are bearer material. Current host-driver output redacts URL queries; if any tool exposes them, do not copy the full URL into a command argument, daily log, report, screenshot caption, Slack message, or committed file. Record only the verified origin and outcome.
- **Give Tart enough display space before boot, but fit it to the host.** On a 1920x1200 host use `manual-vm.sh --display 1600x900pt` or `tart set <vm> --display 1600x900pt --no-display-refit`; a 1920x1200pt guest plus Tart/macOS chrome is clipped on that host. Use the 1920x1200pt default only on a larger host. Synthetic scroll-wheel events, Page Down, and End are unreliable in Tart. A large host-fitting guest makes the complete onboarding controls visible without brittle resizing tricks.
- **Accounts are dedicated field-test identities**, never the developer's real Openbase account. See [Field-test account lifecycle](#field-test-account-lifecycle).
- **Phones run the field-test app variant**, never the developer's normal Openbase app. The field-test variant must have its own bundle/application id and storage so it can coexist with the normal app without replacing its binary, login, VPN state, notification registration, or local data. See [Field-test mobile app variants](#field-test-mobile-app-variants).
- If a request would require mutating the developer's live install, account, or services, stop and re-scope it into the VM + field-test-account model rather than running it against real state.

## Non-Negotiables

- **The disposable VM is entirely yours to drive — never hand the user a Tart step.** It is a throwaway macOS VM with no access to the developer's real machine, data, services, or accounts, so there is *no risk* to delegate and *no reason* to ask. You drive everything about it yourself: `tart clone`/`run`/`stop`/`delete`, SSH in, download and install the DMG, drive the guest GUI (Gatekeeper clicks, Finder drags, System Settings toggles, Login Items "Allow in the Background"), **sign the desktop app into the field-test account by driving its browser OAuth**, toggle its VPN/background items, and enter the disposable VM's *own* admin password — via the `install-tests/electron-macos/` semantic endpoints (`guest-automate.sh safari-tunnel`/`app-cdp` over SSH) or `osascript`/`open` over SSH, never by asking the user to click, type, sign in, or "boot the VM." Asking the user to perform any action *inside* Tart is a process error — the VM has no risk surface to protect. The ONLY things you escalate are actions on the user's **real** devices (their physical iPhone) or genuine external approvals; nothing in the VM qualifies. (Corollary: signing the VM's desktop app in, and thereby starting its backend on 7999, is your job, not a blocker to report. The one genuinely un-SSH-able case, `csrutil enable` in Recovery, is pre-baked into the SIP golden (`openbase-ft-fresh`) — clone it and you never touch Recovery.)
- **Give audible notices around Tart foreground use.** Whenever a field-test step requires bringing the Tart window to the foreground for a visible guest interaction, first run `tts "Hey Gabe, I need to foreground the disposable Tart test VM for the next field-test step."`, then foreground Tart and perform the interaction yourself. As soon as foreground-only work is finished and Tart no longer needs focus, run `tts "Hey Gabe, the disposable Tart test VM no longer needs to stay in the foreground."` so the user knows they can resume using the Mac normally. These notices are informational, not requests for permission or a handoff of the VM step. Do not emit either notice while the phone may be listening during an acoustic test; in that case, end or pause the listening state before the notice, then restore the intended test state afterward.
- Do not mock Codex, Super Agents, the dispatcher, LiveKit, Cartesia, Tailscale, Openbase Cloud, Appium, WebDriverAgent, the iOS/Android app, the desktop app, or phone interaction. A field test is real end-to-end or it is not a field test.
- A direct user request to run or continue a full field test explicitly authorizes the expected clean-room installation sequence inside the disposable VM: open the verified signed channel DMG, drag Openbase into Applications, accept the ordinary macOS first-launch confirmation, and launch it. Do not interrupt that routine sequence for another install/run confirmation. Pause only if the UI requests an unexpected privilege, credential, security bypass, destructive action, or materially different software installation.
- On macOS, choosing the recommended Openbase VPN can install the `OpenbaseNetmesh` background item and pause setup until it is enabled in **System Settings → General → Login Items & Extensions → Allow in the Background**. This is a routine settings change inside an isolated disposable VM, so the field-testing agent has standing permission to navigate there with Computer Use, enable it, and enter the disposable VM's own credentials without pausing to ask the user. Keep the setup process running because it resumes automatically after approval. Record whether the onboarding UI and public installation documentation disclosed this requirement before macOS blocked progress.
  Before sending the user into System Settings, the product UI must show an exact screenshot or a short screenshot slideshow when more than one pane/sheet is involved, plus a control that opens the correct pane. Text-only directions are a field-test UX defect. Verify the screenshots match the current macOS path and that the app continues automatically after approval.
  Reference screenshots: [enabled background item](../../../install-tests/electron-macos/images/allow-openbase-netmesh-background.png) and [authorization sheet](../../../install-tests/electron-macos/images/authorize-login-items-change.png).
- After background approval, wait for the companion to report ready before judging the enrollment result. If the first supported `tailnet set-provider netmesh` attempt failed during the approval transition, record that failure and retry once through the same supported setup surface after the helper settles; do not bootstrap the helper manually or edit protected state. Electron and the bundled CLI are legitimate concurrent clients and must not kill one another's listener. `Address already in use`, a disappearing listener, or a connection refusal while the other client polls is a release regression, not expected VPN latency.
- Dedicated field-test mobile variants target staging Openbase Cloud by default: `https://app-staging.openbase.cloud` for cloud/account APIs and `openbase_cloud` for the coding backend. Verify the desktop/VM uses the same cloud target before starting. A production field test requires an explicitly production-targeted field-test build; never substitute the normal app.
- Never infer the desktop Cloud target from its staging icon, version suffix, branch, or update feed. At the login step, open the browser flow and verify its origin before entering field-test credentials; staging must open `https://app-staging.openbase.cloud`, and a production origin is a blocker. Also verify the generated CLI environment persists the expected `OPENBASE_CODER_CLI_WEB_BACKEND_URL` so later services use the same target.
- A multi-repo release records sibling repository SHAs and aborts if any captured branch moves before publication. Once a CLI or desktop release build starts, freeze every sibling staging branch it consumes until that workflow completes; batch field-testing skill and documentation promotions before triggering the release or after it finishes. If the coherent-snapshot guard catches a race, leave the already-tested trees unchanged and rerun only after all captured refs are stable.
- If release automation withholds an artifact because an externally packaged runtime has advanced beyond the repository's explicit pin, do not bypass the guard or substitute the host binary. Review the upstream patch, advance the single shared pin on `develop`, run its compatibility tests, promote normally, and validate the rebuilt artifact in another fresh clone. The rejected artifact and any VM that received it remain debugging evidence, not a passing field test.
- Before running a field test, record a concise run plan in the gitignored daily field-test log. A separate RMOT or Typora window is not required. See [Required Run Plan](#required-run-plan).
- Use `openbase-coder user say "<agent name>" "<message>"` whenever the user needs to do something off-chat (move the phone near the speaker, unlock it, trust the Mac, provide a missing credential). Keep spoken prompts short and natural.
- When the phone app may be listening, do not use incidental `tts`/`user say` for status or completion updates. Speak only when the audio is an intentional test stimulus or the user explicitly asks for an audible prompt.
- Any time the agent interacts with Appium directly — driving the phone, screenshots, page source, alerts, app lifecycle — it must go through the `appium` MCP server (`mcp__appium__*` tools; registered as `appium`, command `npx -y appium-mcp`). Never hand-start an `appium` CLI server, curl WebDriver endpoints, or write one-off WebdriverIO scripts. iOS uses the XCUITest driver; Android uses the UiAutomator2 driver — both through this one MCP surface. See [Direct Appium Interaction](#direct-appium-interaction).
- Do not source broad env files into the test process. Cherry-pick only the specific credentials required (e.g. extract a single Cartesia key), never `source` a whole private env file.
- **Long waits must survive session death.** Background monitors, armed watchers, and task-completion notifications die silently with the agent session (client close, idle teardown, crash) — a field test that ends its turn "waiting to be woken" by one of these can lose the whole night. Before any wait expected to outlive a few minutes (CI builds, cloud deploys, notarization, config rollouts): (1) write the exact resumable state and the next command to the daily log — this is the line a fresh session resumes from; (2) prefer polling from within an active turn over ending the turn with only an in-session wake signal armed; (3) if the wait genuinely spans a possible session boundary (overnight), schedule a durable out-of-session continuation — an `openbase-coder` routine or an explicit scheduled wakeup — rather than trusting in-session notifications; and (4) on resume, treat every previously armed watcher as dead and re-derive state from the log plus live checks, never from the watcher's silence. (Learned 2026-09-02: a staging config-sync watcher died with the session at 00:30 and the run sat idle for 9 hours; the log-first discipline made resume instant, the in-session-only wake signal caused the loss.)

## Field-Test Procedure

Every field-test session runs the same four steps, in order:

1. **Installation.** Stand up a clean environment (Tart macOS VM, or a Windows VM for the native-Windows pathway), install the product using the sampled installation method, build/install the mobile field-test variant, and create the designated throwaway account through the real [signup and verification lifecycle](#field-test-account-lifecycle).
2. **Smoke test.** A short basic check that the core loop works at all — place a call, get a dispatcher response through the full acoustic loop — before investing in anything deeper. If the smoke test fails, that is the finding; stop and file it.
3. **Super Agent gate.** Spawn a real non-dispatcher Super Agent in a new folder, make it perform a small file-backed task, and hear its unsolicited self-announcement. On every macOS/Tart run, use a fresh Desktop folder, reset Desktop-folder TCC before the attempt, wait for the real macOS Desktop-access alert, and click **Allow directly in the Tart window**. A previously granted permission, a dispatcher-only answer, or log-only evidence does not satisfy this gate.
4. **Targeted testing.** Exercise whatever most likely changed since the last field test. Determine this by reading recent commits across the workspace repos since the previous field-test log entry (see below). Effort follows the code: concentrate on the surfaces and flows that were just modified.

### Mandatory Super Agent and Desktop-permission gate

The dispatcher answering a question ("what is seven times six?") only proves the **voice dispatcher** brain + cloud auth + acoustic loop. Every full field test must also prove the product's actual job: **spawning and steering a coding Super Agent**. This is a completion gate, never an optional stretch goal. After the dispatcher smoke passes:

1. Create a new folder and a `briefing.md` that asks for a small exact file-backed task. On macOS/Tart, put the folder on the VM Desktop and reset only Desktop-folder TCC in the disposable guest before the attempt. Do not accept an earlier grant from onboarding or another test in the same VM as coverage of this gate.
2. By voice, tell the dispatcher to start a coding session in that folder and follow the briefing. Keep brittle specifics in the briefing and do not tell the Super Agent to introduce itself; the announcement must be unsolicited.
3. On macOS/Tart, wait for the real Desktop-folder access alert and click **Allow manually in the Tart window**. macOS may attribute the request to `Openbase` or to the packaged runtime child such as `python3.12`; either is valid only when it appears during the sampled Super Agent turn. The field-testing agent performs this click; do not ask the user, bypass the alert with an API, or treat a log message as permission evidence. If the prompt does not appear because access is already granted, reset Desktop-folder TCC and repeat with a fresh Desktop folder.
   Reference screenshot: [Desktop-folder access alert](../../../install-tests/electron-macos/images/allow-openbase-desktop-folder.png).
4. Confirm a **Super Agent thread is actually started** — not just a spoken dispatcher reply. Check the store and the log:

   ```bash
   sqlite3 ~/.local/share/super-agents-*/state.sqlite3 \
     'select name,backend,model,status from sessions;'   # a non-"dispatcher" thread appears
   grep -E 'start_thread|turn_start_response|super_agents_client' ~/.openbase/logs/livekit-agent.log | tail
   ```

   A Super Agent turn requires the coding backend to authenticate (the same `openbase_cloud`/machine-token or personal `claude login`/`codex login` path as the dispatcher). If the dispatcher says a coding-backend error aloud (now a graceful "trouble reaching the coding service" line, not a raw dump), grep for `stage=voice_turn_backend_auth_failure` / `voice_turn_backend_error` — that is the finding.
   If the agent announces, begins work, and then fails exactly when the dispatcher turn exits, inspect the Super Agents MCP lifecycle before blaming permissions or the model. Recursive Super Agents calls must be owned by the long-lived SDK client; a dispatcher-scoped stdio child can be torn down while its delegated turn is still running. Do not accept a partially written file as a pass—validate the thread's final state and exercise transfer/return on the fixed release.
5. Verify the thread **did the work** (the exact file/command exists in the VM), hear the Super Agent's unsolicited self-announcement on the physical phone, and confirm that the dispatcher can **report its result back** by voice and **hand the call to it / return to dispatch**. Database rows and voice-delivery logs corroborate the result but never replace listening. The scripted `manual:e2e:ios:parallel-agents-truth` gate (below) is the frozen version of this — launch agents from a briefing, verify their Markdown reports, transfer the voice route, ask what happened, return to dispatch.

Note the store's `UNIQUE(name)` on sessions is not backend-scoped: if a prior run left a `dispatcher` (or same-named) session under a *different* backend identity, `create_session` collides (`sqlite3.IntegrityError: UNIQUE constraint failed: sessions.name`). Clear stale rows (`DELETE FROM sessions …`) or start from a fresh clone — a real clean-room run never hits this.

Deciding what to target from recent commits:

```bash
# What changed across the workspace since the last field test?
multi git -- log --oneline --since="<date of last field-test log>"
# Or per repo, e.g.:
git -C ios log --oneline -20
git -C cli log --oneline -20
```

Read the last entry in `.local/field-tests/` to find the previous run's date and what was covered, so this run targets new risk rather than repeating old ground.

## Parameter Model (sample per run)

Each run samples a point in this space. Sampling is **stochastic but weighted**: prioritize **iOS and macOS**, sampling the others less often, so coverage spreads over time without abandoning the most-used surfaces. Record the sampled values in the daily log.

| Parameter | Options |
| --- | --- |
| Starting OS (host) | macOS Tart VM *(prioritized)* · Windows VM |
| Mobile OS | iOS / XCUITest *(prioritized)* · Android / UiAutomator2 |
| Mobile app | field-test variant only; never the normal Openbase app |
| Connectivity profile | strong Wi-Fi · constrained/lossy · cellular-like |
| Branch | `main` · `staging` · `develop` |

**Branch↔Cloud pairing:** only two clouds are deployed — production (`app.openbase.cloud`, serves `main`) and staging (`app-staging.openbase.cloud`, serves the `staging` branch). There is **no deployed develop cloud**, so a `develop`-branch field test means: coder-workspace repos at `develop`, cloud target = **staging**. That is fully feasible for coder-side changes, with one caveat: any cloud-side (`openbase-cloud-workspace`) change on develop is NOT live until promoted develop→staging — so promote the cloud side first if the test depends on it. (After an exact-tree promote, staging ≡ develop anyway, and a staging run doubles as a develop run.) A true isolated develop cloud would require deploying a third PaaS app; don't spin one up ad hoc for a field test.
| Installation method | normal user install · developer install (`./scripts/setup`) |

Pick a concrete value for each before starting the run. If the sampler is unavailable, choose by hand but keep the iOS/macOS bias and vary from the previous run so the matrix fills in.

## Full Acoustic Loop

**The product's own audio uses the Openbase Cloud provider** (`--audio-provider openbase-cloud`: Cloud TTS + Cloud STT — the managed default and the realistic user path). Configure the field-test install that way; do not set Cartesia or local audio unless those providers are specifically the subject under test. This is about the *dispatcher's* speech and hearing — distinct from the two host-side legs below, which are how the agent injects a stimulus and verifies the answer.

Field tests close the real audio loop **in both directions**:

- **Outbound stimulus:** the field-test probe's neutral **host** Cartesia voice, played through the Mac/host speakers into the phone's microphone as genuine acoustic input — not a direct API call. Use macOS `say` only as an explicit fallback. (The stimulus is host-generated; the product still hears it through its Cloud STT.)
- **Inbound capture:** the phone's spoken reply recorded back through the host microphone and transcribed by the bundled `scripts/acoustic-probe.py`, so the agent asserts on the *meaning* of what the product said, not just on log lines. That host-side transcription uses AssemblyAI (`$ASSEMBLYAI_API_KEY`, `--stt mlx` local fallback) — Openbase Cloud STT is realtime-streaming for live calls, not a batch-file endpoint, so it is not the tool for transcribing a saved recording.

**Transport health is NOT a pass — assert on the actual words.** `voice_delivery_audio_delivered delivered=True`, RTP flowing, a non-empty `speech_len`, and a clean STT round-trip only prove the *pipe* works in both directions. They do **not** prove the assistant answered. The dispatcher will faithfully speak an *error* through that same healthy pipe — e.g. every reply being the 34-char `"Not logged in · Please run /login."` when the coding backend is unauthenticated (`~/.codex/auth.json` missing), which looks identical in the delivery logs to a real answer. Before calling the loop (or the whole test) a pass: read the real spoken **text** (`tts_stream_flush` / `livekit_llm_delta_emitted` `text_excerpt=`), confirm it is a correct, substantive response to what was asked, and confirm it is not the same canned string every turn. A clean-room install that reaches a live call where the assistant can only say "/login" is a **failed** field test, not a passing acoustic loop.

### Driving the call through Appium (do this before you speak)

A from-scratch run stalls here if it just speaks and reads logs. The concrete mechanics:

- **Query system alerts immediately after every first `call.start` on a fresh app install.** Call `appium_alert action=get_text` before interpreting a page source that says `Connecting...`: iOS can present the microphone permission sheet while the ordinary accessibility tree still describes the underlying call UI. If the sheet says the field-test app would like microphone access, accept **Allow** through Appium, then verify it closed. Current app code requests and resolves microphone permission before joining; if an older build already joined a room before permission was granted, end that stale room and start a fresh call. Microphone permission is not the VPN passcode prompt, and the agent can accept it without asking the user to touch the phone.
- **Verify the mic is live before you speak — don't assume it's muted OR unmuted.** A *fresh* call is not muted, but "Auto-mute (mute when the agent speaks)" is a real feature and leftover state from a prior test cycle (a still-connected room, a call you muted earlier) can leave it muted; speaking into a muted mic gives STT only ambient fragments. Check: when live the bottom-left control is `call.mute` (label "Mute"); if it is `call.unmute` (label "Unmute") / the screen reads "Microphone muted", appium-tap `call.unmute`. If Auto-mute keeps re-muting you mid-prompt, toggle the Auto-mute switch OFF for the test. Call-control accessibility ids: `call.start`, `call.end`, `call.mute`, `call.unmute`, `call.speaker`.
- **Front-load phone placement with the other human actions.** Before touching the VM, ask the user to unlock the physical test phone, keep it beside the Mac speakers, and be ready for its platform-specific trust prompts. For iOS, expect Mac trust and VPN device-passcode prompts; for Android over USB, have USB debugging enabled and require the user to accept the computer/RSA trust prompt before provisioning starts. If the inbound leg is silent after placement is confirmed, debug in this order: (1) host audio output device; (2) host output volume; (3) call mic state and whether the call started before mic permission was granted; (4) restart the call if needed.
- **Check host output volume before every spoken stimulus**: `osascript -e 'output volume of (get volume settings)'` — the user may have turned it down between rounds; set it (`set volume output volume 60`) rather than assuming (missed this 2026-09-12; a stimulus played inaudibly).
- **SPEAKER mode is a hard precondition for speaking to the phone.** The required order is: connect the call → appium-tap `call.speaker` → take an Appium screenshot → verify the speaker control has the solid high-contrast selected fill (dark/navy in light mode; light/white in dark mode), while the inactive control uses the pale or dark surface-muted fill with an outline → only then emit any host-TTS or other acoustic stimulus. A tap, an enabled control, the `call.speaker` identifier, and the `Volume High` accessibility label are not proof because they are present in both route states. If the screenshot does not prove the selected styling, do not speak; resolve the route or end and restart the call. iOS otherwise routes call audio to the earpiece, so the host-mic recording hears no reply even when `tts_stream_flush` and `voice_delivery_audio_delivered delivered=True` prove that the dispatcher generated and sent one. No screenshot-verified speaker mode = no acoustic test.
- **In a noisy room, keep the phone muted between stimuli.** Speaker remains enabled. Immediately before the prepared Cartesia audio plays, verify speaker again and tap Unmute; immediately after the complete stimulus finishes, tap Mute. Do not leave the phone microphone open while preparing commands, reading logs, or waiting for the next turn.
- **Never prompt the behavior under test.** If the test is "the spawned agent announces itself," do NOT say "the agent should introduce itself" — the introduction is standard behavior and the test is whether it happens UNPROMPTED. Telling the dispatcher contaminates the result (Gabe, 2026-09-12). Speak only the task; assert on the untold behavior.
- **A hung turn is often a GUI prompt in the VM — look at the Tart window.** Real case (2026-09-12): the dispatcher's Bash `mkdir ~/Desktop/...` hung on macOS TCC at `python3.12 would like to access files in your Desktop folder`. The product now surfaces a spoken blocked-turn hint, but the OS dialog still requires a visible choice. Screenshot the Tart window first, foreground Tart, then click **Allow directly in the Tart window** with Computer Use and verify the prompt disappears. Do not bypass the prompt with `cliclick`, `osascript`, an API, pre-granting, or provisioning-time folder touches; every full macOS field test must reset Desktop-folder TCC and exercise this first-use gate on a fresh Desktop folder. Desktop, Documents, and Downloads are separate TCC grants, so only the folder actually sampled by the test is covered. A stall in a dispatcher-spawned sub-agent is not caught by a watchdog that only wraps the dispatcher's awaited turn because the dispatcher fire-and-forgets that thread. Blocked-turn surfacing must therefore cover spawned-agent threads. PR openbase#32 implemented a session-wide poller keyed on the reliable signal: a turn failing with `Control request timeout: initialize` when a spawned process blocks at init behind the consent dialog. Do not reuse two disproven detectors: a long-running `turn.status`, because affected sub-agent turns can fail quickly, or dialog-presenter process recency, because UserNotificationCenter is long-lived and reused. An on-screen CGWindowList owner probe was not shipped because it was not positively confirmed against a live prompt.
- **Two minutes of silence = failure, not latency.** If the dispatcher/agent hasn't audibly responded within ~2 minutes of a spoken turn, it is not going to — stop waiting, read the logs for the failure, and treat it as a finding. Do not keep extending the wait.
- **Use Cartesia for the host stimulus.** The macOS system voices can have accents that reduce phone STT reliability. `scripts/acoustic-probe.py` therefore defaults to the realistic Cartesia voice shared with scripted E2E. Extract only `CARTESIA_API_KEY` from `~/Developer/.env`; never source or pass the whole file. Use `--tts macos` only as an explicit fallback. This changes only the test stimulus; the product reply still uses its configured real TTS voice.
- **Read the dispatcher's ACTUAL answer from the VM agent log**, not the phone screen alone:

  ```bash
  # What the phone heard (your stimulus):
  grep stage=stt_final_transcript ~/.openbase/logs/livekit-agent.log | tail -3
  # What the dispatcher actually SAID (assert on this):
  grep tts_stream_flush ~/.openbase/logs/livekit-agent.log | tail -3   # text_excerpt=...
  # Whether the turn was really an error masquerading as an answer:
  grep stage=voice_turn_result ~/.openbase/logs/livekit-agent.log | tail -2   # backend_auth_failure=<bool>
  ```

  A pass is a correct, substantive `text_excerpt` with `backend_auth_failure=False` — e.g. asking "what is seven times six?" and getting "Seven times six is 42." with `voice_delivery_audio_delivered delivered=True`.
- **When the dispatcher runs cloud-side there is no local `livekit-agent.log` to read** — a *managed* Cloud backend (openbase_cloud / openbase_cloud_codex, the fresh-install default) runs the dispatcher in Openbase Cloud, and a Mac paired via the **desktop app** doesn't write that log locally. In that case you cannot read the answer from a VM log; capture it acoustically instead with the bundled probe, which speaks the stimulus and transcribes the room (so the transcript holds *both* your question and the product's spoken reply):

  ```bash
  export ASSEMBLYAI_API_KEY=…   # product-parity STT; --stt mlx falls back to local whisper
  scripts/acoustic-probe.py "What is seven times six?" --seconds 16
  ```

  The probe defaults to Cartesia TTS and AssemblyAI STT; use `--stt mlx` for the local Whisper fallback. It synthesizes before recording so network latency does not consume the response window.

  Two host-side gotchas, both one-time and both silent-failing:
  - **Microphone permission.** The recorder is `ffmpeg -f avfoundation`; the terminal/app running it needs Privacy & Security → Microphone. Without it macOS returns *digital silence* (a wav whose `volumedetect` mean/max is ~-91 dB) — the `say` still plays, so it *sounds* fine while capturing nothing. Verify capture with `ffmpeg -i out.wav -af volumedetect -f null -` before trusting a transcript.
  - **Pick the built-in mic, not Continuity.** `ffmpeg -f avfoundation -list_devices true -i ""` often lists the user's iPhone (Continuity) as audio device `:0`; that mic isn't in the room with the test phone. Use the MacBook mic index (`--device 1` here) so it actually hears the phone's speaker.
- **`appium_screenshot` returns oversized inline base64** (it errors on token size); it also saves a PNG to a temp path in its result — read that file instead of the inline payload.
- **If you restart the livekit-agent (e.g. to load a patch), the live call's agent is gone** and the phone shows "The agent left the call. End the call and try again." — appium-tap `call.end` then `call.start` for a fresh room. A normal run that isn't restarting services rarely sees this; the pool self-heal watchdog (`livekit_pool_watchdog`, see `dev-docs/TROUBLESHOOTING.md`) only bounces the agent on the WebRTC-timeout failure signature, with an active-call guard.

Treat speaker-prompt audio as a real but lossy dependency. Do not put exact paths, filenames, people's names, or acceptance criteria into spoken audio. Put brittle details in a prepared `briefing.md` file and make the spoken prompt a short natural pointer, e.g. "In the home folder, open the folder named openbase field test and follow the briefing markdown file." Do not use meta-instructions like "the real instruction starts after this sentence." If the phone display dims or locks during a long run, pause and ask the user to keep the phone awake or set Auto-Lock to Never.

## Driving the desktop onboarding in the Tart VM (verified 2026-09-04)

The macOS desktop onboarding is fully agent-drivable over SSH-forwarded CDP — no
Tart-window typing. Relaunch the installed app with a debug port and drive it by
button text with the `install-tests/electron-macos` host driver:

```bash
cd install-tests/electron-macos
# the installed app is /Applications/Openbase.app (NOT "Openbase Coder.app" —
# pass the path explicitly or app-cdp fails on CFBundleExecutable)
./guest-automate.sh app-cdp <clone> "/Applications/Openbase.app" &   # tunnels CDP :9222
D() { node driver/host-drive.mjs --cdp http://127.0.0.1:9222 "$@"; }   # (inline, not a var, in zsh)
D snapshot            # lists buttons; D text dumps body innerText; D shot x.png screenshots
```

`click` matches `getByRole("button", {name: RegExp(target,'i')})`, so the target
is a **regex** — pick a clean unique substring, never one with `()`/`—` (e.g.
`recommended`, `^No$`, `I understand, run setup`). The clickthrough that worked:
Follow the [conditional stage sequence](#conditional-desktop-onboarding-stages). For the managed path, click `Let's get you set up` → inspect the transport choices and trust copy, select the sampled transport, and click `Check prerequisites` → answer `^No$` (no existing Codex/Claude CLI to import), click `Run setup`, then confirm with `I understand, run setup` → poll `curl 127.0.0.1:7999/api/health/` until 200 (setup installs the 5 launchd services and binds 7999; ~60–90 s) → click `^Continue$` → on Sign in, `Sign in` opens browser OAuth. Drive it with `safari-tunnel` + `host-drive.mjs --wd`, verifying the origin is `app-staging.openbase.cloud` before filling the field-test credentials. The setup command uses `--backend openbase-cloud --audio-provider openbase-cloud` plus `--tailnet-provider netmesh` for Openbase VPN or `--tailnet-provider netmesh-tsnet` for Openbase Direct. Do not expect or automate invisible placeholder stages for options the user did not choose.

**The visible security-decision step — the Openbase VPN background-item consent.** Choosing
Openbase VPN registers the `cloud.openbase.netmesh.helper` daemon via
SMAppService; until it is approved (System Settings → General → Login Items &
Extensions → **Allow in the Background**) `sfltool dumpbtm` shows NetmeshHelper
`disallowed`, the companion can't hold the tailnet (node flaps offline), and the
onboarding's `Sign in` action stays gated. Do not bypass this consent by editing system state over SSH
(`launchctl asuser` GUI scripting fails `Could not switch to audit
session … Operation not permitted`) and CANNOT be forced with sudo (the daemon
uses a bundle-relative `BundleProgram`, so a manual `launchctl bootstrap` fails
`5: Input/output error`; the BTM db is SIP-protected). The supported automation
is **Computer Use clicking the Tart window** — which needs the Computer Use
plugin attached to the session (console → Settings → Coding backend (Claude Code)
→ Computer Use; if `mcp__(openbase-)computer-use__*` tools aren't present it's
off). This consent is a **real user-facing part of setup** — approve it fresh
each run via Computer Use, and record whether onboarding/docs disclosed it before
macOS blocked progress. Do NOT pre-bake this approval into the golden: that would
hide the exact OS-prerequisite friction the field test exists to surface. (SIP
itself is different — it is on by default for real users, so a SIP-on golden is
faithful; this VPN background-item consent is a per-run setup step, not baseline
image state.)

## iOS passcode prompts and app relaunches (hard-won, 2026-09-12)

Identify the prompt by its visible wording before attributing it to VPN. Saved-password AutoFill/local authentication, device/Mac trust, and VPN configuration are different gates; a prompt to fill a saved password is not evidence that VPN configuration was modified. Staging and field-test iOS builds disable saved-login storage and password AutoFill through the shared AllAuth environment policy, including signup and password confirmation, while retaining secure text entry. A saved-password unlock prompt on those builds is a regression, not an expected human prerequisite. VPN configuration may separately require the user to enter their passcode directly on-device. Appium session creation with a bundle id can relaunch the app, so preserve the current session and inspect the actual prompt rather than assuming every relaunch requires VPN consent. Consequences:

- **Do the phone's entire user-gated chain (sign-in/up → VPN connect → any system passcode prompt) in ONE uninterrupted Appium session, first thing in the run.** Do not recreate the session casually; surface VPN consent at the earliest valid point after authentication.
- **When the accessibility tree wedges** (`Timed out while fetching snapshot from testmanagerd`) — historically triggered by the login page engaging saved-password/AutoFill machinery (FT-7) — do NOT reflexively recreate the session. On a current staging/field-test build, first record any saved-password UI or local-auth prompt as a regression. Screenshots still work when the tree doesn't; fall back to `appium_screenshot` + coordinate taps + `appium_set_value` with `w3cActions:true` (keyboard events to the focused element). Session recreation is the LAST resort because it relaunches the app and can disrupt a pending VPN flow.
- **THE text-entry recipe (use FIRST, not as a fallback):** this app's fields violate common Appium assumptions — `set_value` with an element APPENDS/INSERTS at the cursor (it does NOT replace, and an empty `set_value` does NOT clear); typing `\b` sends literal backslash-b characters, not backspaces; and prefilled fields (e.g. a dead account's email) will silently corrupt into spliced garbage. The reliable sequence for every field: (1) `long_press` the field (~1200ms) → find `label == 'Select All'` (plain `accessibility id` may miss it; the menu is transient — find immediately) → tap it; (2) type the full value with `appium_set_value` + `w3cActions:true` (typing replaces the selection); (3) VERIFY with `appium_get_element_attribute value` — exact string for text fields, dot-count == password length for secure fields; (4) re-find the submit button fresh (`type == 'XCUIElementTypeButton' AND label == '...'` — a bare label match can hit the nav title) and tap. A Save-Password or saved-password unlock sheet on staging/field-test builds is a regression; dismiss it to continue only after recording the finding.
- Appium element handles go stale after keyboard/layout changes and **stale-element taps silently no-op** — re-find every button immediately before tapping it. RN/SwiftUI secure fields: element-setValue may append or clear on focus loss; the reliable pattern is tap-to-focus then w3cActions typing, and verify with `appium_get_element_attribute value` (dots count = char count) before submitting.
- If an account was destroyed since the phone last signed in, inspect the next launch for stale authentication or VPN state; do not predict or label a passcode prompt without observing its purpose.

## Field-Test Mobile App Variants

Always build, install, and launch the platform's dedicated field-test variant. The normal Openbase app must remain installed, signed in, and otherwise untouched so the user can continue using it while the field test runs.

- **iOS:** generate the project and build the `OpenbaseFieldTest` scheme. Its bundle id is `com.openbase.coder.field-test`, its authentication URL scheme is `openbase-field-test`, and its app group/VPN extension are distinct from the normal app. It targets `https://app-staging.openbase.cloud`. Install and launch the resulting artifact, then create the Appium MCP session against `com.openbase.coder.field-test`.
- **Android:** run `./gradlew :app:assembleFieldTest`, install and launch the resulting field-test APK, and create the UiAutomator2 session against `com.openbase.android.fieldtest`. The variant has separate storage and the `openbase-field-test` authentication URL scheme, targets `https://app-staging.openbase.cloud`, and can coexist with `com.openbase.android`. Never substitute, reset, or uninstall the normal app.

Typical iOS source build:

```bash
cd ios
tuist generate
xcodebuild -workspace Openbase.xcworkspace \
  -scheme OpenbaseFieldTest \
  -destination 'id=<physical-device-udid>' \
  build
```

Typical Android source build:

```bash
cd android
./gradlew :app:assembleFieldTest
```

Use the Appium MCP preparation/session flow to install or launch the built artifact. Do not uninstall, reset, sign out, terminate for cleanup, or otherwise manipulate the normal app as a shortcut.

## Field-Test Account Lifecycle

A core field test creates a real **throwaway Openbase account** through the product's normal signup UI. It never uses a developer account, personal email, or personal inbox. Generate a fresh address matching `delivered+openbase-field-<opaque-run-slug>@resend.dev` for each run; no deployment allowlist change is required. This is Resend's official delivered-test recipient with a run-specific label; the `+` form is allowed only for this exact reserved contract. Personal-provider addresses and every other plus-address are forbidden.

The product performs the real signup and email-verification flow: allauth creates the initially unverified user, renders its normal verification message, the selected Cloud deployment submits it to Resend, the field-test agent retrieves that exact rendered message, and the agent follows its real confirmation URL through the tested app/browser surface. Do not mark an `EmailAddress` verified directly.

The cloud API's `field_test_account` Django management command deliberately cannot create or verify users. It owns only the two exceptional lifecycle operations:

- **`--destroy EMAIL`** deletes the account through the canonical cascade. It is idempotent when the user is absent and is used before a reused identity and after every run.
- **`--mock-payment EMAIL`** grants paid entitlement after real verification via a purely local `payment.Subscription` row at the normal default-tier cap—no payment-provider call or charge. Run it for every full field test because the mandatory Super Agent gate is paid-feature scope and a realistic agent context can make the free plan's conservative next-request reservation exceed the remaining allowance before the settled spend reaches the displayed cap.

The lifecycle across one core product field test:

1. Generate an opaque run slug and choose `delivered+openbase-field-<slug>@resend.dev`. Confirm it matches the reserved pattern exactly; do not use `test@…`, `@example.com`, another Resend test outcome, or a personal-provider plus-address.
2. Record the UTC run start time. Run `openbase run --memory 1024 -a <app> python manage.py field_test_account --destroy <email>` so a reused address starts clean; an idempotent `not_found` result is acceptable. The composed staging app's default 256 MiB one-off task can be OOM-killed with exit 137, so every `field_test_account` invocation must set `--memory 1024`.
3. Generate a strong, long, alphanumeric-only ephemeral password locally without printing it, drive the field-test app's normal signup UI, and require the expected unverified/"Verify Your Email" state. Avoid punctuation because Tart/iOS keyboard forwarding can corrupt it. A long-running field test must not rely only on agent/tool memory for this password: store it in the host OS credential vault under a run-specific service label, never in a tracked file or durable log, and delete that vault item during cleanup.
4. Use an authenticated Resend CLI profile to poll sent-email metadata. The active/default profile is acceptable; a separate field-test profile is not required. Select only a message addressed to the exact field-test address and created after the recorded start time, then retrieve that message by id. Never pass an API key with `--api-key` or source a broad environment file.
5. Read the returned HTML/text, find the real confirmation URL, and follow it through the tested phone/browser surface. Verification URLs are bearer credentials: never put one in a shell command, run plan, report, Slack message, screenshot caption, or durable log.
6. Confirm the product reports the email verified and the account can sign in. For every full field test, run `openbase run --memory 1024 -a <app> python manage.py field_test_account --mock-payment <email>` immediately after verification and before the first dispatcher or Super Agent call. A smoke-only account test may omit this only when it explicitly excludes the mandatory full-test gates.
7. After the run, always run `openbase run --memory 1024 -a <app> python manage.py field_test_account --destroy <email>` and remove any ephemeral local credential material.

Resend CLI retrieval uses the active authenticated profile, whose credential remains in secure CLI storage. Use `--profile <name>` only when an explicit non-active profile is needed:

```bash
resend emails list --limit 100 --json
resend emails get <message-id> --json
```

Inspect list results before `get`: the recipient must exactly equal the selected address, `created_at` must be after the recorded run start, and the message must be the expected verification message. If the authenticated profile is unavailable, the exact message does not arrive, or the provider reports a non-delivered outcome, stop and record the blocker. Never fall back to a personal inbox, another person's inbox, Slack, an arbitrary admin-mail endpoint, or direct database verification.

Cloud lifecycle invocations contain no credential:

```bash
openbase run --memory 1024 -a <app> python manage.py field_test_account \
  --mock-payment delivered+openbase-field-20260901-a7f3@resend.dev
openbase run --memory 1024 -a <app> python manage.py field_test_account \
  --destroy delivered+openbase-field-20260901-a7f3@resend.dev
```

This exercises real signup against the selected Cloud deployment, mandatory verification, template rendering, Resend submission, message retrieval, and allauth confirmation. Resend's delivered-test recipient simulates the mailbox end without sending to a person. A separate scheduled delivery canary may test receipt by a real mailbox provider; it never uses a personal inbox.

## Required Run Plan

Before any field-test command, add a concise Markdown plan to the gitignored daily log at `.local/field-tests/<date>.md`. Do not open a separate RMOT or Typora window. The plan must include:

- exact date/time and the requested test scope;
- the **sampled parameters** for this run (host OS, mobile OS, connectivity, branch, installation method) and the previous run's date;
- the fresh field-test account identity and confirmation it matches `delivered+openbase-field-<slug>@resend.dev`, the recorded UTC start time, the Resend CLI profile being used (the active/default profile is acceptable; never record its credential), the planned real signup/message-retrieval/verification steps, and mandatory post-verification `--mock-payment` for a full field test;
- clean-room confirmation: which disposable VM (Tart macOS / Windows) and that the developer's real install/account/services are untouched;
- planned steps: install → smoke → targeted, with the specific targeted areas derived from recent commits;
- iOS/Android target: device/emulator, driver (XCUITest/UiAutomator2), field-test variant name, its distinct bundle/application id, app provenance, and confirmation the normal Openbase app will remain untouched;
- local runtime target inside the VM: `electron-bundled`, `standalone`, or `workspace`;
- CLI/service details: runtime mode, package version, service status, coding backend, and cloud web backend;
- exact cloud-target confirmation, normally staging for the dedicated mobile variants;
- audio path: Cartesia model/voice, host speaker audio, phone mic, and local STT for inbound capture;
- audio-prompt reliability notes: prepared briefing file, minimal spoken pointer, keep-phone-awake / disable Auto-Lock;
- expected human actions and when `user say` will be used;
- no-mock statement listing the real systems involved;
- rollback/cleanup notes (VM deletion, `field_test_account --destroy`, ephemeral-password cleanup, field-test Appium session deletion, and field-test app cleanup without touching the normal app).
- **Teardown timing (learned 2026-09-12): don't tear down the moment the smoke gate passes.** Follow-up "one more test" requests are the norm, and deleting the VM + destroying the account converts a 2-minute follow-up into a ~40-minute clean-room rebuild (fresh signup/Resend cycle, VPN consent dance, phone re-login — the phone app is left signed into a now-destroyed account). Keep the run VM (stopped) and the account alive until the user confirms the testing session is over; the hard teardown is the LAST step of the session, not of the first passing test.

Use repo-relative or `~`-relative paths in the run plan. Keep brittle scratch in `.local/` (gitignored) — never reference `.local/` files from committed docs.

## Preflight Sequence

0. **Assert Appium control of the physical phone as the first operational step, with a one-minute deadline (Gabe's rule, 2026-09-13).** For any field test with a physical phone, begin the Appium MCP chain within the first 60 seconds of the request and drive it continuously through device selection, real-device preparation, and field-test-app session creation or attachment. Nothing else comes first: do not read additional runbooks, edit documentation, write the run plan, inspect releases, create an account, build the mobile app, or touch Tart until the Appium attempt is actively underway. The target is a visible iOS **Automation Running** state or the Android equivalent within that first minute when the connected device permits it. Appium does not routinely require the iPhone passcode: a passcode may be needed only if iOS must establish device/Mac trust, while the recurring passcode prompt discussed elsewhere in this skill belongs to Openbase VPN configuration. If WDA installation, device lock, missing trust, or another external dependency prevents completion within 60 seconds, immediately state the exact live blocker while the Appium call continues; never fill that time with unrelated setup. If the phone is locked or trust is missing, let this first attempt surface that human dependency immediately; ask the user to unlock the phone, keep it next to the Mac speakers/on a charger, and resolve any trust prompt on-device, then finish establishing Appium control. On iOS, have the user set Auto-Lock to Never. On Android over USB, require USB debugging and the on-device computer/RSA trust prompt. The agent never learns or enters a device passcode.

   After Appium control exists, apply the transport-conditional [early iPhone VPN passcode gate](#blocking-early-iphone-vpn-passcode-gate) below. Merely announcing the request, checking USB visibility outside Appium, or postponing session creation until after provisioning does not satisfy the one-minute Appium rule. Keep that single Appium session attached through all acoustic testing, follow-up requests, audit completion, and the final audible handoff; a passing assertion is not permission to release device control while the agent is still working. For an Openbase VPN run, warn that the field-test VPN displaces the normal app's VPN because only one can be active. New human dependencies discovered mid-run get asked immediately and appended here for future runs.

### Blocking early iPhone VPN passcode gate

Immediately after Appium control is active, resolve this gate from the sampled transport. For **Openbase Direct**, record `PASSCODE_GATE=NOT_APPLICABLE_DIRECT` with a timestamp and proceed: Direct creates no iOS VPN configuration, so manufacturing a VPN prompt would change the test matrix and invalidate the run. For **Openbase VPN**, set `PASSCODE_GATE=PENDING`. That state is an execution lock, not a preference: until the exact iOS VPN passcode sheet has been observed or proven genuinely absent, do not run health checks, doctor/model probes, recent-commit review, acoustic setup, targeted tests, bug fixing, documentation edits, commits, release work, or any other unrelated task. The only permitted work is the minimum critical path below. If a prerequisite is slow, remain on that prerequisite; elapsed time does not authorize a detour.

1. In the field-test app, create or recover the dedicated field-test account through the real signup, Resend verification, and sign-in flow. Appium itself does not require the passcode. A saved-password or AutoFill authentication prompt is not the VPN prompt and is a staging/field-test regression.
2. Bring the sampled developer or signed-DMG VM install only far enough to target the same Cloud, sign into the same field-test account, and select/connect **Openbase VPN** (`netmesh`). A newly created account may initially send the phone to Tailscale onboarding; treat that screen as a signal that the account-level transport has not been written yet. Do not wait on it or explore it—set Openbase VPN from the VM immediately, then refresh the phone.
3. On the phone, require the onboarding copy to name **Openbase VPN** and require the computer to show connected. Tap the current `onboarding.netmesh.connect` element.
4. Inspect every system alert by its exact text. If the first tap produces the notifications alert, accept it, re-find `onboarding.netmesh.connect`, and tap again immediately. Accept the alert whose title says the field-test app **Would Like to Add VPN Configurations**. Do not announce that the passcode is ready before this alert has been accepted.
5. Poll Appium immediately and require visible evidence containing both **Enter iPhone Passcode** and **Add VPN Configurations**. Only then tell Gabe to enter the passcode directly on the physical device. Record `PASSCODE_GATE=VISIBLE` and the timestamp in the daily log before proceeding. After the required account/VM state becomes ready, this visible prompt has a 60-second deadline.

For an Openbase VPN run, the gate has not passed merely because the phone is authenticated, the VM's VPN is running, `Connect` was tapped, a notification sheet appeared, or the agent believes a prompt should be present. If iOS genuinely reuses an already-valid field-test VPN configuration and presents no add/modify passcode sheet, record `PASSCODE_GATE=NOT_PRESENT` with the observed Appium state and explain it immediately; never claim that the passcode was surfaced. Android follows the analogous earliest system VPN confirmation chain but has no iPhone-passcode assertion.

1. Confirm the disposable VM path is ready (macOS): see `install-tests/electron-macos/README.md`. For a full installation field test, use `manual-vm.sh` to start a bare VM and download the real signed channel DMG inside it. Reserve the pre-provisioned `openbase-golden` image and `run.sh` for harness-specific testing or secondary diagnostics.
2. Build/install the platform's field-test mobile variant and verify its distinct bundle/application id. If only the normal app is available, stop.
3. Confirm the fresh address matches the reserved Resend field-test pattern, confirm the active authenticated Resend CLI profile can list sent-message metadata without exposing its credential, record the UTC start time, and run `openbase run --memory 1024 -a <app> python manage.py field_test_account --destroy <email>`. A separate field-test profile is not required. Never substitute a personal inbox.
4. Inside the VM, confirm the Cloud target matches the mobile field-test build (staging by default):

   ```bash
   openbase-coder backend status
   ```

   If the backend is not `openbase_cloud`, switch it with the packaged CLI and restart services before the run.
4.5. **Confirm the selected Cloud's netmesh (Openbase VPN) is actually configured before starting a pairing/VPN test.** Staging and prod each need their OWN headscale control plane; staging must NOT borrow prod's (prod's headscale API key is a global admin credential — the least-trusted env must never hold it). Verify from the selected Cloud app that `HEADSCALE_API_URL`/`HEADSCALE_API_KEY`/`HEADSCALE_CONTROL_URL` are set and the enroll endpoint returns 200 (not 502): `openbase run --memory 1024 -a "<Cloud app>" python -c "import os;print(os.environ.get('HEADSCALE_API_URL'))"`. Staging's isolated headscale is `net-staging.openbase.cloud`, provisioned by `../openbase-cloud-workspace/netmesh-infra/aws-headscale` with `-var-file=terraform.staging.tfvars` against `netmesh/headscale-staging.tfstate` (see that README's "Staging control plane" section). If enroll 502s, netmesh is misconfigured — that is a real finding, and pairing/VPN/acoustic is blocked until it's fixed; do not wire staging into prod's headscale to force it. (Note: creating a *secret* config var via `openbase config set --secret[-stdin]` currently 500s; store non-DB secrets like `HEADSCALE_API_KEY` as a plaintext config var, matching how prod already stores it.)
4.6. **Confirm the dispatcher/Super-Agent model is runnable by the configured backend AND available on the account's plan.** The model is chosen per *execution* backend in `~/.openbase/dispatcher-config.json` (`backend_models.<claude_code|codex>`), and `openbase_cloud` executes on `claude_code`. Fresh Openbase Cloud installs must store `haiku` for both roles and the Settings UI must visibly identify Claude Haiku as the default; a local Sonnet default hidden by proxy substitution fails this UX gate. Staging managed/free/trial traffic defaults to Claude Haiku. Because the Claude SDK may still send an explicit Sonnet family model, the staging proxy must transparently route `claude-sonnet-5` and `claude-sonnet-4-6` to the plan's configured Haiku model; direct Haiku requests must also work. Opus/Fable remain restricted. Do not infer the upstream billed model only from the client request name: confirm the deployed plan policy when investigating unexpectedly fast credit use. Probe both the explicit-Sonnet compatibility path and direct Haiku with the machine token:

   ```bash
   TOK=$(openbase-coder auth print-machine-token)
   BASE=$(grep -E '^OPENBASE_CODER_CLI_WEB_BACKEND_URL=' ~/.openbase/.env | cut -d= -f2-)
   curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/api/openbase/llm/anthropic/v1/messages" \
     -H "Authorization: Bearer $TOK" -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
     -d '{"model":"claude-sonnet-5","max_tokens":16,"messages":[{"role":"user","content":"ok"}]}'
   ```

   Repeat with `"model":"claude-haiku-4-5"`. The proxy authenticates machine tokens ONLY via `Authorization: Bearer` (`OpenbaseMachineTokenAuthentication`); an `x-api-key` header is ignored and yields 403 "Authentication credentials were not provided" — that 403 is an auth-header mistake, not a plan/model finding (hit 2026-09-12).

   Both probes must return 200. A 403 naming Sonnet means the compatibility routing is missing; a 403 naming Haiku means the plan policy is wrong. If the dispatcher answers turns with a spoken auth/proxy error, this and the netmesh check above are the first two suspects. For cost reporting, use the account's settled provider counters and distinguish the whole debugging campaign from the marginal cost of the final clean retry; host-side Cartesia/AssemblyAI probes may use operator credentials and therefore are not necessarily present in account counters.
4.7. **Confirm the Mac's coder backend is actually RUNNING before you pair the phone — netmesh reachability is not backend readiness.** A fresh **desktop-app** install brings up only the Electron shell and its control server (`~/.openbase/desktop-control.json`, port 49154); it does **not** start the coder runtime (Django API on 7999, LiveKit, tunneld) until the app is *signed in* and started. The phone's pairing flow only checks that the netmesh resolves the Mac's host and reports "paired and ready" — it does **not** verify the backend answers, so an unsigned-in Mac yields a phone that pairs cleanly, connects a call, and then shows "**Can't reach the Openbase backend**" (its `/api/status/` poll 404s through tunneld's unauth fallback). Before pairing, confirm on the Mac that the backend serves: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7999/api/health/` returns 200 and `lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(7999|18080)'` shows listeners — *only* 49154 means the app is idle/not-signed-in. The field-testing agent must sign the disposable VM's desktop app into the dedicated field-test account itself through controlled browser OAuth, then re-confirm the backend is up; never pause to ask the user to operate or authenticate inside Tart. (Open observation: onboarding should probe backend health before declaring "paired and ready," and the "Can't reach backend" banner is indistinguishable from the earlier iOS confusion where the *transport* was healthy but the *backend/auth* was not.)

5. If the mobile target is a physical iPhone, confirm it is visible:

   ```bash
   xcrun xctrace list devices
   xcrun devicectl list devices   # xctrace can show a Wi-Fi-reachable phone as "offline"; devicectl is authoritative
   ```

   A "visible" phone is NOT a ready phone: WebDriverAgent cannot launch on a **locked** device, and the acoustic legs need it awake and physically near the host speakers. Those are user actions — request them at run start per step 0, not when the phone leg arrives.

6. Provide only the specific credential the child process needs (e.g. one Cartesia key), never a whole env file. Resend access must use an authenticated CLI profile in secure storage, not an exported key.

## Direct Appium Interaction

When you drive or inspect the phone yourself, use only the `appium` MCP server tools. If `mcp__appium__*` are deferred, load them via ToolSearch first. Typical iOS flow:

1. `select_device` — pick the target device.
2. `appium_prepare_ios_real_device` — call once without `provisioningProfileUuid` to list profiles, then again with the chosen UUID to ready WebDriverAgent (iOS only; Android skips this).
3. `appium_session_management` `action=create` against the installed field-test app id (`com.openbase.coder.field-test` on iOS; the distinct application id declared by the Android field-test variant), or `action=attach` to inspect an existing field-test session. Refuse the normal app ids.
4. Interact with `appium_find_element`, `appium_gesture`, `appium_set_value`, `appium_get_text`, `appium_get_page_source`, `appium_screenshot`, `appium_alert`, `appium_app_lifecycle`.
5. Keep the session attached through all requested follow-ups and the final audible handoff. Only after the testing session genuinely ends, use `appium_session_management` `action=delete` (or `detach`); never release phone automation merely because the latest assertion passed.

Android is the same MCP surface with the UiAutomator2 driver. Do not create an MCP session while a wdio spec is mid-run — a second session can steal the driver from the run; interact between runs, or attach rather than create.

**Android environment prerequisite (check before the run, not mid-run).** The `appium` MCP server resolves the Android SDK and JDK from *its own process env at launch* (`requireSdkRoot` reads `ANDROID_HOME`/`ANDROID_SDK_ROOT`; UiAutomator2 build/install needs `JAVA_HOME`). If those are not exported into the MCP server's environment, `select_device(platform=android)` fails with `Neither ANDROID_HOME nor ANDROID_SDK_ROOT environment variable was exported` — and it **cannot be fixed mid-session**: the running server's env is frozen at spawn, killing it does not reliably respawn a fresh one, and ad-hoc `adb` driving is disallowed by the workspace Appium-via-MCP rule. So the `appium` entry in `~/.claude.json` (`mcpServers.appium.env`) must carry, before the session starts: `ANDROID_HOME` + `ANDROID_SDK_ROOT` (e.g. `~/Library/Android/sdk`), `JAVA_HOME` (e.g. a Homebrew `openjdk@17`), and a `PATH` that includes the SDK `platform-tools`. iOS needs none of this. If a run reaches Android and hits the env error, fix `~/.claude.json` and hand the Android leg to a fresh Openbase Coder session rather than trying to patch the live MCP.

## Handling Failures (every failure, three ways + maybe four)

Rigorously test the running system. **Every** failure a field test finds gets:

1. **Recorded** in the daily field-test log (see below).
2. **Reported to Slack** — post a clearly-scoped message to the team **`#qa`** channel via the `slack-mcp` skill / official Slack MCP. Include: what failed, the sampled parameters, the branch/commit under test, and a link to the PR once opened (or the "already fixed in `develop`" note per step 3).
3. **Fixed on `develop` — never by patching `staging` (or the VM) durably.** All fixes are authored against `develop` (READY PR by default; direct push to develop only when the user has explicitly authorized fix-as-you-go for the session). When the run's Branch parameter is `staging` and the fix is needed to CONTINUE the run, the durable path is: land it on `develop`, then **promote develop→staging** (`scripts/promote develop staging`) so staging stays a pure snapshot of develop — never commit to staging directly. An in-VM hot-fix (editing `~/.openbase/.env`, staging a prebuilt by hand) is fine to unblock the live run, but it must be mirrored by the develop fix in the same session or it evaporates with the VM. The field-testing agent, or a dispatched fix agent, implements the fix on a branch against `develop`, with tests, and opens a pull request. **Never merge.** Follow each touched repo's `AGENTS.md`; keep diffs minimal and focused; run the affected tests.

   **Exception — the failure was observed on a `main` or `staging` build.** When this run's sampled **Branch** parameter is `main` or `staging`, the fix may already be sitting in `develop`, unreleased. Before opening any PR, **first check whether `develop` already contains the fix** for the affected area: inspect `develop`'s history/diff around the affected code, and reproduce against `develop` if that is quick. If the fix already exists in `develop`, do **not** open a duplicate PR. Instead record the failure in the daily log and the `#qa` Slack message as **"already fixed in `develop`, pending promotion/release"**, so it reads as a **release-gap signal** (a promotion is overdue), not a new bug. Only when `develop` does *not* already contain the fix do you open a READY PR against `develop` as above.

And, when appropriate:

4. **Pin the reproduction as a scripted-E2E spec** in `e2e-scripted/` (tier 2). That is tier-2's whole purpose — freezing a found bug so it cannot silently return. Add one spec for the specific failure; keep the suite small.

## Daily Testing Log

Every field-test session appends to a **gitignored** daily log at `.local/field-tests/<date>.md` at the workspace root (`.local/` is gitignored; verify with `git check-ignore .local/field-tests/x.md`). Each entry records:

- the **parameters sampled** for the run;
- **what was tested** (smoke + targeted areas, and why they were chosen);
- **failures** found, with concise evidence (not long logs);
- **PRs opened** (repo + link);
- **Slack messages sent** (channel + summary);
- any scripted-E2E specs pinned as a result.

Because the log is gitignored, it is safe to include machine-specific detail; do not reference it from committed docs.

## Reporting

After the run, report (and write a summary artifact per the `openbase-coder-reports` skill):

- sampled parameters and the field-test account used;
- clean-room confirmation (which VM; developer state untouched);
- which surfaces were tested and whether the full acoustic loop was exercised (outbound TTS + inbound STT);
- exact cloud-target confirmation;
- first failure with concise evidence, PRs opened, Slack messages sent, and any scripted-E2E specs pinned;
- VM/user teardown status.

In this public workspace, the summary artifact stays workspace-local under `.reports/` or `.local/field-tests/`. Never force-add it, commit it, link a public GitHub blob for it, or copy operational test evidence into another tracked workspace file. If a versioned report is required, write it in the relevant private Openbase workspace and verify that repository's visibility before staging. Before any workspace commit, require `git ls-files -- .reports` to produce no output.

## Scripted-E2E Annex (tier 2)

The tier-2 **scripted-E2E** suite lives in `e2e-scripted/` and exists for regression pinning: deterministic wdio/Appium specs that freeze a previously-found bug. Its suite map, environment reference, and package script inventory are in `e2e-scripted/README.md`. The live-run gates above (run plan, exact cloud-target confirmation, audio handling, `user say` rules, Appium-via-MCP) apply to scripted runs too.

Safe checks (no real Codex flows):

```bash
pnpm --dir e2e-scripted test
pnpm --dir e2e-scripted typecheck
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app-staging.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_IOS_BUNDLE_ID=com.openbase.coder.field-test \
  pnpm --dir e2e-scripted e2e:ios:doctor
```

Live manual specs (only after the run plan is recorded and the doctor passes):

```bash
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app-staging.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_IOS_BUNDLE_ID=com.openbase.coder.field-test \
OPENBASE_E2E_CARTESIA_API_KEY="$CARTESIA_KEY" \
  pnpm --dir e2e-scripted manual:e2e:ios:basic-call-response
```

Every live scripted spec must target the isolated field-test app variant under the same mobile-variant rules as tier 3. A doctor result naming the normal app bundle/application id is a failed preflight.

`manual:e2e:ios:parallel-agents-truth` is the live share-readiness gate: it drives the phone, launches two Super Agents from a prepared `briefing.md`, verifies both Markdown reports exist, verifies the voice route transfers to the Bill Gates report agent, asks what happened, and returns the route to dispatch. Keep exact paths/names/topics out of spoken prompts and in the briefing file.

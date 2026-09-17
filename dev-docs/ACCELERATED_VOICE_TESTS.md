# Accelerated voice tests

Use this track when installation is already understood and the question is how the dispatcher, Super Agents, phone audio, and mute lifecycle behave during a real call. Each run starts from a fresh clone of a **stopped, prepared Tart fixture**, with the developer installation and dedicated test-account login already complete. This provides repeatable voice coverage without reinstalling the product. It provides **no installation coverage**. A retained, modified run VM is debugging evidence; fix, refresh the prepared fixture, and repeat from another fresh clone before reporting the fix as verified.

The [field-testing skill](../.agents/skills/field-testing/SKILL.md) owns all shared phone, Appium, account, permission, speaker, acoustic-loop, model, and reporting gates. Follow its Appium-first and early iPhone VPN-passcode ordering before preparing the computer. The user enters any physical-device passcode directly; a test must record whether the actual VPN passcode sheet appeared. This page owns only prepared-fixture mechanics, scenario timing, and evidence interpretation.

## Prepare and seal a fixture

1. Clone the maintained clean OS image once. Install the developer workspace using [DEV_RUNBOOK](DEV_RUNBOOK.md), with Cloud environment and transport chosen before setup. Use the real reserved field-test signup, delivered verification email, and paid mock entitlement from the shared skill. Complete browser OAuth against the chosen Cloud environment, approve the guest's VPN background item visibly when requested, and require `openbase-coder doctor` to pass. The desktop Electron dashboard is optional for this CLI/voice fixture.
2. Stage current, signed mobile field-test builds. Record the actual workspace, CLI, Super Agents, SDK, and mobile revisions and any dirty patch digest. Rebuilding a phone app can stop its VPN and return it to pairing; reconnect through its onboarding UI and wait for the private backend to become reachable. Keep normal phone apps untouched. Enable Verbose Audio Playback Diagnostics in iOS Settings for these timing runs; leave Auto-mute and Auto-unmute enabled.
3. Prepare two short, speech-friendly Desktop folders, for example Maple and Cedar, with briefings for React Tetris and chess. Briefings request a build, a file-backed result, and a short completion announcement with the agent's assigned speaking name. Do not request an introduction: it must arrive unsolicited. Reset only guest Desktop-folder TCC before sealing so the clone can exercise the shared Super Agent/Desktop-permission gate. Keep fixture credentials and operational manifests in ignored local storage.
4. Stop the preparation VM. Write a reviewed JSON provenance file with `revisions`, `doctor_passed`, `cloud_environment`, `fixture_account`, and `desktop_permission_reset`. Seal it, then create a fresh run clone:

```bash
python3 voice-tests/baseline.py seal <prepared-vm> <versioned-baseline> \
  --manifest .local/field-tests/voice-baseline.json \
  --provenance .local/field-tests/provenance.json
python3 voice-tests/baseline.py clone <versioned-baseline> <run-vm> \
  --manifest .local/field-tests/voice-baseline.json
tart run <run-vm>
```

Keep the master stopped and unchanged. Authenticated clones retain the dedicated fixture network identity, so **never run the master, preparation VM, or two clones simultaneously**. The clone helper checks its recorded siblings; also check the preparation VM in `tart list`. Do not upload or distribute an authenticated image. Refresh a versioned fixture when code, toolchains, configuration, account entitlement, or service credentials change. Do not silently update an existing master or report old source as current coverage.

## Explore the voice scenarios

Start with a short recorded dispatcher response. Then ask it to start both agents in the separate Desktop folders during one spoken turn. Observe and handle the actual guest Desktop-access alert through computer control. Capture the dispatcher confirmation, both unsolicited introductions, background progress/completion announcements, and actual file/build results.

Steer each agent separately by its durable thread identity. Try corrections while the agents are still working, fragmented sentences, a brief hesitation followed by an addition near the mute boundary, and an addition after the dispatcher has already submitted a turn. Confirm that each instruction reached the intended agent exactly once and that it changed the resulting work. Exercise transfer to an agent and return to dispatch. Do not judge successful steering from a dispatcher acknowledgment alone.

Repeat with constrained guest bandwidth, latency, and loss before spending the remaining effort on platform parity. Shape only traffic inside the disposable guest, preserve and restore its previous firewall configuration, and record the active rules plus measured throughput/latency. Keep host and physical-phone networking unchanged. Distinguish a constrained computer leg from a constrained phone leg; guest shaping does not simulate poor phone Wi-Fi. Restore shaping after each run, including failed runs. Never label a configured limit as a measured network condition.

## Capture and regenerate timing evidence

`voice-tests/capture.py` reuses the shared Cartesia/AssemblyAI acoustic probe. A scenario JSON contains `seconds` and ordered `stimuli` entries with `at_s` and `text`; offsets are the earliest requested times after recorder readiness. Ordinary stimuli wait for a request-specific native readiness permit. Delays are recorded rather than silently treating the original schedule as the actual playback time. Use enough capture time for the final response and announcements; `response_tail_s` defaults to ten seconds and reserves a minimum response interval. A scenario schedule is instrumentation, not a replacement for agent-driven observation or Appium phone control.

```json
{"seconds": 40, "stimuli": [{"at_s": 2, "text": "What is seven times six? Say complete answer delivered after the answer."}]}
```

```bash
python3 voice-tests/capture.py .local/field-tests/scenario.json \
  .reports/voice-run/ios-smoke --credentials-file <private-env-file>
uv run --with matplotlib python voice-tests/timeline.py .reports/voice-run/ios-smoke
python3 -m unittest discover -s voice-tests -p 'test_*.py'
```

Only the Cartesia and AssemblyAI keys are extracted from the optional credentials file; existing environment values take precedence. Never source a broad private env file. Artifacts include the original native room WAV, converted WAV, scheduled stimulus audio, provider word spans, host process events, sample-clock mapping, normalized event JSON/CSV, and PNG/SVG timing plots. Save them with a durable Markdown report under `.reports`; do not force-add ignored reports to a public repository.

For each ordinary stimulus, wait for `gates/request-N.json`, obtain a fresh native page source through Appium MCP, and save its XML immediately in the gate directory. The iPhone must visibly show Listening and an enabled Mute button inside the screen viewport, with no Unmute button. Verify the selected speaker styling by screenshot after every call restart. Run the permit helper within 1.5 seconds of saving the fresh observation:

```bash
python3 voice-tests/permit.py <run>/gates/request-0.json \
  <run>/gates/native.xml --speaker-verified
```

Never refresh an old snapshot's modification time to satisfy the gate. A permit expires after 1.5 seconds and belongs to one request nonce. A rejected or missing permit produces no stimulus; the recorder continues so failed tests retain acoustic and sample-clock evidence. This gate reduces harness mistakes but cannot prevent an announcement racing after observation: classify that race from the native journal and recording. Use `mode: "overlap"` only for an explicitly intentional interruption scenario, and keep it distinct from ordinary steering coverage. Cartesia emits floating-point WAV; use `ffprobe` for stimulus durations rather than Python's PCM-only `wave` reader.

The dedicated iOS field-test variant writes already-redacted diagnostics to Documents/`voice-timing.jsonl`; the normal app does not enable persistence or file sharing. The Android fieldTest variant writes whitelisted voice events to its external-files `voice-timing.jsonl`. Both rotate at 16 MiB, retaining one `.previous` file. Pull both files through Appium MCP after every scenario, before rotation can discard them: iOS uses `@<field-test-bundle-id>:documents/voice-timing.jsonl`, Android uses `/sdcard/Android/data/<field-test-package>/files/voice-timing.jsonl`. Save iOS records as `ios.jsonl` and Android records as `android.jsonl`; normalization accepts direct journal entries and deduplicates overlapping iOS uploads. Check persistence failures and the first/last retained timestamps. The in-memory iOS upload buffer contains only 1,000 entries and can lose the beginning of a single long call; it is a fallback, not adequate evidence for a missing interval.

Plots include an overview, SVG/PNG detail views every twenty seconds, and a `timeline.html` index. Separate lanes show recorded sound, recognized acoustic words, host stimulus processes, VM lifecycle publication, phone receipt, acknowledged microphone application, and native playback-level diagnostics. Missing initial microphone history is hatched UNKNOWN. Native audio-level samples corroborate playback activity; they are not proof of audible word completion.

Collect a bounded `livekit-agent.log` tail as `server.log`. Ask the foreground iPhone to upload retained diagnostics using `openbase-coder user ios upload-logs`, then collect a bounded `ios-app.log` tail as `ios.jsonl`. Wait for the upload to finish; command delivery only confirms receipt. Include the relevant Django log records in `server.log` for `ios_control_round_trip`. Upload before and after scenarios to avoid losing the bounded phone buffer. Existing uploads may overlap; normalization deduplicates identical entries and ignores an incomplete first line from a bounded tail. For Android, provide actual native event records as `android.jsonl` with `unix_ms`, `event`, and metadata; absent Android events must be reported as missing instrumentation, never invented from server events.

Each acknowledged iPhone control command logs its native receipt and the server send/ack interval with the same command ID. The causal inequality bounds **phone clock minus VM clock** without assuming symmetric latency. Measure VM clock minus host clock with timestamped SSH round trips; store the resulting midpoint and half-width as `{"server":{"offset_ms":...,"uncertainty_ms":...}}` in `clock-calibration.json`. The plotter combines those intervals, retains native timestamps, rejects contradictory phone bounds, and marks uncalibrated clocks explicitly. Repeat calibration around a run; clock jumps or conflicting bounds invalidate a merged timing claim.

Alternatively, bracket Appium MCP's device-time request with host wall timestamps, request millisecond ISO formatting (`YYYY-MM-DDTHH:mm:ss.SSSZ`), and save samples in `device-clock-samples.json`. Each sample contains `source` (`ios` or `android`), `host_before_unix_ms`, `host_after_unix_ms`, `device_unix_ms`, and `timestamp_resolution_ms`. The native clock lies between request and response, yielding an interval rather than a symmetric-delay estimate. The plotter intersects repeated samples and server-mediated bounds, rejecting inconsistent intervals. Preserve raw samples and repeat around long runs.

The first Core Audio tap maps the first recorded sample's host time to wall time and reports frame counts and sample discontinuities. `afplay` process start/end are scheduling markers, **not audible onset/end**. Use the recorded waveform and recognized words to judge actual sound. AssemblyAI word offsets are milliseconds from the WAV start but are estimates; its [published guidance](https://support.assemblyai.com/articles/6819078983-does-your-api-return-timestamps-for-individual-words) describes roughly 400 ms accuracy. Retain the waveform and review finer mute boundaries against it or a more precise alignment method. Millisecond log formatting does not establish millisecond clock accuracy or prove that the speaker played those words.

For each scenario, report user speech end → turn acceptance → mic mute, server audio start/finish → device receipt → audible first/last word, mic unmute relative to audible end, introduction ordering, steer acceptance/target/result, duplicate instructions, gaps, and missing/clipped words. Device-side microphone application and playback-level events corroborate the room recording. If any source is missing, coarse, or uncalibrated, state the resulting limit instead of passing the timing requirement.

## Known setup roadblocks

- A cached `OpenbaseFieldTest.app` may be unsigned. Rebuild for the physical-device destination with `-allowProvisioningUpdates`, then install through Appium. A cached APK can contain older behavior even when its real netmesh library is present; rebuild before claiming current-source coverage.
- Regenerate Tuist after `ios/Project.swift` changes. `OpenbaseFieldTest` is a physical field-test build scheme without a test action; use the `Openbase` scheme and a dedicated simulator for mocked unit tests. The UIKit auth package is iOS-only; a plain host `swift test` is not its supported test path. Test through an iOS Xcode destination.
- SwiftUI can report `visible=true` for an off-screen control, and `scroll_to_element` can stop before the control's center enters the viewport. Verify its bounds and screenshot. A row-wide Settings switch element can cover the text as well as the actual switch; tapping its center may do nothing. Tap the observed switch control and assert its new value. Recheck Verbose Audio Playback Diagnostics and the speaker route after installing a new build.
- Gradle needs a JDK even if an old APK exists. Set `JAVA_HOME` to an installed JDK 17 before rebuilding; do not infer a runtime from the presence of Gradle caches.
- A local cached Electron bundle without a bundled runtime is not a signed-DMG installer sample. For developer voice tests use `./scripts/setup`; omit Electron or use the developer dashboard launcher from the developer runbook. Do not report the cache's missing CLI as an installation regression.
- Browser OAuth can open outside the existing Safari automation session. Adopt the real guest browser through the Tart Safari harness after confirming the Cloud origin, then use semantic controls. Disposable-guest helper approvals and credentials are agent-controlled; do not ask the user to operate the VM.

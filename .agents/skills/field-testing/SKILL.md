---
name: field-testing
description: Use when planning, running, debugging, or reporting an Openbase Coder field test — the tier-3, agent-driven, clean-room, full-acoustic-loop test where an agent installs the product into a disposable VM under a dedicated field-test account and exercises it like a real user. Also the operational annex for running the tier-2 scripted-E2E regression suite.
---

# Field Testing (tier 3)

This workspace-local skill is the operating procedure for **field tests** — tier
3 of the testing taxonomy (`specs/testing-tiers.md`). A field test is
agent-driven: no script. An agent installs Openbase Coder from scratch into a
disposable, isolated environment, exercises it like a real user (driving the
phone through the `appium` MCP server), notices what breaks, and turns every
failure into a logged, Slack-reported, READY-PR fix.

It applies whenever the user asks for a field test, live/full-system/no-mock test, or
to install-and-exercise the product end to end. For the **tier-2 scripted-E2E
regression suite** (deterministic wdio/Appium specs in `e2e-scripted/`), see the
[Scripted-E2E annex](#scripted-e2e-annex-tier-2) at the bottom — it is the same
live-run gates, applied to frozen specs instead of agent-driven exploration.

## The One Hard Boundary: Never Touch The Developer's State

**A field test never touches the developer's active user, machine, or local
installation.** There is no "uninstall your active install first" step — that old
flow is gone. Field tests are clean-room by construction:

- **Host OS runs in a disposable VM.** On macOS, use a
  [Tart](https://tart.run) macOS VM exclusively — the harness in
  `install-tests/electron-macos/` clones a throwaway VM so the real machine's
  install, launchd services, Tailscale routes, and ports 7999/7880 are never
  touched. The native-Windows pathway uses a Windows VM (later). Never install a
  field-test build onto the developer's own macOS session.
- **Test the real user installation path.** For a full staging or production macOS field test, start from a bare VM and install the signed, notarized channel DMG through the normal download, Gatekeeper, Applications, prerequisite, and onboarding flow. Open `https://openbase.cloud/downloads?staging=true` in the VM for a staging build (omit `?staging=true` for production) and use the page's download control; do not start with the raw S3 release-bucket URL, because that bypasses the public CDN-backed download pathway under test and is not the user-facing installation flow. If Tart keyboard or clipboard forwarding prevents reliable navigation, or the user explicitly opts out of testing the marketing download page, stop fighting the guest UI: use SSH and the bare macOS VM's built-in `curl -fL` to download the exact signed channel DMG into `~/Downloads`, then resume the normal Finder, Gatekeeper, Applications, prerequisite, and onboarding flow. Bare macOS does not include `wget`; do not install it just for this fallback. Record the SSH download as an explicit exception and leave the marketing-download surface unclaimed. Tart supplies disposable hardware isolation; Tart-only provisioning is not the installation under test. Use the pre-provisioned golden image, `run.sh`, or a local unsigned app only when the harness or a local build is explicitly the subject, or as a secondary diagnostic after the public path has been tested. Record every prerequisite encountered and whether the user-facing product or public documentation disclosed it before it was needed.
- **Accounts are dedicated field-test identities**, never the developer's real
  Openbase account. See [Field-test account lifecycle](#field-test-account-lifecycle).
- **Phones run the field-test app variant**, never the developer's normal Openbase app. The field-test variant must have its own bundle/application id and storage so it can coexist with the normal app without replacing its binary, login, VPN state, notification registration, or local data. See [Field-test mobile app variants](#field-test-mobile-app-variants).
- If a request would require mutating the developer's live install, account, or
  services, stop and re-scope it into the VM + field-test-account model rather
  than running it against real state.

## Non-Negotiables

- Do not mock Codex, Super Agents, the dispatcher, LiveKit, Cartesia, Tailscale,
  Openbase Cloud, Appium, WebDriverAgent, the iOS/Android app, the desktop app,
  or phone interaction. A field test is real end-to-end or it is not a field
  test.
- A direct user request to run or continue a full field test explicitly authorizes the expected clean-room installation sequence inside the disposable VM: open the verified signed channel DMG, drag Openbase into Applications, accept the ordinary macOS first-launch confirmation, and launch it. Do not interrupt that routine sequence for another install/run confirmation. Pause only if the UI requests an unexpected privilege, credential, security bypass, destructive action, or materially different software installation.
- On macOS, choosing the recommended Openbase VPN can install the `OpenbaseNetmesh` background item and pause setup until the user approves it in **System Settings → General → Login Items & Extensions → Allow in the Background**. Treat this as an expected OS-level prerequisite but not as part of the routine DMG confirmation: prepare and navigate to the setting, then obtain the user's action-time approval before enabling it. Keep the setup process running because it resumes automatically after approval. Record whether the onboarding UI and public installation documentation disclosed this requirement before macOS blocked progress.
- Dedicated field-test mobile variants target staging Openbase Cloud by default: `https://app-staging.openbase.cloud` for cloud/account APIs and `openbase_cloud` for the coding backend. Verify the desktop/VM uses the same cloud target before starting. A production field test requires an explicitly production-targeted field-test build; never substitute the normal app.
- Before running a field test, record a concise run plan in the gitignored daily field-test log. A separate RMOT or Typora window is not required. See [Required Run Plan](#required-run-plan).
- Use `openbase-coder user say "<agent name>" "<message>"` whenever the user needs to
  do something off-chat (move the phone near the speaker, unlock it, trust the
  Mac, provide a missing credential). Keep spoken prompts short and natural.
- When the phone app may be listening, do not use incidental `tts`/`user say` for
  status or completion updates. Speak only when the audio is an intentional test
  stimulus or the user explicitly asks for an audible prompt.
- Any time the agent interacts with Appium directly — driving the phone,
  screenshots, page source, alerts, app lifecycle — it must go through the
  `appium` MCP server (`mcp__appium__*` tools; registered as `appium`, command
  `npx -y appium-mcp`). Never hand-start an `appium` CLI server, curl WebDriver
  endpoints, or write one-off WebdriverIO scripts. iOS uses the XCUITest driver;
  Android uses the UiAutomator2 driver — both through this one MCP surface. See
  [Direct Appium Interaction](#direct-appium-interaction).
- Do not source broad env files into the test process. Cherry-pick only the
  specific credentials required (e.g. extract a single Cartesia key), never
  `source` a whole private env file.

## Field-Test Procedure

Every field-test session runs the same three steps, in order:

1. **Installation.** Stand up a clean environment (Tart macOS VM, or a Windows VM for the native-Windows pathway), install the product using the sampled installation method, build/install the mobile field-test variant, and create the designated throwaway account through the real [signup and verification lifecycle](#field-test-account-lifecycle).
2. **Smoke test.** A short basic check that the core loop works at all — place a
   call, get a dispatcher response through the full acoustic loop — before
   investing in anything deeper. If the smoke test fails, that is the finding;
   stop and file it.
3. **Targeted testing.** Exercise whatever most likely changed since the last
   field test. Determine this by reading recent commits across the workspace
   repos since the previous field-test log entry (see below). Effort follows the
   code: concentrate on the surfaces and flows that were just modified.

Deciding what to target from recent commits:

```bash
# What changed across the workspace since the last field test?
multi git -- log --oneline --since="<date of last field-test log>"
# Or per repo, e.g.:
git -C ios log --oneline -20
git -C cli log --oneline -20
```

Read the last entry in `.local/field-tests/` to find the previous run's date and
what was covered, so this run targets new risk rather than repeating old ground.

## Parameter Model (sample per run)

Each run samples a point in this space. Sampling is **stochastic but weighted**:
prioritize **iOS and macOS**, sampling the others less often, so coverage spreads
over time without abandoning the most-used surfaces. Record the sampled values in
the daily log.

| Parameter | Options |
| --- | --- |
| Starting OS (host) | macOS Tart VM *(prioritized)* · Windows VM |
| Mobile OS | iOS / XCUITest *(prioritized)* · Android / UiAutomator2 |
| Mobile app | field-test variant only; never the normal Openbase app |
| Connectivity profile | strong Wi-Fi · constrained/lossy · cellular-like |
| Branch | `main` · `staging` · `develop` |
| Installation method | normal user install · developer install (`./scripts/setup`) |

Pick a concrete value for each before starting the run. If the sampler is
unavailable, choose by hand but keep the iOS/macOS bias and vary from the
previous run so the matrix fills in.

## Full Acoustic Loop

Field tests close the real audio loop **in both directions**:

- **Outbound stimulus:** Cartesia TTS played through the Mac/host speakers into
  the phone's microphone as genuine acoustic input — not a direct API call.
- **Inbound capture:** the phone's spoken reply captured back through a
  microphone and transcribed with **local STT**, so the agent asserts on the
  *meaning* of what the product said, not just on log lines.

Treat speaker-prompt audio as a real but lossy dependency. Do not put exact
paths, filenames, people's names, or acceptance criteria into spoken audio. Put
brittle details in a prepared `briefing.md` file and make the spoken prompt a
short natural pointer, e.g. "In the home folder, open the folder named openbase
field test and follow the briefing markdown file." Do not use meta-instructions
like "the real instruction starts after this sentence." If the phone display
dims or locks during a long run, pause and ask the user to keep the phone awake or
set Auto-Lock to Never.

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
- **`--mock-payment EMAIL`** grants paid entitlement after real verification via a purely local `payment.Subscription` row at the normal default-tier cap—no payment-provider call or charge.

The lifecycle across one core product field test:

1. Generate an opaque run slug and choose `delivered+openbase-field-<slug>@resend.dev`. Confirm it matches the reserved pattern exactly; do not use `test@…`, `@example.com`, another Resend test outcome, or a personal-provider plus-address.
2. Record the UTC run start time. Run `openbase run --memory 1024 -a <app> python manage.py field_test_account --destroy <email>` so a reused address starts clean; an idempotent `not_found` result is acceptable. The composed staging app's default 256 MiB one-off task can be OOM-killed with exit 137, so every `field_test_account` invocation must set `--memory 1024`.
3. Generate a strong ephemeral password locally without printing it, drive the field-test app's normal signup UI, and require the expected unverified/"Verify Your Email" state.
4. Use an authenticated Resend CLI profile to poll sent-email metadata. The active/default profile is acceptable; a separate field-test profile is not required. Select only a message addressed to the exact field-test address and created after the recorded start time, then retrieve that message by id. Never pass an API key with `--api-key` or source a broad environment file.
5. Read the returned HTML/text, find the real confirmation URL, and follow it through the tested phone/browser surface. Verification URLs are bearer credentials: never put one in a shell command, run plan, report, Slack message, screenshot caption, or durable log.
6. Confirm the product reports the email verified and the account can sign in. If paid features are in scope, run `openbase run --memory 1024 -a <app> python manage.py field_test_account --mock-payment <email>` only now.
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
- the **sampled parameters** for this run (host OS, mobile OS, connectivity,
  branch, installation method) and the previous run's date;
- the fresh field-test account identity and confirmation it matches `delivered+openbase-field-<slug>@resend.dev`, the recorded UTC start time, the Resend CLI profile being used (the active/default profile is acceptable; never record its credential), the planned real signup/message-retrieval/verification steps, and optional post-verification `--mock-payment`;
- clean-room confirmation: which disposable VM (Tart macOS / Windows) and that
  the developer's real install/account/services are untouched;
- planned steps: install → smoke → targeted, with the specific targeted areas
  derived from recent commits;
- iOS/Android target: device/emulator, driver (XCUITest/UiAutomator2), field-test variant name, its distinct bundle/application id, app provenance, and confirmation the normal Openbase app will remain untouched;
- local runtime target inside the VM: `electron-bundled`, `standalone`, or
  `workspace`;
- CLI/service details: runtime mode, package version, service status, coding
  backend, and cloud web backend;
- exact cloud-target confirmation, normally staging for the dedicated mobile variants;
- audio path: Cartesia model/voice, host speaker audio, phone mic, and local STT
  for inbound capture;
- audio-prompt reliability notes: prepared briefing file, minimal spoken
  pointer, keep-phone-awake / disable Auto-Lock;
- expected human actions and when `user say` will be used;
- no-mock statement listing the real systems involved;
- rollback/cleanup notes (VM deletion, `field_test_account --destroy`, ephemeral-password cleanup, field-test Appium session deletion, and field-test app cleanup without touching the normal app).

Use repo-relative or `~`-relative paths in the run plan. Keep brittle scratch in
`.local/` (gitignored) — never reference `.local/` files from committed docs.

## Preflight Sequence

1. Confirm the disposable VM path is ready (macOS): see `install-tests/electron-macos/README.md`. For a full installation field test, use `manual-vm.sh` to start a bare VM and download the real signed channel DMG inside it. Reserve the pre-provisioned `openbase-golden` image and `run.sh` for harness-specific testing or secondary diagnostics.
2. Build/install the platform's field-test mobile variant and verify its distinct bundle/application id. If only the normal app is available, stop.
3. Confirm the fresh address matches the reserved Resend field-test pattern, confirm the active authenticated Resend CLI profile can list sent-message metadata without exposing its credential, record the UTC start time, and run `openbase run --memory 1024 -a <app> python manage.py field_test_account --destroy <email>`. A separate field-test profile is not required. Never substitute a personal inbox.
4. Inside the VM, confirm the Cloud target matches the mobile field-test build (staging by default):

   ```bash
   openbase-coder backend status
   ```

   If the backend is not `openbase_cloud`, switch it with the packaged CLI and
   restart services before the run.
5. If the mobile target is a physical iPhone, confirm it is visible:

   ```bash
   xcrun xctrace list devices
   ```

6. Provide only the specific credential the child process needs (e.g. one Cartesia key), never a whole env file. Resend access must use an authenticated CLI profile in secure storage, not an exported key.

## Direct Appium Interaction

When you drive or inspect the phone yourself, use only the `appium` MCP server
tools. If `mcp__appium__*` are deferred, load them via ToolSearch first. Typical
iOS flow:

1. `select_device` — pick the target device.
2. `appium_prepare_ios_real_device` — call once without
   `provisioningProfileUuid` to list profiles, then again with the chosen UUID to
   ready WebDriverAgent (iOS only; Android skips this).
3. `appium_session_management` `action=create` against the installed field-test app id (`com.openbase.coder.field-test` on iOS; the distinct application id declared by the Android field-test variant), or `action=attach` to inspect an existing field-test session. Refuse the normal app ids.
4. Interact with `appium_find_element`, `appium_gesture`, `appium_set_value`,
   `appium_get_text`, `appium_get_page_source`, `appium_screenshot`,
   `appium_alert`, `appium_app_lifecycle`.
5. `appium_session_management` `action=delete` (or `detach`) when done.

Android is the same MCP surface with the UiAutomator2 driver. Do not create an
MCP session while a wdio spec is mid-run — a second session can steal the driver
from the run; interact between runs, or attach rather than create.

## Handling Failures (every failure, three ways + maybe four)

Rigorously test the running system. **Every** failure a field test finds gets:

1. **Recorded** in the daily field-test log (see below).
2. **Reported to Slack** — post a clearly-scoped message to the team **`#qa`**
   channel via the `slack-mcp` skill / official Slack MCP. Include: what failed,
   the sampled parameters, the branch/commit under test, and a link to the PR
   once opened (or the "already fixed in `develop`" note per step 3).
3. **Fixed as a READY PR into `develop`.** The field-testing agent, or a
   dispatched fix agent, implements the fix on a branch against `develop`, with
   tests, and opens a pull request. **Never merge.** Follow each touched repo's
   `AGENTS.md`; keep diffs minimal and focused; run the affected tests.

   **Exception — the failure was observed on a `main` or `staging` build.** When
   this run's sampled **Branch** parameter is `main` or `staging`, the fix may
   already be sitting in `develop`, unreleased. Before opening any PR, **first
   check whether `develop` already contains the fix** for the affected area:
   inspect `develop`'s history/diff around the affected code, and reproduce
   against `develop` if that is quick. If the fix already exists in `develop`, do
   **not** open a duplicate PR. Instead record the failure in the daily log and
   the `#qa` Slack message as **"already fixed in `develop`, pending
   promotion/release"**, so it reads as a **release-gap signal** (a promotion is
   overdue), not a new bug. Only when `develop` does *not* already contain the
   fix do you open a READY PR against `develop` as above.

And, when appropriate:

4. **Pin the reproduction as a scripted-E2E spec** in `e2e-scripted/` (tier 2).
   That is tier-2's whole purpose — freezing a found bug so it cannot silently
   return. Add one spec for the specific failure; keep the suite small.

## Daily Testing Log

Every field-test session appends to a **gitignored** daily log at
`.local/field-tests/<date>.md` at the workspace root (`.local/` is gitignored;
verify with `git check-ignore .local/field-tests/x.md`). Each entry records:

- the **parameters sampled** for the run;
- **what was tested** (smoke + targeted areas, and why they were chosen);
- **failures** found, with concise evidence (not long logs);
- **PRs opened** (repo + link);
- **Slack messages sent** (channel + summary);
- any scripted-E2E specs pinned as a result.

Because the log is gitignored, it is safe to include machine-specific detail; do
not reference it from committed docs.

## Reporting

After the run, report (and write a summary artifact per the
`openbase-coder-reports` skill):

- sampled parameters and the field-test account used;
- clean-room confirmation (which VM; developer state untouched);
- which surfaces were tested and whether the full acoustic loop was exercised
  (outbound TTS + inbound STT);
- exact cloud-target confirmation;
- first failure with concise evidence, PRs opened, Slack messages sent, and any
  scripted-E2E specs pinned;
- VM/user teardown status.

In this public workspace, the summary artifact stays workspace-local under
`.reports/` or `.local/field-tests/`. Never force-add it, commit it, link a
public GitHub blob for it, or copy operational test evidence into another
tracked workspace file. If a versioned report is required, write it in the
relevant private Openbase workspace and verify that repository's visibility
before staging. Before any workspace commit, require
`git ls-files -- .reports` to produce no output.

## Scripted-E2E Annex (tier 2)

The tier-2 **scripted-E2E** suite lives in `e2e-scripted/` and exists for
regression pinning: deterministic wdio/Appium specs that freeze a
previously-found bug. Its suite map, environment reference, and package
script inventory are in `e2e-scripted/README.md`. The live-run gates above (run plan, exact cloud-target
confirmation, audio handling, `user say` rules, Appium-via-MCP) apply to scripted
runs too.

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

`manual:e2e:ios:parallel-agents-truth` is the live share-readiness gate: it
drives the phone, launches two Super Agents from a prepared `briefing.md`,
verifies both Markdown reports exist, verifies the voice route transfers to the
Bill Gates report agent, asks what happened, and returns the route to dispatch.
Keep exact paths/names/topics out of spoken prompts and in the briefing file.

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

It applies whenever Gabe asks for a field test, live/full-system/no-mock test, or
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
- **Accounts are dedicated field-test identities**, never the developer's real
  Openbase account. See [Field-test account lifecycle](#field-test-account-lifecycle).
- If a request would require mutating the developer's live install, account, or
  services, stop and re-scope it into the VM + field-test-account model rather
  than running it against real state.

## Non-Negotiables

- Do not mock Codex, Super Agents, the dispatcher, LiveKit, Cartesia, Tailscale,
  Openbase Cloud, Appium, WebDriverAgent, the iOS/Android app, the desktop app,
  or phone interaction. A field test is real end-to-end or it is not a field
  test.
- Field tests target production Openbase Cloud by default:
  `https://app.openbase.cloud` for cloud/account APIs and `openbase_cloud` for
  the coding backend, unless Gabe explicitly asks for another backend.
- Before running a field test, write an RMOT plan to `.local/field-tests/` (or
  `/tmp`) and open it in Typora. Do not skip this even if the command seems
  obvious. See [Required RMOT](#required-rmot).
- Use `openbase-coder user say "<agent name>" "<message>"` whenever Gabe needs to
  do something off-chat (move the phone near the speaker, unlock it, trust the
  Mac, provide a missing credential). Keep spoken prompts short and natural.
- When the phone app may be listening, do not use incidental `tts`/`user say` for
  status or completion updates. Speak only when the audio is an intentional test
  stimulus or Gabe explicitly asks for an audible prompt.
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

1. **Installation.** Stand up a clean environment (Tart macOS VM, or Windows VM
   for the Docker pathway) and install the product using the sampled
   installation method. Use the designated
   [field-test account](#field-test-account-lifecycle): destroy any prior
   account first, then sign it up for real as part of this step.
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
the RMOT and the daily log.

| Parameter | Options |
| --- | --- |
| Starting OS (host) | macOS Tart VM *(prioritized)* · Windows VM |
| Mobile OS | iOS / XCUITest *(prioritized)* · Android / UiAutomator2 |
| Connectivity profile | strong Wi-Fi · constrained/lossy · cellular-like |
| Branch | `main` · `staging` · `develop` |
| Installation method | normal user install · developer install (`./scripts/setup`) |

Pick a concrete value for each before writing the RMOT. If the sampler is
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
dims or locks during a long run, pause and ask Gabe to keep the phone awake or
set Auto-Lock to Never.

## Field-Test Account Lifecycle

A field test runs as a **real, designated account** — never a developer's real
Openbase account. Its email must be listed in the cloud API's
`FIELD_TEST_ALLOWED_EMAILS` allowlist (comma-separated env/config var); the
`field_test_account` command refuses to touch any email not on that list, and an
empty/unset allowlist refuses everything. Use **plus-addressing** to mint
unlimited distinct real signup addresses that all land in one controlled inbox:
`you+<run-slug>@gmail.com` all deliver to `you@gmail.com`, yet each is a distinct
account to Openbase.

Because the account is real, the field test exercises the **real signup and real
email-verification** flow — that is the whole point of this design. Nothing about
verification is mocked: the verification email actually arrives in the controlled
inbox and the agent reads it to finish signing up. Only two lifecycle steps are
done out-of-band, by the `field_test_account` Django management command in the
cloud API (openbase-drf-api-core PR
[#13](https://github.com/openbase-community/openbase-drf-api-core/pull/13), which
cross-links back to this workspace PR):

- **`--destroy EMAIL`** (pre-test): deletes the designated user via the canonical
  account-deletion cascade, so the run starts from a clean slate. Idempotent — a
  no-op if the user does not exist.
- **`--mock-payment EMAIL`** (mid-test, AFTER the real signup + verification):
  grants paid entitlement via a local `payment.Subscription` row at the normal
  **default-tier** cap — no Stripe checkout, subscription, or charge.

It **never creates users and never mocks verification.** Both operations are
guarded by the allowlist before any read/write and emit one line of
machine-readable JSON for the harness (`action`, `email`, `user_id`, and
`destroyed`/`entitled`).

The lifecycle across one field test:

1. **Destroy** any prior account: `field_test_account --destroy <email>`.
2. **Real signup** happens as part of installation / first-run testing — the
   agent drives the product through actual account creation for `<email>`.
3. **Read the verification email** from the controlled inbox and complete
   verification for real: use the `gmail-cli` skill to find and open the Openbase
   verification message and follow its link/code.
4. **Mock payment** once signed in: `field_test_account --mock-payment <email>`
   to unlock paid features.

Invoke in production via `openbase run` against the cloud app (the
`FIELD_TEST_ALLOWED_EMAILS` config var must be set on the app):

```bash
# Pre-test: destroy the designated field-test account.
openbase run -a <app> python manage.py field_test_account --destroy you+<run-slug>@gmail.com
# → {"action":"destroy","email":"you+<run-slug>@gmail.com","destroyed":true,"user_id":…}

# After the real signup + email verification: grant paid entitlement.
openbase run -a <app> python manage.py field_test_account --mock-payment you+<run-slug>@gmail.com
# → {"action":"mock-payment","email":"…","user_id":…,"entitled":true,"subscription_created":true}
```

Cross-reference PR #13 from the field-test RMOT.

## Required RMOT

Before any field-test command, create a Markdown RMOT (open it in Typora). It
must include:

- exact date/time and the requested test scope;
- the **sampled parameters** for this run (host OS, mobile OS, connectivity,
  branch, installation method) and the previous run's date;
- the field-test account identity and confirmation its email is on the
  `FIELD_TEST_ALLOWED_EMAILS` allowlist, that `field_test_account --destroy` ran
  pre-test, and that signup + email verification will run for real (payment
  mocked post-signup via `field_test_account --mock-payment`);
- clean-room confirmation: which disposable VM (Tart macOS / Windows) and that
  the developer's real install/account/services are untouched;
- planned steps: install → smoke → targeted, with the specific targeted areas
  derived from recent commits;
- iOS/Android target: device/emulator, driver (XCUITest/UiAutomator2), app
  bundle/package id, and app provenance;
- local runtime target inside the VM: `electron-bundled`, `standalone`, or
  `workspace`;
- CLI/service details: runtime mode, package version, service status, coding
  backend, and cloud web backend;
- production-cloud confirmation;
- audio path: Cartesia model/voice, host speaker audio, phone mic, and local STT
  for inbound capture;
- audio-prompt reliability notes: prepared briefing file, minimal spoken
  pointer, keep-phone-awake / disable Auto-Lock;
- expected human actions and when `user say` will be used;
- no-mock statement listing the real systems involved;
- rollback/cleanup notes (VM deletion, field-test account teardown via
  `field_test_account --destroy`).

Use repo-relative or `~`-relative paths in the RMOT. Keep brittle scratch in
`.local/` (gitignored) — never reference `.local/` files from committed docs.

## Preflight Sequence

1. Confirm the disposable VM harness is ready (macOS): see
   `install-tests/electron-macos/README.md` — `bootstrap-golden.sh` bakes the
   golden VM once; `run.sh` clones a throwaway instance per run.
2. Destroy any prior field-test account
   (`field_test_account --destroy <email>`); the run signs it up for real, so do
   not pre-create it. Confirm the email is on the `FIELD_TEST_ALLOWED_EMAILS`
   allowlist.
3. Inside the VM, confirm production cloud targeting:

   ```bash
   openbase-coder backend status
   ```

   If the backend is not `openbase_cloud`, switch it with the packaged CLI and
   restart services before the run.
4. If the mobile target is a physical iPhone, confirm it is visible:

   ```bash
   xcrun xctrace list devices
   ```

5. Provide only the specific credential the child process needs (e.g. one
   Cartesia key), never a whole env file.

## Direct Appium Interaction

When you drive or inspect the phone yourself, use only the `appium` MCP server
tools. If `mcp__appium__*` are deferred, load them via ToolSearch first. Typical
iOS flow:

1. `select_device` — pick the target device.
2. `appium_prepare_ios_real_device` — call once without
   `provisioningProfileUuid` to list profiles, then again with the chosen UUID to
   ready WebDriverAgent (iOS only; Android skips this).
3. `appium_session_management` `action=create` against the app id
   (`com.openbase.coder`), or `action=attach` to inspect an existing session.
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
- production-cloud confirmation;
- first failure with concise evidence, PRs opened, Slack messages sent, and any
  scripted-E2E specs pinned;
- VM/user teardown status.

## Scripted-E2E Annex (tier 2)

The tier-2 **scripted-E2E** suite lives in `e2e-scripted/` and exists for
regression pinning: deterministic wdio/Appium specs that freeze a
previously-found bug. Its stable suite map, environment reference, and package
script inventory are in `LIVE_E2E_TESTING.md`; per-package details are in
`e2e-scripted/README.md`. The live-run gates above (RMOT, production-cloud
confirmation, audio handling, `user say` rules, Appium-via-MCP) apply to scripted
runs too.

Safe checks (no real Codex flows):

```bash
pnpm --dir e2e-scripted test
pnpm --dir e2e-scripted typecheck
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
  pnpm --dir e2e-scripted e2e:ios:doctor
```

Live manual specs (only after the RMOT is open and the doctor passes):

```bash
OPENBASE_E2E_EXPECT_RUNTIME=electron-bundled \
OPENBASE_E2E_EXPECT_WEB_BACKEND=https://app.openbase.cloud \
OPENBASE_E2E_EXPECT_CODING_BACKEND=openbase_cloud \
OPENBASE_E2E_CARTESIA_API_KEY="$CARTESIA_KEY" \
  pnpm --dir e2e-scripted manual:e2e:ios:basic-call-response
```

`manual:e2e:ios:parallel-agents-truth` is the live share-readiness gate: it
drives the phone, launches two Super Agents from a prepared `briefing.md`,
verifies both Markdown reports exist, verifies the voice route transfers to the
Bill Gates report agent, asks what happened, and returns the route to dispatch.
Keep exact paths/names/topics out of spoken prompts and in the briefing file.

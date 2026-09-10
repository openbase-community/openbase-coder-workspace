# Openbase Coder Testing Tiers

Openbase Coder is a voice IDE that spans many moving parts — the local CLI
runtime, the desktop app, the iOS and Android apps, the web console, Openbase
Cloud, LiveKit voice, Cartesia audio, and the coding backends. No single kind of
test can cover a system that wide. This document defines the **three testing
tiers**, the distinct job each one does, and how a defect flows down through
them.

The three tiers are complementary, not redundant. Each tier catches a class of
problem the tier below it structurally cannot, and feeds regressions back up.

| Tier | Name | Driver | Environment | Job |
| --- | --- | --- | --- | --- |
| 1 | Unit tests | Test runner | Mocked, in-process | Fast per-repo correctness |
| 2 | Scripted E2E | wdio/Appium script | Real services, real phone | Regression pinning |
| 3 | Field tests | An AI agent | Clean-room install, full acoustic loop | Find unknown breakage |

## Tier 1 — Unit tests

Per-repo, mocked, and fast. Each repository owns its own unit suite and runs it
in CI on every change: Python tests in `cli`, component and logic tests in the
React packages, Kotlin tests in `android`, Swift tests in `ios`, and so on.
Dependencies outside the unit under test — network, services, the filesystem,
other repos — are mocked or stubbed. These tests answer "does this function,
component, or module behave correctly in isolation?" and are expected to be
numerous, cheap, and green before anything merges.

Unit tests deliberately do **not** exercise the seams between repos, the
installed product, or real voice/audio. That is what tiers 2 and 3 exist for.

## Tier 2 — Scripted E2E (regression pinning)

The scripted E2E suite lives in `e2e-scripted/`. It drives a **real** iPhone
through Appium/XCUITest with deterministic WebdriverIO scripts, against the real
local runtime and real services (Openbase Cloud, LiveKit, Cartesia audio, the
coding backends). Nothing here is mocked; the scripts are the only "scripted"
part.

Its defined role is **regression pinning**, and that role is narrow on purpose.
Scripted E2E is not where broad coverage is invented. It exists to hold the line
on bugs that have already appeared: when a field test (tier 3) surfaces a
defect, the reproduction is distilled into a deterministic spec and frozen here
so the same bug cannot silently come back. Every spec in `e2e-scripted/` should
be traceable to a real defect it prevents from returning.

Because specs are added only in response to real defects, the suite is expected
to stay **small** and grow one spec at a time. A scripted suite that balloons
with speculative "what if" coverage has drifted from its job. The current specs
(basic call/response, Super Agent self-naming, the parallel-agents share
readiness gate, orphaned-answer recovery, and others) each pin a specific past
failure mode.

Scripted E2E is manual-to-launch because it spends real API credits, speaks
audio, and creates real agent work. See `e2e-scripted/README.md` for the suite
map, environment knobs, and run commands.

## Tier 3 — Field tests

Field tests are the top tier and the source of new coverage. A field test is
**agent-driven**: there is no script. An AI agent installs the product from
scratch, exercises it like a user would, decides what to poke at, notices what
breaks, and files the breakage. It is the tier designed to find the unknown —
the failures nobody wrote a spec for yet.

Three properties define a field test and separate it from tier 2:

1. **Agent-driven, not scripted.** The agent drives the phone through the
   `appium` MCP server (the same server used for ad-hoc device driving), decides
   the next action from what it observes, and judges outcomes. Mobile coverage
   includes iOS (XCUITest driver) and Android (Appium's UiAutomator2 driver),
   both through that one MCP surface.

2. **Clean-room installation.** Every field test installs the product fresh into
   a disposable, isolated environment — never the developer's own machine, user,
   or existing installation. On macOS the host side runs exclusively inside a
   disposable [Tart](https://tart.run) macOS VM; the native-Windows pathway runs
   inside a Windows VM. Accounts are dedicated field-test identities, never a
   developer's real account. A field test must be able to run without disturbing
   any live developer state.

3. **Full acoustic loop.** Field tests close the real audio loop in both
   directions. Cartesia TTS is played through speakers into the phone's
   microphone as genuine acoustic stimulus, and the phone's spoken reply is
   captured back through a microphone and transcribed with local STT so the
   agent can assert on the *meaning* of what the product said — not just on log
   lines. This is the only tier that proves the product works as a spoken
   experience end to end.

### Field-test procedure

Every field-test session follows the same three-step shape:

1. **Installation** — stand up a clean environment and install the product via
   the sampled installation method.
2. **Smoke test** — a short, basic check that the core call/response loop works
   at all before investing in anything deeper.
3. **Targeted testing** — exercise whatever most likely changed since the last
   field test, determined by reading recent commits across the workspace repos.
   Field-test effort follows the code, so testing concentrates where the risk
   was just introduced.

### Field-test parameter model

Each field-test run samples a point in a small parameter space, so that over
many runs the tests spread across the real matrix of environments instead of
always retreading one path. Sampling is **stochastic but weighted**: iOS and
macOS are prioritized because they are the most-used surfaces, so the sampler
favors them while still occasionally covering the others.

| Parameter | Options |
| --- | --- |
| Starting OS (host) | macOS Tart VM · Windows VM |
| Mobile OS | iOS (XCUITest) · Android (UiAutomator2) |
| Connectivity profile | e.g. strong Wi-Fi, constrained/lossy, cellular-like |
| Branch | `main` · `staging` · `develop` |
| Installation method | normal user install · developer install (`./scripts/setup`) |

The sampled parameters for each run are recorded in the field-test log so a
result is always reproducible and the coverage spread is auditable.

### What happens when a field test finds a bug

A field test is only useful if its findings turn into durable protection. Every
failure a field test finds is handled three ways:

- **Recorded** in the daily field-test log.
- **Reported** to the team over Slack so a human sees it promptly.
- **Fixed as a READY PR** — the field-testing agent (or a dispatched fix agent)
  implements the fix on a branch against `develop`, with tests, and opens a
  pull request. Field tests never merge.

And, when the bug is a reproducible regression worth guarding forever, its
reproduction is **pinned as a new scripted-E2E spec in `e2e-scripted/`**. That
is the loop that keeps tier 2 small and meaningful: tier 3 discovers, tier 2
remembers, tier 1 stays fast.

## How the tiers reinforce each other

```
tier 3 (field test) discovers an unknown failure
        │
        ├─ opens a READY PR that fixes it (against develop)
        │
        └─ freezes a reproduction as a tier-2 scripted spec
                 │
                 └─ tier-2 spec fails fast forever if the bug returns
```

Unit tests keep individual repos correct and fast. Scripted E2E remembers every
bug that has already bitten us. Field tests go looking for the bugs nobody has
found yet — and every bug they find is pushed down into the cheaper tiers so it
never has to be found twice.

## Operational references

- Field-test operating procedure (clean-room VM, dedicated account, acoustic
  loop, sampling, logging, Slack, PRs): the workspace-local `field-testing`
  skill, `.agents/skills/field-testing/SKILL.md`.
- Scripted-E2E suite map, environment reference, and run commands:
  `e2e-scripted/README.md`.
- Disposable macOS VM harness used for clean-room installs:
  `install-tests/electron-macos/`.
- Core field-test account lifecycle: real product signup with a fresh `delivered+openbase-field-<opaque-run-slug>@resend.dev` address in Openbase's reserved Resend testing namespace, real allauth message rendering and Resend submission through the selected Cloud deployment, retrieval through an authenticated Resend CLI profile in secure storage, real confirmation through the tested product, optional post-verification local entitlement, and canonical teardown. A separate field-test-specific Resend profile and per-address deployment allowlist are not required. The `field_test_account` command in openbase-drf-api-core can destroy or grant entitlement but cannot create or verify users. Personal inboxes are forbidden.
- Terminology: `GLOSSARY.md` ("field test", "scripted E2E", "Live E2E test").

# Onboarding Spec

This spec translates the "Onboarding Openbase" Notion doc into an engineering
spec that agents in each repo (`desktop`, `ios`, `cli`, and the private
openbase-cloud backend) can implement against.

Onboarding has two entry points: **Web** (user starts on desktop) and
**App Store** (user starts on iOS, TestFlight for now). Both paths converge at
the same terminal state: desktop and mobile paired via Tailscale, CLI
configured on the Mac.

```
terminal_state = desktop_authenticated
             AND mobile_authenticated
             AND tailscale_paired
             AND cli_configured
```

Related docs:

- [cloud-api.md](cloud-api.md) — proposed openbase-cloud API contract
- [work-items.md](work-items.md) — per-repo work items

## Status and launch blockers (handoff, July 2026)

All four codebases are implemented per this spec (see
[work-items.md](work-items.md) for what landed where): CLI
(`onboarding status/report`, `setup --json-progress`, login/setup hooks),
backend endpoints + `OpenbaseDevice` model, desktop Phone/Pairing pages with
QR + polling + setup checklist, and the iOS Path B flow
(`OnboardingClient.swift`, `OnboardingFlowView.swift`).

The flow is fully no-terminal by design — the Mac app installs the CLI with
one click from a **bundled package** (no `curl`), setup renders as a
checklist, and pairing is button-driven. Four things stand between the design
and a real non-developer succeeding:

1. **Cloud endpoints aren't live.** The backend code was implemented in the
   `openbase-cloud-api` repo (`openbase_api/openbase/`), but the deployed
   Django project is **`api-core`** — the endpoints must be ported there and
   migrated. Until then, none of the cross-device spinners (phone signed in,
   devices paired) ever turn green; both apps detect the missing endpoints
   (404/405/HTML responses) and fall back to "skip" mode. The flow won't
   block a user, but the guided experience doesn't function.
2. **Placeholder URLs.** The desktop QR points at
   `https://openbase.cloud/ios` and Path B tells users to visit
   `https://app.openbase.cloud`; those need to actually redirect to the App
   Store/TestFlight listing and a Mac-app download page.
3. **Distribution.** The Mac app must ship signed/notarized with the CLI
   package actually bundled in — verify the electron-builder packaging
   includes it (in `pnpm dev` there may be no bundled package to activate).
   The iOS app needs a TestFlight/App Store listing.
4. **Tailscale is the remaining friction.** No terminal, but the user
   installs two apps and creates a third-party Tailscale account. That's the
   accepted v1 trade-off; a v2 could embed Tailscale via their iOS/macOS SDKs
   or use pre-provisioned auth keys to skip account creation.

To verify locally: `uv run pytest tests/test_onboarding_status_api.py
tests/test_cloud_registration.py tests/test_onboarding_cli.py` in `cli/`
(23 tests), `uv run openbase-coder onboarding status` for a live check,
`pnpm dev` in `desktop/` to click through the flow, and the iOS simulator
(delete the app first so the `openbase_onboarding_completed` UserDefaults
flag resets).

## Onboarding states

| State | Meaning | Source of truth | Set when |
| --- | --- | --- | --- |
| `desktop_authenticated` | User is logged into the Openbase Mac app / CLI (same account session) | openbase-cloud | Desktop/CLI OAuth token exchange completes for the user |
| `mobile_authenticated` | User is logged into the Openbase iOS app | openbase-cloud | iOS login/signup completes for the user |
| `tailscale_paired` | Both devices are on the user's tailnet and known to Openbase | openbase-cloud (derived) | Both a `desktop` and a `mobile` device for the user have registered a Tailscale identity (see [Device registration](#device-registration)) |
| `cli_configured` | CLI installed and set up on the Mac | Computed by the CLI, reported to openbase-cloud | `openbase-coder setup` completes and the CLI reports state |

States are **monotonic during onboarding**: once a state becomes true, clients
may assume it stays true for the remainder of the flow. (Logout/unlink
resetting states is out of scope for onboarding v1.)

All cross-device state is observed by polling a single backend endpoint,
`GET /api/openbase/onboarding/state/` (see [cloud-api.md](cloud-api.md)).
Clients poll every 2–5 seconds with backoff while an onboarding screen is
waiting on a remote state change.

## Device registration

Per the Notion doc, Tailscale DNS exchange is automatic: devices register with
openbase-cloud and poll for each other's appearance there — no manual DNS
entry or QR-scanning ceremony between devices.

- Each device calls `POST /api/openbase/devices/register/` with its kind
  (`desktop` or `mobile`), hostname/platform info, and — once Tailscale is up —
  its Tailscale identity (MagicDNS name, node hostname, tailnet, IPs).
- Registration is an upsert keyed on `(user, kind, hostname)`; devices
  re-register freely (e.g. after Tailscale comes up, adding the `tailscale`
  block to an earlier registration).
- The backend derives `tailscale_paired = true` when at least one `desktop`
  and one `mobile` device for the user both have a Tailscale identity.
- Mutual peer visibility (the Mac seeing the iPhone in `tailscale status`) is
  a **health check**, not a gate for `tailscale_paired`. The CLI already
  exposes peer discovery at `GET /api/devices/` on the local server.

## Path A: entry via Web (desktop first)

### A1 — Mac app download

- **Trigger:** user navigates to `https://app.openbase.cloud`
- **Render:** download button for the Openbase Mac app
- **Action:** user downloads and opens the Mac app
- **Next:** A2

### A2 — Desktop authentication

- **Render:** login screen on Mac app launch (browser-based OAuth)
- **On success:** backend sets `desktop_authenticated`; Mac app polls
  onboarding state → is `mobile_authenticated` true?
  - **yes** → A4
  - **no** → A3

### A3 — Mobile not yet set up

- **Render:** QR code linking to the App Store listing (TestFlight for now)
- **Copy:** "Scan to download Openbase on your iPhone"
- **Wait:** poll onboarding state until `mobile_authenticated`
- **On detected:** A4

### A4 — Both devices authenticated, begin pairing

Shared `pairDevices()` step — identical to B4, implement once per client.

- **Trigger:** `desktop_authenticated AND mobile_authenticated`
- **Mac:** prompt the user to install Tailscale (v1 is prompt-based; silent
  background install is an open question). Once `tailscale status` reports
  the node is up, register the desktop's Tailscale identity with the cloud
  (`openbase-coder onboarding report` does this).
- **iOS:** redirect the user to the Tailscale app on the App Store, tell them
  to come back when set up. Once the iOS app can read its Tailscale identity,
  register it with the cloud.
- **Wait:** both clients poll onboarding state until `tailscale_paired`.
- **Next:** A5

### A5 — CLI setup

Shared `setupCLI()` step — identical to B5, implement once.

- **Render:** single-click "Set up CLI" button in the Mac app
- **Action:** the Mac app activates its **bundled** CLI package (as
  implemented in `desktop/electron/main.cjs`; the
  `curl -fsSL .../cli/scripts/install.sh | sh` script is the standalone
  path for users without the app, and requires a published GitHub release)
  then runs `openbase-coder setup --json-progress`, rendering the NDJSON step
  events as a checklist (see [Setup progress protocol](#setup-progress-protocol)).
- **On success:** setup reports `cli_configured = true` to the cloud.
- **Terminal state reached.**

## Path B: entry via App Store (mobile first)

### B1 — iOS app launch

- **Render:** login screen on first app open
- **Action:** user logs in or creates an account
- **On success:** backend sets `mobile_authenticated` → B2

### B2 — Setup mode selection

- **Render:** two primary CTAs + one secondary link:
  `[ Link Your Computer ]  [ Start with Cloud (Beta) ]` / `View Documentation →`
- **"Link Your Computer"** → B3
- **"Start with Cloud (Beta)"** → cloud onboarding flow, out of scope here
- **"View Documentation"** → open docs in browser

### B3 — Prompt desktop install

- **Render:** instruction screen
- **Copy:** "Go to `https://app.openbase.cloud` on your Mac to install Openbase"
- **Secondary link:** "Installation Guide" → CLI docs
  (`cli/docs/getting-started.md`, the main open-source entrypoint)
- **Wait:** poll onboarding state until `desktop_authenticated`
- **On detected:** B4

### B4 — Both devices authenticated, begin pairing

Same shared `pairDevices()` step as A4.

### B5 — CLI setup

Same shared `setupCLI()` step as A5. **Terminal state reached.**

## Convergence map

```
Path A (Web)          Path B (App Store)
    │                       │
   A4 ←——————————————————→ B4
    │     Both devices      │
    │     authenticated     │
    ↓                       ↓
  Tailscale pairing (shared pairDevices)
    ↓
  CLI setup (shared setupCLI)
    ↓
  DONE
```

## Setup progress protocol

`openbase-coder setup --json-progress` emits NDJSON on stdout so the Mac app
can render a live checklist. Events:

```jsonc
{"event": "step", "id": "<step-id>", "status": "start", "detail": null}
{"event": "step", "id": "<step-id>", "status": "ok" | "warn" | "error", "detail": "<optional message>"}
// ... one start + one terminal event per step, in order ...
{"event": "result", "ok": true, "cli_configured": true, "tailscale_serve_healthy": true}
```

Step IDs (in execution order):

| id | Meaning |
| --- | --- |
| `workspace` | Clone or sync the setup workspace (dev-workspace mode only) |
| `installation_config` | Write `~/.openbase/installation.json` |
| `env` | Generate `~/.openbase/.env` (voice provider keys) |
| `agent_config` | Symlink Codex/Claude config and instructions |
| `services` | Install background services (launchd/systemd) |
| `tailscale_serve` | Configure Tailscale Serve routes |
| `cloud_report` | Register device + report `cli_configured` to openbase-cloud |

`warn` is non-fatal (setup continues; e.g. Tailscale Serve unavailable).
`error` on a required step ends the run with a nonzero exit code and
`{"event": "result", "ok": false, ...}`.

The Mac app can also read local state at any time via
`openbase-coder onboarding status --json` (works before the local server is
running) or `GET http://127.0.0.1:7999/api/onboarding/status/` (after).

## Open questions

1. **Silent Tailscale install on macOS** — the Notion doc floats installing
   and configuring Tailscale silently in the background on the Mac. v1 is
   prompt-based (user installs the Tailscale app); silent install would
   require bundling `tailscaled` or Homebrew automation.
2. **`tailscale_paired` strictness** — currently both-registered-with-cloud
   (assumption). If flaky tailnets make this too weak, gate on mutual peer
   visibility reported by the CLI instead.
3. **Auth for device registration** — currently the user JWT stored by the
   CLI after login (assumption). Alternative: a dedicated machine-token scope
   (e.g. `device_state`) added to the machine-token mechanism.
4. **Install artifact hosting** — the install script currently pulls from
   GitHub releases; S3/CDN hosting and deployment are deferred.
5. **Cloud endpoint paths** — the paths in [cloud-api.md](cloud-api.md) are
   proposals; confirm against openbase-cloud URL conventions before backend
   implementation.

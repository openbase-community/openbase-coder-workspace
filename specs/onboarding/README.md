# Onboarding Spec

This spec translates the "Onboarding Openbase" Notion doc into an engineering
spec that agents in each repo (`desktop`, `ios`, `cli`, and the private
openbase-cloud backend) can implement against.

Onboarding has two entry points: **Web** (user starts on desktop) and
**App Store** (user starts on iOS, TestFlight for now). Both paths converge at
the same terminal state: a desktop and mobile are registered, each side has
enough Tailscale rendezvous facts to reach the other, and desktop readiness is
verified live over Tailscale.

```
terminal_state = desktop_registered
             AND mobile_registered
             AND tailscale_address_advertised
             AND desktop_ready_live_over_tailscale
```

Related docs:

- [cloud-api.md](cloud-api.md) — openbase-cloud rendezvous API contract
- [work-items.md](work-items.md) — per-repo work items

## Status and launch blockers (handoff, July 2026)

All four codebases are implemented per this spec (see
[work-items.md](work-items.md) for what landed where): CLI
(`onboarding status/report`, `setup --json-progress`, login/setup hooks),
backend rendezvous endpoints + `OpenbaseDevice` model, desktop Phone/Pairing
pages with QR + polling + setup checklist, and the iOS Path B flow
(`OnboardingClient.swift`, `OnboardingFlowView.swift`).

The flow is fully no-terminal by design — the Mac app installs the CLI with
one click from a **bundled package** (no `curl`), setup renders as a
checklist, and pairing is button-driven. Four things stand between the design
and a real non-developer succeeding:

1. **Cloud endpoints aren't live.** The backend code is implemented in the
   right place — `openbase-cloud-api` (`openbase_api/openbase/`) is a plugin
   package installed into the deployed **api-core** project via `api_core.*`
   entry points, and api-core's URL loader mounts the app at `api/openbase/`.
   What remains is operational: merge openbase-cloud-api PR #1, deploy, and
   run migration `0006_openbasedevice`. Until then, none of the cross-device
   spinners (phone signed in, devices discovered) ever turn green; both apps
   detect the missing endpoints (404/405/HTML responses) and fall back to
   "skip" mode. The flow won't block a user, but the guided experience
   doesn't function. (One check at deploy time: if production sets the
   `URL_PREFIXES` env var, confirm it doesn't remap `openbase_api` away from
   the default `api/openbase/` prefix the clients call.)
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
| `desktop_registered` | At least one desktop device has registered for the user | openbase-cloud rendezvous registry | Desktop/CLI OAuth token exchange completes and registration succeeds |
| `mobile_registered` | At least one mobile device has registered for the user | openbase-cloud rendezvous registry | iOS login/signup completes and registration succeeds |
| `tailscale_address_advertised` | A desktop and mobile have enough Tailscale facts to attempt direct contact | openbase-cloud rendezvous registry | Devices register `tailscale_ip`, `tailscale_magic_dns`, or a `tailscale` block |
| `desktop_ready_live_over_tailscale` | Desktop backend and setup are actually ready | Desktop local API over Tailscale | Mobile or desktop client queries the desktop's live status endpoint |

Cloud registration facts are freshness hints, not durable readiness truth.
Clients should treat `last_seen` and advertised capabilities as hints, then
verify setup/readiness directly from the desktop once Tailscale reachability is
available.

All cross-device state is observed by polling a single backend endpoint,
`GET /api/openbase/onboarding/state/` (see [cloud-api.md](cloud-api.md)).
Clients poll every 2–5 seconds with backoff while an onboarding screen is
waiting on a remote state change.

## Device registration

Per the Notion doc, Tailscale DNS exchange is automatic: devices register with
openbase-cloud and poll for each other's appearance there — no manual DNS
entry or QR-scanning ceremony between devices.

- Each device calls `POST /api/openbase/devices/register/` with a stable
  `device_id`, its kind (`desktop` or `mobile`), hostname/display/platform
  info, version, and advertised capabilities. Users may have multiple phones
  and multiple desktops.
- Once Tailscale is up, devices re-register with Tailscale identity
  (`tailscale_ip`, MagicDNS name, node hostname, tailnet, IPs).
- Registration is an upsert keyed on `(user, device_id)`; hostname changes must
  not create replacement devices.
- The backend does not store `paired`, `install_ready`, or equivalent durable
  readiness flags. Clients use cloud data only to discover fresh candidates,
  then query the desktop over Tailscale for peer visibility and setup status.

## Path A: entry via Web (desktop first)

### A1 — Mac app download

- **Trigger:** user navigates to `https://app.openbase.cloud`
- **Render:** download button for the Openbase Mac app
- **Action:** user downloads and opens the Mac app
- **Next:** A2

### A2 — Desktop authentication

- **Render:** login screen on Mac app launch (browser-based OAuth)
- **On success:** desktop registers; Mac app polls onboarding state → is a
  mobile device registered?
  - **yes** → A4
  - **no** → A3

### A3 — Mobile not yet set up

- **Render:** QR code linking to the App Store listing (TestFlight for now)
- **Copy:** "Scan to download Openbase on your iPhone"
- **Wait:** poll onboarding state until a mobile device is registered
- **On detected:** A4

### A4 — Both devices authenticated, begin pairing

Shared `pairDevices()` step — identical to B4, implement once per client.

- **Trigger:** desktop and mobile registrations both exist
- **Mac:** prompt the user to install Tailscale (v1 is prompt-based; silent
  background install is an open question). Once `tailscale status` reports
  the node is up, register the desktop's Tailscale identity with the cloud
  (`openbase-coder onboarding report` does this).
- **iOS:** redirect the user to the Tailscale app on the App Store, tell them
  to come back when set up. Once the iOS app can read its Tailscale identity,
  register it with the cloud.
- **Wait:** both clients poll onboarding state until the other side advertises
  a Tailscale IP or MagicDNS name, then verify direct reachability.
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
- **On success:** setup advertises current CLI/setup capabilities to the
  rendezvous registry; clients verify readiness live from the desktop.
- **Terminal state reached.**

## Path B: entry via App Store (mobile first)

### B1 — iOS app launch

- **Render:** login screen on first app open
- **Action:** user logs in or creates an account
- **On success:** mobile registers → B2

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
- **Wait:** poll onboarding state until a desktop device is registered
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
    │      registered       │
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
| `cloud_report` | Register device + advertise current CLI/setup capabilities |

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
2. **Live desktop verification strictness** — once a peer advertises a
   Tailscale address, decide which desktop status fields are required before
   the mobile app marks onboarding complete.
3. **Auth for device registration** — currently the user JWT stored by the
   CLI after login (assumption). Alternative: a dedicated machine-token scope
   (e.g. `device_state`) added to the machine-token mechanism.
4. **Install artifact hosting** — the install script currently pulls from
   GitHub releases; S3/CDN hosting and deployment are deferred.
5. **Cloud endpoint paths** — confirm production URL prefixing still mounts
   the API at `api/openbase/` before deploy.

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

## Status (updated 2026-07-06)

All four codebases are implemented and **deployed** per this spec (see
[work-items.md](work-items.md) for what landed where):

- **Cloud endpoints are live** on app.openbase.cloud (device registry +
  onboarding state, migration `0006_openbasedevice` applied). Clients'
  fallback "skip" mode now only triggers against genuinely old backends.
- **URLs are real**: `openbase.cloud/ios` forwards to the TestFlight
  listing (single-source forwarder page in the marketing site), and Path B's
  web URL serves the product dashboard with OAuth resume fixed for
  signed-out users.
- **Distribution ships**: desktop CI publishes a signed/notarized DMG on
  every desktop main push, seeded with the latest *released* CLI package;
  the iOS TestFlight build is current.
- Desktop onboarding routing is **derived from observable state**
  (`desktop/src/onboarding/deriveStep.ts`) rather than scripted page jumps;
  acknowledgments persist in `~/.openbase/desktop-onboarding.json` so wiping
  the Openbase home resets onboarding.

Remaining v1 trade-off: **Tailscale friction** — no terminal, but the user
installs two apps and creates a third-party Tailscale account. A v2 could
embed Tailscale via their SDKs or pre-provisioned auth keys.

To verify locally: `uv run pytest tests/test_onboarding_status_api.py
tests/test_cloud_registration.py tests/test_onboarding_cli.py` in `cli/`,
`uv run openbase-coder onboarding status` for a live check, and a clean-slate
walk per `DEV_RUNBOOK.md` §6 (also remove
`~/Library/Application Support/@openbase/coder-desktop` and
`~/.openbase/desktop-onboarding.json` for a true first run).

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
- **Next:** coding agent sign-in (see
  [Coding backend sign-in](#coding-backend-sign-in)), then the remaining
  desktop steps.
- **On success:** setup advertises current CLI/setup capabilities to the
  rendezvous registry; clients verify readiness live from the desktop.
- **Terminal state reached.**

## Coding backend sign-in

Setup configures a coding backend (`codex`, `claude_code`, or
`openbase_cloud`) but must not block on that backend's own interactive
login: under `--json-progress` the CLI **never** launches a browser OAuth
flow (interactive terminal setup still runs the Claude Code login when that
backend is selected). Instead, the local onboarding status payload reports
auth readiness for the selected backend:

```jsonc
// GET /api/onboarding/status/ (or `openbase-coder onboarding status --json`)
{
  "backend_auth": { "backend": "claude_code", "ready": false },
  // ... cli_configured, checks, versions, authenticated, tailscale_*, cloud
}
```

`ready` means the backend can start coding sessions without an interactive
login: Claude Code via `claude auth status` against Openbase's managed
`CLAUDE_CONFIG_DIR`, Codex via the service home's `auth.json` (setup links
it to `~/.codex/auth.json` — even before that file exists — so a later
`codex login` is picked up without re-running setup), and Openbase Cloud
rides on the CLI's own cloud login (`ready` equals `authenticated`).

The desktop renders a **backendAuth** onboarding step right after setup
(`desktop/src/onboarding/deriveStep.ts`), derived from `backend_auth` and
polled while the step is visible:

- **claude_code:** a sign-in button runs `openbase-coder claude login`
  through the installer bridge; manual fallback is the same command.
- **codex:** instruct the user to run `codex login` in a terminal; the step
  advances automatically once the CLI reports `ready`.
- **openbase_cloud:** skipped — the later Openbase sign-in step covers it.
- Older CLIs that do not report `backend_auth` never block the step.

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
| `workspace` | Detect the bundled runtime package, or locate the development workspace checkout (never clones) |
| `installation_config` | Write `~/.openbase/installation.json` |
| `env` | Generate `~/.openbase/.env` (voice provider keys) |
| `agent_config` | Symlink Codex/Claude config and instructions |
| `services` | Install background services (launchd/systemd) |
| `tailscale_serve` | Configure Tailscale Serve routes |

`warn` is non-fatal (setup continues; e.g. Tailscale Serve unavailable).
`error` on a required step ends the run with a nonzero exit code and
`{"event": "result", "ok": false, ...}`.

The Mac app can also read local state at any time via
`openbase-coder onboarding status --json` (works before the local server is
running) or `GET http://127.0.0.1:7999/api/onboarding/status/` (after). The
payload includes the `backend_auth` block described in
[Coding backend sign-in](#coding-backend-sign-in).

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

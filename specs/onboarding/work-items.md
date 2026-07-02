# Onboarding Work Items by Repo

Concrete work items per repo, implementable independently. The CLI items ship
first (they degrade gracefully without the backend); the backend unblocks the
cross-device polling; the apps build their flows on both.

See [README.md](README.md) for the flow spec and
[cloud-api.md](cloud-api.md) for the backend contract.

## openbase-cloud (private backend)

1. Implement the device model and the three endpoints in
   [cloud-api.md](cloud-api.md).
2. Set `desktop_authenticated` when the CLI/desktop OAuth token exchange
   completes (`/api/openbase/auth/cli/token-exchange/`), and
   `mobile_authenticated` on iOS login/signup.
3. Derive `tailscale_paired` (both device kinds registered with Tailscale
   identities) and top-level `cli_configured` (any desktop device reported it).

## desktop (Mac app, private)

1. Onboarding window implementing the Path A state machine (A2–A5 in
   [README.md](README.md)); on launch, poll
   `GET /api/openbase/onboarding/state/` to decide which step to show.
2. Step A3: render a QR code linking to the App Store listing (TestFlight for
   now); poll until `mobile_authenticated`.
3. `pairDevices()`: prompt the user to install Tailscale (v1; no silent
   install); once up, run `openbase-coder onboarding report` (or POST the
   registration directly) so the desktop's Tailscale identity reaches the
   cloud; poll until `tailscale_paired`.
4. `setupCLI()`: single-click button that runs the install script
   (`curl -fsSL .../cli/scripts/install.sh | sh`) followed by
   `openbase-coder setup --json-progress`, rendering the NDJSON step events
   (step IDs in [README.md](README.md#setup-progress-protocol)) as a
   checklist. The existing deep link
   (`openbase-coder://open?source=cli-auth&intent=login-complete`) already
   returns the user to the app after browser login.
5. Local state reads: `openbase-coder onboarding status --json` before the
   local server is up, `GET http://127.0.0.1:7999/api/onboarding/status/`
   after.

## ios (private)

1. Path B state machine (B1–B5): login → setup mode selection ("Link Your
   Computer" / "Start with Cloud (Beta)" / "View Documentation").
   Fix the signup flow issues noted in the Notion doc (separate card).
2. B3 instruction screen ("Go to `https://app.openbase.cloud` on your Mac");
   poll until `desktop_authenticated`.
3. `pairDevices()`: redirect to the Tailscale app on the App Store; once the
   app can determine its Tailscale identity, call
   `POST /api/openbase/devices/register/` with `kind: "mobile"`; poll until
   `tailscale_paired`.
4. Poll until `cli_configured` for the final "all set" state.

## cli (this workspace — implemented alongside this spec)

1. `services/onboarding.py`: `onboarding_status_payload()` computing
   `cli_configured`, Tailscale Serve health, local Tailscale identity, and
   local auth presence.
2. `GET /api/onboarding/status/` on the local Django server and
   `openbase-coder onboarding status --json` (works pre-setup).
3. `services/cloud_registration.py`: `register_device_with_cloud()` and
   `report_cli_state()` against the [cloud-api.md](cloud-api.md) endpoints;
   tolerate the endpoints being unshipped (404/405 or HTML error pages);
   cache the last result in `~/.openbase/onboarding.json`.
4. Hooks: register/report at the end of `openbase-coder login` and
   `openbase-coder setup`; explicit `openbase-coder onboarding report` for
   retries and the Mac app's pairing step.
5. `openbase-coder setup --json-progress`: NDJSON step events per the
   [setup progress protocol](README.md#setup-progress-protocol).

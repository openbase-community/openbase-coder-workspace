# Onboarding Work Items by Repo

Concrete work items per repo, implementable independently. The CLI items ship
first (they degrade gracefully without the backend); the backend unblocks the
cross-device polling; the apps build their flows on both.

See [README.md](README.md) for the flow spec and
[cloud-api.md](cloud-api.md) for the backend contract.

## openbase-cloud (private backend) — DONE

Implemented in `openbase-cloud-api` (`openbase_api/openbase/`): the
`OpenbaseDevice` model and rendezvous endpoints in
[cloud-api.md](cloud-api.md). The backend stores fresh device facts keyed by
stable `device_id`, supports multiple devices per kind, and returns device
lists/counts. It does not store pairing, install readiness, or CLI readiness as
durable truth; clients verify those live over Tailscale once a peer advertises
an address.

## desktop (Mac app, private) — DONE

Implemented in `openbase-coder-desktop`: the onboarding shell
(`src/DesktopShell.tsx`) gained "Phone" (QR code + mobile registration polling)
and "Pairing" (Tailscale install prompt + "Register this Mac" via
`openbase-coder onboarding report` + Tailscale address discovery) steps; setup
runs with `--json-progress` and renders the step checklist; the
`intent=login-complete` deep link advances to the phone step; cloud state is
fetched in the main process (`electron/main.cjs`) using a CLI-minted access
token. Pairing can be degraded/dismissed when the backend does not serve the
onboarding endpoints yet, without permanently recording pairing completion.

Original work items:

1. Onboarding window implementing the Path A state machine (A2–A5 in
   [README.md](README.md)); on launch, poll
   `GET /api/openbase/onboarding/state/` to decide which step to show.
2. Step A3: render a QR code linking to the App Store listing (TestFlight for
   now); poll until a mobile device is registered.
3. `pairDevices()`: prompt the user to install Tailscale (v1; no silent
   install); once up, run `openbase-coder onboarding report` (or POST the
   registration directly) so the desktop's Tailscale identity reaches the
   cloud; poll until the peer advertises a Tailscale address, then verify live
   reachability.
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

## ios (private) — DONE

Implemented in `openbase-ios`: `Services/OnboardingClient.swift` (cloud state
fetch + device registration + local Tailscale detection via CGNAT interface
addresses) and `Views/OnboardingFlowView.swift` (Path B steps with
`OnboardingViewModel` + `OnboardingGateView` wrapping the authenticated root
in `OpenbaseApp.swift`). The app registers `kind: "mobile"` with a stable
`device_id` right after login, re-registers with Tailscale facts once a
100.64/10 utun address appears, auto-adds the desktop's MagicDNS name as the
backend host, and can dismiss a degraded cloud flow without permanently
recording pairing completion.

Original work items:

1. Path B state machine (B1–B5): login → setup mode selection ("Link Your
   Computer" / "Start with Cloud (Beta)" / "View Documentation").
   Fix the signup flow issues noted in the Notion doc (separate card).
2. Immediately after login, call `POST /api/openbase/devices/register/` with
   `kind: "mobile"` (no Tailscale facts yet) — this is what makes the mobile
   discoverable for Path A's step A3.
3. B3 instruction screen ("Go to `https://app.openbase.cloud` on your Mac");
   poll until a desktop device is registered.
4. `pairDevices()`: redirect to the Tailscale app on the App Store; once the
   app can determine its Tailscale identity, re-register with Tailscale facts;
   poll until a desktop advertises a Tailscale address, then verify the desktop
   live over Tailscale.
5. Use the desktop's live onboarding/status API for the final "all set" state.

## cli (this workspace — implemented alongside this spec)

1. `services/onboarding.py`: `onboarding_status_payload()` computing
   local CLI setup, Tailscale Serve health, local Tailscale identity, and
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

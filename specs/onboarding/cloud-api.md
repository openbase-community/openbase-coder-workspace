# Onboarding Cloud API Contract (Proposed)

Endpoints to be implemented in the private openbase-cloud backend
(openbase-cloud-workspace). Paths are proposals — confirm against existing
openbase-cloud URL conventions before implementing. Clients in this workspace
(the CLI) are written to tolerate these endpoints not existing yet — a
404/405 or an HTML error page (the current backend returns Django's 403 CSRF
HTML page for unknown API paths) is treated as "not supported yet" and
skipped without failing — so the backend can ship after the clients. This
also means the real endpoints must return JSON errors (standard DRF
behavior), never HTML.

Authentication: all endpoints take the user's JWT (the CLI uses the access
token stored in `~/.openbase/auth.json` after `openbase-coder login`; the
apps use their existing session credentials). See open question 3 in
[README.md](README.md) about a machine-token scope alternative.

## GET /api/openbase/onboarding/state/

Single polling endpoint for all cross-device onboarding state. Polled by the
Mac app, the iOS app, and optionally the CLI, every 2–5 s with backoff while
an onboarding screen is waiting.

Response `200`:

```jsonc
{
  "desktop_authenticated": true,
  "mobile_authenticated": false,
  "tailscale_paired": false,
  "cli_configured": false,
  "devices": [
    {
      "kind": "desktop",
      "hostname": "zokys-macbook-pro",
      "platform": "darwin",
      "os_version": "15.5",
      "app_version": "1.4.2",
      "tailscale": {
        "dns_name": "zokys-macbook-pro.tail1234.ts.net.",
        "node_hostname": "zokys-macbook-pro",
        "tailnet": "tail1234.ts.net",
        "ips": ["100.64.0.1"]
      },
      "cli_configured": false,
      "last_seen": "2026-07-01T22:00:00Z"
    }
  ]
}
```

- `desktop_authenticated` / `mobile_authenticated`: set by the backend when a
  login completes from a desktop (Mac app / CLI OAuth token exchange) or
  mobile (iOS) client respectively. The existing CLI token exchange endpoint
  (`/api/openbase/auth/cli/token-exchange/`) should set
  `desktop_authenticated`.
- `tailscale_paired`: derived — true when at least one `desktop` and one
  `mobile` device both have a non-null `tailscale` block.
- `cli_configured`: true when any desktop device has reported
  `cli_configured` (see PATCH below).

## POST /api/openbase/devices/register/

Registers (or re-registers) the calling device. Upsert keyed on
`(user, kind, hostname)` — devices call this repeatedly as their state
evolves (e.g. first without `tailscale`, again once Tailscale is up).

Request:

```jsonc
{
  "kind": "desktop",            // "desktop" | "mobile"
  "hostname": "zokys-macbook-pro",
  "platform": "darwin",          // "darwin" | "ios" | "linux" | ...
  "os_version": "15.5",
  "app_version": "1.4.2",        // app or CLI version
  "tailscale": {                 // optional; omit/null until Tailscale is up
    "dns_name": "zokys-macbook-pro.tail1234.ts.net.",
    "node_hostname": "zokys-macbook-pro",
    "tailnet": "tail1234.ts.net",
    "ips": ["100.64.0.1"]
  }
}
```

Response `200`/`201`: the stored device record (same shape as entries in
`devices` above).

## PATCH /api/openbase/devices/self/state/

Reports CLI state for the calling desktop device (matched on
`(user, kind="desktop", hostname)` from the request body or auth context).
Called by the CLI at the end of `openbase-coder setup` and by
`openbase-coder onboarding report`.

Request:

```jsonc
{
  "hostname": "zokys-macbook-pro",
  "cli_configured": true,
  "cli_version": "1.4.2",
  "serve_healthy": true          // Tailscale Serve routes responding
}
```

Response `200`: the updated device record.

## Backend work summary

1. Device model: `(user, kind, hostname)` unique, platform/version fields,
   nullable `tailscale` JSON, `cli_configured`, `cli_version`,
   `serve_healthy`, `last_seen`.
2. The three endpoints above.
3. `desktop_authenticated` / `mobile_authenticated` flags set from the
   respective login flows (client type must be distinguishable at login /
   token exchange).
4. Derivation logic for `tailscale_paired` and top-level `cli_configured`.

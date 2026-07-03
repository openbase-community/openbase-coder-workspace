# Onboarding Cloud API Contract

Implemented in `openbase-cloud-api` under `openbase_api/openbase/`.
The cloud is a rendezvous registry: it records fresh device facts so signed-in
clients can discover each other, but it is not the source of truth for pairing,
install readiness, or desktop health. Once a mobile app has a Tailscale IP or
MagicDNS name for a desktop, it should query that desktop live over Tailscale
for setup/readiness details.

Authentication: all endpoints take the user's JWT. The CLI uses the access
token stored in `~/.openbase/auth.json`; the apps use their existing session
credentials.

## GET /api/openbase/onboarding/state/

Returns the signed-in user's registered devices. Poll this every 2-5 seconds
with backoff while an onboarding screen is waiting for another device to appear
or advertise a Tailscale address.

Response `200`:

```jsonc
{
  "desktop_count": 2,
  "mobile_count": 1,
  "devices": [
    {
      "id": 42,
      "device_id": "desktop-8b6b2f7a-7be1-4ad5-a5cc-0a9d7a1a3a0e",
      "kind": "desktop",
      "hostname": "zokys-macbook-pro",
      "display_name": "Zoe's MacBook Pro",
      "platform": "darwin",
      "os_version": "15.5",
      "version": "1.4.2",
      "tailscale": {
        "dns_name": "zokys-macbook-pro.tail1234.ts.net.",
        "node_hostname": "zokys-macbook-pro",
        "tailnet": "tail1234.ts.net",
        "ips": ["100.64.0.1"]
      },
      "tailscale_ip": "100.64.0.1",
      "tailscale_magic_dns": "zokys-macbook-pro.tail1234.ts.net.",
      "capabilities": {
        "cli_configured": true,
        "tailscale_serve_healthy": true
      },
      "last_seen": "2026-07-01T22:00:00Z"
    }
  ]
}
```

- `desktop_count` and `mobile_count` are counts of registered devices by kind.
- `devices` may contain multiple phones and multiple Macs or Mac minis for the
  same user.
- `capabilities` are advertised facts from the device. They are useful hints,
  not authoritative readiness gates.
- Pairing/install readiness should be verified live from the desktop over
  Tailscale when `tailscale_ip` or `tailscale_magic_dns` is available.

## POST /api/openbase/devices/register/

Registers or re-registers the calling device. Upsert is keyed on
`(user, device_id)` so a user can own multiple phones and multiple desktops.

Request:

```jsonc
{
  "device_id": "desktop-8b6b2f7a-7be1-4ad5-a5cc-0a9d7a1a3a0e",
  "kind": "desktop",
  "hostname": "zokys-macbook-pro",
  "display_name": "Zoe's MacBook Pro",
  "platform": "darwin",
  "os_version": "15.5",
  "version": "1.4.2",
  "tailscale": {
    "dns_name": "zokys-macbook-pro.tail1234.ts.net.",
    "node_hostname": "zokys-macbook-pro",
    "tailnet": "tail1234.ts.net",
    "ips": ["100.64.0.1"]
  },
  "tailscale_ip": "100.64.0.1",
  "tailscale_magic_dns": "zokys-macbook-pro.tail1234.ts.net.",
  "capabilities": {
    "cli_configured": true,
    "tailscale_serve_healthy": true
  }
}
```

Response `200`: `{"message": "Device registered.", "device": {...}}` where
`device` has the same shape as entries in `GET /onboarding/state/`.

Clients may first register without Tailscale facts and re-register later.
Omitting Tailscale fields does not clear previously stored Tailscale identity;
clients must send updated Tailscale facts when they intentionally have them.

## Removed Endpoint

`PATCH /api/openbase/devices/self/state/` is intentionally not part of the
contract. CLI setup status and local desktop health are advertised as
capabilities on registration, then verified from the desktop itself when a
client can reach it over Tailscale.

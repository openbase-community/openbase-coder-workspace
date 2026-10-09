# Plan: localhost ports on the phone and localhost OAuth callbacks for Maritime agents

Status: plan, not yet implemented. MWW `maritime-localhost-oauth` (branch `feature/maritime-localhost-oauth`) of the coder workspace; the Cloud API changes need a sibling MWW of the same name in the cloud workspace, created when step 2 starts. Assessment: `~/Projects/openbase/.reports/2026-10-09-maritime-localhost-oauth-assessment.md` (2026-10-09). Pipeline: implement → local review → merge, no QA stage; step 5 (the iOS packet-tunnel listener) is a networking spike and may request optional QA.

## Goal

An agent running in a Maritime cloud workspace can (1) expose a localhost port over the Openbase VPN and have it opened in the browser on the user's iPhone or Android phone, including when the Openbase app is not in front, and (2) complete CLI logins whose OAuth redirect points at `http://localhost:<port>/...` (Codex, gcloud, MCP server OAuth, Openbase's own login, and any other RFC 8252 loopback client) with the browser on the phone.

## Decisions (product defaults, per the assessment's questions)

1. **Tap-to-open when the app is not in front (confirmed by Gabe, 2026-10-09).** Neither OS permits a silent background switch to the browser. A notification "Open <host> to finish signing in to <tool>" is the behaviour; auto-open only when the app is foreground and the workspace is its selected computer.
2. **URL shape for exposed ports: `http://<workspace-magicdns>:<port>/` first.** `https://<svc>.<ns>.vpn.obs.so/` parity for Maritime is step 6, optional.
3. **Callback forwarding is automatic.** The open-on-phone command parses `redirect_uri` from the login URL; `--callback-port` overrides. A forward lives 10 minutes or until its first completed HTTP exchange, whichever comes first.
4. **iOS fallback if the extension listener spike fails:** ship Goal 2 on iOS as in-call / in-app-browser listener plus paste-back, document the limit, keep the extension listener as a later item.
5. **Phone-side forwarders are host-agnostic.** The command carries the target tailnet address; a Mac host can use it later through the signed helper's existing `published-dynamic` rule kind. This MWW enables Maritime only.
6. **Login priority for native backends:** Codex (`localhost:1455`), MCP server OAuth (random loopback port), gcloud; gh and Claude already complete through device-code / paste flows.
7. **Push payloads carry the provider login URL** (state and PKCE challenge, never secrets). Length-capped and scheme-restricted.

## Architecture

```
workspace (Maritime container)                     phone (Openbase VPN mode)
┌──────────────────────────────┐                   ┌────────────────────────────────┐
│ CLI login: listens 127.0.0.1:P│                   │ Safari / Chrome                 │
│ opens URL with redirect_uri   │                   │   http://localhost:P/callback   │
│          │                    │                   │          │ loopback             │
│ openbase-coder browser open   │  push / socket    │ loopback listener :P            │
│  - parse redirect_uri → P     │ ────────────────▶ │  (Android: NetmeshVpnService    │
│  - tunneld POST /forwards {P} │  forward_loopback │   iOS: packet tunnel extension) │
│  - notify phone (open_url)    │                   │          │ tcp over WireGuard   │
│ tunneld: tailnet :P → 127.0.0.1:P ◀───────────────┼──────────┘                      │
└──────────────────────────────┘  owner-only (ACL)  └────────────────────────────────┘
```

Workspace → phone control goes over the existing app-control websocket when the app is foreground and has the workspace selected, otherwise over Cloud push (APNs/FCM) using a new workspace machine-token scope. Data goes phone → workspace only, over the tailnet, under the existing headscale `autogroup:self` policy.

## Steps and PR-sized landings

Each step is one review + merge through the MWW pipeline. Steps 1–3 are independent of the phone work and land first. Steps 4 and 5 depend on 2 and 3. Step 6 is optional and depends on 2.

### Step 0: skill and `BROWSER` shim (S, 0.5–1 day) — repos: `skills`, `cli`

- `skills/skills/openbase-cloud-workspace-logins/SKILL.md` (bundled, user-facing): how to log a CLI in from a cloud workspace or any host whose browser is on another device. Prefer device-code or paste flows where the tool has one: `gh auth login` (device code by default), `codex login --device-auth`, `claude` (printed URL + pasted code), `gcloud auth login --no-launch-browser`, Heroku-style browser-link. For tools that require a loopback redirect, use `openbase-coder browser open <url>` (step 2) and, as the universal fallback, paste the failed `http://localhost:<port>/...?code=...` address from the phone's browser into the thread so the agent replays it with `curl` against `localhost` inside the workspace.
- `cli/docker/entrypoint.sh` / `cli/Dockerfile`: export `BROWSER` and `GH_BROWSER` pointing at `openbase-coder browser open` in the Maritime image so CLIs that honour `BROWSER` route their login URL to the phone without agent involvement. Until step 2 lands, the command prints the URL and the paste-back instructions.
- `cli/docs/docker.md` and `cli/docs/cloud-devspace.md`: replace the `socat` bridging section's "desktop only" framing with a pointer to the skill.
- Tests: skill linted by the skills repo checks; entrypoint unit test for the env export; `openbase-coder browser open --help` smoke test.

### Step 1: tunneld dynamic forwards + `openbase-coder service expose` (S, 1–2 days) — repo: `cli`

- `cli/tunneld/localapi.go`: `POST /forwards` `{port, ttl_seconds, peer_node_id?}` → `srv.Listen("tcp", ":<port>")` → existing `forwardTCP` to `127.0.0.1:<port>`; `DELETE /forwards/{port}`; `GET /forwards`. Same token guard as the other routes. Reject ports already served (18080, 7880, 7881, 3478), ports < 1024, and more than 16 concurrent forwards. TTL expiry closes the listener. When `peer_node_id` is set, accept only connections whose remote address belongs to that peer (tsnet `WhoIs`); otherwise any peer the ACL admits (owner devices only). `one_shot: true` closes the forward after the first connection finishes.
- `cli/openbase_coder_cli/services/tunneld.py`: client helpers `add_forward`, `remove_forward`, `list_forwards`.
- `cli/openbase_coder_cli/cli/service.py`: `openbase-coder service expose <port> [--ttl 10m] [--one-shot]` and `service unexpose <port>`; on a tsnet host it prints `http://<self-magicdns>:<port>/` (from tunneld `/status`); on a non-tsnet host it explains that `service publish` is the Mac path. `service list` shows forwards alongside publications.
- Tests: Go tests for the forward lifecycle with an in-process tsnet pair (reuse the `peer` test tool pattern); Python tests for the client and command with a fake tunneld.
- Security: listener is on the tailnet only (tsnet), never a container interface; owner-only by the headscale policy; TTL and one-shot; peer pinning for OAuth forwards.

### Step 2: URL-carrying push and "open on phone" (S/M, 2–3 days) — repos: `api` (cloud MWW), `cli`, `ios`, `android`

- **Cloud `api`:** add machine-token scopes `notify` and (for step 6) `netmesh_publish` to `MARITIME_MACHINE_SCOPES` in `devspaces/bootstrap.py`; a `OpenbaseNotifyScopePermission` alongside the existing proxy-scope permissions in `openbase/authentication.py`; `NotifyNotificationView` accepts `OpenbaseMachineTokenAuthentication` with that permission in addition to JWT. `notification_serializers.py`: new optional `user_info.url` (http, https, `openbase-app` only; max 2048 chars; no control characters), new destination `OPEN_URL`, and a `loopback_forward` object `{port, target, ttl_seconds, token}` for step 4/5 payloads. Existing throttle applies per user. Tests for scope enforcement, payload validation, APNs/FCM fan-out shape. Migration only if the scope list is a DB-constrained field.
- **`cli`:** `openbase-coder browser open <url> [--callback-port P] [--no-forward]`: parse `redirect_uri` (and `redirect_url`) from the query; if it is loopback with a port, call step 1's `add_forward` (ttl 10 min, one-shot, peer pinned when the phone's node id is known from the device registry); then deliver `{action: "open_url", url, loopback_forward?}` over the app-control socket (fast path, waits for the post-open ack) and, if no ack within 5 s or the workspace is not the phone's selected computer, via Cloud `notifications/notify/` with the machine token. `user ios open-url` becomes an alias of `browser open --no-forward`; `ios_app_control.py` gains the `loopback_forward` field and renames the public action set to platform-neutral names while keeping the old websocket path for compatibility. Server reports `delivered: socket|push|none`.
- **`ios`:** `IOSAppControlConnection`: ack after `UIApplication.open` completes and include `opened: Bool`; when the scene is not active (in-call background), post a local notification instead of calling `open`. `AppDelegate` / `AppRouteManager` / `DeepLinkRoute`: new `open_url` destination from APNs `userInfo["url"]` (same scheme filter) → `UIApplication.open` on tap. Unit tests for route parsing and the scheme filter.
- **`android`:** `AppControlConnection`: ack after `startActivity` with `opened`; when the activity is not resumed, post a notification with an `ACTION_VIEW` tap `PendingIntent` (reuse `AlertNotificationPoster`). `OpenbaseMessagingService` / `PendingNotificationDestination`: `open_url` destination with URL validation → notification → `ACTION_VIEW`. Tests for the destination parsing and the ack ordering.
- Device check (Gabe QA, documented in the PR): `*.net.obs.so` resolves in Chrome on Android with the VPN up, including with Private DNS set to automatic; note the result for strict Private DNS and Chrome Secure DNS.

After step 2, Goal 1 is complete on both phones and every login with a device-code or paste path works from the phone. Goal 2 still needs paste-back for loopback-only CLIs.

### Step 3: paste-back affordance (S, 1 day per platform) — repos: `cli`, `ios`, `android`

- `cli`: `POST /api/user/oauth-callback-replay/` `{url}` (authenticated app endpoint): validates that the URL is loopback, port currently forwarded or any listening loopback port, and replays `GET` against `127.0.0.1` with the original path and query; returns the status. Also `openbase-coder browser replay <url>` for the agent.
- `ios`: share extension accepting a URL ("Send to Openbase") plus a "Paste login URL" row in the thread composer overflow; both post to the selected workspace's replay endpoint. `android`: `ACTION_SEND` text share target plus the same composer row.
- Tests: replay endpoint unit tests (rejects non-loopback hosts, forwards query intact); app unit tests for URL extraction.

### Step 4: Android loopback forwarder in `NetmeshVpnService` (M, 2–3 days) — repo: `android`

- `netmesh/LoopbackForwarder.kt` inside the VPN service process: on `forward_loopback {port, target, ttl, token}` (from the app-control socket or an FCM data message), bind `127.0.0.1:<port>` and `[::1]:<port>` (`ServerSocket`, `SO_REUSEADDR`), for each accepted connection open a plain socket to `<target>:<port>` (goes through the tun; do not `protect()`), pump both directions, close after TTL or after the first completed exchange when `one_shot`. Idempotent per port; bind failure (port in use) reports `forward_failed` back over the socket so the agent can fall back to paste-back.
- Delivery: when the app is foreground, the app-control socket hands the command to the service via a bound call; when not, the FCM data message (high priority) reaches `OpenbaseMessagingService`, which starts the forward in the already-running VPN service and posts the open-URL notification. If the VPN is not up, report `vpn_down` and fall back to paste-back.
- Tests: Robolectric/JVM tests for the forwarder with a local target; instrumentation test on an emulator with a fake "workspace" socket; manual device check by Gabe: Codex login in a cloud workspace completed from Chrome on Android.

### Step 5: iOS spike and packet-tunnel loopback forwarder (spike 0.5 day; M/L, 3–5 days) — repos: `ios`, possibly `netmesh-go`

**Spike first, in this MWW, before any design work on the forwarder.** Add a temporary `NWListener` to `PacketTunnelProvider` on `127.0.0.1:8765` and `[::1]:8765` answering a static HTTP 200, started on tunnel start, plus a temporary provider-message handler that dials a tailnet peer (`<workspace-magicdns>:18080/api/health/`) from the extension with a plain `NWConnection`. Build to Gabe's phone (wireless devicectl, per the existing memory), VPN up, app killed.

Go / no-go criteria:

- GO if, with the Openbase app killed and only the VPN running: Safari and Chrome both load `http://localhost:8765/` and `http://127.0.0.1:8765/`; the extension's `NWConnection` to the workspace's 100.x address succeeds (its own traffic routes through its own utun); the extension's memory stays under 40 MB during a transfer (Xcode memory gauge or `os_proc_available_memory`); the listener survives 10 minutes of backgrounded phone use.
- NO-GO if any of: the listener cannot bind or Safari gets "cannot connect"; the extension's outbound socket to 100.x fails or loops; memory exceeds 45 MB; iOS kills the extension while the listener is live. On NO-GO: ship the fallback (listener in the app process via a generalised `EmbeddedTcpForward` with fixed ports, which works in-call and when the login page is opened in an in-app `SFSafariViewController`; otherwise paste-back), record the finding in the dev docs, and stop.

Forwarder on GO:

- `PacketTunnel/LoopbackForwarder.swift`: per-port dual-stack `NWListener`, pipe to `NWConnection(host: target, port)`, TTL and one-shot, token check, `forward_failed` reporting. Control via `NETunnelProviderSession.sendProviderMessage` from the app (`NetmeshVPNController`), payload `forward_loopback` / `cancel_forward` / `list_forwards`.
- App side: `IOSAppControlConnection` and the APNs `open_url` route hand `loopback_forward` to the controller before opening the URL; if the VPN is down, prompt to connect and fall back to paste-back.
- Tests: unit tests for the forwarder with a loopback target in the extension target; app tests for the provider-message encoding; manual device check by Gabe: Codex login completed from Safari and from Chrome with the app killed.
- `netmesh-go` is not expected to change; if the extension's own sockets cannot reach the tailnet, the alternative is exporting a `Dial` from the bridge, which is a separate decision (memory).

### Step 6 (optional): Maritime `service publish` parity (M/L, 3–5 days) — repos: `cli`, `api` (cloud MWW)

- `api`: `service-hostnames/` and `certificate-dns/` views accept the machine token with scope `netmesh_publish`, restricted to the caller's own `node_id` (the workspace's enrollment); capabilities report `serve_routing: true` for tsnet nodes.
- `cli`: `tailscale_provider.serve_capability` returns a tsnet capability (tunneld version, port 443 TCP) instead of "not a host VPN"; `published_service_routes` allows tsnet, resolves the hostname self-check through tunneld (`/resolve` endpoint using the tsnet node's resolver) instead of `getaddrinfo`; tunneld `POST /forwards` learns `{port: 443, local: 59443}` and `{port: 80, local: <redirect-port>}`; the Python TLS ingress and ACME flow run unchanged in the container; persistence via entrypoint-supervised restore instead of launchd. Certificate renewal runs at container start and while a publication is active.
- Tests: existing publish test lanes extended with a tsnet provider fake; Go tests for the 443/80 forwards.

## Test strategy

- **Unit and integration in each repo, same change as the behaviour** (review fails otherwise): Go tests for tunneld; pytest for cli (`uv run --project cli pytest` in the MWW venv); Django tests for api scopes and serializers; XCTest for ios routes, provider messages and forwarder; JVM/Robolectric for android.
- **Isolated live check of the workspace side** with the `docker-verification` dev skill: a container with tunneld on a throwaway tsnet node against the local headscale harness (`netmesh-infra/local-headscale`), a fake CLI callback server on `127.0.0.1:1455`, and a second tsnet peer (`tunneld peer --forward`) playing the phone. Proves forward lifecycle, TTL, one-shot and peer pinning without any phone.
- **Phones:** no agent-run phone QA (Gabe does QA). Each PR lists the exact manual check for Gabe: Codex login from a cloud workspace completed from Safari, Chrome on iOS, and Chrome on Android, app in front, app backgrounded, app killed; `service expose 3000` of a Vite dev server opened from a notification tap. Step 5's spike results are recorded in the PR.
- **Cross-backend review** by the `mww-review` loop per step; step 5 may request optional QA as a networking spike.

## Security

- Workspace listeners exist only on the tsnet node (never a container interface), are reachable only by the owner's devices under the headscale `autogroup:self` policy, expire after 10 minutes, are one-shot for OAuth, and are pinned to the requesting phone's node when known. No Funnel, no public ingress, no change to the Cloud→workspace proxy (stays dormant).
- The phone's loopback listener is reachable by any app on the phone for the window; this equals a desktop CLI's loopback exposure, and the OAuth `state` and PKCE verifier protect the exchange. The CLI's callback server must see the request unchanged, so the forward token authenticates only the control messages between workspace and phone; nothing is injected into the HTTP stream.
- Callback data crosses only WireGuard inside the account; Cloud sees only the login URL in the push payload (state and challenge, no codes or tokens). Push payloads are scheme-restricted and length-capped; `data:`, `file:`, `javascript:` stay rejected on both ends.
- New machine-token scopes are additive and per-workspace; `notify` can only target the owner's own devices; `netmesh_publish` can only act on the workspace's own node. Existing throttles apply. Revocation follows the existing revoke-on-rebootstrap path.
- The replay endpoint accepts only loopback targets and does not follow redirects.
- No secrets in tracked files; no local paths in docs or tests.

## Repos and ownership summary

| Step | cli | api (cloud MWW) | ios | android | skills | netmesh-go |
|---|---|---|---|---|---|---|
| 0 skill + BROWSER | entrypoint, docs | | | | new skill | |
| 1 tunneld forwards | tunneld, service cmd | | | | | |
| 2 push + open on phone | browser open, app-control | scopes, notify, serializers | push route, ack, local notif | push route, ack, notif | | |
| 3 paste-back | replay endpoint | | share ext, composer | share target, composer | | |
| 4 Android forwarder | | | | VpnService forwarder | | |
| 5 iOS spike + forwarder | | | extension listener, IPC | | | (none expected) |
| 6 publish parity | provider, routes, tunneld 443/80 | publish scopes | | | | |

## Out of scope

Mac-host enablement of the phone forwarder (helper rule change), Openbase Direct mode on phones (browsers cannot use the embedded node by design), Windows/Linux desktop hosts, waking a sleeping workspace from a browser hit, and any redirect-URI rewriting through Cloud.

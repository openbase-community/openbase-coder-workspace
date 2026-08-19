# Inbound VoIP Calls

## Status (updated 2026-08-19)

Implementation and automated validation are complete on `develop`. This
feature is not release-ready until the composed Cloud/CLI revisions are
deployed, production APNs configuration is verified, and the signed
physical-iPhone matrix passes.

## Product boundary

`openbase-coder user call <agent-name>` is an explicit urgent escalation. It
rings the signed-in user's registered iPhones, and an answered call joins the
same LiveKit voice runtime used by an outbound call. Failed `user say` remains
an ordinary alert notification and never escalates itself to a ring.

An inbound call targets the named agent's existing thread when that assignment
can be resolved locally. The user falls back to the dispatcher if post-connect
route activation fails; the call must not silently join an arbitrary thread.

## Trust and data flow

1. The authenticated local API resolves the exact agent name to a thread,
   creates a random 32-byte invitation capability, and persists a pending,
   owner-only record before contacting Cloud.
2. The CLI asks Openbase Cloud to ring the same authenticated user's registered
   PushKit devices. Cloud accepts the 43-character URL-safe invitation ID,
   applies its own expiry of at most 60 seconds, rate-limits rings, and queues a
   VoIP push.
3. The VoIP push contains only the invitation version, opaque ID, display name,
   and expiry. It never contains a LiveKit credential, room, URL, local path,
   thread ID, or agent-routing detail.
4. iOS validates the payload and immediately reports it to CallKit. If the user
   answers, iOS exchanges the capability with the currently configured local
   runtime over its existing authenticated API.
5. The local runtime atomically validates account ownership, status, and expiry,
   then mints a normal short-lived LiveKit participant token for its stored room.
   After the room connects, iOS asks that same runtime to activate the stored
   target route. The target never crosses APNs or Cloud.
6. Decline, expiry, and successful activation close the local invitation state.
   Replayed pushes are suppressed on-device, while an authenticated answer
   exchange may be retried idempotently to recover a lost HTTP response.

APNs provider authentication protects the PushKit transport. The opaque
capability is additionally useful only to the authenticated Cloud user against
the same authenticated local runtime; possession alone does not mint a token.

## Cloud API

All routes use the app's AllAuth bearer JWT and reject unknown fields.

### PushKit device registration

`PUT /api/openbase/voice/voip-token/`

```json
{
  "device_id": "8f41a8c1-4ce9-4c2d-a38b-78b57ab020ba",
  "token": "64-lowercase-hex-characters",
  "environment": "sandbox"
}
```

`environment` is `sandbox` or `production`. Tokens are separate from ordinary
APNs alert tokens. Multiple devices per account are supported; token transfer
between accounts is atomic. `DELETE` accepts only `device_id` and removes that
user's registration.

### Ring invitation

`POST /api/openbase/voice/invitations/`

```json
{
  "invitation_id": "43_url_safe_characters_from_32_random_bytes",
  "caller_name": "Agent display name"
}
```

The response is HTTP 202 with the same `invitation_id`, Cloud's `expires_at`,
and `device_count`. Repeating the same user, ID, and name is idempotent and does
not ring twice. A changed or cross-account reuse conflicts. No registered
device is a clear client error rather than a false delivery claim.

Default ring rate is three per user per minute. HTTP 202 means queued, not
delivered.

## VoIP APNs contract

Headers:

- `apns-push-type: voip`
- `apns-topic: <iOS bundle identifier>.voip`
- `apns-priority: 10`
- `apns-expiration`: the invitation expiry

Payload:

```json
{
  "aps": {"content-available": 1},
  "openbase_voip_version": 1,
  "invitation_id": "43_url_safe_characters_from_32_random_bytes",
  "caller_name": "Agent display name",
  "expires_at": 1787170000
}
```

The stored device environment selects the sandbox or production APNs host.
Definitive APNs invalid-token responses may remove that registration; transient
provider failures are logged and retained for retry on a later explicit call.

## Local API and state

- `POST /api/user/call/` accepts only `agent_name` and optional `caller_name`.
  It resolves the named assignment, persists the invitation, requests the Cloud
  ring, and returns the invitation expiry/device count.
- `POST /api/livekit-room-token/` accepts either the existing outbound token
  request or only `inbound_invitation_id`. The inbound form validates and marks
  the stored invitation answered before minting a token for its fixed room.
- `POST /api/inbound-call/activate/` accepts the invitation ID and room name,
  retries briefly for the dispatched LiveKit agent, then transfers to the
  locally stored thread.
- `POST /api/inbound-call/decline/` accepts only the invitation ID and marks a
  still-pending invitation declined.

The state file is schema-versioned, atomically replaced, and mode 0600 under the
existing Openbase data directory. Stale records are pruned. It stores no Cloud,
APNs, or LiveKit secret.

## iOS behavior

- A dedicated PushKit registry and uploader are modern-app only. Registration
  waits for authenticated account identity, retries transient failures, tracks
  token rotation and account switching, and deregisters before logout.
- The app declares the `voip` background mode in addition to the existing APNs
  entitlement. Legacy iOS is unchanged.
- Strict parsing rejects unknown versions, malformed IDs/names, and unreasonable
  expiry windows. Duplicate invitation IDs are not reported twice.
- CallKit is reported before the PushKit completion handler returns. Answering
  performs the authenticated local exchange; declining records the outcome.
- Existing outbound call, mute, audio routing, reconnect, and room-token
  preparation semantics remain unchanged.

## Release gate

Unit/simulator tests are necessary but insufficient. A signed physical iPhone
must pass foreground, background, and terminated delivery; answer, decline,
missed/expired, duplicate, and offline-runtime cases; Bluetooth and speaker
routing; mute/unmute; target transfer; and ordinary outbound-call regression.
Cloud must have a `.voip` APNs topic/profile, matching production/sandbox
credentials, a running worker, and the composed API package deployed.

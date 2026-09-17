# Voice Lockdown

## Status (updated 2026-08-19)

Feature branch implementation for review. This design is not enabled by
default and must not be merged until its backend policy and physical-device
voice behavior have received dedicated security review.

## Purpose

Voice lockdown adds a knowledge-factor check to an approval that is already
pending. It does not unlock a thread, session, machine, or backend policy.

The safe phrase authorizes exactly one action for 30 seconds. The authorization
is bound to the backend, approval request, thread, turn, tool call, canonical
action digest, LiveKit room, and participant. Consumption is atomic and
one-use.

## Non-negotiable invariants

- Lockdown can be enabled only when every configured backend already uses a
  non-bypass approval policy and a non-dangerous sandbox.
- Lockdown never selects `approvalPolicy=never`, `danger-full-access`, Claude
  `bypassPermissions`, or an equivalent policy.
- Missing or corrupt authoritative state fails closed after configuration.
- The phrase is never stored as plaintext and is never returned by an HTTP,
  MCP, or library API.
- Phrase, verifier, capability material, and unredacted action data never enter
  audit output.
- Decline and cancel decisions never require the phrase.
- Callers cannot submit a capability or an action digest. Both are derived at
  trusted execution boundaries.

## Ownership boundary

Openbase Coder owns all product-specific behavior:

- macOS Keychain configuration and phrase verifier;
- setup, enable, disable, rotate, status, and audit commands;
- baseline preflight;
- approval challenge and one-use lease broker;
- LiveKit room and participant binding;
- transcript interception and user-facing status;
- authenticated local status/challenge API; and
- audit events.

Super Agents remains a standalone product. It provides optional generic
`ExecutionPolicyGuard` and `ApprovalAuthorizer` protocols and invokes them from
both its public Python clients and MCP-backed paths. Standalone defaults remain
backwards compatible. An embedder can require controls, in which case a missing
control denies execution.

## Phrase handling

Setup is available only from an interactive local terminal on macOS. All
authoritative configuration, including the salted memory-hard verifier and
audit key, is stored in Keychain. There is no file or environment fallback.

Normalization is versioned and deliberately conservative: Unicode NFKC,
case-folding, normalized apostrophes, collapsed whitespace, and removal of
terminal sentence punctuation. Only the complete final utterance matches.
Substring, prefix, suffix, fuzzy, semantic, phonetic, and partial matching are
not permitted.

A challenge must already be armed for a pending approval. While it is armed,
the raw STT provider is wrapped at the innermost boundary. Interim and final
candidate transcripts are consumed before scoring, diagnostic logging,
deduplication, chat history, proactive steering, or model input. Three failed
attempts cause a five-minute cooldown.

Phrase-only authorization proves knowledge, not speaker identity. It cannot
defend against an authorized room participant who records the phrase. If the
STT path cannot attribute a single participant, phrase verification remains
unavailable for that call. A future high-impact tier should add authenticated
device confirmation.

## Challenge and lease contract

The authenticated local API exposes:

- `GET /api/lockdown/` — non-secret health, baseline, and pending challenge
  metadata;
- `POST /api/lockdown/challenges/` — arm one current pending approval for the
  current room and participant; and
- `DELETE /api/lockdown/challenges/{id}/` — cancel a challenge.

There is intentionally no phrase-submission endpoint and no endpoint that
returns a verifier, salt, audit key, capability, or unredacted action.

The broker covers the original unredacted action with canonical compact JSON
and SHA-256 at the execution boundary. Display copies may be redacted, but the
authorization digest is not derived from those redactions. A successful exact
utterance creates a random internal capability valid for 30 seconds. An accept
decision succeeds only if the broker atomically consumes a capability whose
entire scope matches. Restart, logout, route transfer, call shutdown, phrase
rotation, disablement, cancellation, or expiry revokes it.

## Backend enforcement

The Openbase-managed Super Agents clients always inject required controls.
Policy validation occurs for thread starts, turn starts, queueing, queue drain,
and routines. Codex accept decisions are authorized immediately before their
response is sent to app-server. Claude tool decisions are authorized
immediately before `PermissionResultAllow` is returned to the SDK.

This protects supported Openbase MCP and direct-Python entry points. It does
not claim to stop an attacker with arbitrary local-user code execution from
opening an unmanaged raw app-server connection.

## Audit

The local broker uses an owner-only SQLite database for challenges and
append-only audit events. Each audit event is chained with an HMAC whose key is
in Keychain. Events contain hashes of identifiers, the action digest, policy
decision, timestamps, and reason codes. They do not contain transcript text,
the phrase, verifier input, capability material, or raw tool arguments.

The HMAC chain detects modification but cannot prevent deletion or rollback by
the local user or root; it must not be described as tamper-proof.

## Required validation before merge

- Unit and property tests for exact normalization, attempt limits, expiry,
  atomic one-use consumption, every scope mismatch, and restart revocation.
- MCP/direct parity tests for Codex and Claude, including queued and routine
  execution.
- Transcript-leakage tests with verbose diagnostics enabled.
- Auth tests proving every API is authenticated and returns no secret fields.
- Real backend canaries proving Codex read-only mutation and Claude tools reach
  the guarded approval boundary.
- A physical-device LiveKit test proving room/participant attribution and that
  the phrase is absent from logs, history, and model input.
- Secret scanning and dependency/security scanning of every changed repository.

# VocalBridge Voice Dispatch

An alternative, settings-toggleable way for Openbase Coder calls to reach a
dispatcher. Instead of the local LiveKit stack, calls connect to a hosted
[VocalBridge](https://vocalbridgeai.com) voice agent, which handles all
speech (STT, TTS, greetings, turn-taking) and delegates dispatch questions
back to the user's machine, where a deliberately restricted dispatcher agent
answers them. The vanilla local LiveKit behavior remains the default and can
be switched back at any time.

## Provider selection

- Setting: `voice_dispatch_provider` in `~/.openbase/dispatcher-config.json`
  — `livekit` (default) or `vocalbridge`
  (`cli/openbase_coder_cli/dispatcher_config.py`).
- Settings API: `GET/PUT /api/settings/voice-dispatch/`
  (`cli/openbase_coder_cli/openbase_coder_cli_app/voice_dispatch_settings.py`).
  PUT accepts `provider`, `vocalbridge_api_key`, `vocalbridge_agent_id`,
  `vocalbridge_api_url`. Credentials are stored in the Openbase env file as
  `VOCAL_BRIDGE_API_KEY` / `VOCAL_BRIDGE_AGENT_ID` / `VOCAL_BRIDGE_API_URL`
  and are never echoed back (the payload only reports
  `api_key_configured`). Switching to `vocalbridge` requires a configured
  API key.
- Console UI: "Voice dispatch" section on the settings page
  (`coder-react/src/pages/settings/VoiceDispatchSettings.tsx`).

## Call flow (vocalbridge mode)

1. A client requests `POST /api/livekit-room-token/` exactly as before.
2. The CLI mints two VocalBridge tokens via `POST {api_url}/api/v1/token`
   (`X-API-Key`, optional `X-Agent-Id`) sharing one generated `session_id`
   so both participants land in the same room: one for the caller and one
   for a local responder participant named "Openbase Coder".
3. The endpoint returns `{token, room_name, url, provider: "vocalbridge"}`.
   `url` is the VocalBridge LiveKit server; clients must connect there and
   use the server-assigned `room_name`. In `livekit` mode the response stays
   `{token, room_name, provider: "livekit"}` with no `url`, because local
   clients derive the LiveKit URL from the backend host they reached.
4. The CLI starts a `VocalBridgeResponder`
   (`cli/openbase_coder_cli/vocalbridge/responder.py`) in a background
   thread. It joins the room, acks `heartbeat` actions, and answers
   VocalBridge `query_agent` data-channel actions
   (`{query, turn_id}` on topic `client_actions`) with `agent_response`
   (`{response, turn_id}`), per VocalBridge's AI Agents protocol.
5. Each query runs one turn on the VocalBridge dispatcher agent. VocalBridge
   stops waiting after ~60s, so the responder replies with a holding message
   at 50s while the turn continues; a follow-up query picks up the result.

## The restricted dispatcher agent

`cli/openbase_coder_cli/vocalbridge/dispatcher_agent.py` builds a
`SuperAgentsLiveKitClient` with:

- label `vocalbridge-dispatcher`, persistent thread state in
  `~/.openbase/vocalbridge-dispatcher.json` (separate from the main
  dispatcher's thread),
- sandbox `read-only` — it can coordinate Super Agents over MCP and explore
  the file system, but cannot edit files or run state-changing commands,
- builtin instructions (overridable at
  `~/.openbase/instructions/VOCALBRIDGE_DISPATCHER_INSTRUCTIONS.md`) that
  scope it to dispatch-only behavior with short, speakable replies.

## Client contract

Clients should prefer the token response's `url` and `room_name` when
present and fall back to their configured LiveKit URL and client-generated
room name otherwise. iOS implements this via `CallTokenResponse` and the
backward-compatible `CallTokenProvider.fetchCallToken` default
(`ios/Openbase/AgentUI/Protocols/CallTokenProvider.swift`).

## Out of scope / follow-ups

- Android does not yet honor the server-provided `url`/`room_name`.
- Voice routing (transfer-to-agent/thread) is a local-LiveKit concept and is
  not available in vocalbridge mode; the dispatcher reports thread status
  instead of transferring the call.
- No Openbase Cloud changes are required: the CLI talks to VocalBridge
  directly, and the Openbase Cloud audio subscription check is intentionally
  skipped in vocalbridge mode because VocalBridge hosts the audio pipeline.

## Per-repo work items

- `cli`: config accessor, `vocalbridge/` module (credentials, token minting,
  responder, restricted agent), token endpoint branch, settings endpoint,
  tests.
- `coder-react`: settings section + API types (used by console and desktop).
- `ios`: token response overrides (URL/room name).
- `android` (future): same token response overrides as iOS.

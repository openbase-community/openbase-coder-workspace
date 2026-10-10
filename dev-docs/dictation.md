# Dictation: composer voice notes through Openbase STT

Status: **implemented 2026-10-09**, with selected-backend BYOK preparation added 2026-10-10. The microphone button in the iOS and Android chat composers streams the user's speech to the Openbase speech-to-text service and merges the transcript into the message box. There is no on-device recognizer and no fallback (Gabe, 2026-10-09: the dictation button must go to the Openbase STT system, never the phone's local dictation); when the service is unreachable the composer shows an error instead. The console and desktop composers have no dictation button today.

## The service

Before either native recorder opens a microphone or streaming socket, it sends an owner-authenticated `POST /api/dictation/session/` to a snapshot of the selected coding backend URL. The backend reads `selected_stt_provider_id()` independently of GPT-Live versus Classic call-engine selection. Switching backends during preparation invalidates the response. The API ignores caller-supplied provider/key/URL fields and uses the local API's normal installation-owner authorization; another Cloud identity cannot mint a capability from this backend.

For `openbase_cloud`, the API returns `{"provider":"openbase_cloud"}`. The phone then opens the existing Cloud audio proxy with its Openbase account JWT in the Authorization header. Sessions use the user's Openbase audio credits and Cloud concurrency limits.

For `assemblyai`, the backend reads its configured `ASSEMBLY_AI_API_KEY` (the current canonical environment file takes precedence over a stale process value) and calls `GET https://streaming.assemblyai.com/v3/token` with that key in a header. It requests `expires_in_seconds=60` and `max_session_duration_seconds=300`; the API returns only `{"provider":"assemblyai","token":"<temporary capability>"}` with `Cache-Control: no-store`. The phone connects directly to `wss://streaming.assemblyai.com/v3/ws` using the temporary `token` query parameter and sends no Openbase JWT to AssemblyAI. The permanent provider key stays on the backend. Each recording prepares a fresh token, and tokens are never cached or logged. AssemblyAI temporary tokens are reusable within their redemption window, not single-use; the short window bounds that capability. See [AssemblyAI token API](https://www.assemblyai.com/docs/streaming/api-spec/generate-streaming-token).

Missing keys and unsupported STT providers (`deepgram`, `local_mlx_whisper`) return controlled `409` errors. AssemblyAI key/account rejection becomes `422 invalid_key`, never an Openbase `401` that could trigger login refresh. Transport failures, malformed provider replies and other upstream refusals become controlled `503 provider_unavailable` errors; raw provider bodies and credentials are never returned. Native clients fail closed on malformed/unknown selection, old backends without the endpoint, preparation cancellation, and unreachable backends. There is no automatic managed-Cloud fallback from BYOK and no phone recognizer fallback.

## The session contract

Both managed and BYOK dictation use the existing pinned AssemblyAI streaming options; managed dictation opens the same session the pipeline opens (`cli/openbase_coder_cli/livekit_agent/livekit.py`, `_build_stt`, provider `openbase_cloud`). The values are pinned in `cli/openbase_coder_cli/stt_providers.py` (`OPENBASE_CLOUD_STT_MODEL`, `OPENBASE_CLOUD_STT_SAMPLE_RATE`, `OPENBASE_CLOUD_STT_ENCODING`) and mirrored by `DictationSession` (iOS, `ios/Openbase/Shell/Dictation/`) and `DictationSession.kt` (Android, `voice/`). A cli test checks the pinned values against the LiveKit AssemblyAI plugin defaults, so a plugin upgrade that moves them is a deliberate contract change touching all three repos.

- Managed endpoint: `wss://<cloud>/api/openbase/audio/assemblyai/v3/ws` where `<cloud>` is the app's cloud base URL (`app.openbase.cloud`, or staging for staging builds).
- Query: `sample_rate=16000`, `encoding=pcm_s16le`, `speech_model=universal-3-6-pro`, `format_turns=true`, `min_turn_silence=100`, `max_turn_silence=100`, `language_detection=true` (the plugin's defaults for this model; no language codes, so language is detected as on calls).
- Managed auth: `Authorization: Bearer <jwt access token>` request header. The proxy strips any `token` query parameter before forwarding, but the apps keep the token out of URLs.
- Audio: binary frames of raw little-endian 16-bit mono PCM at 16 kHz, 50 ms (1600 bytes) each, converted on the phone from the microphone's native format.
- Server messages (JSON text): `Begin` (session open), `Turn` (`turn_order`, `transcript`, `end_of_turn`, `turn_is_formatted`), `Termination`. The transcript shown is every turn's latest text joined in turn order, so a formatted final replaces its unformatted preview and the current turn's partial trails the finished ones.
- Stop: the app sends `{"type":"Terminate"}`, waits briefly for the last `Turn`, then closes. Cancel closes at once.
- Managed proxy close codes: `4401` not signed in, `4403` no audio credits or too many concurrent sessions, `1011` provider unreachable. Each maps to a composer error. BYOK maps AssemblyAI `1008` authentication/account refusal and `3009` concurrency refusal to an AssemblyAI key/account message, without claiming Openbase credits are depleted or expiring Openbase login.

## Cost guards

A session is never left open without the user: dictation stops when the user taps stop or send, when the view goes away, when the app leaves the foreground, after ten seconds with no new speech, and after five minutes regardless. The limits live in `DictationLimits` on both platforms with unit tests.

# Dictation: composer voice notes through Openbase STT

Status: **implemented 2026-10-09** (`feature/dictation-stt`). The microphone button in the iOS and Android chat composers streams the user's speech to the Openbase speech-to-text service and merges the transcript into the message box. There is no on-device recognizer and no fallback (Gabe, 2026-10-09: the dictation button must go to the Openbase STT system, never the phone's local dictation); when the service is unreachable the composer shows an error instead. The console and desktop composers have no dictation button today.

## The service

Dictation uses exactly the speech-to-text the voice pipeline engine uses when its STT provider is Openbase Cloud: AssemblyAI streaming, reached through the Openbase Cloud audio proxy. The provider key lives only in Openbase Cloud; the phone authenticates with the signed-in user's allauth JWT access token, which the proxy accepts next to CLI machine tokens (`openbase_api/proxy_auth.py` in the cloud workspace). Sessions are billed per second of open socket against the user's audio credits, the same meter as pipeline calls, with the same per-user concurrent-session cap.

## The session contract

Both apps open the same session the pipeline opens (`cli/openbase_coder_cli/livekit_agent/livekit.py`, `_build_stt`, provider `openbase_cloud`). The values are pinned in `cli/openbase_coder_cli/stt_providers.py` (`OPENBASE_CLOUD_STT_MODEL`, `OPENBASE_CLOUD_STT_SAMPLE_RATE`, `OPENBASE_CLOUD_STT_ENCODING`) and mirrored by `DictationSession` (iOS, `ios/Openbase/Shell/Dictation/`) and `DictationSession.kt` (Android, `voice/`). A cli test checks the pinned values against the LiveKit AssemblyAI plugin defaults, so a plugin upgrade that moves them is a deliberate contract change touching all three repos.

- Endpoint: `wss://<cloud>/api/openbase/audio/assemblyai/v3/ws` where `<cloud>` is the app's cloud base URL (`app.openbase.cloud`, or staging for staging builds).
- Query: `sample_rate=16000`, `encoding=pcm_s16le`, `speech_model=universal-3-6-pro`, `format_turns=true`, `min_turn_silence=100`, `max_turn_silence=100`, `language_detection=true` (the plugin's defaults for this model; no language codes, so language is detected as on calls).
- Auth: `Authorization: Bearer <jwt access token>` request header. The proxy strips any `token` query parameter before forwarding, but the apps keep the token out of URLs.
- Audio: binary frames of raw little-endian 16-bit mono PCM at 16 kHz, 50 ms (1600 bytes) each, converted on the phone from the microphone's native format.
- Server messages (JSON text): `Begin` (session open), `Turn` (`turn_order`, `transcript`, `end_of_turn`, `turn_is_formatted`), `Termination`. The transcript shown is every turn's latest text joined in turn order, so a formatted final replaces its unformatted preview and the current turn's partial trails the finished ones.
- Stop: the app sends `{"type":"Terminate"}`, waits briefly for the last `Turn`, then closes. Cancel closes at once.
- Proxy close codes: `4401` not signed in, `4403` no audio credits or too many concurrent sessions, `1011` provider unreachable. Each maps to a composer error.

## Cost guards

A session is never left open without the user: dictation stops when the user taps stop or send, when the view goes away, when the app leaves the foreground, after ten seconds with no new speech, and after five minutes regardless. The limits live in `DictationLimits` on both platforms with unit tests.

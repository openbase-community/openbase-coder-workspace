# Live Voice: a full-duplex voice layer over Super Agents

Status: **implemented 2026-10-06** on the coder side (`feature/modern-voice`): dependency bump to livekit-agents 1.8.4, the live engine wiring in `livekit_agent/livekit.py`, the delegation bridge in `livekit_agent/live_delegation.py`, the pre-start checks and fail-soft fallback in `livekit_agent/live_voice.py`, tier-1 tests with a fake GPT-Live gateway. Proven with fakes only: no live GPT-Live session has been exercised yet (no gateway deployed, no key on the dev machine), so the tier-3 field test is still owed. Design deltas against the original spec are called out inline as **Delta (implemented)**. Companion spec: the Openbase Cloud side is `api/docs/live-voice-gateway.md` in `openbase-cloud-workspace` (MWW `live-voice-gateway`). This document owns the coder-workspace side: the LiveKit agent, the CLI settings, and the phone/desktop client changes.

## Problem

Voice calls feel slow. The current LiveKit agent (`cli/openbase_coder_cli/livekit_agent/livekit.py`) is a half-duplex pipeline: AssemblyAI STT → a Codex app-server thread acting as the "LLM" (`CodexLiveKitLLM`) → Cartesia TTS, with a turn detector in front and `preemptive_generation=False`. Every spoken turn waits for a full Super Agent turn (reasoning, tool calls, skills) before the first syllable of TTS can start, and the phone mutes its microphone while the agent speaks (`voice_delivery.py`, `CallManager+AutoMute.swift`). STT and TTS are not the bottleneck; the agent turn is, and nothing talks while it runs.

Swapping the STT or TTS vendor cannot fix this. The voice layer has to keep the conversation going while the agent works.

## Goals

- Snappy, natural voice: the user hears an acknowledgement within a few hundred milliseconds, can talk over the agent, and gets results as they arrive instead of after the whole turn.
- Talk to **any** agent: the dispatcher is just the persistent agent that is always there; any Super Agent thread can be the one on the call, exactly as today's voice route and the direct voice mode already allow.
- MCP and skills keep working unchanged, because they live in the Super Agent thread, not in the voice model.
- One account: a user needs only an Openbase account. No OpenAI key is ever required, and none ever lives on a user's device: GPT-Live is always reached through the Openbase Cloud gateway (product decision 2026-10-06; the earlier bring-your-own-key option was dropped).
- LiveKit stays the transport. Phones and desktop keep joining the same private LiveKit room; the agent process keeps running on the user's Mac or DevSpace.

## Non-goals

- Replacing Super Agents, the dispatcher skill, or thread routing semantics.
- Dropping the current pipeline. It stays as the `pipeline` engine for local-only installs (Kokoro TTS, MLX Whisper) and as the fallback.
- Video, screen-share narration, or telephony changes.

## Model choice

Researched 2026-10-05 against official pricing pages and the Artificial Analysis speech-to-speech leaderboard. The requirement that the voice layer keeps talking while an external agent works rules out every model that blocks on tool calls.

| Model | Price | Talks while backend works | Where tools live | LiveKit plugin |
| --- | --- | --- | --- | --- |
| **OpenAI GPT-Live-1** (chosen) | $0.05 per session-minute flat, billed per second; backend billed separately | Yes, by design: full duplex plus *client delegation* | In the backend agent (ours) | `openai.realtime.GPTLiveModel`, `livekit-agents[openai]>=1.8` |
| Gemini 3.8 Live (fallback engine) | $3 in / $12 out per 1M audio tokens (≈$0.005 + $0.018 per minute) | Yes: `NON_BLOCKING` function calls, narrates background work | LiveKit function tools / `MCPToolset` | `google` plugin, 3.8 supported |
| gpt-realtime-2.1 | $32 / $64 per 1M audio tokens | No, blocks on tool results | Native remote MCP | `openai` |
| Grok Voice Think Fast 2.0 | $0.08 per minute | No | Function tools | `spacexai` |
| Nova 2 Sonic, Ultravox, Phonic, PersonaPlex | $0.05–0.14 per minute or self-host | No | Function tools or none | various |

Anthropic has no realtime audio API, so Claude can only ever be the brain behind a voice front-end; that is exactly the role Super Agent threads play here.

GPT-Live-1 facts that shape this design (OpenAI docs, LiveKit plugin source `gpt_live_model.py`):

- A session is one WebSocket to `{base_url}/live/sessions` with `Authorization: Bearer <key>`. The plugin takes `base_url` and `api_key` constructor arguments, so an Openbase gateway is a drop-in.
- `model`, `voice`, startup `instructions`, startup history, and `delegation.type` are fixed at session start. The LiveKit plugin accepts up to 128 startup-history messages / 8192 rendered startup-history tokens, and each `append_*` call is capped at 500 tokens. Appended instructions add developer guidance for the rest of the session; they do not replace the startup persona.
- Under `delegation: {type: "client"}` the model emits `session.delegation.created` (id, `offset_ms`, **no utterance text**); the plugin attaches `pending_transcript` from the input transcript it has seen. We answer with `session.commentary.append` (spoken), `session.thinking.append` (silent context) or `session.instructions.append`, each ≤500 tokens, tagged with the `delegation_id`, as many times as we like. `delegation_id: null` steers the whole session.
- Input and output transcripts arrive as timed `*.transcript.delta` events. `session.usage.updated` reports cumulative seconds about once a minute; `session.closed` carries final usage.
- Barge-in is model-controlled: it listens while speaking and decides when to stop. The plugin can cut playback with VAD, but the model's context still holds the whole turn.
- In client-delegation mode the LiveKit plugin has no tool channel and ignores `@function_tool` methods. That is fine: tools belong to the thread.
- Audio is 24 kHz PCM16 mono over the socket; the plugin handles resampling to the LiveKit room.

## Architecture

```
phone / desktop ── LiveKit room ── livekit-agent (user's Mac or DevSpace)
                                     │
                                     ├─ AgentSession(llm=GPTLiveModel(delegation="client",
                                     │        base_url=<Openbase Cloud gateway>,
                                     │        api_key=<Openbase machine token>))
                                     │        │ wss  (voice only, $0.05/min)
                                     │        ▼
                                     │   Openbase Cloud live-voice gateway ──▶ OpenAI GPT-Live
                                     │
                                     └─ LiveDelegationBridge
                                          delegation_created ─▶ LiveKitVoiceRouter.active_client
                                                               (dispatcher / direct / transferred thread)
                                                               .run_turn(prompt) ──▶ Super Agent thread
                                                                                     (Codex or Claude Code,
                                                                                      MCP + skills as today)
                                          progress/final speech ◀─ callback, polling, or completed turn
                                          append_thinking / append_commentary(delegation_id)
```

Nothing changes for the room, the mobile signalling, the announcer data packets, inbound calls, or the thread model. The change is confined to what the `AgentSession` is built from and how thread output reaches the user.

### Voice engines

**Delta (implemented):** the engine is not a separate `voice_engine` setting; it follows from the selectable **voice model** (`voice_models.py`, `dispatcher_config.selected_voice_model_id()` / `selected_voice_engine()`), picked like the agent model: `gpt-live-1` (default) selects the `live` engine, `pipeline` selects the classic STT → thread → TTS path. Exposed as the `voice_model` key of `dispatcher-config.json`, `GET/PUT /api/settings/voice-model/`, `openbase-coder defaults voice-model`, and the voice settings pickers. It is orthogonal to `voice_mode` (`dispatcher` | `direct`) and to the STT/TTS provider settings, which only apply to the pipeline engine. The LiveKit agent reads it per call (`selected_voice_engine()` inside the job), so no restart is needed.

**Delta (implemented):** there is no `live_voice_provider` setting. GPT-Live always runs through the Openbase Cloud live voice gateway: `base_url` = `{WEB_BACKEND_URL}/api/openbase/live/openai/v1` (`OPENBASE_CLOUD_LIVE_BASE_URL` overrides it for staging or a locally running cloud API, mirroring `OPENBASE_CLOUD_AUDIO_BASE_URL`), `api_key` = the installation's Cloud machine token, exactly the token the Cloud STT/TTS proxies use (`_openbase_cloud_audio_token()`). The agent never reads `OPENAI_API_KEY`. Entitlement is checked before the session starts through `ensure_openbase_cloud_audio_subscription(..., live_voice=True)`, which adds the Cloud provider `live_voice` and reads `live_voice_limit_cents` / `live_voice_remaining_cents` from the audio usage summary. The model slug and the voice are constants (`LIVE_VOICE_MODEL = "gpt-live-1"`, `LIVE_VOICE_DEFAULT_VOICE = "marin"`, env-overridable) in `livekit_agent/config.py`.

Gemini 3.8 Live stays a documented fallback engine (see below). It is not part of phase 1.

### Fail-soft: live falls back to the pipeline for the call

GPT-Live is the default voice model, but the gateway may not be deployed yet when an install updates, and an install may have no Cloud login. The live engine therefore **fails soft**: `livekit_agent/live_voice.py::decide_voice_engine` runs before the `AgentSession` starts (concurrently with the room connect) and, when any prerequisite is missing, the call runs on the pipeline engine with the user's configured STT/TTS providers instead of ending. One warning is logged with the reason, clients receive a **non-fatal** agent status packet `code = live_voice_unavailable` (payload adds `severity: "warning"`; `type` stays `agent_error` so old clients still render the `detail`), and the participant attribute `openbase.voice.engine` reads `pipeline` so clients keep today's auto-mute. Triggers: no Cloud login or machine token (`login_required`); the entitlement check does not know the provider because the gateway is not deployed (`cloud_live_voice_unknown`: the usage summary has no `live_voice_*` fields) or live credits are exhausted (`subscription_required`); the pre-start websocket handshake probe of `{base_url}/live/sessions` fails (`gateway_unreachable`, `gateway_http_401|403|404` → `gateway_not_deployed` for 404, or an immediate close `gateway_close_4401|4403`); the GPT-Live plugin cannot be imported (`plugin_import_failed`); or `AgentSession.start` itself raises (`live_session_start_failed`). The probe opens the websocket with the real bearer and closes without sending `session.start`, so nothing is billed. Only when the pipeline fallback also cannot start do the existing fatal codes (`login_required`, `subscription_required`, `cloud_unavailable`, `agent_start_failed`) apply. An unrecoverable GPT-Live error after the call started ends the call with the new fatal code `live_voice_provider_failed`.

### The delegation bridge

`livekit_agent/live_delegation.py`, class `LiveDelegationBridge`, subscribes to the `GPTLiveSession` events and owns the mapping between delegations and Super Agent turns. It reuses `LiveKitVoiceRouter` unchanged for *which* thread is on the call.

1. `delegation_created(delegation)`:
   - Build the prompt from `delegation.pending_transcript` plus any input transcript deltas accumulated since the previous delegation that the plugin did not include (the bridge keeps its own transcript ring buffer from `session.input_transcript.delta`, because OpenAI's own event carries no text).
   - Wrap with `wrap_voice_prompt` (the `<voice>` tag the `responding-to-voice-tag` skill keys on) so threads still know the text was spoken and the reply will be spoken.
   - Call `voice_router.active_client.run_turn(prompt, developer_instructions=…)` with the same dispatcher/direct instructions as today. `run_turn` already steers an in-flight turn when the user speaks again; the bridge relies on that instead of cancelling.
   - Immediately `append_thinking("Working on it: <short restatement>", delegation_id)` so the voice model knows the request was taken and can acknowledge naturally instead of guessing.
2. **Delta (implemented):** `SuperAgentsLiveKitClient` gained `add_turn_progress_listener(listener)`; the turn wait loop (`_poll_turn_until_ready`) calls `listener(client, turn_id, progress)` for every snapshot it fetches. The bridge runs each snapshot through `_speech_text_from_progress` (same useful-text and cached-message rules as the pipeline, raw backend errors skipped) and a per-turn `LiveSpeechCursor` that speaks only sentences not spoken yet, holding back an unfinished trailing sentence until the final answer, so nothing is said twice and stale cached text is never spoken. The final `_livekit_speech_text` goes through the same cursor. While a turn runs, a quiet `append_thinking` heartbeat every 20 s tells the model work is still in progress.
3. Spoken chunks are sentence-bounded and ≤500 tokens (`chunk_commentary`, conservative 3.2 chars/token estimate since there is no tokenizer; one oversized sentence splits at word boundaries), using the same `speech_formatter.py` / `speech_replacements.py` rules as today. Progress-only output goes to `append_thinking`, never spoken. If the thread produced nothing speakable, `append_commentary("Done, nothing else to report.")` closes the delegation from the model's point of view; a duplicate utterance that joined an already-spoken turn gets only an `append_thinking`.
4. Turn errors become immediate `append_commentary(..., delegation_id)` ("deep in a long task" when `backend_appears_busy()`, otherwise "backend is not responding"). A pending approval seen in a progress snapshot is spoken once and retained as `append_instructions(..., delegation_id)` ("the agent's turn is paused on an approval; the caller can approve it from the Approvals tab").

Speech ownership: today the `backend_answer_ownership` / `claim_speech` logic prevents two threads talking over each other. In the live engine the single voice model is the only speaker, but the bridge still needs an ownership ledger: each delegation is bound to the route snapshot and backend turn that accepted it, stale progress from superseded routes is dropped before it becomes commentary, and final `_livekit_speech_text` is only appended once. **Implemented** as `LiveDelegationEntry` records: a newer delegation on the same client marks the older ones superseded (they never speak; `run_turn` steers the shared turn, so the newest delegation speaks the merged answer once), a result whose route snapshot no longer matches is dropped and its delivery record marked `suppressed_stale`, and `claim_speech(turn_id)` is called when the final commentary is appended so orphaned-result delivery does not repeat it.

Speculative start (phase 2): the OpenAI guidance is to start backend work on transcript fragments before the delegation arrives. The bridge can start the thread turn when the input transcript goes quiet for N ms, then bind it to the delegation when it arrives. Measured first; not in phase 1.

### Routing and talking to any agent

Unchanged primitives: `LiveKitVoiceRouter.transfer_to_thread`, `exit_to_dispatch`, `openbase-coder user transfer-to-agent`, voice-route data packets, direct voice mode. What the bridge adds:

- Phase 1 keeps one startup persona for the whole call (`LIVE_VOICE_STARTUP_INSTRUCTIONS` in `livekit_agent/config.py`: the Openbase voice relay for the currently active agent). On a route change, the bridge appends session context (`append_thinking` plus a short `append_commentary` handoff, "You are now talking to <agent>." / "Back to dispatch.") with the active agent label and a compact summary of the route's developer instructions. It must not rely on `append_instructions` to replace the startup persona; LiveKit's GPT-Live handoff docs require a new session when voice, instructions, or chat context truly change.
- Spoken commands (`spoken_commands.py`: "exit to dispatch") are detected on the input transcript stream (final `user_input_transcribed` events from the duplex adapter) instead of on STT finals; when the model then delegates the same utterance it is answered with the "Back to dispatch." receipt, never sent to a thread. **Delta (implemented):** `session_diagnostics` proactive steering and dropped-utterance recovery are disabled in live mode (`proactive_steering=False`): the bridge owns every thread submission, and `generate_reply` on a duplex model would make it speak.
- Per-agent voices: today each Super Agent has a stable Cartesia voice (`livekit_voice_route.py`). GPT-Live fixes the voice at session start, so phase 1 uses **one voice per call** and names the agent in speech. Phase 2 evaluates recycling the GPT-Live session on transfer, as LiveKit's GPT-Live handoff path does for changed instructions or chat context, against the cost of a short gap and resending bounded startup history.

### Announcer, `user say`, inbound calls

`openbase-coder user say AGENT MESSAGE` and Super Agent completion notices currently synthesise TTS through the announcer. In the live engine they become `append_commentary(f"{agent}: {message}", delegation_id=None)`, which the model weaves into the conversation instead of cutting in. **Delta (implemented):** the announcer packet now carries `agent_name` (additive; `publish_announcer_message(agent_name=...)`, parsed into `AnnouncerMessage.agent_name`) so the live engine can name the agent; the pipeline keeps choosing a voice by `voice_id` and ignores it. Audio-file announcements (`kind: audio_file`) still play through the `AnnouncerSpeechQueue` (constructed without a TTS in live mode). The phone-alert fallback when no room is active is unchanged. Inbound calls (`inbound_calls.py`) only change in that the agent they ring into may be live-engine.

### Phone and desktop clients

Full duplex needs the microphone open while the agent speaks. Today's clients mute on `agent_audio_started` and unmute on `safe_to_unmute` (`CallManager+AutoMute.swift`, Android `VoiceLifecycleMuteAction`). Required change, small and additive:

- The agent publishes a participant attribute `openbase.voice.engine = live|pipeline` on join. Clients that see `live` disable the lifecycle auto-mute and leave the mic on; acoustic echo cancellation is already provided by the WebRTC stack on iOS/Android/Electron and by the LiveKit noise-cancellation plugin on the agent side. Clients that do not understand the attribute keep today's behaviour and still work, just half duplex.
- Voice lifecycle packets stay, but live mode must create synthetic delivery records because there is no STT → TTS `VoiceDeliveryRecord` path. The bridge emits `utterance_accepted` on `delegation_created` (`accept_utterance(message_id="live-<delegation id>")`), emits `agent_audio_started` / `agent_audio_finished` from the agent session's `agent_state_changed` speaking transitions (`VoiceDeliveryLedger.mark_live_audio_started/finished`, with `track_live_speech()` for model speech no delegation asked for), and never emits `safe_to_mute_user`, `safe_to_unmute` or `mute_keepalive` in live mode: the ledger is constructed with `live_mode=True`, which hard-blocks those events whatever path asks for them. Diagnostics and the delivery ledger keep working without a transport change.
- The Call tab shows the live-engine badge and the current speaking agent as today.

### Dependencies and runtime

- **Done:** `livekit-agents[silero,turn-detector]` 1.5.17 → 1.8.4, `livekit-plugins-assemblyai/cartesia/deepgram` 1.8.4, `livekit-plugins-openai` 1.8.4 (`openai` 2.44 → 2.54). Pipeline fixes for 1.8: the deprecated `AgentSession(preemptive_generation=)` kwarg moved into `turn_handling` (same semantics); `ProcPool` gained a `simulation_end_fnc` constructor argument (test only). Both monkey patches were re-verified against the 1.8.4 source and kept: `proc_pool_patch.py` still applies (upstream issue 3841 is open; the version gate now lists 1.8.4) and `vad_backlog_patch.py` applies unchanged. The live engine passes the Silero VAD explicitly (the session drops its default VAD for a duplex model) with `turn_handling={"interruption": {"mode": "vad"}}` so LiveKit cuts playout on barge-in; the model owns turn-taking. `livekit.plugins.turn_detector` is deprecated in 1.8 in favour of `livekit.agents.inference.TurnDetector`; the pipeline keeps the plugin for now (warning only).
- The pinned `livekit-server` (`livekit_version.py`, 1.13.7) is unaffected.
- The agent process already runs under the `livekit-agent` service; no new service. Memory: the GPT-Live plugin replaces the STT and TTS plugin processes, so footprint should drop (see `openbase-memory-footprint-fixes` in memory for how it is measured).

### Cost

Live engine: $0.05 per minute of **session** (silence included), roughly $3 per hour of call, through the gateway at the metered rate it sets. Today's pipeline through Openbase Cloud costs about $0.0025/min AssemblyAI plus Cartesia at the metered 100 millicents per second of generated speech (≈$0.06 per minute the agent is talking). For a typical call where the agent talks a third of the time these are within a factor of two of each other. Agent token cost is unchanged and dominates either way.

### Fallback engine: Gemini 3.8 Live

Kept as a documented alternative, not built in phase 1. Shape: `google` plugin's realtime model with LiveKit function tools; a single `delegate_to_agent(text)` tool marked `NON_BLOCKING` routes to `active_client.run_turn` and returns the result as the tool response, while the model narrates. Cheaper (≈$0.02/min blended) and smart enough to answer small talk itself, but proactive audio bills while listening, MCP goes through LiveKit's toolset, and the plugin lacks some 3.8 knobs. Worth a spike if GPT-Live's one-voice-per-session limitation or its price becomes a problem.

## Phases

0. **Spike (dispatcher only).** Originally a bring-your-own-key spike; superseded by the decision that the key never lives on a device. The measurement goal stands and moves to phase 1 against the staging gateway: time-to-first-audio and perceived latency on a real phone against the pipeline. Go/no-go.
1. **Gateway + Openbase Cloud provider.** Cloud MWW `live-voice-gateway` lands; the CLI side (this branch) has the entitlement check, agent status codes (`live_voice_unavailable`, `live_voice_provider_failed`), settings surface, the fail-soft fallback, transfers and direct mode with one voice per call, publishes `openbase.voice.engine`, and the phone/desktop clients keep the mic open when that attribute is `live`. Still owed: tier-3 field test against a deployed gateway.
2. **Polish.** Speculative start, per-agent voice via session recycle on transfer, and deeper spoken-command parity.
3. **Default flip.** `voice_model` defaults to `gpt-live-1`; `pipeline` remains selectable for local-only installs and as a per-call fallback when the gateway is missing or returns `subscription_required`.

## Testing

- Tier 1 (**implemented**): `cli/tests/test_live_delegation.py` drives `LiveDelegationBridge` with a fake `GPTLiveSession` (chunking at 500 tokens, delegation ↔ turn binding, overlapping delegations, route-change handoff, errors, announcer, lifecycle emission and the never-mute rule); `cli/tests/test_live_voice.py` runs a fake GPT-Live gateway on loopback (`session.start` / `session.started` / transcript delta / `session.delegation.created` / `*.appended`) against the preflight probe and against the real `GPTLiveModel` plugin session with the bridge attached, plus Cloud entitlement with `live_voice_*` fields and every fallback trigger; `cli/tests/test_livekit_live_engine_wiring.py` covers engine selection in the agent entrypoint, attribute publication, the fallback packet and the untouched pipeline path. Settings API tests live with the voice model settings.
- Tier 2: a scripted E2E spec only once a field test finds a bug worth freezing (`dev-docs/testing-tiers.md`).
- Tier 3: field test on a physical phone through the real gateway with a field-test account; the acoustic loop is the point, so no mocks.

## Open questions for Gabe

1. Confirm GPT-Live-1 as the phase-1 engine (Gemini 3.8 Live stays a documented fallback). Resolved 2026-10-06: no OpenAI key on any device; the gateway is the only path.
2. One voice per call in phase 1 (agents named in speech) versus session recycle per transfer from the start.
3. Should `pipeline` remain selectable forever (local-only installs need it), or be hidden once `live` is default?
4. Which GPT-Live voice is the Openbase default, and do we want to use one of OpenAI's twelve for the dispatcher and a different one for direct mode.

## References

- OpenAI: GPT-Live getting started, delegation and tools, session management, pricing (`developers.openai.com/api/docs/guides/live*`, `/pricing`).
- LiveKit: GPT-Live plugin guide and `gpt_live_model.py` in `livekit/agents` (`livekit-plugins-openai`).
- This workspace: `cli/docs/voice-routing.md`, `dev-docs/GLOSSARY.md` (Dispatcher, Voice route, Voice lifecycle packet), `feature/direct-voice-mode`.

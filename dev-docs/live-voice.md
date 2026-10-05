# Live Voice: a full-duplex voice layer over Super Agents

Status: **spec, not implemented** (2026-10-05). Companion spec: the Openbase Cloud side is `api/docs/live-voice-gateway.md` in `openbase-cloud-workspace` (MWW `live-voice-gateway`). This document owns the coder-workspace side: the LiveKit agent, the CLI settings, and the phone/desktop client changes.

## Problem

Voice calls feel slow. The current LiveKit agent (`cli/openbase_coder_cli/livekit_agent/livekit.py`) is a half-duplex pipeline: AssemblyAI STT → a Codex app-server thread acting as the "LLM" (`CodexLiveKitLLM`) → Cartesia TTS, with a turn detector in front and `preemptive_generation=False`. Every spoken turn waits for a full Super Agent turn (reasoning, tool calls, skills) before the first syllable of TTS can start, and the phone mutes its microphone while the agent speaks (`voice_delivery.py`, `CallManager+AutoMute.swift`). STT and TTS are not the bottleneck; the agent turn is, and nothing talks while it runs.

Swapping the STT or TTS vendor cannot fix this. The voice layer has to keep the conversation going while the agent works.

## Goals

- Snappy, natural voice: the user hears an acknowledgement within a few hundred milliseconds, can talk over the agent, and gets results as they arrive instead of after the whole turn.
- Talk to **any** agent: the dispatcher is just the persistent agent that is always there; any Super Agent thread can be the one on the call, exactly as today's voice route and the direct voice mode already allow.
- MCP and skills keep working unchanged, because they live in the Super Agent thread, not in the voice model.
- One account: a user needs only an Openbase account. No OpenAI key is ever required (bring-your-own key stays an option, like the existing direct Cartesia/AssemblyAI keys).
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
                                     │        base_url=<gateway or api.openai.com>,
                                     │        api_key=<Openbase token or user's key>))
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

A new per-installation setting `voice_engine` with two values:

- `pipeline` (today's STT → thread → TTS; default until the live engine has passed field tests and the gateway is deployed).
- `live` (GPT-Live full duplex with client delegation).

It is orthogonal to `voice_mode` (`dispatcher` | `direct`, from `feature/direct-voice-mode`) and to the STT/TTS provider settings, which only apply to the pipeline engine. Exposed like the existing voice settings: `dispatcher-config.json` key, `GET/PUT /api/settings/voice-engine/`, `openbase-coder defaults voice-engine`, and a picker in the desktop/console voice settings. Read per call by the LiveKit agent, so no restart is needed.

Live engine provider, `live_voice_provider`:

- `openbase_cloud` (default): `base_url` = `{WEB_BACKEND_URL}/api/openbase/live/openai/v1`, `api_key` = the installation's Cloud token, exactly as `openbase_cloud` STT/TTS use `OPENBASE_CLOUD_AUDIO_BASE_URL` and the machine token (`config/cloud_audio.py`). Entitlement is checked before the agent joins the room through the existing `ensure_openbase_cloud_audio_subscription` path, extended with the new provider so `subscription_required` / `login_required` agent status packets keep working.
- `openai`: the user's own key from the same provider-key settings surface that holds direct Cartesia/AssemblyAI keys; `base_url` left at OpenAI's default.

Gemini 3.8 Live is reserved as `live_voice_provider = gemini` for a later phase (see Fallback engine). It is not part of phase 1.

### The delegation bridge

`livekit_agent/live_delegation.py`, class `LiveDelegationBridge`, subscribes to the `GPTLiveSession` events and owns the mapping between delegations and Super Agent turns. It reuses `LiveKitVoiceRouter` unchanged for *which* thread is on the call.

1. `delegation_created(delegation)`:
   - Build the prompt from `delegation.pending_transcript` plus any input transcript deltas accumulated since the previous delegation that the plugin did not include (the bridge keeps its own transcript ring buffer from `session.input_transcript.delta`, because OpenAI's own event carries no text).
   - Wrap with `wrap_voice_prompt` (the `<voice>` tag the `responding-to-voice-tag` skill keys on) so threads still know the text was spoken and the reply will be spoken.
   - Call `voice_router.active_client.run_turn(prompt, developer_instructions=…)` with the same dispatcher/direct instructions as today. `run_turn` already steers an in-flight turn when the user speaks again; the bridge relies on that instead of cancelling.
   - Immediately `append_thinking("Working on it: <short restatement>", delegation_id)` so the voice model knows the request was taken and can acknowledge naturally instead of guessing.
2. The existing `SuperAgentsLiveKitClient.run_turn` waits for the backend turn to finish and returns a final `_livekit_speech_text` plus the progress snapshot; it does not currently stream assistant deltas to callers. Phase 1 therefore must either add a progress callback / async event stream to `SuperAgentsLiveKitClient`, or start conservatively by sending `append_thinking` for acceptance/progress and one final `append_commentary` from `_livekit_speech_text`. If a polling adapter is used, it must reuse the same useful-text and duplicate-suppression semantics as `_speech_text_from_progress` so stale cached messages are never spoken.
3. Spoken chunks are sentence-bounded and ≤500 tokens, using the same `speech_formatter.py` / `speech_replacements.py` rules as today. Progress-only output (tool calls starting, "reading file X") goes to `append_thinking`, never spoken. If the thread produced nothing speakable, a short `append_commentary("Done.")`-style fallback is sent so the delegation is closed from the model's point of view.
4. Turn errors (`backend_appears_busy`, approval needed, thread gone) become immediate `append_commentary(..., delegation_id)` when the user should hear about them now, plus `append_instructions(..., delegation_id)` only for state the model should retain for the rest of that delegation (for example "the agent is waiting for an approval; offer to open it on the phone").

Speech ownership: today the `backend_answer_ownership` / `claim_speech` logic prevents two threads talking over each other. In the live engine the single voice model is the only speaker, but the bridge still needs an ownership ledger: each delegation is bound to the route snapshot and backend turn that accepted it, stale progress from superseded routes is dropped before it becomes commentary, and final `_livekit_speech_text` is only appended once.

Speculative start (phase 2): the OpenAI guidance is to start backend work on transcript fragments before the delegation arrives. The bridge can start the thread turn when the input transcript goes quiet for N ms, then bind it to the delegation when it arrives. Measured first; not in phase 1.

### Routing and talking to any agent

Unchanged primitives: `LiveKitVoiceRouter.transfer_to_thread`, `exit_to_dispatch`, `openbase-coder user transfer-to-agent`, voice-route data packets, direct voice mode. What the bridge adds:

- Phase 1 keeps one startup persona for the whole call: "the Openbase voice relay for the currently active agent." On a route change, the bridge appends session context (`append_thinking` plus a short `append_commentary` handoff) with the active agent label and a compact summary of the route's developer instructions. It must not rely on `append_instructions` to replace the startup persona; LiveKit's GPT-Live handoff docs require a new session when voice, instructions, or chat context truly change.
- Spoken commands (`spoken_commands.py`: "exit to dispatch", "transfer me to Lucy") are detected on the input transcript stream instead of on STT finals.
- Per-agent voices: today each Super Agent has a stable Cartesia voice (`livekit_voice_route.py`). GPT-Live fixes the voice at session start, so phase 1 uses **one voice per call** and names the agent in speech. Phase 2 evaluates recycling the GPT-Live session on transfer, as LiveKit's GPT-Live handoff path does for changed instructions or chat context, against the cost of a short gap and resending bounded startup history.

### Announcer, `user say`, inbound calls

`openbase-coder user say AGENT MESSAGE` and Super Agent completion notices currently synthesise TTS through the announcer. In the live engine they become `append_commentary(f"{agent}: {message}", delegation_id=None)`, which the model weaves into the conversation instead of cutting in. The phone-alert fallback when no room is active is unchanged. Inbound calls (`inbound_calls.py`) only change in that the agent they ring into may be live-engine.

### Phone and desktop clients

Full duplex needs the microphone open while the agent speaks. Today's clients mute on `agent_audio_started` and unmute on `safe_to_unmute` (`CallManager+AutoMute.swift`, Android `VoiceLifecycleMuteAction`). Required change, small and additive:

- The agent publishes a participant attribute `openbase.voice.engine = live|pipeline` on join. Clients that see `live` disable the lifecycle auto-mute and leave the mic on; acoustic echo cancellation is already provided by the WebRTC stack on iOS/Android/Electron and by the LiveKit noise-cancellation plugin on the agent side. Clients that do not understand the attribute keep today's behaviour and still work, just half duplex.
- Voice lifecycle packets stay, but live mode must create synthetic delivery records because there is no STT → TTS `VoiceDeliveryRecord` path. The bridge emits `utterance_accepted` on `delegation_created`, emits `agent_audio_started` / `agent_audio_finished` from model audio playout or LiveKit session speech events rather than transcript deltas, and does not emit `safe_to_mute_user` or `safe_to_unmute` in live mode. Diagnostics and the delivery ledger keep working without a transport change.
- The Call tab shows the live-engine badge and the current speaking agent as today.

### Dependencies and runtime

- `livekit-agents` 1.5.17 → ≥1.8.4 and `livekit-plugins-openai` (same version; it needs `openai>=2.50`; the lock has 2.44). The AssemblyAI, Cartesia and Deepgram plugins move to the same release. The local monkey patches `proc_pool_patch.py` and `vad_backlog_patch.py` must be re-verified or dropped against 1.8. The multilingual turn detector is pipeline-only, but GPT-Live still needs an explicit VAD if we want LiveKit to cut playback on barge-in; if that remains Silero, `vad_backlog_patch.py` still matters for the live engine.
- The pinned `livekit-server` (`livekit_version.py`, 1.13.7) is unaffected.
- The agent process already runs under the `livekit-agent` service; no new service. Memory: the GPT-Live plugin replaces the STT and TTS plugin processes, so footprint should drop (see `openbase-memory-footprint-fixes` in memory for how it is measured).

### Cost

Live engine: $0.05 per minute of **session** (silence included), roughly $3 per hour of call, through the gateway at the metered rate it sets. Today's pipeline through Openbase Cloud costs about $0.0025/min AssemblyAI plus Cartesia at the metered 100 millicents per second of generated speech (≈$0.06 per minute the agent is talking). For a typical call where the agent talks a third of the time these are within a factor of two of each other. Agent token cost is unchanged and dominates either way.

### Fallback engine: Gemini 3.8 Live

Kept as a documented alternative, not built in phase 1. Shape: `google` plugin's realtime model with LiveKit function tools; a single `delegate_to_agent(text)` tool marked `NON_BLOCKING` routes to `active_client.run_turn` and returns the result as the tool response, while the model narrates. Cheaper (≈$0.02/min blended) and smart enough to answer small talk itself, but proactive audio bills while listening, MCP goes through LiveKit's toolset, and the plugin lacks some 3.8 knobs. Worth a spike if GPT-Live's one-voice-per-session limitation or its price becomes a problem.

## Phases

0. **Spike (BYO key, dispatcher only).** `voice_engine=live`, `live_voice_provider=openai`, dependency bump, bridge with `append_commentary` only, no transfers. Goal: measure time-to-first-audio and perceived latency on a real phone against the pipeline. Go/no-go.
1. **Gateway + Openbase Cloud provider.** Cloud MWW `live-voice-gateway` lands; CLI gains `openbase_cloud` as the default live provider, entitlement checks, agent status codes, settings UI. Transfers and direct mode work with one voice per call. Phone/desktop attribute-driven auto-mute change. Field test (tier 3).
2. **Polish.** Speculative start, per-agent voice via session recycle on transfer, spoken-command parity, announcer integration, Android parity.
3. **Default flip.** `voice_engine` defaults to `live` for installs with a Cloud login; `pipeline` remains for local-only and as a fallback when the gateway returns `subscription_required`.

## Testing

- Tier 1: a fake `GPTLiveSession` (event emitter with the three `append_*` methods) drives `LiveDelegationBridge` tests: chunking at 500 tokens, delegation ↔ turn binding, steering on overlapping delegations, route-change instructions, error → instruction mapping, lifecycle packet emission. Settings API tests mirror `tests/test_voice_mode_settings_api.py`.
- Tier 2: a scripted E2E spec only once a field test finds a bug worth freezing (`dev-docs/testing-tiers.md`).
- Tier 3: field test on a physical phone through the real gateway with a field-test account; the acoustic loop is the point, so no mocks.

## Open questions for Gabe

1. Confirm GPT-Live-1 as the phase-1 engine (Gemini 3.8 Live stays a documented fallback), and whether phase 0 may use your OpenAI key.
2. One voice per call in phase 1 (agents named in speech) versus session recycle per transfer from the start.
3. Should `pipeline` remain selectable forever (local-only installs need it), or be hidden once `live` is default?
4. Which GPT-Live voice is the Openbase default, and do we want to use one of OpenAI's twelve for the dispatcher and a different one for direct mode.

## References

- OpenAI: GPT-Live getting started, delegation and tools, session management, pricing (`developers.openai.com/api/docs/guides/live*`, `/pricing`).
- LiveKit: GPT-Live plugin guide and `gpt_live_model.py` in `livekit/agents` (`livekit-plugins-openai`).
- This workspace: `cli/docs/voice-routing.md`, `dev-docs/GLOSSARY.md` (Dispatcher, Voice route, Voice lifecycle packet), `feature/direct-voice-mode`.

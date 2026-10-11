"""Headless GPT-Live audio cut-off probe: the voice bridge's audio path, no phone.

Runs the same plugin, duplex adapter and speech gate the voice agent runs,
with a scripted caller utterance (a WAV) instead of a microphone and a
capturing sink instead of a LiveKit track. Every reply's audio is measured
at each stage:

- S1: PCM as received from the gateway websocket (``session.output_audio.delta``)
- G:  the adapter's ``FixedGate`` decision per frame (frames it drops while closed)
- S2: frames after our ``LiveSpeechGate`` (``SpeechGatedAgent``)
- S3: frames the ``AgentSession`` handed to the audio output sink (what would
  be published to the LiveKit track)

Per reply it reports transcript length, an expected duration from the text,
and the delivered duration plus peak/RMS dBFS at S1, S2 and S3, so a cut
localises to the gateway/model (S1 short), the adapter gate (S1 full, S2
short), or downstream (S3 short).

Run with the cli virtualenv's python (the installed plugin versions matter):

    .venv/bin/python voice-tests/gptlive_cutoff_probe.py --runs 10 --out /tmp/probe

Credentials come from the install's machine token (the same lookup the voice
agent uses) unless ``--api-key-env`` names an environment variable holding a
bearer token, together with ``--base-url`` (``.../live/openai/v1`` on the
Openbase Cloud gateway, or ``https://api.openai.com/v1`` for a direct run from
inside the cloud). Keys are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import math
import os
import sys
import time
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("gptlive_cutoff_probe")

SAMPLE_RATE = 24000
FRAME_MS = 100
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

DEFAULT_ANSWERS = [
    "Nine plus five is fourteen. Let me know if you want me to check anything else.",
    "The answer is fourteen. Nine and five together make fourteen, and I am happy to help with more.",
    "Nine plus five equals fourteen. That one is quick, so ask me a harder one next time.",
]


def dbfs(value: float) -> float:
    return 20 * math.log10(max(value, 1e-6))


AUDIBLE_FLOOR_DBFS = -50.0  # speech sits far above; the idle stream is not digital silence


def frame_rms_dbfs(raw: bytes) -> float:
    data = array("h")
    data.frombytes(raw[: len(raw) - len(raw) % 2])
    if not data:
        return -120.0
    return dbfs(math.sqrt(sum(v * v for v in data) / len(data)) / 32768)


@dataclass
class PcmStats:
    """Running peak and RMS over int16 PCM; GPT-Live streams silence between
    replies, so audible frames (above ``AUDIBLE_FLOOR_DBFS``) are tracked apart."""

    samples: int = 0
    sum_sq: float = 0.0
    peak: int = 0
    frames: int = 0
    audible_samples: int = 0
    audible_frames: int = 0
    idle_max_rms_dbfs: float = -120.0

    def add(self, raw: bytes) -> float:
        """Account for one frame; returns its RMS in dBFS."""
        data = array("h")
        data.frombytes(raw[: len(raw) - len(raw) % 2])
        if not data:
            return -120.0
        self.frames += 1
        self.samples += len(data)
        sum_sq = sum(v * v for v in data)
        self.sum_sq += sum_sq
        self.peak = max(self.peak, max(abs(v) for v in data))
        rms = dbfs(math.sqrt(sum_sq / len(data)) / 32768)
        if rms > AUDIBLE_FLOOR_DBFS:
            self.audible_samples += len(data)
            self.audible_frames += 1
        else:
            self.idle_max_rms_dbfs = max(self.idle_max_rms_dbfs, rms)
        return rms

    @property
    def ms(self) -> int:
        return self.samples * 1000 // SAMPLE_RATE

    @property
    def audible_ms(self) -> int:
        return self.audible_samples * 1000 // SAMPLE_RATE

    @property
    def peak_dbfs(self) -> float:
        return dbfs(self.peak / 32768)

    @property
    def rms_dbfs(self) -> float:
        if not self.samples:
            return -120.0
        return dbfs(math.sqrt(self.sum_sq / self.samples) / 32768)

    def summary(self) -> dict[str, Any]:
        return {
            "ms": self.ms,
            "audible_ms": self.audible_ms,
            "idle_max_rms_dbfs": round(self.idle_max_rms_dbfs, 1),
            "frames": self.frames,
            "peak_dbfs": round(self.peak_dbfs, 1),
            "rms_dbfs": round(self.rms_dbfs, 1),
        }


@dataclass
class ReplyRecord:
    index: int
    utterance: str
    answer: str
    started_at: float
    appended_at: float | None = None
    delegation_id: str | None = None
    caller_transcript: str = ""
    transcript: str = ""
    first_delta_at: float | None = None
    last_delta_at: float | None = None
    s1: PcmStats = field(default_factory=PcmStats)
    s1_max_gap_ms: int = 0
    s1_pcm: bytearray = field(default_factory=bytearray)
    gate_dropped: PcmStats = field(default_factory=PcmStats)
    gate_dropped_max_rms_dbfs: float = -120.0
    gate_bursts: int = 0
    gate_closed_by_quiet: int = 0
    s2: PcmStats = field(default_factory=PcmStats)
    s2_pcm: bytearray = field(default_factory=bytearray)
    s2_bursts: list[dict[str, Any]] = field(default_factory=list)
    s3: PcmStats = field(default_factory=PcmStats)
    events: list[str] = field(default_factory=list)
    unauthorized_bursts: int = 0
    last_text_at: float | None = None
    s3_cleared_audible_ms: int = 0
    interrupted_messages: int = 0

    @property
    def expected_ms(self) -> int:
        # Measured on VM2 and direct OpenAI runs (2026-10-11): marin reads
        # these answers at 45-60 ms per transcript character.
        chars = len(self.transcript) or len(self.answer)
        return chars * 45

    def verdict(self) -> str:
        if self.s1.audible_ms == 0:
            return "NO_AUDIO"
        if self.s1.audible_ms < 0.6 * self.expected_ms:
            return "CUT_AT_S1"
        if self.s2.frames == 0 and self.s3.frames == 0 and self.s2_bursts == []:
            return "OK"  # raw mode: S1 only
        if self.unauthorized_bursts and self.s2.audible_ms == 0:
            return "UNAUTHORIZED"
        if self.s2.audible_ms < 0.8 * self.s1.audible_ms:
            return "CUT_AT_S2"
        if self.s3.audible_ms < 0.8 * self.s2.audible_ms:
            return "CUT_AT_S3"
        return "OK"

    def row(self) -> dict[str, Any]:
        return {
            "reply": self.index,
            "verdict": self.verdict(),
            "transcript_chars": len(self.transcript),
            "expected_ms": self.expected_ms,
            "first_audio_after_append_ms": (
                round((self.first_delta_at - self.appended_at) * 1000)
                if self.first_delta_at and self.appended_at
                else None
            ),
            "s1": self.s1.summary(),
            "s1_max_gap_ms": self.s1_max_gap_ms,
            "audio_ended_before_text_ms": (
                round((self.last_text_at - self.last_delta_at) * 1000)
                if self.last_text_at and self.last_delta_at
                else None
            ),
            "gate": {
                "bursts": self.gate_bursts,
                "closed_by_quiet": self.gate_closed_by_quiet,
                "dropped_ms": self.gate_dropped.ms,
                "dropped_max_rms_dbfs": round(self.gate_dropped_max_rms_dbfs, 1),
            },
            "s2": self.s2.summary(),
            "s2_bursts": self.s2_bursts,
            "s3": self.s3.summary(),
            "unauthorized_bursts": self.unauthorized_bursts,
            "s3_cleared_audible_ms": self.s3_cleared_audible_ms,
            "interrupted_messages": self.interrupted_messages,
            "delegation_id": self.delegation_id,
            "caller_transcript": self.caller_transcript,
            "transcript": self.transcript,
            "events": self.events,
        }


def scale_pcm(raw: bytes, gain: float) -> bytes:
    data = array("h")
    data.frombytes(raw[: len(raw) - len(raw) % 2])
    return array("h", (int(v * gain) for v in data)).tobytes()


def mix_pcm(a: bytes, b: bytes) -> bytes:
    x, y = array("h"), array("h")
    x.frombytes(a)
    y.frombytes(b)
    return array(
        "h", (max(-32768, min(32767, p + q)) for p, q in zip(x, y))
    ).tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


def read_wav_frames(path: Path) -> list[bytes]:
    """100 ms frames of the caller utterance; [] for ``--wav none`` (the answer
    prompt alone makes the model speak, no caller turn)."""
    if str(path) == "none":
        return []
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (
            SAMPLE_RATE,
            1,
            2,
        ):
            raise SystemExit(f"{path}: need {SAMPLE_RATE} Hz mono 16-bit PCM")
        pcm = w.readframes(w.getnframes())
    step = FRAME_SAMPLES * 2
    pad = (-len(pcm)) % step
    pcm += b"\x00" * pad
    return [pcm[i : i + step] for i in range(0, len(pcm), step)]


def resolve_credentials(args) -> tuple[str, str]:
    """(base_url, api_key); the key is the install's machine token by default."""
    if args.api_key_env:
        key = os.environ.get(args.api_key_env, "")
        if not key:
            raise SystemExit(f"{args.api_key_env} is not set")
        if not args.base_url:
            raise SystemExit("--base-url is required with --api-key-env")
        return args.base_url.rstrip("/"), key
    from openbase_coder_cli.config.machine_token_manager import MachineTokenManager
    from openbase_coder_cli.livekit_agent.config import (
        OPENBASE_CLOUD_LIVE_BASE_URL,
        WEB_BACKEND_URL,
    )

    token = MachineTokenManager(WEB_BACKEND_URL).get_machine_token()
    if not token:
        raise SystemExit("no Openbase machine token; run openbase-coder login")
    return (args.base_url or OPENBASE_CLOUD_LIVE_BASE_URL).rstrip("/"), token


async def run_probe(args) -> int:
    from livekit import rtc
    from livekit.agents import AgentSession, llm
    from livekit.agents.voice import io
    from livekit.plugins.openai.realtime import GPTLiveModel
    if args.gate_module:
        # Try a gate from a file against an installed runtime, untouched.
        import importlib.util

        import openbase_coder_cli.livekit_agent  # noqa: F401 - parent package

        name = "openbase_coder_cli.livekit_agent.live_speech_gate"
        spec = importlib.util.spec_from_file_location(name, args.gate_module)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        print(f"gate module: {args.gate_module}", flush=True)
    from openbase_coder_cli.livekit_agent.live_preconnect import (
        wait_live_session_started,
    )
    from openbase_coder_cli.livekit_agent.live_speech_gate import (
        LiveSpeechGate,
        SpeechGatedAgent,
    )
    from openbase_coder_cli.livekit_agent.live_spoken_output import answer_commands

    base_url, api_key = resolve_credentials(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    def now() -> float:
        return time.monotonic() - t0

    records: list[ReplyRecord] = []
    current: dict[str, ReplyRecord | None] = {"r": None}
    utterance_closed = asyncio.Event()
    delegation_seen: dict[str, str | None] = {"id": None}
    delegation_event = asyncio.Event()
    session_errors: list[str] = []

    def rec() -> ReplyRecord | None:
        return current["r"]

    # --- S1: raw gateway events -------------------------------------------------
    # Simulated speakerphone echo: the model's own output, attenuated and
    # delayed, mixed into the caller's microphone.
    echo_gain = 10 ** (args.echo_db / 20) if args.echo_db is not None else 0.0
    echo_buf = bytearray()
    echo_delay_bytes = args.echo_delay_ms * SAMPLE_RATE // 1000 * 2

    def on_gateway_event(event) -> None:
        r = rec()
        if not isinstance(event, dict):
            return
        kind = str(event.get("type") or "")
        if kind == "session.output_audio.delta":
            if r is None:
                return
            raw = base64.b64decode(event.get("delta") or "")
            t = now()
            rms = r.s1.add(raw)
            if args.dump:
                r.s1_pcm += raw
            if echo_gain:
                echo_buf.extend(scale_pcm(raw, echo_gain))
            if rms <= AUDIBLE_FLOOR_DBFS:
                return
            if r.first_delta_at is None:
                r.first_delta_at = t
            elif r.last_delta_at is not None:
                r.s1_max_gap_ms = max(
                    r.s1_max_gap_ms, round((t - r.last_delta_at) * 1000)
                )
            r.last_delta_at = t
            return
        if kind == "session.output_transcript.delta":
            if hasattr(speech_gate, "agent_said"):
                speech_gate.agent_said(str(event.get("delta") or ""))
            if r is not None:
                r.transcript += str(event.get("delta") or "")
                r.last_text_at = now()
            return
        if kind == "session.input_transcript.delta":
            if hasattr(speech_gate, "caller_heard"):
                speech_gate.caller_heard(str(event.get("delta") or ""))
            if r is not None:
                r.caller_transcript += str(event.get("delta") or "")
            return
        if kind in ("session.usage.updated",):
            return
        if kind == "response.event":
            inner = event.get("event") if isinstance(event.get("event"), dict) else {}
            kind = "response.event:" + str(inner.get("type") or "?")
            if kind.endswith(".delta"):
                return
        line = f"{now():7.2f} {kind}"
        if kind == "error":
            line += " " + json.dumps(event.get("error"))[:200]
            session_errors.append(line)
        if r is not None:
            r.events.append(line)
        logger.info("gateway %s", line)

    # --- G: the adapter's FixedGate, observed -----------------------------------
    class ObservedGate:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.was_open = False

        def deactivate(self) -> None:
            self.inner.deactivate()
            self.was_open = False

        def update(self, frame: rtc.AudioFrame) -> bool:
            is_open = self.inner.update(frame)
            r = rec()
            if r is not None:
                raw = bytes(frame.data)
                if is_open and not self.was_open:
                    r.gate_bursts += 1
                if not is_open:
                    rms = frame_rms_dbfs(raw)
                    if rms > AUDIBLE_FLOOR_DBFS:
                        r.gate_dropped.add(raw)
                    r.gate_dropped_max_rms_dbfs = max(r.gate_dropped_max_rms_dbfs, rms)
                    if self.was_open:
                        r.gate_closed_by_quiet += 1
            self.was_open = is_open
            return is_open

    model = GPTLiveModel(
        model=args.model,
        voice=args.voice,
        delegation="client",
        api_key=api_key,
        base_url=base_url,
    )
    original_gate = model.audio_gate

    def observed_gate():
        gate = original_gate()
        if args.gate == "adaptive":
            gate = llm.AdaptiveNoiseGate()
        elif args.gate_floor is not None:
            gate = llm.FixedGate(args.gate_floor, min_silence_duration=0.8)
        return ObservedGate(gate)

    model.audio_gate = observed_gate  # type: ignore[method-assign]

    # --- S2: our speech gate -----------------------------------------------------
    speech_gate = (
        LiveSpeechGate(barge_in_min_seconds=args.barge_in_min)
        if args.barge_in_min is not None
        else LiveSpeechGate()
    )

    class ProbeAgent(SpeechGatedAgent):
        _speech_gate = speech_gate

        def __init__(self) -> None:
            super().__init__(instructions=args.instructions)

        def realtime_audio_output_node(self, audio, model_settings):
            upstream = super().realtime_audio_output_node(audio, model_settings)
            permitted = speech_gate.authorized and not speech_gate.speaking

            async def observe():
                r = rec()
                stats = PcmStats()
                started = now()
                async for frame in upstream:
                    if isinstance(frame, rtc.AudioFrame) and r is not None:
                        raw = bytes(frame.data)
                        stats.add(raw)
                        r.s2.add(raw)
                        if args.dump:
                            r.s2_pcm += raw
                    yield frame
                if r is not None:
                    if not permitted:
                        r.unauthorized_bursts += 1
                    r.s2_bursts.append(
                        {
                            "permitted": permitted,
                            "ms": stats.ms,
                            "peak_dbfs": round(stats.peak_dbfs, 1),
                            "at": round(started, 2),
                        }
                    )

            return observe()

        async def on_enter(self) -> None:
            ds = self.duplex_session
            ds.on("openai_server_event_received", on_gateway_event)
            ds.on("input_audio_transcription_completed", on_utterance_closed)
            ds.on("delegation_created", on_delegation)
            ds.on(
                "error",
                lambda ev: session_errors.append(repr(getattr(ev, "error", ev))),
            )
            duplex["s"] = ds

    duplex: dict[str, Any] = {}

    def on_utterance_closed(ev) -> None:
        r = rec()
        text = getattr(ev, "transcript", "")
        if r is not None:
            r.events.append(f"{now():7.2f} utterance_closed {text!r}")
        utterance_closed.set()

    def on_delegation(delegation) -> None:
        delegation_seen["id"] = getattr(delegation, "id", None) or getattr(
            delegation, "delegation_id", None
        )
        r = rec()
        if r is not None:
            r.events.append(f"{now():7.2f} delegation_created {delegation_seen['id']}")
        delegation_event.set()

    # --- caller audio in, S3 audio out -------------------------------------------
    class ProbeAudioInput(io.AudioInput):
        def __init__(self) -> None:
            super().__init__(label="probe")
            self.queue: asyncio.Queue[bytes] = asyncio.Queue()
            self.stimulus: list[bytes] = []
            self._task: asyncio.Task | None = None

        def on_attached(self) -> None:
            self._task = asyncio.create_task(self._pace())

        def on_detached(self) -> None:
            if self._task:
                self._task.cancel()

        async def _pace(self) -> None:
            step = FRAME_SAMPLES * 2
            silence = b"\x00" * step
            next_at = time.monotonic()
            while True:
                chunk = self.stimulus.pop(0) if self.stimulus else silence
                if echo_gain and len(echo_buf) >= step + echo_delay_bytes:
                    echo = bytes(echo_buf[:step])
                    del echo_buf[:step]
                    chunk = mix_pcm(chunk, echo)
                self.queue.put_nowait(chunk)
                next_at += FRAME_MS / 1000
                await asyncio.sleep(max(0.0, next_at - time.monotonic()))

        async def __anext__(self) -> rtc.AudioFrame:
            chunk = await self.queue.get()
            return rtc.AudioFrame(
                data=chunk,
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(chunk) // 2,
            )

    class ProbeAudioOutput(io.AudioOutput):
        """Stands in for the LiveKit room output: pausable like it, and it
        "plays" captured audio at real time, so a clear_buffer drops what had
        not been heard yet (counted as S3 cleared)."""

        def __init__(self) -> None:
            super().__init__(
                label="probe",
                capabilities=io.AudioOutputCapabilities(pause=args.vad),
                sample_rate=SAMPLE_RATE,
            )
            self._segment_samples = 0
            self._pending: list[bytes] = []
            self._paused = False
            self._player = asyncio.create_task(self._play())

        async def _play(self) -> None:
            next_at = time.monotonic()
            while True:
                next_at += FRAME_MS / 1000
                await asyncio.sleep(max(0.0, next_at - time.monotonic()))
                if self._paused or not self._pending:
                    next_at = time.monotonic()
                    continue
                need = FRAME_SAMPLES * 2
                out = bytearray()
                while self._pending and len(out) < need:
                    chunk = self._pending[0]
                    take = chunk[: need - len(out)]
                    out += take
                    if len(take) == len(chunk):
                        self._pending.pop(0)
                    else:
                        self._pending[0] = chunk[len(take):]
                r = rec()
                if r is not None:
                    r.s3.add(bytes(out))

        async def capture_frame(self, frame: rtc.AudioFrame) -> None:
            await super().capture_frame(frame)
            self._pending.append(bytes(frame.data))
            self._segment_samples += frame.samples_per_channel

        def pause(self) -> None:
            self._paused = True
            r = rec()
            if r is not None:
                r.events.append(f"{now():7.2f} output_paused")

        def resume(self) -> None:
            self._paused = False
            r = rec()
            if r is not None:
                r.events.append(f"{now():7.2f} output_resumed")

        def flush(self) -> None:
            super().flush()
            position = self._segment_samples / SAMPLE_RATE
            self._segment_samples = 0
            self.on_playback_finished(playback_position=position, interrupted=False)

        def clear_buffer(self) -> None:
            r = rec()
            dropped = sum(len(c) for c in self._pending)
            if r is not None:
                stats = PcmStats()
                for c in self._pending:
                    stats.add(c)
                r.s3_cleared_audible_ms += stats.audible_ms
                r.events.append(f"{now():7.2f} output_cleared ms={dropped * 1000 // (SAMPLE_RATE * 2)} audible_ms={stats.audible_ms}")
            self._pending.clear()
            self._paused = False
            position = self._segment_samples / SAMPLE_RATE
            self._segment_samples = 0
            self.on_playback_finished(playback_position=position, interrupted=True)

    audio_in = ProbeAudioInput()
    audio_out = ProbeAudioOutput()
    if args.vad:
        from livekit.plugins import silero

        # As livekit.py builds the live session: VAD-driven interruption,
        # and the caller's speech feeding our gate's barge-in rule.
        session = AgentSession(
            llm=model,
            vad=silero.VAD.load(),
            turn_handling={
                "interruption": (
                    {"enabled": False}
                    if args.no_framework_interrupt
                    else {"mode": "vad"}
                )
            },
        )

        # Mirrors livekit.py's gate_caller_speech / on_barge_in wiring. With
        # a gate that predates on_barge_in, fall back to the old timer rule.
        has_callback = hasattr(speech_gate, "on_barge_in")

        def gate_caller_speech(ev) -> None:
            speech_gate.user_state_changed(ev.new_state)
            r = rec()
            if r is not None:
                r.events.append(f"{now():7.2f} user_state {ev.old_state}->{ev.new_state}")
            if ev.new_state == "speaking":
                asyncio.get_running_loop().call_later(
                    speech_gate.barge_in_min_seconds, check_barge_in
                )

        def check_barge_in() -> None:
            if speech_gate.speaking and not has_callback:
                session.interrupt(force=True)

        def on_barge_in() -> None:
            r = rec()
            if r is not None:
                r.events.append(f"{now():7.2f} barge_in_interrupt")
            asyncio.get_running_loop().call_soon(lambda: session.interrupt(force=True))

        if has_callback:
            speech_gate.on_barge_in = on_barge_in

        session.on("user_state_changed", gate_caller_speech)
    else:
        session = AgentSession(llm=model)
    session.input.audio = audio_in
    session.output.audio = audio_out

    def on_item(ev) -> None:
        item = getattr(ev, "item", None)
        r = rec()
        if r is not None and getattr(item, "role", None) == "assistant":
            if getattr(item, "interrupted", False):
                r.interrupted_messages += 1
            r.events.append(
                f"{now():7.2f} assistant_item interrupted={getattr(item, 'interrupted', None)} "
                f"text={(getattr(item, 'text_content', '') or '')[:60]!r}"
            )

    session.on("conversation_item_added", on_item)

    def on_agent_state(ev) -> None:
        r = rec()
        if r is not None:
            r.events.append(f"{now():7.2f} agent_state {ev.old_state}->{ev.new_state}")

    session.on("agent_state_changed", on_agent_state)

    stimulus_frames = read_wav_frames(Path(args.wav))
    barge_frames = read_wav_frames(Path(args.barge_wav)) if args.barge_at is not None else []
    answers = args.answers or DEFAULT_ANSWERS
    print(
        f"probe: gateway={base_url} model={args.model} voice={args.voice} "
        f"runs={args.runs} wav={args.wav} gate={args.gate} answer_delay={args.answer_delay}s",
        flush=True,
    )
    agent = ProbeAgent()
    await session.start(agent=agent)
    ds = duplex.get("s")
    if ds is None:
        raise RuntimeError("duplex session not created")
    await wait_live_session_started(ds, timeout=20)
    print(f"{now():7.2f} session started id={ds.session_id}", flush=True)
    await asyncio.sleep(1.0)

    exit_code = 0
    try:
        for i in range(args.runs):
            answer = answers[i % len(answers)]
            r = ReplyRecord(
                index=i + 1, utterance=args.wav, answer=answer, started_at=now()
            )
            current["r"] = r
            records.append(r)
            utterance_closed.clear()
            delegation_event.clear()
            delegation_seen["id"] = None
            if not args.late_authorize:
                # The model answers the moment the utterance closes; permit
                # that burst so the audio path, not the bridge's timing, is
                # what gets measured. --late-authorize reproduces the bridge.
                speech_gate.authorize()
            if stimulus_frames:
                audio_in.stimulus = list(stimulus_frames)
                try:
                    await asyncio.wait_for(utterance_closed.wait(), timeout=15)
                except asyncio.TimeoutError:
                    r.events.append(f"{now():7.2f} utterance never closed")
                # The bridge waits for the model's delegation when one comes
                # quickly, then appends the backend's answer as a spoken instruction.
                try:
                    await asyncio.wait_for(delegation_event.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    pass
            if args.answer_delay:
                await asyncio.sleep(args.answer_delay)
            r.delegation_id = delegation_seen["id"]
            speech_gate.authorize()
            r.appended_at = now()
            for command in answer_commands(answer, max_chars=1600):
                if not stimulus_frames:
                    command += SPEAK_NOW
                ds.append_instructions(command, delegation_id=r.delegation_id)
            r.events.append(f"{now():7.2f} append_instructions chars={len(answer)}")
            # Reply window: first audio within 30 s, then quiet for `settle` s.
            deadline = now() + 30
            while now() < deadline and r.first_delta_at is None:
                await asyncio.sleep(0.05)
            if barge_frames and r.first_delta_at is not None:
                # A short caller interjection mid-reply ("okay"): does the
                # model stop its audio while the transcript runs on?
                await asyncio.sleep(max(0.0, r.first_delta_at + args.barge_at - now()))
                audio_in.stimulus = list(barge_frames)
                r.events.append(f"{now():7.2f} barge_in {args.barge_wav}")
            while r.first_delta_at is not None:
                await asyncio.sleep(0.1)
                last = r.last_delta_at
                if last is not None and now() - last >= args.settle:
                    break
                if now() > deadline + 60:
                    r.events.append(f"{now():7.2f} reply window timed out")
                    break
            # Let the adapter close its burst and the output finish playing.
            await asyncio.sleep(1.2)
            drain_until = now() + 15
            while audio_out._pending and now() < drain_until:
                await asyncio.sleep(0.1)
            current["r"] = None
            speech_gate.revoke()
            row = r.row()
            if args.dump:
                if r.s1_pcm:
                    write_wav(out / f"reply{r.index:02d}-s1.wav", bytes(r.s1_pcm))
                if r.s2_pcm:
                    write_wav(out / f"reply{r.index:02d}-s2.wav", bytes(r.s2_pcm))
            with (out / "replies.jsonl").open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(
                f"reply {r.index:2d} {row['verdict']:9s} text={len(r.transcript):3d}ch "
                f"exp={r.expected_ms:5d}ms  S1={r.s1.audible_ms:5d}ms peak={r.s1.peak_dbfs:6.1f} "
                f"gap={r.s1_max_gap_ms:4d}ms  "
                f"G:bursts={r.gate_bursts} quietclose={r.gate_closed_by_quiet} drop={r.gate_dropped.ms}ms  "
                f"S2={r.s2.audible_ms:5d}ms/{len(r.s2_bursts)}b  S3={r.s3.audible_ms:5d}ms cleared={r.s3_cleared_audible_ms}ms int={r.interrupted_messages}  "
                f"lat={row['first_audio_after_append_ms']}ms  {r.transcript[:60]!r}",
                flush=True,
            )
            await asyncio.sleep(args.pause)
    finally:
        try:
            await asyncio.wait_for(session.aclose(), timeout=10)
        except Exception as exc:  # the run is over; report, do not hang
            print(f"session close: {exc!r}", flush=True)
        await model.aclose()

    verdicts = [r.verdict() for r in records]
    summary = {
        "gateway": base_url,
        "model": args.model,
        "voice": args.voice,
        "runs": args.runs,
        "gate": args.gate,
        "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))},
        "session_errors": session_errors[:10],
        "host": os.uname().nodename,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print("summary:", json.dumps(summary), flush=True)
    if any(v != "OK" for v in verdicts):
        exit_code = 1
    return exit_code


ANSWER_PREFIX_RAW = (
    "Read this next backend answer segment aloud exactly once and in full. "
    "Keep every sentence and detail; do not summarize, answer it yourself, "
    "or add words. Finish earlier answer segments first and read these in "
    "order: "
)
SPEAK_NOW = " Do not wait for the caller to speak first. After that, pause and listen."


async def run_raw(args) -> int:
    """S1-only probe speaking the GPT-Live protocol directly (aiohttp only).

    Runs anywhere, including the staging API container with the provider key
    in its environment, so the same measurement can be taken through the
    Openbase Cloud gateway and straight from OpenAI.
    """
    import aiohttp

    base_url, api_key = resolve_credentials(args)
    url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    if not url.endswith("/live/sessions"):
        url += "/live/sessions"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    def now() -> float:
        return time.monotonic() - t0

    stimulus_frames = read_wav_frames(Path(args.wav))
    answers = args.answers or DEFAULT_ANSWERS
    records: list[ReplyRecord] = []
    current: dict[str, ReplyRecord | None] = {"r": None}
    started = asyncio.Event()
    delegation_seen: dict[str, str | None] = {"id": None}
    last_input_delta: dict[str, float | None] = {"t": None}
    session_errors: list[str] = []
    stimulus: list[bytes] = []
    print(
        f"probe(raw): gateway={base_url} model={args.model} voice={args.voice} "
        f"runs={args.runs} wav={args.wav} answer_delay={args.answer_delay}s",
        flush=True,
    )
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "LiveKit Agents"}
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url, headers=headers, max_msg_size=0) as ws:

            async def send(event: dict) -> None:
                await ws.send_str(json.dumps(event))

            await send(
                {
                    "type": "session.start",
                    "event_id": "session_start_probe",
                    "session": {
                        "model": args.model,
                        "instructions": args.instructions,
                        "audio": {
                            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                            "output": {"voice": args.voice},
                        },
                        "delegation": {"type": "client"},
                    },
                }
            )

            async def pace() -> None:
                silence = b"\x00" * (FRAME_SAMPLES * 2)
                next_at = time.monotonic()
                while True:
                    chunk = stimulus.pop(0) if stimulus else silence
                    await send(
                        {
                            "type": "session.input_audio.append",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    )
                    next_at += FRAME_MS / 1000
                    await asyncio.sleep(max(0.0, next_at - time.monotonic()))

            async def recv() -> None:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            session_errors.append(f"{now():7.2f} ws closed {ws.close_code}")
                            break
                        continue
                    event = json.loads(msg.data)
                    kind = str(event.get("type") or "")
                    r = current["r"]
                    if kind == "session.started":
                        started.set()
                    elif kind == "session.output_audio.delta":
                        if r is None:
                            continue
                        raw = base64.b64decode(event.get("delta") or "")
                        t = now()
                        rms = r.s1.add(raw)
                        if args.dump:
                            r.s1_pcm += raw
                        if args.trace_frames:
                            print(f"{t:8.3f} delta bytes={len(raw)} rms={rms:6.1f}", flush=True)
                        if rms <= AUDIBLE_FLOOR_DBFS:
                            continue
                        if r.first_delta_at is None:
                            r.first_delta_at = t
                        elif r.last_delta_at is not None:
                            r.s1_max_gap_ms = max(
                                r.s1_max_gap_ms, round((t - r.last_delta_at) * 1000)
                            )
                        r.last_delta_at = t
                    elif kind == "session.output_transcript.delta":
                        if r is not None:
                            r.transcript += str(event.get("delta") or "")
                    elif kind == "session.input_transcript.delta":
                        last_input_delta["t"] = now()
                        if r is not None:
                            r.caller_transcript += str(event.get("delta") or "")
                    elif kind == "session.delegation.created":
                        delegation = event.get("delegation") or {}
                        delegation_seen["id"] = delegation.get("id") or event.get("delegation_id")
                        if r is not None:
                            r.events.append(f"{now():7.2f} delegation_created {delegation_seen['id']}")
                    elif kind in ("session.usage.updated",):
                        continue
                    else:
                        if kind == "response.event":
                            inner = event.get("event") if isinstance(event.get("event"), dict) else {}
                            kind = "response.event:" + str(inner.get("type") or "?")
                            if kind.endswith(".delta"):
                                continue
                        line = f"{now():7.2f} {kind}"
                        if kind == "error":
                            line += " " + json.dumps(event.get("error"))[:200]
                            session_errors.append(line)
                        if r is not None:
                            r.events.append(line)
                        logger.info("gateway %s", line)

            recv_task = asyncio.create_task(recv())
            await asyncio.wait_for(started.wait(), timeout=20)
            print(f"{now():7.2f} session started", flush=True)
            pace_task = asyncio.create_task(pace())
            await asyncio.sleep(1.0)
            try:
                for i in range(args.runs):
                    answer = answers[i % len(answers)]
                    r = ReplyRecord(index=i + 1, utterance=args.wav, answer=answer, started_at=now())
                    current["r"] = r
                    records.append(r)
                    delegation_seen["id"] = None
                    last_input_delta["t"] = None
                    if stimulus_frames:
                        stimulus[:] = list(stimulus_frames)
                        # The plugin closes the caller's turn 0.8 s after its
                        # last transcript fragment; wait the same way, bounded.
                        deadline = now() + 15
                        while now() < deadline:
                            await asyncio.sleep(0.1)
                            t = last_input_delta["t"]
                            if t is not None and now() - t >= 0.8 and not stimulus:
                                break
                        r.events.append(f"{now():7.2f} utterance_closed {r.caller_transcript!r}")
                    if args.answer_delay:
                        await asyncio.sleep(args.answer_delay)
                    r.delegation_id = delegation_seen["id"]
                    r.appended_at = now()
                    await send(
                        {
                            "type": "session.instructions.append",
                            "event_id": f"append_{i}",
                            "delegation_id": r.delegation_id,
                            "content": ANSWER_PREFIX_RAW
                            + json.dumps(answer)
                            + ("" if stimulus_frames else SPEAK_NOW),
                        }
                    )
                    r.events.append(f"{now():7.2f} append_instructions chars={len(answer)}")
                    deadline = now() + 30
                    while now() < deadline and r.first_delta_at is None:
                        await asyncio.sleep(0.05)
                    while r.first_delta_at is not None:
                        await asyncio.sleep(0.1)
                        last = r.last_delta_at
                        if last is not None and now() - last >= args.settle:
                            break
                        if now() > deadline + 60:
                            r.events.append(f"{now():7.2f} reply window timed out")
                            break
                    current["r"] = None
                    row = r.row()
                    if args.dump and r.s1_pcm:
                        write_wav(out / f"reply{r.index:02d}-s1.wav", bytes(r.s1_pcm))
                    with (out / "replies.jsonl").open("a") as f:
                        f.write(json.dumps(row) + "\n")
                    print(
                        f"reply {r.index:2d} {row['verdict']:9s} text={len(r.transcript):3d}ch "
                        f"exp={r.expected_ms:5d}ms  S1={r.s1.audible_ms:5d}ms deltas={r.s1.audible_frames} "
                        f"peak={r.s1.peak_dbfs:6.1f} gap={r.s1_max_gap_ms:4d}ms  "
                        f"lat={row['first_audio_after_append_ms']}ms  {r.transcript[:60]!r}",
                        flush=True,
                    )
                    await asyncio.sleep(args.pause)
            finally:
                pace_task.cancel()
                await ws.close()
                recv_task.cancel()
    verdicts = [r.verdict() for r in records]
    summary = {
        "mode": "raw",
        "gateway": base_url,
        "model": args.model,
        "voice": args.voice,
        "runs": args.runs,
        "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))},
        "session_errors": session_errors[:10],
        "host": os.uname().nodename,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print("summary:", json.dumps(summary), flush=True)
    return 0 if all(v in ("OK",) for v in verdicts) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", default="/tmp/gptlive-probe")
    parser.add_argument(
        "--wav",
        default=str(
            Path(__file__).parent / "fixtures/gptlive-probe/nine-plus-five.wav"
        ),
        help="caller utterance, 24 kHz mono 16-bit; 'none' skips the caller turn",
    )
    parser.add_argument(
        "--answers", nargs="*", help="scripted backend answers to read aloud"
    )
    parser.add_argument(
        "--answer-delay",
        type=float,
        default=0.0,
        help="seconds between the utterance closing and the backend answer (the real bridge: 2-8 s)",
    )
    parser.add_argument(
        "--settle", type=float, default=2.0, help="quiet seconds that end a reply"
    )
    parser.add_argument(
        "--pause", type=float, default=1.0, help="seconds between replies"
    )
    parser.add_argument(
        "--model", default=os.getenv("LIVEKIT_LIVE_VOICE_MODEL", "gpt-live-1")
    )
    parser.add_argument("--voice", default="marin")
    parser.add_argument("--base-url", default=None)
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="env var holding a bearer token (direct OpenAI runs inside the cloud)",
    )
    parser.add_argument(
        "--gate",
        choices=["fixed", "adaptive"],
        default="fixed",
        help="adapter audio gate to use (A/B for the fix)",
    )
    parser.add_argument(
        "--gate-floor",
        type=float,
        default=None,
        help="FixedGate silence floor override (default 0.0006)",
    )
    parser.add_argument(
        "--dump", action="store_true", help="write S1/S2 WAVs per reply"
    )
    parser.add_argument(
        "--instructions",
        default="You are Marian, a friendly voice assistant on a phone call. Speak briefly.",
    )
    parser.add_argument(
        "--echo-db",
        type=float,
        default=None,
        help="feed the model's own output back as caller audio at this level (e.g. -20): speakerphone echo",
    )
    parser.add_argument("--echo-delay-ms", type=int, default=150)
    parser.add_argument("--barge-in-min", type=float, default=None, help="LiveSpeechGate barge_in_min_seconds (agent default 0.5)")
    parser.add_argument("--gate-module", default=None, help="load live_speech_gate from this file instead of the installed one")
    parser.add_argument("--no-framework-interrupt", action="store_true", help="AgentSession interruption enabled=False")
    parser.add_argument("--vad", action="store_true", help="run the agent's silero VAD + VAD interruption + pausable output, as in a real call")
    parser.add_argument("--barge-at", type=float, default=None, help="seconds into each reply to play --barge-wav as caller speech")
    parser.add_argument(
        "--barge-wav",
        default=str(Path(__file__).parent / "fixtures/gptlive-probe/okay.wav"),
    )
    parser.add_argument(
        "--late-authorize",
        action="store_true",
        help="permit audio only when the answer is appended, as the bridge does",
    )
    parser.add_argument(
        "--mode",
        choices=["sdk", "raw"],
        default="sdk",
        help="sdk: full pipeline (S1, gate, S2, S3); raw: S1 only, aiohttp only",
    )
    parser.add_argument("--trace-frames", action="store_true", help="raw mode: print every audio delta")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    runner = run_raw if args.mode == "raw" else run_probe
    sys.exit(asyncio.run(runner(args)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Acoustic field-test probe: speak a stimulus, record the reply, transcribe it.

The tier-3 acoustic loop needs the dispatcher's *spoken* answer verified, not
just transport health. This does the whole loop in one shot from the host Mac:

  1. start recording the host microphone (which hears the phone's speaker),
  2. speak the stimulus question through the host speaker (the phone's mic picks
     it up and sends it to the dispatcher over the call),
  3. keep recording through the dispatcher's spoken answer,
  4. transcribe the recording and print it.

Transcription defaults to AssemblyAI (the same STT the product uses), reading
the key from $ASSEMBLYAI_API_KEY (or $ASSEMBLY_AI_API_KEY). Pass --stt mlx to
fall back to a local mlx-whisper CLI when no key is available.

Because the host mic records the whole room, the transcript contains BOTH the
spoken question and the dispatcher's answer — which is exactly what you want to
eyeball: "did it actually answer, and was the answer right?"

Examples:
  CARTESIA_API_KEY=... acoustic-probe.py "What is seven times six?"
  acoustic-probe.py "Start a super agent that lists my repos" --seconds 25
  acoustic-probe.py --no-tts --seconds 12    # just capture + transcribe

Requires: macOS Core Audio, Swift, ffmpeg (for conversion), and Cartesia for the
default realistic TTS stimulus. Pass --tts macos for the explicit `say`
fallback. Native Core Audio capture is the default because current FFmpeg
AVFoundation builds can advance timestamps without delivering the corresponding
microphone samples. The old FFmpeg path remains an explicit diagnostic fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

AAI_BASE = "https://api.assemblyai.com/v2"
CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
DEFAULT_CARTESIA_VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
DEFAULT_CARTESIA_MODEL_ID = "sonic-3.5"
DEFAULT_CARTESIA_VERSION = "2026-03-01"
DEFAULT_MLX_MODEL_ID = "mlx-community/whisper-large-v3-turbo"
NATIVE_RECORDER = Path(__file__).with_name("record-microphone.swift")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def synthesize_cartesia(
    *,
    text: str,
    api_key: str,
    voice_id: str,
    model_id: str,
    version: str,
    out_path: str,
) -> None:
    """Synthesize realistic host-stimulus audio without exposing the API key."""
    request = urllib.request.Request(
        CARTESIA_TTS_URL,
        data=json.dumps(
            {
                "model_id": model_id,
                "transcript": text,
                "voice": {"id": voice_id},
                "output_format": {
                    "container": "wav",
                    "encoding": "pcm_f32le",
                    "sample_rate": 44100,
                },
                "language": "en",
                "generation_config": {"volume": 1, "speed": 1},
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-API-Key": api_key,
            "Cartesia-Version": version,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        audio = response.read()
    with open(out_path, "wb") as output:
        output.write(audio)


def record_and_speak(
    *,
    question: str | None,
    seconds: float,
    tts_delay: float,
    device: str,
    voice: str,
    rate: int,
    stimulus_audio_path: str | None,
    capture: str,
    out_path: str,
) -> None:
    """Record `seconds` of host mic to out_path, speaking `question` shortly in."""
    native_path = out_path + ".native.wav"
    if capture == "coreaudio":
        rec = subprocess.Popen(
            ["swift", str(NATIVE_RECORDER), native_path, str(seconds)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if rec.stdout is None or rec.stdout.readline().strip() != "READY":
            detail = rec.stderr.read().strip() if rec.stderr else ""
            raise RuntimeError(f"native microphone recorder failed to start: {detail}")
    else:
        rec = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "avfoundation",
                "-i",
                f":{device}",
                "-t",
                str(seconds),
                native_path,
            ],
            stdin=subprocess.DEVNULL,
        )
    try:
        # Let the capture path warm up before speaking so the question isn't clipped.
        time.sleep(tts_delay)
        if question:
            _log(f'▶ speaking: "{question}"')
            if stimulus_audio_path:
                subprocess.run(["afplay", stimulus_audio_path], check=True)
            else:
                subprocess.run(
                    ["say", "-v", voice, "-r", str(rate), question], check=True
                )
        rec.wait(timeout=seconds + 30)
    finally:
        if rec.poll() is None:
            rec.terminate()
            try:
                rec.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rec.kill()
    if rec.returncode != 0:
        detail = rec.stderr.read().strip() if rec.stderr else ""
        raise RuntimeError(f"microphone recorder failed: {detail}")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            native_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            out_path,
        ],
        check=True,
    )
    os.unlink(native_path)


def transcribe_assemblyai(wav_path: str, api_key: str) -> str:
    with open(wav_path, "rb") as fh:
        audio = fh.read()
    up = urllib.request.Request(
        f"{AAI_BASE}/upload",
        data=audio,
        headers={"authorization": api_key, "content-type": "application/octet-stream"},
    )
    upload_url = json.load(urllib.request.urlopen(up, timeout=120))["upload_url"]
    req = urllib.request.Request(
        f"{AAI_BASE}/transcript",
        data=json.dumps({"audio_url": upload_url, "punctuate": True}).encode(),
        headers={"authorization": api_key, "content-type": "application/json"},
    )
    tid = json.load(urllib.request.urlopen(req, timeout=60))["id"]
    poll = urllib.request.Request(
        f"{AAI_BASE}/transcript/{tid}", headers={"authorization": api_key}
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        data = json.load(urllib.request.urlopen(poll, timeout=60))
        status = data.get("status")
        if status == "completed":
            return data.get("text") or "(empty transcript)"
        if status == "error":
            raise RuntimeError(f"AssemblyAI error: {data.get('error')}")
        time.sleep(2)
    raise RuntimeError("AssemblyAI transcription timed out")


def transcribe_mlx(wav_path: str, model_id: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            [
                "mlx_whisper",
                wav_path,
                "--model",
                model_id,
                "--language",
                "en",
                "--output-dir",
                td,
                "--output-format",
                "txt",
            ],
            check=True,
        )
        base = os.path.splitext(os.path.basename(wav_path))[0]
        with open(os.path.join(td, base + ".txt")) as fh:
            return fh.read().strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Acoustic field-test probe.")
    ap.add_argument(
        "question", nargs="?", help="Stimulus to speak. Omit with --no-tts."
    )
    ap.add_argument("--no-tts", action="store_true", help="Record + transcribe only.")
    ap.add_argument("--seconds", type=float, default=45.0, help="Total record seconds.")
    ap.add_argument(
        "--tts-delay", type=float, default=1.2, help="Seconds before speaking."
    )
    ap.add_argument(
        "--device", default="1", help="FFmpeg fallback audio input index."
    )
    ap.add_argument(
        "--capture",
        choices=["coreaudio", "ffmpeg"],
        default="coreaudio",
        help="Microphone capture backend (default: native Core Audio).",
    )
    ap.add_argument(
        "--tts",
        choices=["cartesia", "macos"],
        default="cartesia",
        help="Host stimulus TTS (default: realistic Cartesia voice).",
    )
    ap.add_argument("--voice", default="Samantha", help="macOS `say` fallback voice.")
    ap.add_argument("--rate", type=int, default=175, help="Speech rate wpm.")
    ap.add_argument(
        "--cartesia-voice-id",
        default=os.getenv("OPENBASE_E2E_CARTESIA_VOICE_ID", DEFAULT_CARTESIA_VOICE_ID),
    )
    ap.add_argument(
        "--cartesia-model-id",
        default=os.getenv("OPENBASE_E2E_CARTESIA_MODEL_ID", DEFAULT_CARTESIA_MODEL_ID),
    )
    ap.add_argument(
        "--cartesia-version",
        default=os.getenv("OPENBASE_E2E_CARTESIA_VERSION", DEFAULT_CARTESIA_VERSION),
    )
    ap.add_argument("--stt", choices=["assemblyai", "mlx"], default="assemblyai")
    ap.add_argument(
        "--mlx-model",
        default=os.getenv("OPENBASE_E2E_MLX_MODEL_ID", DEFAULT_MLX_MODEL_ID),
        help="mlx-whisper model used by the local STT fallback.",
    )
    ap.add_argument("--out", default="", help="Keep the wav at this path.")
    args = ap.parse_args()

    if not args.no_tts and not args.question:
        ap.error("provide a question, or pass --no-tts")

    key = os.getenv("ASSEMBLYAI_API_KEY") or os.getenv("ASSEMBLY_AI_API_KEY")
    if args.stt == "assemblyai" and not key:
        _log("No $ASSEMBLYAI_API_KEY set. Set it, or pass --stt mlx.")
        return 2

    cartesia_key = os.getenv("OPENBASE_E2E_CARTESIA_API_KEY") or os.getenv(
        "CARTESIA_API_KEY"
    )
    if not args.no_tts and args.tts == "cartesia" and not cartesia_key:
        _log(
            "No $CARTESIA_API_KEY set. Provide only that key, or pass --tts macos."
        )
        return 2

    wav = args.out or tempfile.mktemp(suffix=".wav")
    stimulus_audio_path = None
    if not args.no_tts and args.tts == "cartesia":
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as stimulus:
            stimulus_audio_path = stimulus.name
        _log(f"◆ synthesizing realistic stimulus via Cartesia {args.cartesia_model_id}")
        synthesize_cartesia(
            text=args.question,
            api_key=cartesia_key,
            voice_id=args.cartesia_voice_id,
            model_id=args.cartesia_model_id,
            version=args.cartesia_version,
            out_path=stimulus_audio_path,
        )
    _log(f"● recording {args.seconds:.0f}s from audio device :{args.device} → {wav}")
    try:
        record_and_speak(
            question=None if args.no_tts else args.question,
            seconds=args.seconds,
            tts_delay=args.tts_delay,
            device=args.device,
            voice=args.voice,
            rate=args.rate,
            stimulus_audio_path=stimulus_audio_path,
            capture=args.capture,
            out_path=wav,
        )
    finally:
        if stimulus_audio_path:
            os.unlink(stimulus_audio_path)
    if not os.path.exists(wav) or os.path.getsize(wav) < 1024:
        _log("Recording produced no audio (check mic permission / --device).")
        return 3

    _log(f"⧗ transcribing via {args.stt}…")
    text = (
        transcribe_assemblyai(wav, key)
        if args.stt == "assemblyai"
        else transcribe_mlx(wav, args.mlx_model)
    )
    print("\n=== TRANSCRIPT ===")
    print(text)
    if not args.out:
        os.unlink(wav)
    return 0


if __name__ == "__main__":
    sys.exit(main())

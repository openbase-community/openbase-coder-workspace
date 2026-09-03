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
  export ASSEMBLYAI_API_KEY=...              # once per shell
  acoustic-probe.py "What is seven times six?"
  acoustic-probe.py "Start a super agent that lists my repos" --seconds 25
  acoustic-probe.py --no-tts --seconds 12    # just capture + transcribe

Requires: ffmpeg (brew), macOS `say`. Host mic device defaults to the built-in
MacBook Pro Microphone; list devices with `ffmpeg -f avfoundation
-list_devices true -i ""` and override with --device.
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

AAI_BASE = "https://api.assemblyai.com/v2"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def record_and_speak(
    *,
    question: str | None,
    seconds: float,
    tts_delay: float,
    device: str,
    voice: str,
    rate: int,
    out_path: str,
) -> None:
    """Record `seconds` of host mic to out_path, speaking `question` shortly in."""
    # avfoundation: ":<idx>" selects audio-only input by index. Mono 16 kHz keeps
    # the upload small and matches what STT expects.
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
            "-ac",
            "1",
            "-ar",
            "16000",
            out_path,
        ],
        stdin=subprocess.DEVNULL,
    )
    try:
        # Let avfoundation warm up before speaking so the question isn't clipped.
        time.sleep(tts_delay)
        if question:
            _log(f'▶ speaking: "{question}"')
            subprocess.run(["say", "-v", voice, "-r", str(rate), question], check=False)
        rec.wait(timeout=seconds + 30)
    finally:
        if rec.poll() is None:
            rec.terminate()
            try:
                rec.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rec.kill()


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


def transcribe_mlx(wav_path: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            ["mlx_whisper", wav_path, "--output-dir", td, "--output-format", "txt"],
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
    ap.add_argument("--seconds", type=float, default=16.0, help="Total record seconds.")
    ap.add_argument(
        "--tts-delay", type=float, default=1.2, help="Seconds before speaking."
    )
    ap.add_argument(
        "--device", default="1", help="avfoundation audio input index (1=MacBook mic)."
    )
    ap.add_argument("--voice", default="Daniel", help="macOS `say` voice (neutral).")
    ap.add_argument("--rate", type=int, default=175, help="Speech rate wpm.")
    ap.add_argument("--stt", choices=["assemblyai", "mlx"], default="assemblyai")
    ap.add_argument("--out", default="", help="Keep the wav at this path.")
    args = ap.parse_args()

    if not args.no_tts and not args.question:
        ap.error("provide a question, or pass --no-tts")

    key = os.getenv("ASSEMBLYAI_API_KEY") or os.getenv("ASSEMBLY_AI_API_KEY")
    if args.stt == "assemblyai" and not key:
        _log("No $ASSEMBLYAI_API_KEY set. Set it, or pass --stt mlx.")
        return 2

    wav = args.out or tempfile.mktemp(suffix=".wav")
    _log(f"● recording {args.seconds:.0f}s from audio device :{args.device} → {wav}")
    record_and_speak(
        question=None if args.no_tts else args.question,
        seconds=args.seconds,
        tts_delay=args.tts_delay,
        device=args.device,
        voice=args.voice,
        rate=args.rate,
        out_path=wav,
    )
    if not os.path.exists(wav) or os.path.getsize(wav) < 1024:
        _log("Recording produced no audio (check mic permission / --device).")
        return 3

    _log(f"⧗ transcribing via {args.stt}…")
    text = (
        transcribe_assemblyai(wav, key)
        if args.stt == "assemblyai"
        else transcribe_mlx(wav)
    )
    print("\n=== TRANSCRIPT ===")
    print(text)
    if not args.out:
        os.unlink(wav)
    return 0


if __name__ == "__main__":
    sys.exit(main())

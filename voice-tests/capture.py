#!/usr/bin/env python3
"""Capture a scheduled acoustic voice scenario using the shared field-test probe."""
from __future__ import annotations

import argparse
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import subprocess
import shutil
import time
import uuid
import sys
from acoustic_session import acoustic_session

from segment_fixture import synthesize_fixture
from readiness import valid_permit
from clock_probe import sample_vm_clock, calibration_from_samples

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("acoustic_probe", ROOT / ".agents/skills/field-testing/scripts/acoustic-probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def credentials(path: Path | None) -> dict[str, str]:
    names = {"CARTESIA_API_KEY", "ASSEMBLYAI_API_KEY", "ASSEMBLY_AI_API_KEY"}
    values = {}
    if path:
        for line in path.read_text().splitlines():
            name, sep, value = line.removeprefix("export ").partition("=")
            if sep and name.strip() in names:
                values[name.strip()] = value.strip().strip("\"'")
    values.update({name: os.environ[name] for name in names if os.environ.get(name)})
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, help="JSON: seconds and stimuli [{at_s,text}]")
    parser.add_argument("output", type=Path, help="Ignored report artifact directory")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--reuse-stimuli", type=Path, help="Replay exact WAV fixtures from a prior capture with identical stimulus texts")
    parser.add_argument("--prepare-only", action="store_true", help="Synthesize immutable reusable fixtures without recording or playing them")
    parser.add_argument("--vm", help="Bracket the recording with causal guest clock probes")
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text())
    seconds = float(scenario["seconds"])
    stimuli = scenario.get("stimuli", [])
    if args.reuse_stimuli:
        fixture = json.loads((args.reuse_stimuli / "scenario.json").read_text())
        if [s["text"] for s in fixture.get("stimuli", [])] != [s["text"] for s in stimuli]:
            raise ValueError("Reused audio fixture texts do not match this scenario")
    if seconds <= 0 or any(float(s["at_s"]) < 0 or float(s["at_s"]) >= seconds for s in stimuli):
        raise ValueError("Stimuli must start inside the positive recording interval")
    if [s["at_s"] for s in stimuli] != sorted(s["at_s"] for s in stimuli):
        raise ValueError("Stimuli must be ordered by at_s")
    keys = credentials(args.credentials_file)
    cartesia = keys.get("CARTESIA_API_KEY")
    aai = keys.get("ASSEMBLYAI_API_KEY") or keys.get("ASSEMBLY_AI_API_KEY")
    if not aai or (stimuli and not cartesia and not args.reuse_stimuli):
        raise RuntimeError("Required provider credentials are absent")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "scenario.json").write_text(json.dumps(scenario, indent=2) + "\n")
    stimulus_durations = []
    reuse_provenance = json.loads((args.reuse_stimuli / "stimulus-provenance.json").read_text()) if args.reuse_stimuli else {}
    segment_evidence = reuse_provenance.get("segmented_fixtures", [])
    for index, stimulus in enumerate(stimuli):
        target = args.output / f"stimulus-{index}.wav"
        if args.reuse_stimuli:
            shutil.copyfile(args.reuse_stimuli / target.name, target)
            expected = next((item["sha256"] for item in reuse_provenance.get("fixtures", []) if item["index"] == index), None)
            if expected and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("Reused stimulus WAV differs from its retained digest")
        else:
            def synthesize(text, path):
                probe.synthesize_cartesia(text=text, api_key=cartesia,
                    voice_id=probe.DEFAULT_CARTESIA_VOICE_ID, model_id=probe.DEFAULT_CARTESIA_MODEL_ID,
                    version=probe.DEFAULT_CARTESIA_VERSION, out_path=str(path))
            segments = synthesize_fixture(stimulus, target, synthesize)
            if segments:
                segment_evidence.append({"index": index, "segments": segments,
                    "timing_basis": "Sample offsets in fixture WAV; process launch is not exact acoustic onset"})
        # Cartesia emits floating-point WAV, which Python's wave module cannot read.
        stimulus_durations.append(float(subprocess.check_output(["ffprobe", "-v", "error",
            "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
            str(args.output / f"stimulus-{index}.wav")], text=True)))
    (args.output / "stimulus-provenance.json").write_text(json.dumps({
        "reused": bool(args.reuse_stimuli), "segmented_fixtures": segment_evidence, "fixtures": [{"index": i, "duration_s": d,
            "sha256": hashlib.sha256((args.output / f"stimulus-{i}.wav").read_bytes()).hexdigest()}
            for i, d in enumerate(stimulus_durations)]}, indent=2) + "\n")
    if args.prepare_only:
        print("Prepared reusable fixtures; no recording or acoustic playback started")
        return
    native = args.output / "room.native.wav"
    clock = args.output / "capture-clock.json"
    events = args.output / "host-events.jsonl"
    gates = args.output / "gates"
    gates.mkdir()
    clock_samples = sample_vm_clock(ROOT / "install-tests/electron-macos/guest-automate.sh", args.vm) if args.vm else []
    if clock_samples:
        (args.output / "clock-calibration.json").write_text(json.dumps(calibration_from_samples(clock_samples), indent=2) + "\n")

    def event(kind: str, **fields) -> None:
        with events.open("a") as output:
            output.write(json.dumps({"source": "host", "event": kind,
                "unix_ms": time.time_ns() / 1e6, "monotonic_ns": time.monotonic_ns(), **fields}) + "\n")

    with (args.output / "recorder-stderr.txt").open("w") as stderr:
        rec = subprocess.Popen(["swift", str(probe.NATIVE_RECORDER), str(native), str(seconds), str(clock)],
            stdout=subprocess.PIPE, stderr=stderr, text=True)
        scenario_failure = None
        try:
            if rec.stdout.readline().strip() != "READY":
                raise RuntimeError("Recorder failed; inspect recorder-stderr.txt")
            start = time.monotonic()
            event("recorder_ready")
            for index, stimulus in enumerate(stimuli):
                delay = start + float(stimulus["at_s"]) - time.monotonic()
                if delay < -0.1:
                    event("schedule_delayed", index=index, delay_ms=-delay * 1000)
                time.sleep(max(0, delay))
                stimulus_seconds = stimulus_durations[index]
                deadline_s = seconds - stimulus_seconds - float(scenario.get("response_tail_s", 10))
                if stimulus.get("mode", "ordinary") != "overlap":
                    nonce = uuid.uuid4().hex
                    request = {"index": index, "nonce": nonce, "text": stimulus["text"], "required": "fresh native listening + mic enabled + speaker verified"}
                    (gates / f"request-{index}.json").write_text(json.dumps(request, indent=2) + "\n")
                    event("readiness_gate_requested", index=index, nonce=nonce)
                    print(f"Waiting for native readiness permit: {gates / f'permit-{index}.json'}", flush=True)
                    permit_path = gates / f"permit-{index}.json"
                    while True:
                        if time.monotonic() - start >= deadline_s:
                            raise TimeoutError("No fresh native readiness permit before recording deadline; stimulus was not played")
                        if permit_path.exists():
                            permit = json.loads(permit_path.read_text())
                            if valid_permit(permit, nonce):
                                event("readiness_gate_permitted", index=index, proof=permit)
                                break
                        time.sleep(.02)
                else:
                    event("intentional_overlap_stimulus", index=index)
                if time.monotonic() - start >= deadline_s:
                    raise TimeoutError("Recording has insufficient stimulus and response time; stimulus was not played")
                event("playback_process_start", index=index, text=stimulus["text"])
                print(f"Stimulus {index}: {stimulus['text']}", flush=True)
                subprocess.run(["afplay", str(args.output / f"stimulus-{index}.wav")], check=True)
                event("playback_process_end", index=index)
        except (TimeoutError, RuntimeError, subprocess.CalledProcessError) as failure:
            # Keep the full acoustic and clock evidence even when a gate rejects a test.
            scenario_failure = failure
            event("scenario_aborted", error_type=type(failure).__name__, reason=str(failure))
            (args.output / "assessment.json").write_text(json.dumps({"status": "harness_error", "finding": str(failure)}, indent=2) + "\n")
        finally:
            rec.wait(timeout=seconds + 30)
            if rec.returncode:
                raise RuntimeError("Recorder failed; inspect recorder-stderr.txt")
    event("recording_complete")
    if args.vm:
        clock_samples += sample_vm_clock(ROOT / "install-tests/electron-macos/guest-automate.sh", args.vm)
        (args.output / "clock-calibration.json").write_text(json.dumps(calibration_from_samples(clock_samples), indent=2) + "\n")
    wav = args.output / "room.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(native),
        "-ac", "1", "-ar", "16000", str(wav)], check=True)
    result = probe.transcribe_assemblyai_details(str(wav), aai)
    # Upload URLs are unnecessary in durable evidence; retain words and model provenance.
    details = {k: result.get(k) for k in ("text", "words", "utterances", "confidence", "speech_model_used", "audio_duration")}
    (args.output / "transcript.json").write_text(json.dumps(details, indent=2) + "\n")
    print(details["text"], flush=True)
    if scenario_failure:
        raise scenario_failure


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        main()
    else:
        with acoustic_session(ROOT / ".local/field-tests/acoustic-session.lock"):
            main()

#!/usr/bin/env python3
"""Approve a gate from a fresh, saved Appium native snapshot; no phone UI calls."""
import argparse
import json
from pathlib import Path
import time

from readiness import ios_ready, android_ready, ios_speaker_enabled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--platform", choices=("ios", "android"), default="ios")
    parser.add_argument("--speaker-verified", action="store_true", required=True,
        help="Observer verified selected speaker styling since the latest call restart")
    args = parser.parse_args()
    age_ms = (time.time() - args.snapshot.stat().st_mtime) * 1000
    request = json.loads(args.request.read_text())
    ready = {"ios": ios_ready, "android": android_ready}[args.platform](args.snapshot.read_text())
    if args.platform == 'ios':
        ready = ready and ios_speaker_enabled(args.snapshot.read_text())
    if not 0 <= age_ms <= 1500 or not ready:
        reason = "Snapshot is stale, not listening, or microphone is muted; no stimulus permitted"
        with (args.request.parent.parent / "host-events.jsonl").open("a") as output:
            output.write(json.dumps({"source": "host", "event": "readiness_gate_rejected",
                "unix_ms": time.time_ns() / 1e6, "index": request["index"], "nonce": request["nonce"],
                "platform": args.platform, "snapshot": args.snapshot.name, "reason": reason}) + "\n")
        raise ValueError(reason)
    permit = {"nonce": request["nonce"], "allow": True, "observed_at_unix_ms": args.snapshot.stat().st_mtime_ns / 1e6,
        "microphone_enabled": True, "phone_state": "listening", "speaker_verified": True,
        "platform": args.platform, "snapshot": args.snapshot.name}
    target = args.request.with_name(f"permit-{request['index']}.json")
    temp = target.with_suffix(".new")
    temp.write_text(json.dumps(permit, indent=2) + "\n")
    temp.replace(target)


if __name__ == "__main__":
    main()

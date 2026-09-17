#!/usr/bin/env python3
"""Approve a gate from a fresh, saved Appium native snapshot; no phone UI calls."""
import argparse
import json
from pathlib import Path
import time

from readiness import ios_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--speaker-verified", action="store_true", required=True,
        help="Observer verified selected speaker styling since the latest call restart")
    args = parser.parse_args()
    age_ms = (time.time() - args.snapshot.stat().st_mtime) * 1000
    if not 0 <= age_ms <= 1500 or not ios_ready(args.snapshot.read_text()):
        raise ValueError("Snapshot is stale, not listening, or microphone is muted; no stimulus permitted")
    request = json.loads(args.request.read_text())
    permit = {"nonce": request["nonce"], "allow": True, "observed_at_unix_ms": args.snapshot.stat().st_mtime_ns / 1e6,
        "microphone_enabled": True, "phone_state": "listening", "speaker_verified": True, "snapshot": args.snapshot.name}
    target = args.request.with_name(f"permit-{request['index']}.json")
    temp = target.with_suffix(".new")
    temp.write_text(json.dumps(permit, indent=2) + "\n")
    temp.replace(target)


if __name__ == "__main__":
    main()

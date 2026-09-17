#!/usr/bin/env python3
"""Collect bounded VM/phone evidence and causal VM-to-host clock bounds."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from clock_probe import sample_vm_clock, calibration_from_samples

ROOT = Path(__file__).resolve().parents[1]
GUEST = ROOT / "install-tests/electron-macos/guest-automate.sh"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vm")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--ios", action="store_true", help="Request an iPhone log upload and await the file append")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)

    def ssh(command):
        return subprocess.check_output([str(GUEST), "ssh", args.vm, command], text=True, stderr=subprocess.PIPE)

    samples = sample_vm_clock(GUEST, args.vm)
    previous_calibration = args.directory / "clock-calibration.json"
    if previous_calibration.exists():
        samples = json.loads(previous_calibration.read_text()).get("samples", []) + samples
    calibration = calibration_from_samples(samples)
    calibration["measured_at"] = datetime.now(timezone.utc).isoformat()
    (args.directory / "clock-calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    if args.ios:
        def size():
            return int(ssh("stat -f %z ~/.openbase/logs/ios-app.log 2>/dev/null || echo 0").strip())
        try:
            previous = size()
            ssh("~/.local/bin/openbase-coder user ios upload-logs")
            deadline = time.monotonic() + 15
            while size() <= previous:
                if time.monotonic() >= deadline:
                    raise TimeoutError("iPhone acknowledged the command but no diagnostics upload completed")
                time.sleep(.5)
            # An upload must never overwrite the more complete native journal.
            target = "ios-upload.jsonl" if (args.directory / "ios.jsonl").exists() else "ios.jsonl"
            (args.directory / target).write_text(ssh("tail -c 1500000 ~/.openbase/logs/ios-app.log"))
        except (subprocess.CalledProcessError, TimeoutError) as error:
            (args.directory / "collection-errors.json").write_text(json.dumps({"ios_upload": type(error).__name__,
                "finding": "Upload unavailable; collecting VM records anyway. Obtain the native journal through Appium."}, indent=2) + "\n")
    # Only needed timing records enter the report. Never collect raw ASGI access URLs.
    livekit = ssh("tail -c 2000000 ~/.openbase/logs/livekit-agent.log")
    lines = []
    for line in livekit.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "dispatch_timing" in record.get("message", ""):
            # Reject credential-bearing records rather than relying on an incomplete secret regex.
            if re.search(r"(?i)bearer\s|[?&](?:token|access_token|session_token)=|authorization[=:]", record["message"]):
                continue
            lines.append(json.dumps(record))
    django = ssh("tail -c 2000000 ~/.openbase/logs/django-cli.log")
    for line in django.splitlines():
        match = re.search(r"INFO (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) \S+ (dispatch_timing stage=ios_control_round_trip .*)", line)
        if match:
            timestamp = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc).isoformat()
            lines.append(json.dumps({"timestamp": timestamp, "message": match[2]}))
    (args.directory / "server.log").write_text("\n".join(lines) + "\n")
    print("Collected bounded timing records; VM clock uncertainty ±%.1f ms" % calibration["server"]["uncertainty_ms"])


if __name__ == "__main__":
    main()

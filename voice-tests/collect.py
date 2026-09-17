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
from guest import read_guest
from provider_failures import failure_record

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
        return read_guest(GUEST, args.vm, command)

    samples = sample_vm_clock(GUEST, args.vm)
    previous_calibration = args.directory / "clock-calibration.json"
    if previous_calibration.exists():
        samples = json.loads(previous_calibration.read_text()).get("samples", []) + samples
    calibration = calibration_from_samples(samples)
    calibration["measured_at"] = datetime.now(timezone.utc).isoformat()
    (args.directory / "clock-calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    if args.ios:
        attempt = {"source":"host", "event":"ios_diagnostics_upload_requested", "unix_ms":time.time_ns()/1e6}
        def size():
            return int(ssh("stat -f %z ~/.openbase/logs/ios-app.log 2>/dev/null || echo 0").strip())
        try:
            previous = size()
            command = subprocess.run([str(GUEST), "ssh", args.vm,
                "~/.local/bin/openbase-coder user ios upload-logs"], text=True, capture_output=True, timeout=20)
            attempt['receipt_confirmed'] = command.returncode == 0
            attempt['command_exit_code'] = command.returncode
            identifier = re.search(r'ios-app-control-[a-f0-9]{32}', command.stdout)
            if identifier:
                attempt['command_id'] = identifier[0]
            deadline = time.monotonic() + 15
            while size() <= previous:
                if time.monotonic() >= deadline:
                    raise TimeoutError("No diagnostics append observed after the request; receipt may be unconfirmed")
                time.sleep(.5)
            # An upload must never overwrite the more complete native journal.
            target = "ios-upload.jsonl" if (args.directory / "ios.jsonl").exists() else "ios.jsonl"
            (args.directory / target).write_text(ssh("tail -c 1500000 ~/.openbase/logs/ios-app.log"))
            attempt.update(event='ios_diagnostics_append_observed', completed_unix_ms=time.time_ns()/1e6,
                limitation='An append after the request provides diagnostics, but an unconfirmed receipt does not identify which command caused it.')
            error_path = args.directory / 'collection-errors.json'
            if error_path.exists():
                attempt['prior_error'] = json.loads(error_path.read_text())
                error_path.write_text('{}\n')
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, TimeoutError) as error:
            attempt.update(event='ios_diagnostics_upload_unavailable', error=type(error).__name__)
            (args.directory / "collection-errors.json").write_text(json.dumps({"ios_upload": type(error).__name__,
                "finding": "Upload unavailable; collecting VM records anyway. Obtain the native journal through Appium."}, indent=2) + "\n")
        with (args.directory/'collection-attempts.jsonl').open('a') as output:
            output.write(json.dumps(attempt)+'\n')
    # Only needed timing records enter the report. Never collect raw ASGI access URLs.
    livekit = ssh("tail -c 2000000 ~/.openbase/logs/livekit-agent.log")
    lines = []
    for line in livekit.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message", "")
        provider_warning = re.fullmatch(r"AssemblyAI no (?:messages received for \d+s|audio frames sent for [\d.]+s) session=[\w-]+", message)
        failure = failure_record(record)
        if failure is not None:
            lines.append(json.dumps(failure))
        elif provider_warning:
            lines.append(json.dumps({"timestamp": record["timestamp"],
                "message": "dispatch_timing stage=stt_provider_warning detail=" + message.replace(" ", "_")}))
        elif "dispatch_timing" in message:
            # Reject credential-bearing records rather than relying on an incomplete secret regex.
            if re.search(r"(?i)bearer\s|[?&](?:token|access_token|session_token)=|authorization[=:]", record["message"]):
                continue
            lines.append(json.dumps(record))
    django = ssh("tail -c 2000000 ~/.openbase/logs/django-cli.log")
    for line in django.splitlines():
        match = re.search(r"INFO (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) \S+ (dispatch_timing stage=(?:ios_control_round_trip|ios_control_ack_received) .*)", line)
        if match:
            timestamp = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc).isoformat()
            lines.append(json.dumps({"timestamp": timestamp, "message": match[2]}))
    (args.directory / "server.log").write_text("\n".join(lines) + "\n")
    print("Collected bounded timing records; VM clock uncertainty ±%.1f ms" % calibration["server"]["uncertainty_ms"])


if __name__ == "__main__":
    main()

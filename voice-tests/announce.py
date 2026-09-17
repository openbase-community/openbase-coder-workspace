#!/usr/bin/env python3
"""Submit labeled model-free playback probes into an already recording field call."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import threading
import time

from guest import read_guest
from finish import pending_backend_work
from readiness import ios_ready, android_ready

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "install-tests/electron-macos/guest-automate.sh"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vm")
    parser.add_argument("directory", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--platform", choices=("ios", "android"), required=True)
    parser.add_argument("--speaker-verified", action="store_true", help="Route verified visually for this call")
    args = parser.parse_args()
    if not args.speaker_verified:
        raise ValueError("Verify the active call's physical speaker route before submitting probes")
    manifest = json.loads(args.manifest.read_text())
    if args.vm not in manifest["clones"]:
        raise ValueError("Probe requires a declared disposable run clone")
    if pending_backend_work(args.vm):
        raise ValueError("Wait for actual backend work to finish before an ordinary playback probe")
    ready = {"ios": ios_ready, "android": android_ready}[args.platform]
    if not 0 <= time.time() - args.snapshot.stat().st_mtime <= 1.5 or not ready(args.snapshot.read_text()):
        raise ValueError("Fresh native Listening is required before these ordinary playback probes")
    events = args.directory / "host-events.jsonl"
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    seconds = json.loads((args.directory / "scenario.json").read_text())["seconds"]
    start = next(r["unix_ms"] for r in rows if r["event"] == "recorder_ready")
    if any(r["event"] == "recording_complete" for r in rows) or time.time() - start / 1000 > seconds - 120:
        raise ValueError("An active capture with at least two minutes remaining is required")
    scenario = json.loads(args.scenario.read_text())
    program = """import json,sqlite3
from pathlib import Path
stores=list((Path.home()/'.local/share').glob('super-agents-*/state.sqlite3'))
assert len(stores)==1
db=sqlite3.connect('file:'+str(stores[0])+'?mode=ro',uri=True)
print(json.dumps(dict(db.execute('select name,agent_name from sessions where agent_name is not null').fetchall())))"""
    names = json.loads(read_guest(HELPER, args.vm, "python3 -c " + shlex.quote(program)))
    probes = scenario["announcements"]
    if not probes:
        raise ValueError("At least one announcement is required")
    for probe in probes:
        if not names.get(probe["thread"]) or not probe["text"].strip():
            raise ValueError("Each probe requires a registered owner and nonempty labeled text")
    (args.directory / "announcement-scenario.json").write_text(json.dumps(scenario, indent=2) + "\n")
    lock = threading.Lock()

    def event(kind, **metadata):
        with lock, events.open("a") as output:
            output.write(json.dumps({"source": "host", "event": kind,
                "unix_ms": time.time_ns() / 1e6, **metadata}) + "\n")

    def submit(item):
        index, probe = item
        name = names[probe["thread"]]
        event("announcement_command_start", index=index, thread=probe["thread"],
            agent_name=name, text=probe["text"], speaker_verified=True,
            timing_basis="Model-free diagnostic submission, not acoustic onset")
        command = "~/.local/bin/openbase-coder user say " + shlex.join([name, probe["text"]])
        try:
            result = subprocess.run([str(HELPER), "ssh", args.vm, command], text=True,
                capture_output=True, timeout=75)
        except subprocess.TimeoutExpired:
            event("announcement_command_end", index=index, exit_code=None,
                outcome="unconfirmed", reason="SSH command deadline; observe native state before any retry")
            return 1
        event("announcement_command_end", index=index, exit_code=result.returncode,
            receipt=result.stdout[:500], stderr_file=f"announcement-command-{index}-stderr.txt"
                if result.stderr else None,
            outcome="accepted" if result.returncode == 0 else "unconfirmed")
        if result.stderr:
            # Private run evidence, never copied into tracked documentation.
            (args.directory / f"announcement-command-{index}-stderr.txt").write_text(result.stderr)
        return result.returncode

    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        results = list(pool.map(submit, enumerate(probes)))
    if any(results):
        raise RuntimeError("A submission is unconfirmed; inspect native state before any retry")
    print("Playback probes accepted; actual audible completion and native release remain unverified.")


if __name__ == "__main__":
    main()

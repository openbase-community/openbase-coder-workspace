#!/usr/bin/env python3
"""Record observed source heads and dirty digests without copying private patches."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import re
from guest import read_guest

ROOT = Path(__file__).resolve().parents[1]
GUEST = ROOT / "install-tests/electron-macos/guest-automate.sh"


def source_record(directory):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(directory), *arguments])
    patch = git("diff", "HEAD", "--binary")
    return {"head": git("rev-parse", "HEAD").decode().strip(),
        "branch": git("branch", "--show-current").decode().strip(),
        "tracked_dirty": bool(patch), "tracked_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "untracked_count": len(git("ls-files", "--others", "--exclude-standard").splitlines())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vm")
    parser.add_argument("output", type=Path, help="Ignored observed-runtime provenance JSON")
    parser.add_argument("--guest-workspace", default="~/Developer/openbase-coder-workspace")
    args = parser.parse_args()
    if not re.fullmatch(r"~/[\w./-]+", args.guest_workspace):
        raise ValueError("Guest workspace must be a home-relative path without shell syntax")
    # Run this same function inside the guest; only hashes and revision metadata return.
    import inspect
    program = "import subprocess,hashlib,json\nfrom pathlib import Path\n" + inspect.getsource(source_record)
    program += "\nroot=Path(" + repr(args.guest_workspace) + ").expanduser()\n"
    program += "print(json.dumps({name:source_record(root/name) for name in ('.','cli','super-agents','skills')}))"
    command = '"$HOME"/' + shlex.quote(args.guest_workspace[2:] + "/.venv/bin/python") + " -c " + shlex.quote(program)
    remote = read_guest(GUEST, args.vm, command)
    record = {"observed_at": datetime.now(timezone.utc).isoformat(), "vm": args.vm,
        "vm_source": json.loads(remote),
        "host_source": {name: source_record(ROOT / name) for name in (".", "cli", "super-agents", "skills", "allauth-client-swift", "ios", "android")},
        "limitation": "Host source revisions do not prove which mobile binary is installed. Record signed build and Appium installation evidence separately."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print("Recorded observed guest and host source heads and dirty patch digests")


if __name__ == "__main__":
    main()

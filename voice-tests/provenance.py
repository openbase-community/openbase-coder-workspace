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
from baseline import validate_fixture_assets

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
    parser.add_argument("--asset", action="append", default=[], help="Guest home-relative test asset to hash")
    parser.add_argument("--fixture-manifest", type=Path, help="Require every declared prepared asset to survive the fresh clone")
    args = parser.parse_args()
    expected_assets = json.loads(args.fixture_manifest.read_text()).get("test_assets", {}) if args.fixture_manifest else {}
    assets = sorted(set(args.asset) | set(expected_assets))
    if any(not re.fullmatch(r"[\w./-]+", asset) or asset.startswith("/") or ".." in Path(asset).parts for asset in assets):
        raise ValueError("Assets must be safe guest home-relative paths")
    if not re.fullmatch(r"~/[\w./-]+", args.guest_workspace):
        raise ValueError("Guest workspace must be a home-relative path without shell syntax")
    # Run this same function inside the guest; only hashes and revision metadata return.
    import inspect
    program = "import subprocess,hashlib,json\nfrom pathlib import Path\n" + inspect.getsource(source_record)
    program += "\nroot=Path(" + repr(args.guest_workspace) + ").expanduser()\n"
    program += "sources={name:source_record(root/name) for name in ('.','cli','super-agents','skills')}\n"
    program += "assets={}\n"
    program += "for asset in " + repr(assets) + ":\n p=Path.home()/asset\n assets[asset]={'exists':p.is_file(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None}\n"
    program += "print(json.dumps({'source':sources,'assets':assets}))"
    command = '"$HOME"/' + shlex.quote(args.guest_workspace[2:] + "/.venv/bin/python") + " -c " + shlex.quote(program)
    remote = read_guest(GUEST, args.vm, command)
    observed = json.loads(remote)
    record = {"observed_at": datetime.now(timezone.utc).isoformat(), "vm": args.vm,
        "vm_source": observed["source"], "vm_assets": observed["assets"],
        "host_source": {name: source_record(ROOT / name) for name in (".", "cli", "super-agents", "skills", "allauth-client-swift", "ios", "android")},
        "limitation": "Host source revisions do not prove which mobile binary is installed. Record signed build and Appium installation evidence separately."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    validate_fixture_assets(expected_assets, record["vm_assets"])
    print("Recorded observed guest and host source heads and dirty patch digests")


if __name__ == "__main__":
    main()

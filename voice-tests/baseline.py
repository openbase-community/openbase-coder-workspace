#!/usr/bin/env python3
"""Seal and clone stopped prepared Tart voice fixtures without reinstalling."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def inventory() -> dict:
    return {item["Name"]: item for item in json.loads(subprocess.check_output(["tart", "list", "--format", "json"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seal", "clone"])
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--manifest", type=Path, required=True, help="Ignored operational fixture manifest")
    parser.add_argument("--provenance", type=Path, help="Seal only: JSON containing source revisions and preflight evidence")
    args = parser.parse_args()
    state = inventory()
    if args.destination in state:
        raise ValueError("Destination already exists; never overwrite a retained VM")
    if args.source not in state or state[args.source]["State"].lower() != "stopped":
        raise ValueError("Source must exist and be stopped before cloning")
    if args.action == "seal":
        if not args.provenance:
            raise ValueError("Seal requires reviewed provenance")
        provenance = json.loads(args.provenance.read_text())
        required = ("revisions", "doctor_passed", "cloud_environment", "fixture_account", "desktop_permission_reset")
        if any(key not in provenance for key in required) or not provenance["doctor_passed"]:
            raise ValueError("Provenance lacks required prepared-fixture gates")
        if args.manifest.exists():
            raise ValueError("Manifest already exists; create a versioned baseline")
    else:
        provenance = json.loads(args.manifest.read_text())
        if provenance["baseline"] != args.source:
            raise ValueError("Manifest does not describe the requested baseline")
        # Authenticated clones share a fixture network identity. Only one may run.
        siblings = [name for name in provenance.get("clones", []) if name in state and state[name]["State"].lower() != "stopped"]
        if siblings:
            raise ValueError("Stop the previous fixture clone before creating another")
    subprocess.run(["tart", "clone", args.source, args.destination], check=True)
    now = datetime.now(timezone.utc).isoformat()
    if args.action == "seal":
        provenance.update(baseline=args.destination, sealed_at=now, track="accelerated_voice", clones=[])
    else:
        provenance.setdefault("clones", []).append(args.destination)
        provenance["last_clone_at"] = now
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.manifest.with_suffix(".new")
    temporary.write_text(json.dumps(provenance, indent=2) + "\n")
    temporary.replace(args.manifest)
    print(f"{args.destination}: stopped prepared voice fixture; installation was not tested")


if __name__ == "__main__":
    main()

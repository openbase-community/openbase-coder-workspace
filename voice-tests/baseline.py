#!/usr/bin/env python3
"""Seal and clone stopped prepared Tart voice fixtures without reinstalling."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def validate_observed_provenance(provenance: dict, observed: dict, source: str) -> None:
    if observed.get("vm") != source:
        raise ValueError("Observed runtime belongs to another VM")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(observed["observed_at"])).total_seconds()
    if not 0 <= age <= 1800:
        raise ValueError("Observe the prepared runtime within thirty minutes of sealing")
    names = {"workspace": ".", "cli": "cli", "super-agents": "super-agents"}
    allowed = provenance.get("allowed_tracked_patches", {})
    for name, guest_name in names.items():
        record = observed["vm_source"][guest_name]
        if provenance["revisions"].get(name) != record["head"]:
            raise ValueError(f"Reviewed {name} revision differs from the observed guest")
        if record["tracked_dirty"] and allowed.get(guest_name) != record["tracked_patch_sha256"]:
            raise ValueError(f"Unreviewed tracked guest patch in {name}")


def inventory() -> dict:
    return {item["Name"]: item for item in json.loads(subprocess.check_output(["tart", "list", "--format", "json"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seal", "clone"])
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--manifest", type=Path, required=True, help="Ignored operational fixture manifest")
    parser.add_argument("--provenance", type=Path, help="Seal only: JSON containing source revisions and preflight evidence")
    parser.add_argument("--observed-runtime", type=Path, help="Seal only: fresh provenance.py output from the actual guest")
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
        required = ("revisions", "doctor_passed", "cloud_environment", "fixture_account")
        if any(key not in provenance for key in required) or not provenance["doctor_passed"]:
            raise ValueError("Provenance lacks required prepared-fixture gates")
        permission = provenance.get("desktop_permission_state")
        if permission not in ("reset_for_permission_gate", "granted_for_accelerated_voice"):
            if provenance.get("desktop_permission_reset") is not True:
                raise ValueError("Record an explicit Desktop permission state for the prepared fixture")
            provenance["desktop_permission_state"] = "reset_for_permission_gate"
        if not args.observed_runtime:
            raise ValueError("Seal requires observed guest runtime, not requested revisions")
        observed = json.loads(args.observed_runtime.read_text())
        validate_observed_provenance(provenance, observed, args.source)
        provenance["observed_runtime"] = observed
        if args.manifest.exists():
            raise ValueError("Manifest already exists; create a versioned baseline")
    else:
        provenance = json.loads(args.manifest.read_text())
        if provenance["baseline"] != args.source:
            raise ValueError("Manifest does not describe the requested baseline")
        # Authenticated clones share a fixture network identity. Only one may run.
        relatives = provenance.get("clones", []) + [provenance.get("preparation_vm", "")]
        siblings = [name for name in relatives if name in state and state[name]["State"].lower() != "stopped"]
        if siblings:
            raise ValueError("Stop the previous fixture clone before creating another")
    subprocess.run(["tart", "clone", args.source, args.destination], check=True)
    now = datetime.now(timezone.utc).isoformat()
    if args.action == "seal":
        provenance.update(baseline=args.destination, preparation_vm=args.source, sealed_at=now, track="accelerated_voice", clones=[])
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

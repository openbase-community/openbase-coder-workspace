#!/usr/bin/env python3
"""Shape only a disposable Tart guest; preserve other anchors and pipe IDs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from guest import read_guest

ROOT = Path(__file__).resolve().parents[1]
GUEST = ROOT / "install-tests/electron-macos/guest-automate.sh"
ANCHOR = "com.apple/openbase-voice-field-test"
PIPES = (30341, 30342)
LEASE = "/tmp/openbase-voice-network-owner"


def owned_restore(token, restore):
    # A delayed timer from an old profile must never flush a newer profile.
    return (f'if [ "$(cat {LEASE} 2>/dev/null)" = {shlex.quote(token)} ]; then '
        f"{restore}; /sbin/pfctl -X {token}; rm -f {LEASE}; fi")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "restore", "inspect"))
    parser.add_argument("vm")
    parser.add_argument("directory", type=Path, help="Ignored network evidence directory")
    parser.add_argument("--down-kbit", type=int, default=768)
    parser.add_argument("--up-kbit", type=int, default=256)
    parser.add_argument("--delay-ms", type=int, default=150, help="Delay in each direction")
    parser.add_argument("--loss", type=float, default=.02)
    parser.add_argument("--safety-seconds", type=int, default=600)
    args = parser.parse_args()
    if min(args.down_kbit, args.up_kbit) <= 0 or not 0 <= args.delay_ms <= 2000 or not 0 <= args.loss < 1:
        raise ValueError("Invalid network profile")
    if not 30 <= args.safety_seconds <= 1800:
        raise ValueError("Safety restoration must be 30–1800 seconds")
    args.directory.mkdir(parents=True, exist_ok=True)
    state_path = args.directory / "network-state.json"

    def sudo(command, *, read_only=False):
        # The existing Tart helper owns SSH. The guest password travels on stdin.
        guest_command = "sudo -S -- sh -c " + shlex.quote("set -e; " + command)
        if read_only:
            return read_guest(GUEST, args.vm, guest_command,
                input=os.environ.get("VM_PASS", "admin") + "\n"), ""
        result = subprocess.run([str(GUEST), "ssh", args.vm, guest_command],
            input=os.environ.get("VM_PASS", "admin") + "\n", text=True, capture_output=True, check=True, timeout=30)
        return result.stdout, result.stderr

    restore = (f"/sbin/pfctl -a {ANCHOR} -F all; "
        f"/usr/sbin/dnctl pipe delete {PIPES[0]} 2>/dev/null || true; "
        f"/usr/sbin/dnctl pipe delete {PIPES[1]} 2>/dev/null || true")
    if args.action == "apply":
        if state_path.exists() and not json.loads(state_path.read_text()).get("restored_at"):
            raise ValueError("Restore the recorded network profile before applying another")
        before, warnings = sudo("/sbin/pfctl -s info; /sbin/pfctl -s dummynet; /usr/sbin/dnctl list", read_only=True)
        if 'dummynet-anchor "com.apple/*"' not in before:
            raise ValueError("Guest lacks the standing Apple dummynet anchor; do not replace its main rules")
        if any(re.search(rf"(?m)^0*{pipe}:", before) for pipe in PIPES):
            raise ValueError("Reserved test pipe IDs already exist")
        existing, _ = sudo(f"/sbin/pfctl -a {ANCHOR} -s dummynet", read_only=True)
        if existing.strip():
            raise ValueError("Test anchor already has rules; preserve it and resolve ownership")
        owner, _ = sudo(f"if [ -f {LEASE} ]; then cat {LEASE}; fi", read_only=True)
        if owner.strip():
            raise ValueError("A previous network profile still owns its restoration lease")
        interface, _ = sudo("/sbin/route -n get default | awk '/interface:/{print $2}'", read_only=True)
        interface = interface.strip()
        if not re.fullmatch(r"en\d+", interface):
            raise ValueError("Expected a Tart Ethernet interface")
        # Keep the existing SSH management channel outside the constrained link.
        # Product traffic, including the netmesh tunnel, remains constrained.
        rules = (f"no dummynet quick on {interface} proto tcp from any port 22 to any\n"
            f"no dummynet quick on {interface} proto tcp from any to any port 22\n"
            f"dummynet out quick on {interface} all pipe {PIPES[0]}\n"
            f"dummynet in quick on {interface} all pipe {PIPES[1]}\n")
        rules_file = "/tmp/openbase-voice-network.pf"
        sudo("printf %s " + shlex.quote(rules) + f" > {rules_file}; /sbin/pfctl -n -a {ANCHOR} -f {rules_file}")
        token = None
        state = None
        try:
            configured, configure_warnings = sudo(f"/usr/sbin/dnctl pipe {PIPES[0]} config bw {args.up_kbit}Kbit/s delay {args.delay_ms}ms plr {args.loss}; "
                f"/usr/sbin/dnctl pipe {PIPES[1]} config bw {args.down_kbit}Kbit/s delay {args.delay_ms}ms plr {args.loss}")
            (args.directory / "network-configure.txt").write_text(configured + configure_warnings)
            configured_pipes, _ = sudo("/usr/sbin/dnctl pipe list")
            (args.directory / "network-pipes-before-traffic.txt").write_text(configured_pipes)
            if not all(re.search(rf"(?m)^0*{pipe}:", configured_pipes) for pipe in PIPES):
                raise RuntimeError("Both directional pipes must exist before loading shaping rules")
            enabled, errors = sudo("/sbin/pfctl -E")
            match = re.search(r"Token\s*:\s*(\d+)", enabled + errors)
            if not match:
                raise RuntimeError("PF enable reference token was not returned")
            token = match[1]
            sudo(f"printf %s {shlex.quote(token)} > {LEASE}")
            rollback = owned_restore(token, restore)
            script = f"sleep {args.safety_seconds}; {rollback}"
            pid, _ = sudo("nohup sh -c " + shlex.quote(script) + " </dev/null >/tmp/openbase-voice-network-rollback.log 2>&1 & echo $!")
            state = {"vm": args.vm, "interface": interface, "anchor": ANCHOR, "pipe_ids": PIPES,
                "enable_token": token, "rollback_pid": int(pid.strip()), "applied_at": datetime.now(timezone.utc).isoformat(),
                "profile": {"down_kbit": args.down_kbit, "up_kbit": args.up_kbit, "delay_ms_each_way": args.delay_ms,
                    "configured_loss": args.loss, "safety_seconds": args.safety_seconds}, "before": before}
            state_path.write_text(json.dumps(state, indent=2) + "\n")
            # Arm the independent guest timer before loading any shaping rule.
            sudo(f"/sbin/pfctl -a {ANCHOR} -f {rules_file}")
            output, warnings = sudo(f"/sbin/pfctl -s info; /sbin/pfctl -a {ANCHOR} -s dummynet; /usr/sbin/dnctl list")
            (args.directory / "network-apply.txt").write_text(output + warnings)
        except Exception:
            # Genuine rollback: a partially applied profile must not strand the guest.
            if token:
                # Lease creation may have succeeded even if its SSH acknowledgement failed.
                # Missing lease is also ours here: no profile rules have been loaded yet.
                sudo(f'if [ ! -f {LEASE} ]; then printf %s {shlex.quote(token)} > {LEASE}; fi; ' +
                    owned_restore(token, restore))
            else:
                sudo(restore)
            if state:
                sudo(f"kill {state['rollback_pid']} 2>/dev/null || true")
                state["restored_at"] = datetime.now(timezone.utc).isoformat()
                state["finding"] = "Application failed; owned network configuration rolled back"
                state_path.write_text(json.dumps(state, indent=2) + "\n")
            raise
    elif args.action == "restore":
        state = json.loads(state_path.read_text())
        if state["vm"] != args.vm:
            raise ValueError("Network state belongs to another guest")
        if not state.get("restored_at"):
            sudo(f"kill {state['rollback_pid']} 2>/dev/null || true; " +
                owned_restore(state['enable_token'], restore))
            state["restored_at"] = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps(state, indent=2) + "\n")
    output, warnings = sudo(f"/sbin/pfctl -s info; /sbin/pfctl -a {ANCHOR} -s dummynet; /usr/sbin/dnctl list", read_only=True)
    (args.directory / f"network-{args.action}.txt").write_text(output + warnings)
    print(f"Guest network {args.action} recorded; configured values are not measurements")


if __name__ == "__main__":
    main()

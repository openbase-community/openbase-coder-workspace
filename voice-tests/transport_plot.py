#!/usr/bin/env python3
"""Plot bounded native socket recovery against a recorded VM process pause."""
import argparse
import json
from pathlib import Path
from timeline import events, unix_ms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--paused-at", required=True, help="Recorded VM UTC timestamp")
    parser.add_argument("--resumed-at", required=True, help="Recorded VM UTC timestamp")
    parser.add_argument("--vm-resolution-ms", type=float, default=1000)
    parser.add_argument("--component", default="IOSAppControl")
    args = parser.parse_args()
    calibration = json.loads((args.directory / "clock-bounds.json").read_text())["calibration"]
    if not all(source in calibration for source in ("server", "ios")):
        raise ValueError("Both native phone and VM clocks must be bounded")
    origin = unix_ms(args.paused_at) - calibration["server"]["offset_ms"]
    resumed = unix_ms(args.resumed_at) - calibration["server"]["offset_ms"]
    if resumed <= origin:
        raise ValueError("Resume must follow pause")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(14, 7), sharex=True)
    axes[0].axvspan(0, (resumed-origin)/1000, color="crimson", alpha=.3)
    vm_error = (args.vm_resolution_ms + calibration["server"]["uncertainty_ms"])/1000
    for x in (0, (resumed-origin)/1000):
        axes[0].axvspan(x-vm_error, x+vm_error, color="crimson", alpha=.15)
    axes[0].text(1, .5, "VM API process paused; automatic resume armed before pause")
    axes[0].set_ylabel("VM process")
    retained = []
    for row in events(args.directory):
        source = row["source"]
        if source not in ("ios", "server"):
            continue
        meta = row.get("metadata", {})
        heartbeat = row["event"].startswith("CLI websocket") and meta.get("component") == args.component
        receipt = row["event"] == "received app control command"
        ack = row["event"] == "ios_control_ack_received"
        if not (heartbeat or receipt or ack):
            continue
        corrected = row["unix_ms"] - calibration[source]["offset_ms"]
        x = (corrected-origin)/1000
        if not -20 <= x <= (resumed-origin)/1000+40:
            continue
        axis = axes[1] if heartbeat else axes[2]
        lane = 0 if heartbeat or receipt else 1
        label = row["event"].removeprefix("CLI websocket ")
        color = "crimson" if "timed out" in label else "seagreen"
        axis.errorbar(x, lane, xerr=calibration[source]["uncertainty_ms"]/1000, marker="|", color=color, markersize=15)
        axis.text(x, lane+.12, label, fontsize=9, rotation=25)
        retained.append({**row, "host_corrected_unix_ms":corrected, "pause_relative_s":x})
    for axis in axes:
        axis.set_ylim(-.3, 2.3)
        axis.grid(axis="x", alpha=.25)
    axes[1].set_ylabel("Native phone\nheartbeats")
    axes[2].set_ylabel("Phone receipt /\nVM ACK receipt")
    axes[2].set_xlabel("Seconds relative to VM pause; shaded edges show coarse VM timestamp uncertainty")
    fig.suptitle(f"{args.component}: socket recovery while phone stays foreground; no active voice call\nPhone clock ±{calibration['ios']['uncertainty_ms']:.1f} ms; VM stop/resume resolution {args.vm_resolution_ms:.0f} ms")
    fig.tight_layout()
    for extension in ("svg", "png"):
        fig.savefig(args.directory / ("transport-recovery."+extension), dpi=150)
    plt.close(fig)
    (args.directory / "transport-recovery-events.json").write_text(json.dumps(retained, indent=2)+"\n")


if __name__ == "__main__":
    main()

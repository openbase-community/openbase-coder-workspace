#!/usr/bin/env python3
"""Render acoustic words and independent host/server/phone event clocks."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re


def unix_ms(timestamp: str) -> float:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A timezone is required; never silently use the host timezone")
    return value.timestamp() * 1000


def read_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            # A bounded log tail may start in the middle of a record.
            continue


def events(directory: Path) -> list[dict]:
    rows = list(read_jsonl(directory / "host-events.jsonl"))
    seen = set()
    for record in read_jsonl(directory / "ios.jsonl"):
        entry = record.get("entry", {})
        message = entry.get("message", "")
        if not any(word in message.lower() for word in ("lifecycle", "mute state", "auto-mute", "auto-unmute", "speech started", "speech ended", "silence gap", "received app control command")):
            continue
        identity = json.dumps(entry, sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        metadata = entry.get("metadata", {})
        stamp = entry.get("timestamp")
        if not stamp:
            continue
        rows.append({"source": "ios", "unix_ms": unix_ms(stamp), "event": metadata.get("event", message),
            "metadata": metadata, "timestamp_resolution_ms": 1 if "." in stamp else 1000})
    for record in read_jsonl(directory / "server.log"):
        message = record.get("message", "")
        if "dispatch_timing" not in message or not record.get("timestamp"):
            continue
        fields = dict(re.findall(r"(\w+)=([^\s]*)", message))
        rows.append({"source": "server", "unix_ms": unix_ms(record["timestamp"]),
            "event": fields.get("stage", "dispatch_timing"), "metadata": fields})
    for record in read_jsonl(directory / "android.jsonl"):
        if "unix_ms" in record:
            rows.append({**record, "source": "android"})
    return sorted(rows, key=lambda row: row["unix_ms"])


def phone_clock_bounds(rows: list[dict]) -> dict | None:
    """Bound device minus server offset using causal send/receipt/ack ordering."""
    receipts = {r.get("metadata", {}).get("command_id"): r for r in rows
        if r["source"] == "ios" and r["event"] == "received app control command"}
    bounds = []
    for row in rows:
        meta = row.get("metadata", {})
        receipt = receipts.get(meta.get("command_id"))
        if row["event"] != "ios_control_round_trip" or not receipt or meta.get("delivered") != "True":
            continue
        lower = receipt["unix_ms"] - float(meta["server_ack_unix_ms"])
        upper = receipt["unix_ms"] + receipt.get("timestamp_resolution_ms", 1) - float(meta["server_sent_unix_ms"])
        if lower <= upper:
            bounds.append((lower, upper))
    if not bounds:
        return None
    lower = max(b[0] for b in bounds)
    upper = min(b[1] for b in bounds)
    if lower > upper:
        raise ValueError("Clock bounds conflict; a clock changed or records are mismatched")
    return {"offset_ms": (lower + upper) / 2, "uncertainty_ms": (upper - lower) / 2, "lower_ms": lower, "upper_ms": upper}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory
    clock = json.loads((directory / "capture-clock.json").read_text())
    origin = clock.get("first_sample_unix_ms")
    if origin is None:
        raise ValueError("Recorder has no valid first-sample clock; cannot align this capture")
    duration = clock["duration_ms"] / 1000
    rows = events(directory)
    calibration = json.loads((directory / "clock-calibration.json").read_text()) if (directory / "clock-calibration.json").exists() else {}
    phone_bounds = phone_clock_bounds(rows)
    if phone_bounds:
        server = calibration.get("server")
        if server:
            calibration["ios"] = {"offset_ms": server["offset_ms"] + phone_bounds["offset_ms"],
                "uncertainty_ms": server["uncertainty_ms"] + phone_bounds["uncertainty_ms"]}
    for row in rows:
        correction = calibration.get(row["source"])
        if correction:
            row["native_unix_ms"] = row["unix_ms"]
            row["unix_ms"] -= correction["offset_ms"]
            row["clock_uncertainty_ms"] = correction["uncertainty_ms"]
    rows = [r for r in rows if -2 <= (r["unix_ms"] - origin) / 1000 <= duration + 2]
    (directory / "clock-bounds.json").write_text(json.dumps({"host_mapping": clock["wall_mapping"], "calibration": calibration, "phone_minus_server": phone_bounds}, indent=2) + "\n")
    for row in rows:
        row["capture_relative_s"] = (row["unix_ms"] - origin) / 1000
    (directory / "timeline-events.json").write_text(json.dumps(rows, indent=2) + "\n")
    with (directory / "timeline-events.csv").open("w") as output:
        writer = csv.writer(output)
        writer.writerow(["source", "event", "unix_ms", "capture_relative_s", "metadata"])
        for row in rows:
            writer.writerow([row["source"], row["event"], row["unix_ms"], row["capture_relative_s"], json.dumps(row.get("metadata", {}))])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import wave

    transcript = json.loads((directory / "transcript.json").read_text())
    with wave.open(str(directory / "room.wav")) as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
    sources = [source for source in ("host", "server", "ios", "android") if any(r["source"] == source for r in rows)]
    figure, axes = plt.subplots(2 + len(sources), 1, figsize=(16, 3 + len(sources) * 1.7), sharex=True,
        gridspec_kw={"height_ratios": [1, 1.3] + [1] * len(sources)})
    stride = max(1, rate // 500)
    axes[0].plot(np.arange(0, len(samples), stride) / rate, samples[::stride], linewidth=0.45)
    axes[0].set_ylabel("Room audio")
    words = transcript.get("words") or []
    for index, word in enumerate(words):
        start, end = word["start"] / 1000, word["end"] / 1000
        lane = index % 3
        axes[1].broken_barh([(start, max(.02, end - start))], (lane, .7), facecolors="steelblue")
        axes[1].text(start, lane + .75, word["text"], fontsize=7, rotation=30)
    axes[1].set_ylim(0, 4.5)
    axes[1].set_ylabel("Acoustic words\nASR estimates")
    colors = {"host": "gray", "server": "darkorange", "ios": "seagreen", "android": "purple"}
    for axis, source in zip(axes[2:], sources):
        source_rows = [r for r in rows if r["source"] == source]
        for index, row in enumerate(source_rows):
            x = row["capture_relative_s"]
            lane = index % 3
            axis.plot(x, lane, "|", color=colors[source], markersize=14)
            # Whole-second historic logs are intervals, not millisecond measurements.
            resolution = row.get("timestamp_resolution_ms", 1) / 1000
            uncertainty = row.get("clock_uncertainty_ms", 0) / 1000
            if uncertainty:
                axis.errorbar(x, lane, xerr=uncertainty, color=colors[source], alpha=.3)
            if resolution > .001:
                axis.axvspan(x, x + resolution, alpha=.07, color=colors[source])
            axis.text(x, lane + .1, row["event"], fontsize=6, rotation=35, clip_on=True)
        axis.set_ylabel(source + " UTC")
        axis.set_ylim(-.3, 4.2)
    axes[-1].set_xlabel("Seconds from first recorded sample")
    axes[-1].set_xlim(0, duration)
    for axis in axes:
        axis.grid(axis="x", alpha=.2)
        axis.set_yticks([])
    uncalibrated = [s for s in sources if s != "host" and s not in calibration]
    figure.suptitle(directory.name + " — recorded sound and native event clocks\n"
        f"Uncalibrated clocks: {', '.join(uncalibrated) or 'none'}. Process playback markers are not audible onset. ASR word boundaries ≈ ±400 ms.", fontsize=11)
    figure.tight_layout()
    figure.savefig(directory / "timeline.svg")
    figure.savefig(directory / "timeline.png", dpi=150)


if __name__ == "__main__":
    main()

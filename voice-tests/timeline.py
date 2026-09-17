#!/usr/bin/env python3
"""Render acoustic words and independent host/server/phone event clocks."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re
from clock_probe import calibration_from_samples


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
    for record in list(read_jsonl(directory / "ios.jsonl")) + list(read_jsonl(directory / "ios-upload.jsonl")):
        entry = record.get("entry", record)
        message = entry.get("message", "")
        if not any(word in message.lower() for word in ("lifecycle", "mute state", "auto-mute", "auto-unmute", "remote audio", "received app control command", "local microphone publish returned", "room connection state changed")):
            continue
        identity = json.dumps(entry, sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        metadata = entry.get("metadata", {})
        if message == "local microphone publish returned":
            metadata = {**metadata, "microphone_enabled": metadata.get("enabled")}
            message = "applied mute state"
        stamp = entry.get("timestamp")
        if not stamp:
            continue
        rows.append({"source": "ios", "unix_ms": unix_ms(stamp), "event": metadata.get("event", message),
            "metadata": metadata, "diagnostic_message": message,
            "timestamp_resolution_ms": 1 if "." in stamp else 1000})
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


def phone_clock_bounds(rows: list[dict], *, window: tuple[float, float] | None = None) -> dict | None:
    """Bound device minus server offset using causal send/receipt/ack ordering."""
    receipts = {r.get("metadata", {}).get("command_id"): r for r in rows
        if r["source"] == "ios" and r["event"] == "received app control command"}
    bounds = []
    for row in rows:
        meta = row.get("metadata", {})
        receipt = receipts.get(meta.get("command_id"))
        if row["event"] != "ios_control_round_trip" or not receipt or meta.get("delivered") != "True":
            continue
        if window and not window[0] <= float(meta["server_sent_unix_ms"]) <= window[1]:
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


def device_clock_bounds(samples: list[dict], *, window=None) -> dict:
    result = {}
    for source in {s["source"] for s in samples}:
        matching = sorted([s for s in samples if s["source"] == source
            and (window is None or window[0] <= s["host_before_unix_ms"] <= window[1])],
            key=lambda s: s["host_before_unix_ms"])
        if not matching:
            continue
        batches = []
        for sample in matching:
            if not batches or sample['host_before_unix_ms'] - batches[-1][-1]['host_after_unix_ms'] > 1000:
                batches.append([])
            batches[-1].append(sample)
        intervals = []
        for batch in batches:
            lower = max(s["device_unix_ms"] - s["host_after_unix_ms"] for s in batch)
            upper = min(s["device_unix_ms"] + s.get("timestamp_resolution_ms", 1) - s["host_before_unix_ms"] for s in batch)
            if lower > upper:
                raise ValueError("Device clock bounds conflict within a probe batch")
            intervals.append((lower, upper))
        lower, upper = min(x[0] for x in intervals), max(x[1] for x in intervals)
        result[source] = {"offset_ms": (lower + upper) / 2, "uncertainty_ms": (upper - lower) / 2,
            "method": "envelope of causal Appium/native clock probe batches; assumes no larger excursion between probes"}
    return result


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
    if "samples" in calibration:
        nearby = [s for s in calibration["samples"]
            if origin - 120_000 <= s["host_before_ms"] <= origin + duration * 1000 + 120_000]
        calibration.pop("server", None)
        if nearby:
            calibration["server"] = calibration_from_samples(nearby)["server"]
    # Historical log uploads can span hours of ordinary device clock drift.
    # Calibrate from commands near this capture, not unrelated old calls.
    phone_bounds = phone_clock_bounds(rows, window=(origin - 120_000, origin + duration * 1000 + 120_000))
    if phone_bounds:
        server = calibration.get("server")
        if server:
            calibration["ios"] = {"offset_ms": server["offset_ms"] + phone_bounds["offset_ms"],
                "uncertainty_ms": server["uncertainty_ms"] + phone_bounds["uncertainty_ms"],
                "method": "causal server/phone control brackets plus nearby SSH offset envelope"}
    samples_path = directory / "device-clock-samples.json"
    if samples_path.exists():
        direct = device_clock_bounds(json.loads(samples_path.read_text()),
            window=(origin - 120_000, origin + duration * 1000 + 120_000))
        for source, bound in direct.items():
            if source in calibration:
                existing = calibration[source]
                lower = max(bound["offset_ms"] - bound["uncertainty_ms"], existing["offset_ms"] - existing["uncertainty_ms"])
                upper = min(bound["offset_ms"] + bound["uncertainty_ms"], existing["offset_ms"] + existing["uncertainty_ms"])
                if lower > upper:
                    raise ValueError("Direct and server-mediated device clock bounds conflict")
                bound.update(offset_ms=(lower + upper) / 2, uncertainty_ms=(upper - lower) / 2)
                bound["method"] += "; intersected with server-mediated control brackets"
            calibration[source] = bound
    for row in rows:
        correction = calibration.get(row["source"])
        if correction:
            row["native_unix_ms"] = row["unix_ms"]
            row["unix_ms"] -= correction["offset_ms"]
            row["clock_uncertainty_ms"] = correction["uncertainty_ms"]
    prior_microphones = []
    for source in ("ios", "android"):
        filename = directory / (source + ".jsonl")
        raw = list(read_jsonl(filename))
        # Only a direct durable journal can establish continuous pre-capture history.
        direct = bool(raw) and all("entry" not in r for r in raw)
        before = [r for r in rows if r["source"] == source and r["event"] in (
            "applied mute state", "LiveKit room connection state changed", "call state changed") and r["unix_ms"] < origin]
        if direct and before:
            prior_microphones.append(before[-1])
    rows = prior_microphones + [r for r in rows if 0 <= (r["unix_ms"] - origin) / 1000 <= duration + 2]
    (directory / "clock-bounds.json").write_text(json.dumps({"host_mapping": clock["wall_mapping"], "calibration": calibration, "phone_minus_server": phone_bounds}, indent=2) + "\n")
    for row in rows:
        row["capture_relative_s"] = (row["unix_ms"] - origin) / 1000
    (directory / "timeline-events.json").write_text(json.dumps(rows, indent=2) + "\n")
    with (directory / "timeline-events.csv").open("w") as output:
        writer = csv.writer(output)
        writer.writerow(["source", "event", "unix_ms", "capture_relative_s", "metadata"])
        for row in rows:
            writer.writerow([row["source"], row["event"], row["unix_ms"], row["capture_relative_s"], json.dumps(row.get("metadata", {}))])
    from plots import render
    render(directory, clock, rows, calibration)


if __name__ == "__main__":
    main()

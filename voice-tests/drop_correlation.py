#!/usr/bin/env python3
"""Correlate desktop audio-input starvation with iOS local speech windows.

When the phone roams out of Wi-Fi range mid-sentence the uplink stalls, so the
server's transcriber stops receiving audio and silently drops or chops the
utterance. The two halves of the evidence now live on one clock-aligned
timeline (see ``timeline.events``):

  * desktop ``stt_audio_gap`` events -- the transcriber input starved for
    ``gap_ms`` (from ``cli`` ``audio_diagnostics``); and
  * iOS ``local audio capture callback`` events whose ``above_threshold`` flag
    marks that the microphone was picking up speech at that wall-clock moment
    (the phone-side ground truth; a postprocessing callback, so it survives the
    uplink stall).

A desktop gap that overlaps an iOS speech window is a suspected dropped/chopped
utterance. This is a heuristic correlation, not acoustic ground truth: it
assumes both devices' wall clocks are within ``tolerance_ms`` (NTP-synced, or
narrowed further by the harness clock calibration). It answers "did the words
reach the server?", not "which words".
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from timeline import events

# A transcript stage carrying the text the server actually recognized, used to
# show what landed on either side of a gap.
TRANSCRIPT_EVENTS = frozenset(("stt_final_transcript", "session_user_input_transcribed"))


def _is_true(value) -> bool:
    return str(value).lower() == "true"


def ios_speech_windows(rows):
    """Merge iOS mic callbacks into [start_ms, end_ms] speech-active windows."""
    windows = []
    open_start = None
    last_active = None
    for row in rows:
        if row.get("source") != "ios" or row.get("diagnostic_message") != "local audio capture callback":
            continue
        above = _is_true(row["metadata"].get("above_threshold"))
        stamp = row["unix_ms"]
        if above:
            if open_start is None:
                open_start = stamp
            last_active = stamp
        elif open_start is not None:
            windows.append((open_start, last_active if last_active is not None else stamp))
            open_start = None
            last_active = None
    if open_start is not None:
        windows.append((open_start, last_active if last_active is not None else open_start))
    return windows


def _nearest_transcript(rows, at_ms, *, after: bool):
    best = None
    for row in rows:
        if row.get("source") != "server" or row.get("event") not in TRANSCRIPT_EVENTS:
            continue
        delta = row["unix_ms"] - at_ms
        if after and delta < 0:
            continue
        if not after and delta > 0:
            continue
        if best is None or abs(delta) < abs(best["unix_ms"] - at_ms):
            best = row
    if best is None:
        return None
    meta = best["metadata"]
    return {
        "unix_ms": best["unix_ms"],
        "offset_ms": round(best["unix_ms"] - at_ms),
        "text_excerpt": meta.get("text_excerpt", ""),
        "text_hash": meta.get("text_hash") or meta.get("textHash", ""),
    }


def suspected_drops(rows, tolerance_ms: float = 1500.0):
    """Flag desktop audio gaps that overlap an iOS speech window."""
    windows = ios_speech_windows(rows)
    drops = []
    for row in rows:
        if row.get("source") != "server" or row.get("event") != "stt_audio_gap":
            continue
        try:
            gap_ms = float(row["metadata"].get("gap_ms", 0))
        except (TypeError, ValueError):
            gap_ms = 0.0
        gap_end = row["unix_ms"]
        gap_start = gap_end - gap_ms
        overlap_ms = 0.0
        for start, end in windows:
            lo = max(gap_start, start - tolerance_ms)
            hi = min(gap_end, end + tolerance_ms)
            if hi > lo:
                overlap_ms += hi - lo
        if overlap_ms <= 0:
            continue
        drops.append({
            "gap_start_unix_ms": gap_start,
            "gap_end_unix_ms": gap_end,
            "gap_ms": gap_ms,
            "speech_overlap_ms": round(overlap_ms),
            "stream_id": row["metadata"].get("stream_id", ""),
            "prior_transcript": _nearest_transcript(rows, gap_start, after=False),
            "next_transcript": _nearest_transcript(rows, gap_end, after=True),
        })
    return drops


def report(directory: Path, tolerance_ms: float = 1500.0):
    rows = events(directory)
    drops = suspected_drops(rows, tolerance_ms)
    return {
        "tolerance_ms": tolerance_ms,
        "suspected_drop_count": len(drops),
        "suspected_drops": drops,
        "limitation": "Heuristic wall-clock overlap of desktop stt_audio_gap and "
                      "iOS mic speech windows; assumes NTP-synced clocks within "
                      "tolerance_ms and is diagnostic, not acoustic ground truth.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="captured session directory")
    parser.add_argument("--tolerance-ms", type=float, default=1500.0,
                        help="cross-device clock skew allowance for overlap")
    args = parser.parse_args()
    result = report(args.directory, args.tolerance_ms)
    output = args.directory / "drop-correlation.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(f"{result['suspected_drop_count']} suspected drop(s) -> {output}")


if __name__ == "__main__":
    main()

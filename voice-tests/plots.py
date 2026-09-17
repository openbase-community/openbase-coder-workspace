"""Readable acoustic and lifecycle timelines, including turn-sized detail views."""
import html
import json
import math
from pathlib import Path
import wave


def render(directory: Path, clock: dict, rows: list[dict], calibration: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    origin = clock["first_sample_unix_ms"]
    duration = clock["duration_ms"] / 1000
    words = json.loads((directory / "transcript.json").read_text()).get("words") or []
    secondary_path = directory / "secondary-transcript.json"
    secondary = json.loads(secondary_path.read_text()).get("words", []) if secondary_path.exists() else []
    with wave.open(str(directory / "room.wav")) as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
    microphone = [r for r in rows if (r["event"] == "applied mute state"
        and str(r.get("metadata", {}).get("microphone_enabled")).lower() in ("true", "false"))
        or r["event"] in ("LiveKit room connection state changed", "call state changed")]
    emitted = [r for r in rows if r["source"] == "server" and r["event"] in (
        "voice_lifecycle_packet_published", "stt_final_transcript", "voice_delivery_cancelled", "livekit_llm_input_committed", "stt_provider_stall", "stt_provider_warning",
        "voice_request_received", "voice_delivery_backend_work_preserved_after_consumer_cancel",
        "turn_start_response", "turn_wait_start", "voice_turn_result", "tts_stream_first_audio", "tts_stream_flush")
        or r['source']=='server' and r['event'].startswith('observed super_agents_')]
    received = [r for r in rows if r["source"] in ("ios", "android")
        and (r.get("diagnostic_message", r["event"]) in (
            "received voice lifecycle event", "voice lifecycle received", "ignored stale voice lifecycle event")
            or r["event"].startswith("CLI websocket"))]
    playback = [r for r in rows if r["source"] in ("ios", "android") and "remote audio" in r["event"]]
    host = [r for r in rows if r["source"] == "host" and "playback_process" in r["event"]]
    acoustic = [r for r in rows if r['source']=='host' and r['event'].startswith('estimated acoustic fixture')]
    host_markers = [r for r in rows if r['source'] == 'host' and r['event'] in (
        'readiness_gate_rejected', 'scenario_aborted', 'network_restored', 'network_restore',
        'vm_desktop_permission_allowed', 'call_teardown_acknowledged',
        'competing_network_probe_start', 'competing_network_probe_end',
        'host_analysis_dependency_download_start', 'host_analysis_dependency_download_end')]
    assessment_path = directory / "assessment.json"
    assessment = json.loads(assessment_path.read_text()) if assessment_path.exists() else {}
    invalid = assessment.get("invalid_stimuli", [])
    uncalibrated = sorted({r["source"] for r in rows if r["source"] != "host" and r["source"] not in calibration})

    def draw(start, end, name, detailed):
        fig, axes = plt.subplots(7, 1, figsize=(18, 12), sharex=True,
            gridspec_kw={"height_ratios": [1, 1.4, 1, 1, 1, .65, 1]})
        stride = max(1, rate // 600)
        first, last = max(0, int(start * rate)), min(len(samples), int(end * rate))
        axes[0].plot(np.arange(first, last, stride) / rate, samples[first:last:stride], linewidth=.55)
        axes[0].set_ylabel("Recorded\nroom sound")
        for index, word in enumerate(words):
            x, stop = word["start"] / 1000, word["end"] / 1000
            if x > end or stop < start:
                continue
            lane = index % 3
            axes[1].broken_barh([(x, max(.02, stop - x))], (lane, .7), facecolors="steelblue")
            if detailed:
                axes[1].text(x, lane + .76, word["text"], fontsize=8, rotation=30, clip_on=True)
        for word in secondary:
            x, stop = word["start"] / 1000, word["end"] / 1000
            if x <= end and stop >= start:
                axes[1].broken_barh([(x, max(.02, stop - x))], (3, .6), facecolors="seagreen", alpha=.6)
                if detailed:
                    axes[1].text(x, 3.65, "DG " + word["text"], fontsize=7, rotation=30, clip_on=True)
        axes[1].set_ylim(0, 4.7 if secondary else 4.2)
        axes[1].set_ylabel("ASR words\nblue: primary\ngreen: secondary")
        for row in host:
            if row["event"] != "playback_process_start":
                continue
            x = row["capture_relative_s"]
            stops = [r["capture_relative_s"] for r in host if r["event"] == "playback_process_end" and r.get("index") == row.get("index")]
            stop = min(stops) if stops else duration
            color = "crimson" if row.get("index") in invalid else "slategray"
            axes[2].axvspan(x, stop, color=color, alpha=.25)
            if start <= x <= end:
                label = f"Host stimulus {row.get('index')}" + (" — HARNESS ERROR" if row.get("index") in invalid else "")
                axes[2].text(x, .3, label, fontsize=9, color=color, clip_on=True)
        for row in acoustic:
            if row['event'] != 'estimated acoustic fixture signal_start':
                continue
            x=row['capture_relative_s']
            stops=[r['capture_relative_s'] for r in acoustic
                if r['event']=='estimated acoustic fixture signal_end'
                and r['metadata']['index']==row['metadata']['index']]
            if not stops:
                continue
            axes[2].broken_barh([(x,min(stops)-x)],(.03,.13),facecolors='teal')
            if detailed and start<=x<=end:
                axes[2].text(x,.82,'Room waveform match (estimate)',fontsize=8,color='teal',clip_on=True)
        axes[2].set_ylabel("Host process /\nwaveform estimate")
        for row in host_markers:
            x = row['capture_relative_s']
            if start <= x <= end:
                axes[2].axvline(x, color='crimson', linestyle=':', linewidth=1)
                axes[2].text(x, .6, row['event'], fontsize=8, rotation=20, clip_on=True)
        for axis, items, title, color in [(axes[3], emitted, "VM turn /\nlifecycle events", "darkorange"),
                (axes[4], received, "Phone receipt /\nlifecycle handling", "seagreen"),
                (axes[6], playback, "Phone playback\ndiagnostics", "purple")]:
            visible = [r for r in items if start <= r["capture_relative_s"] <= end]
            for index, row in enumerate(visible):
                x, lane = row["capture_relative_s"], index % 3
                label = row.get("metadata", {}).get("event", row["event"])
                if row.get("diagnostic_message") == "ignored stale voice lifecycle event":
                    label = "IGNORED stale " + label
                axis.plot(x, lane, "|", color=color, markersize=14)
                error = row.get("clock_uncertainty_ms", 0) / 1000
                if error:
                    axis.errorbar(x, lane, xerr=error, color=color, alpha=.35)
                noisy = any(word in label for word in ('RTP stats', 'mute_keepalive', 'silence gap', 'playback sample', 'before playback'))
                if "deferred auto-unmute" in label:
                    same = [item for item in visible if item["event"] == row["event"]
                        and item.get("metadata", {}).get("delivery_id") == row.get("metadata", {}).get("delivery_id")]
                    noisy = row is not same[0] and row is not same[-1]
                if detailed and not noisy:
                    short = label.replace('decoded remote audio ', 'PCM ').replace('remote audio ', 'audio ')
                    if row['event'] == 'stt_final_transcript':
                        short = 'STT: ' + row.get('metadata', {}).get('text_excerpt', '')[:45]
                    delivery = row.get('metadata', {}).get('delivery_id', '')
                    if delivery:
                        short += ' [' + delivery[-5:] + ']'
                    axis.text(x, lane + .1, short, fontsize=8, rotation=25, clip_on=True)
            axis.set_ylim(-.3, 4)
            axis.set_ylabel(title)
        if microphone:
            x = [r["capture_relative_s"] for r in microphone]
            def mic_state(row):
                if row['event'] == 'applied mute state':
                    return 1 if str(row['metadata']['microphone_enabled']).lower() == 'false' else 0
                metadata = row.get('metadata', {})
                if metadata.get('connected') is False or metadata.get('to') in ('.disconnected', '.disconnecting'):
                    return 2
                return 3
            y = [mic_state(r) for r in microphone]
            unknown_end = max(0, min(duration, x[0]))
            if start < unknown_end:
                axes[5].axvspan(start, min(end, unknown_end), facecolor="none", edgecolor="gray", hatch="///")
                axes[5].text(start + .3, .4, "UNKNOWN — native mic history missing", color="crimson", clip_on=True)
            axes[5].step(x + [duration], y + [y[-1]], where="post", color="crimson")
            for timestamp, state in zip(x, y):
                if start <= timestamp <= end:
                    axes[5].text(timestamp, state + .12, ['LIVE', 'MUTED', 'IDLE', 'UNKNOWN'][state], fontsize=8, clip_on=True)
            axes[5].set_ylim(-.3, 3.8)
        else:
            axes[5].text(start + .3, .4, "MISSING — no phone microphone application records", color="crimson")
        axes[5].set_ylabel("Phone mic\nactually applied")
        axes[-1].set_xlabel("Seconds from first recorded sample")
        axes[-1].set_xlim(start, end)
        for axis in axes:
            axis.grid(axis="x", alpha=.25)
            axis.set_yticks([])
        fig.suptitle(f"{directory.name} · {start:.0f}–{end:.0f} seconds · {assessment.get('status', 'evidence; not a pass assertion')}\n"
            f"Uncalibrated clocks: {', '.join(uncalibrated) or 'none'}. Error bars show clock bounds. ASR words ≈ ±400 ms. Playback process ≠ audible onset.", fontsize=12)
        fig.tight_layout()
        fig.savefig(directory / f"{name}.svg")
        fig.savefig(directory / f"{name}.png", dpi=120)
        plt.close(fig)

    draw(0, duration, "timeline", duration <= 25)
    pages = []
    for index in range(math.ceil(duration / 20)):
        start, end = index * 20, min(duration, (index + 1) * 20)
        name = f"detail-{index:02}"
        draw(start, end, name, True)
        pages.append(f'<h2>{start:.0f}–{end:.0f} seconds</h2><img src="{name}.svg" alt="Detailed timing lanes">')
    transcripts = ''.join('<tr><td>%.3f s</td><td>%s</td></tr>' % (r['capture_relative_s'],
        html.escape(r.get('metadata',{}).get('text_excerpt',''))) for r in rows
        if r['event']=='stt_final_transcript' and 0 <= r['capture_relative_s'] <= duration)
    (directory / "timeline.html").write_text('<!doctype html><meta charset="utf-8"><title>Voice timing evidence</title>'
        '<style>body{font:16px system-ui;margin:2rem;background:#f5f5f5}img{width:100%;background:white}h2{margin-top:3rem}</style>'
        f'<h1>{html.escape(directory.name)}</h1><p>{html.escape(assessment.get("finding", "Recorded evidence; evaluate native clocks and audible boundaries."))}</p>'
        '<p>Overview, followed by readable 20-second windows. Native timestamps and metadata are in timeline-events.json/CSV.</p><img src="timeline.svg" alt="Overview">'
        '<h2>Words registered by VM STT</h2><p>Final-transcript receipt times; excerpts can be bounded. Compare these with the room-audio word spans.</p><table><tr><th>Capture time</th><th>Registered text</th></tr>'+transcripts+'</table>' + ''.join(pages))

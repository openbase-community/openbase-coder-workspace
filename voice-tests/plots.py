"""Readable acoustic and lifecycle timelines, including turn-sized detail views."""
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
        "announcer_say_start", "announcer_playout_end", "announcer_audio_playout_end",
        "announcer_synthesis_incomplete", "announcer_playout_interrupted",
        "voice_provider_connection_options", "voice_delivery_tts_failed",
        "announcer_publish_request", "announcer_target_resolved", "announcer_send_data_end",
        "announcer_audio_publish_request", "announcer_audio_send_data_end", "announcer_duplicate_ignored",
        "turn_start_response", "turn_wait_start", "voice_turn_result", "tts_stream_first_audio", "tts_stream_flush", "tts_stream_audio_gap", "tts_stream_iter_end", "voice_delivery_playout_release_deferred", "super_agent_steer_interrupt_ack", "super_agent_steer_correction_sent", "super_agent_tool_policy_connected",
        "tts_provider_partial_failure", "tts_provider_inference_failure", "tts_provider_connection_failure",
        "tts_provider_retry", "stt_provider_retry", "stt_provider_connection_closed",
        "voice_session_unrecoverable_failure", "voice_worker_recovery_exit", "voice_worker_recycle", "voice_worker_drain_started", "voice_worker_force_exit", "voice_worker_started", "agent_session_start_complete", "session_close", "session_error")
        or r['source']=='server' and r['event'].startswith(('observed super_agents_', 'observed livekit_room'))]
    received = [r for r in rows if r["source"] in ("ios", "android")
        and (r.get("diagnostic_message", r["event"]) in (
            "received voice lifecycle event", "voice lifecycle received", "ignored stale voice lifecycle event", "ignored duplicate voice lifecycle event",
            "scheduling lifecycle stuck-muted recovery unmute", "scheduled auto-unmute",
            "scheduled lifecycle auto-unmute", "auto-unmute task did not apply",
            "abandoned announcement after audio participant departed")
            or r["event"].startswith("CLI websocket"))]
    playback = [r for r in rows if r["source"] in ("ios", "android") and "remote audio" in r["event"]]
    input_capture = [r for r in rows if r['source'] in ('ios', 'android') and r['event'] == 'local audio capture callback']
    output_path = [r for r in rows if r['source'] in ('ios', 'android') and r['event'] == 'audio output path sample']
    host = [r for r in rows if r["source"] == "host" and "playback_process" in r["event"]]
    acoustic = [r for r in rows if r['source']=='host' and r['event'].startswith('estimated acoustic fixture')]
    host_markers = [r for r in rows if r['source'] == 'host' and r['event'] in (
        'readiness_gate_rejected', 'scenario_aborted', 'network_restored', 'network_restore',
        'vm_desktop_permission_allowed', 'call_teardown_acknowledged',
        'competing_network_probe_start', 'competing_network_probe_end',
        'host_analysis_dependency_download_start', 'host_analysis_dependency_download_end',
        'scheduled_network_restore', 'competing_host_fixture_preparation', 'call_end_gesture_acknowledged',
        'announcement_command_start', 'announcement_command_end', 'operator_stimulus_withheld',
        'speaker_route_verified')]
    assessment_path = directory / "assessment.json"
    assessment = json.loads(assessment_path.read_text()) if assessment_path.exists() else {}
    invalid = assessment.get("invalid_stimuli", [])
    uncalibrated = sorted({r["source"] for r in rows if r["source"] != "host" and r["source"] not in calibration})

    def draw(start, end, name, detailed):
        fig, axes = plt.subplots(9, 1, figsize=(18, 16), sharex=True,
            gridspec_kw={"height_ratios": [1, 1.4, 1, 1, 1, .65, 1, .7, .7]})
        stride = max(1, rate // 600)
        first, last = max(0, int(start * rate)), min(len(samples), int(end * rate))
        axes[0].plot(np.arange(first, last, stride) / rate, samples[first:last:stride], linewidth=.55)
        # Keep quiet noise comparable with speech across every run and detail.
        axes[0].set_ylim(-1, 1)
        segment = samples[first:last]
        rms = float(np.sqrt(np.mean(segment * segment))) if len(segment) else 0
        db = 20 * math.log10(max(rms, 1e-12))
        axes[0].text(start + .2, .72, f"Fixed full-scale amplitude; interval RMS {db:.1f} dBFS",
            fontsize=8, clip_on=True)
        hop = max(1, rate // 50)
        count = len(segment) // hop
        if count:
            envelope = np.sqrt(np.mean(segment[:count * hop].reshape(count, hop) ** 2, axis=1))
            level_axis = axes[0].twinx()
            level_axis.plot((first + np.arange(count) * hop) / rate,
                20 * np.log10(np.maximum(envelope, 1e-12)), color='teal', linewidth=.6, alpha=.7)
            level_axis.set_ylim(-90, 0)
            level_axis.set_yticks([-80, -40, 0])
            level_axis.set_ylabel('20 ms RMS\ndBFS', fontsize=8)
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
                probe = row['event'].startswith('announcement_command_')
                color = 'slateblue' if probe and row.get('outcome') != 'unconfirmed' else 'crimson'
                label = row['event']
                if probe:
                    phase = 'API submission' if row['event'].endswith('start') else row.get('outcome', 'receipt')
                    label = f"Probe {row.get('index')} {phase}"
                lane = .6 + .16 * (row.get('index', 0) % 2) if probe else .6
                axes[2].axvline(x, color=color, linestyle=':', linewidth=1)
                axes[2].text(x, lane, label, fontsize=8, rotation=20, clip_on=True)
        for axis, items, title, color in [(axes[3], emitted, "VM turn /\nlifecycle events", "darkorange"),
                (axes[4], received, "Phone receipt /\nlifecycle handling", "seagreen"),
                (axes[6], playback, "Phone playback\ndiagnostics", "purple")]:
            visible = [r for r in items if start <= r["capture_relative_s"] <= end]
            duplicate_labels = set()
            for index, row in enumerate(visible):
                x, lane = row["capture_relative_s"], index % 4
                label = row.get("metadata", {}).get("event", row["event"])
                if row['event'] in ('session_close', 'announcer_playout_interrupted') or row['event'].startswith('observed livekit_room'):
                    metadata = row.get('metadata', {})
                    identity = metadata.get('roomID') or metadata.get('observed_room_id')
                    if identity:
                        label += ' [' + identity + ']'
                if row.get("diagnostic_message") == "ignored stale voice lifecycle event":
                    label = "IGNORED stale " + label
                if row.get("diagnostic_message") == "ignored duplicate voice lifecycle event":
                    label = "IGNORED duplicate " + label
                axis.plot(x, lane, "|", color=color, markersize=14)
                error = row.get("clock_uncertainty_ms", 0) / 1000
                if error:
                    axis.errorbar(x, lane, xerr=error, color=color, alpha=.35)
                noisy = any(word in label for word in ('RTP stats', 'mute_keepalive', 'silence gap', 'playback sample', 'before playback', 'level sampled'))
                if label.startswith('CLI websocket heartbeat') and not any(word in label for word in ('timeout', 'timed out', 'failed', 'error')):
                    noisy = True
                if label.startswith('IGNORED duplicate '):
                    metadata = row.get('metadata', {})
                    # Every receipt keeps its marker and raw table row; repeated
                    # ignored labels need not obscure accepted transitions.
                    key = (metadata.get('delivery_id'), label)
                    noisy = noisy or key in duplicate_labels
                    duplicate_labels.add(key)
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
                    axis.text(x, lane + .1, short, fontsize=8, rotation=15, clip_on=True)
            axis.set_ylim(-.3, 6)
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
            for row, timestamp, state in zip(microphone, x, y):
                if start <= timestamp <= end:
                    error = row.get('clock_uncertainty_ms', 0) / 1000
                    if error:
                        axes[5].errorbar(timestamp, state, xerr=error, color='crimson', alpha=.4, capsize=3)
            axes[5].set_ylim(-.3, 3.8)
        else:
            axes[5].text(start + .3, .4, "MISSING — no phone microphone application records", color="crimson")
        axes[5].set_ylabel("Phone mic\nactually applied")
        visible_input = [r for r in input_capture if start <= r['capture_relative_s'] <= end]
        numeric_input = [r for r in visible_input if r.get('metadata', {}).get('peak') not in (None, 'unknown')]
        if numeric_input:
            axes[7].scatter([r['capture_relative_s'] for r in numeric_input],
                [float(r['metadata']['peak']) for r in numeric_input], s=12, color='teal')
            for row in numeric_input:
                error = row.get('clock_uncertainty_ms', 0) / 1000
                if error:
                    axes[7].errorbar(row['capture_relative_s'], float(row['metadata']['peak']), xerr=error,
                        color='teal', alpha=.25)
        else:
            label = 'UNKNOWN — input callbacks received; sample format unmeasured' if visible_input else 'MISSING — no phone input callback samples'
            axes[7].text(start + .3, .4, label, color='gray', clip_on=True)
        axes[7].set_ylim(0, 1)
        axes[7].set_ylabel('Phone input peak\npostprocessing\n(not sent ACK)')
        visible_output = [r for r in output_path if start <= r['capture_relative_s'] <= end]
        if visible_output:
            for key, color, label in [('system_output_volume', 'navy', 'System volume'),
                    ('livekit_output_volume', 'darkorange', 'SDK mixer volume')]:
                points = [(r['capture_relative_s'], float(r['metadata'][key])) for r in visible_output
                    if key in r.get('metadata', {})]
                if points:
                    axes[8].step([p[0] for p in points], [p[1] for p in points], where='post', color=color, label=label)
            stopped = [r['capture_relative_s'] for r in visible_output
                if r.get('metadata', {}).get('livekit_engine_running') == 'false']
            if stopped:
                axes[8].scatter(stopped, [.05] * len(stopped), color='crimson', marker='x', label='Engine stopped')
            axes[8].legend(loc='upper right', fontsize=8)
        else:
            axes[8].text(start + .3, .4, 'MISSING — no native output-path samples', color='gray', clip_on=True)
        axes[8].set_ylim(0, 1.15)
        axes[8].set_ylabel('Phone output path\nvolume / engine\n(not acoustic proof)')
        axes[-1].set_xlabel("Seconds from first recorded sample")
        axes[-1].set_xlim(start, end)
        for axis in axes:
            axis.grid(axis="x", alpha=.25)
            axis.set_yticks([])
        axes[5].set_yticks([0, 1, 2, 3], ['LIVE', 'MUTED', 'IDLE', 'UNKNOWN'])
        axes[7].set_yticks([0, .5, 1])
        axes[8].set_yticks([0, .5, 1])
        fig.suptitle(f"{directory.name} · {start:.0f}–{end:.0f} seconds · {assessment.get('status', 'evidence; not a pass assertion')}\n"
            f"Uncalibrated clocks: {', '.join(uncalibrated) or 'none'}. Excluded probes: {len(calibration.get('device_clock_sample_errors', []))} invalid phone, {calibration.get('device_clock_outside_window_count', 0)} distant phone, {calibration.get('server_clock_outside_window_count', 0)} distant VM. Error bars: clock bounds. ASR ≈ ±400 ms. Process ≠ audible onset.", fontsize=12)
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
    from timeline_report import write_report
    write_report(directory, rows, words, secondary, pages, assessment, duration)

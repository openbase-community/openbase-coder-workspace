"""Self-contained HTML review with acoustic seeking and searchable timing evidence."""
import html
import json


def cleanup_plot(rows, duration):
    events = [r for r in rows if r['source'] == 'host'
        and r['event'] in {'recording_complete', 'call_end_gesture_acknowledged'}]
    start = max(0, duration - 20)
    end = max([duration] + [r['capture_relative_s'] for r in events]) + 2
    def x(seconds):
        return 70 + 800 * (seconds - start) / (end - start)
    boundary = x(duration)
    svg = '<svg viewBox="0 0 920 170" role="img" aria-label="Recording boundary and driver cleanup timing"><defs><pattern id="unrecorded" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8L8 0" stroke="#aaa"/></pattern></defs>'
    svg += '<rect x="70" y="40" width="800" height="55" fill="#e6f4ea"/>'
    svg += '<rect x="%.2f" y="40" width="%.2f" height="55" fill="url(#unrecorded)"/>' % (boundary, 870 - boundary)
    svg += '<line x1="%.2f" x2="%.2f" y1="30" y2="100" stroke="#c22" stroke-dasharray="4 3"/><text x="%.2f" y="22" font-size="12">Recorded WAV ends: %.3f s</text>' % (boundary, boundary, max(70, boundary - 180), duration)
    svg += '<text x="70" y="150" font-size="12">%.3f s</text><text x="800" y="150" font-size="12">%.3f s</text>' % (start, end)
    for index, row in enumerate(events):
        seconds = row['capture_relative_s']
        if start <= seconds <= end:
            position = x(seconds)
            svg += '<line x1="%.2f" x2="%.2f" y1="45" y2="100" stroke="#246"/><text x="%.2f" y="%d" font-size="11">%s: %.3f s</text>' % (position, position, min(position, 610), 112 + index * 15, html.escape(row['event']), seconds)
    return svg + '</svg>'


def write_report(directory, rows, words, secondary, pages, assessment, duration):
    unrelated_rooms = sum(r.get('case_room_scope') == 'unrelated_room' for r in rows)
    room_scope_note = '<p>%d unrelated room observations are retained in the searchable event table and JSON, and excluded from this call’s plotted lifecycle lane. Room scope follows the accepted announcement receipt or native current-room name; reconnect generations with that same name remain visible.</p>' % unrelated_rooms
    cleanup_events = {'recorder_ready', 'recording_complete', 'call_end_gesture_acknowledged'}
    cleanup_table = '<h2>Recording boundaries and driver cleanup</h2><p>Cleanup gestures are driver acknowledgments, not native microphone or disconnect acknowledgments. Events after the recording boundary have no acoustic coverage.</p><table><tr><th>Capture seconds</th><th>Event</th><th>Acoustic coverage</th></tr>'
    for row in rows:
        if row['source'] == 'host' and row['event'] in cleanup_events:
            seconds = row['capture_relative_s']
            cleanup_table += '<tr><td>%.3f</td><td>%s</td><td>%s</td></tr>' % (
                seconds, html.escape(row['event']),
                'Inside recording' if 0 <= seconds <= duration else 'Outside recording; unobserved acoustically')
    cleanup_table += '</table><p>Green: recorded interval. Hatched: no acoustic recording.</p>' + cleanup_plot(rows, duration)
    transcripts = ''.join('<tr><td>%.3f s</td><td>%s</td></tr>' % (r['capture_relative_s'],
        html.escape(r.get('metadata',{}).get('text_excerpt',''))) for r in rows
        if r['event']=='stt_final_transcript' and 0 <= r['capture_relative_s'] <= duration)
    event_table = ''.join('<tr><td><button data-seek="%.3f">%.3f</button></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        r['capture_relative_s'],
        r['capture_relative_s'], html.escape(r['source']), html.escape(r['event']),
        html.escape(str(r.get('clock_uncertainty_ms', 'uncalibrated'))),
        html.escape(json.dumps(r.get('metadata', {}), sort_keys=True))) for r in rows
        if 0 <= r['capture_relative_s'] <= duration)
    coverage_path = directory / 'speech-coverage.json'
    coverage_table = ''
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text())
        coverage_table = '<h2>Complete announcement text alignment</h2><p>' + html.escape(coverage['limitation']) + '</p><table><tr><th>Thread</th><th>Expected ASR words matched</th><th>Evidence</th></tr>'
        for probe in coverage['probes']:
            percentage = probe.get('coverage_percent')
            coverage_table += '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                html.escape(probe['thread']), 'unknown' if percentage is None else '%.1f%%' % percentage,
                html.escape(probe['status']))
        coverage_table += '</table><p><a href="speech-coverage.json">Per-word expected text and actual ASR times</a></p>'
    acoustic_words = '<details><summary>Seek recorded ASR words</summary><p>Seek positions are approximate ASR boundaries, with one second of lead-in. Seeking does not start playback.</p><table><tr><th>Provider</th><th>Start seconds</th><th>End seconds</th><th>Word</th></tr>'
    for provider, items in [('Primary', words), ('Secondary', secondary)]:
        for word in items:
            acoustic_words += '<tr><td>%s</td><td><button data-seek="%.3f">%.3f</button></td><td>%.3f</td><td>%s</td></tr>' % (
                provider, word['start'] / 1000, word['start'] / 1000, word['end'] / 1000, html.escape(word['text']))
    acoustic_words += '</table></details>'
    (directory / "timeline.html").write_text('<!doctype html><meta charset="utf-8"><title>Voice timing evidence</title>'
        '<style>body{font:16px system-ui;margin:2rem;background:#f5f5f5}img{width:100%;background:white}h2{margin-top:3rem}</style>'
        f'<h1>{html.escape(directory.name)}</h1><p>{html.escape(assessment.get("finding", "Recorded evidence; evaluate native clocks and audible boundaries."))}</p>'
        '<div style="position:sticky;top:0;background:#fff;padding:.7rem;z-index:1"><strong>Original room recording</strong> '
        '<audio id="room-audio" controls preload="metadata" src="room.wav"></audio><span id="seek-status"></span></div>'
        '<p>Overview, followed by 20-second windows. All event markers remain visible; routine heartbeat and repeated duplicate labels are abbreviated for readability. '
        '<a href="timeline-events.json">Event JSON</a> · <a href="timeline-events.csv">Event CSV</a></p><img src="timeline.svg" alt="Overview">'
        + room_scope_note + cleanup_table + coverage_table + acoustic_words + '<h2>Words registered by VM STT</h2><p>Final-transcript receipt times; excerpts can be bounded. Compare these with the room-audio word spans.</p><table><tr><th>Capture time</th><th>Registered text</th></tr>'+transcripts+'</table>' + ''.join(pages)
        + '<details><summary>Search every registered event</summary><input id="event-search" placeholder="Filter event, source or delivery ID" style="width:90%;padding:.6rem">'
        '<table id="event-table"><thead><tr><th>Capture seconds</th><th>Source</th><th>Event</th><th>Clock ±ms</th><th>Metadata</th></tr></thead><tbody>'
        + event_table + '</tbody></table></details><script>document.getElementById("event-search").addEventListener("input", function(){'
        'const q=this.value.toLowerCase();for(const r of document.querySelectorAll("#event-table tbody tr")){r.hidden=!r.textContent.toLowerCase().includes(q)}});'
        'document.addEventListener("click",function(e){const b=e.target.closest("button[data-seek]");if(!b)return;'
        'const a=document.getElementById("room-audio");a.pause();a.currentTime=Math.max(0,Number(b.dataset.seek)-1);'
        'document.getElementById("seek-status").textContent=" Seeked to "+a.currentTime.toFixed(3)+" s; press Play to listen."});</script>')

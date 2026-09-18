#!/usr/bin/env python3
"""Inspect real input endings and internal pauses against calibrated native mute."""
import argparse
import html
import json
from pathlib import Path
import wave


def assess_input(alignment, rows, allowance_ms=10):
    result = {'index': alignment['index'], 'status': 'untrusted_acoustic_alignment'}
    if not alignment.get('trusted') or 'signal_end_s' not in alignment:
        return result
    start, end = alignment['signal_start_s'], alignment['signal_end_s']
    result.update(signal_start_s=start, signal_end_s=end,
                  acoustic_display_allowance_ms=allowance_ms)
    events = sorted((r for r in rows if r['source'] in ('ios', 'android')
                     and r['event'] == 'applied mute state'),
                    key=lambda r: r['capture_relative_s'])
    before = [r for r in events if r['capture_relative_s'] <= start]
    result['initial_sdk_state_observed'] = bool(before)
    if before and str(before[-1].get('metadata', {}).get('microphone_enabled')).lower() == 'false':
        return {**result, 'status': 'input_started_with_last_acknowledged_mic_disabled'}
    following = [r['capture_relative_s'] for r in rows
                 if r['event'] == 'playback_process_start' and r['capture_relative_s'] > end]
    limit = min(following) if following else float('inf')
    muted = [r for r in events if start < r['capture_relative_s'] < limit
             and str(r.get('metadata', {}).get('microphone_enabled')).lower() == 'false']
    if not muted:
        return {**result, 'status': 'native_mute_not_observed'}
    mute = muted[0]
    result.update(native_mute_s=mute['capture_relative_s'],
                  mute_after_signal_ms=1000 * (mute['capture_relative_s'] - end))
    if 'clock_uncertainty_ms' not in mute:
        return {**result, 'status': 'native_clock_uncalibrated'}
    uncertainty = mute['clock_uncertainty_ms'] + allowance_ms
    gap = result['mute_after_signal_ms']
    result.update(phone_clock_uncertainty_ms=mute['clock_uncertainty_ms'],
                  gap_lower_ms=gap-uncertainty, gap_upper_ms=gap+uncertainty)
    result['status'] = ('mute_before_input_end_candidate' if gap+uncertainty < 0 else
                        'mute_after_input_signal' if gap-uncertainty > 0 else
                        'boundary_uncertain')
    return result


def render(directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    alignment = json.loads((directory/'acoustic-alignment.json').read_text())
    rows = json.loads((directory/'timeline-events.json').read_text())
    provenance = json.loads((directory/'stimulus-provenance.json').read_text())
    segments = {s['index']: s['segments'] for s in provenance.get('segmented_fixtures', [])}
    words = json.loads((directory/'transcript.json').read_text()).get('words') or []
    with wave.open(str(directory/'room.wav')) as wav:
        rate = wav.getframerate()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2') / 32768.0
    duration = len(audio)/rate
    results, cards = [], []
    for match in alignment['stimuli']:
        result = assess_input(match, rows, alignment['display_allowance_ms'])
        results.append(result)
        if not match.get('trusted') or 'signal_end_s' not in match:
            continue
        boundaries = [('ending', match['signal_end_s'])]
        for fragment in segments.get(match['index'], []):
            if fragment['gap_after_s']:
                boundaries.append((f"pause-{fragment['index']}",
                                   match['fixture_start_s']+fragment['end_s']))
        for label, center in boundaries:
            lower, upper = max(0, center-2), min(duration, center+4)
            fig, axes = plt.subplots(3, 1, figsize=(14, 7), sharex=True,
                                     gridspec_kw={'height_ratios': [2, 1, 2]})
            a, b = int(lower*rate), int(upper*rate)
            axes[0].plot(np.arange(a,b)/rate, audio[a:b], linewidth=.35, color='#264653')
            axes[0].set_ylim(-1, 1)
            axes[0].set_ylabel('Room PCM\nfull scale')
            for fragment in segments.get(match['index'], []):
                gap_start = match['fixture_start_s']+fragment['end_s']
                gap_end = gap_start+fragment['gap_after_s']
                if gap_end > lower and gap_start < upper and gap_end > gap_start:
                    axes[0].axvspan(gap_start,gap_end,color='#e9c46a',alpha=.4)
            for i, word in enumerate(w for w in words if lower <= w['start']/1000 <= upper):
                x, end = word['start']/1000, word['end']/1000
                axes[1].plot([x,end],[i%2]*2,color='#2a9d8f',linewidth=3)
                axes[1].text(x,i%2+.1,word['text'],fontsize=8)
            axes[1].set_ylim(-.25,1.6)
            axes[1].set_ylabel('ASR words\n~400 ms')
            for row in rows:
                x = row['capture_relative_s'];meta=row.get('metadata',{})
                if not lower <= x <= upper:
                    continue
                if row['source']=='server' and row['event']=='voice_lifecycle_packet_published' and meta.get('event')=='safe_to_mute_user':
                    lane, caption = 2, 'VM: safe to mute'
                elif (row['source'] in ('ios','android') and row['event']=='safe_to_mute_user'
                      and meta.get('disposition') != 'duplicate'):
                    lane, caption = 1, 'Phone: mute received'
                elif row['source'] in ('ios','android') and row['event']=='applied mute state':
                    lane, caption = 0, 'Phone SDK: '+('mic ON' if str(meta.get('microphone_enabled')).lower()=='true' else 'mic OFF')
                else:
                    continue
                error=row.get('clock_uncertainty_ms')
                axes[2].errorbar(x,lane,xerr=error/1000 if error is not None else None,
                                 fmt='D',markersize=5,color='#e76f51')
                axes[2].text(x,lane+.15,f'{caption}\n{x:.3f}s'+(' UNCALIBRATED' if error is None else f' ±{error:.1f}ms'),fontsize=8)
            for axis in axes:
                axis.axvline(center,color='#6d28d9',linestyle='--',linewidth=1)
                axis.grid(axis='x',alpha=.2)
                axis.set_xlim(lower,upper)
            axes[2].set_ylim(-.5,3)
            axes[2].set_ylabel('Lifecycle /\nSDK return')
            axes[2].set_xlabel('Seconds from first recorded sample; this is a waveform estimate, not exact semantic syllable alignment')
            fig.suptitle(f"Input {match['index']} {label}: {result['status']}\nWaveform match {match['normalized_correlation']:.3f}; gap shading uses original fixture sample offsets")
            fig.tight_layout()
            stem=f"input-{match['index']}-{label}"
            for ext in ('svg','png'):
                fig.savefig(directory/f'{stem}.{ext}',dpi=150)
            plt.close(fig)
            cards.append(f'<h2>Input {match["index"]}: {html.escape(label)}</h2><a href="{stem}.svg"><img style="max-width:100%" src="{stem}.png"></a>')
    limitation='Waveform correlation and amplitude thresholds estimate audible fixture boundaries. The 10 ms allowance is a display assumption, not a calibrated physical bound. ASR words are approximate, not syllable timestamps. Native SDK returns do not establish physical mic hardware timing. Review every early-mute candidate against the original sound and full transcript.'
    output={'limitation':limitation,'inputs':results}
    (directory/'input-boundaries.json').write_text(json.dumps(output,indent=2)+'\n')
    (directory/'input-boundaries.html').write_text('<!doctype html><meta charset="utf-8"><title>Input boundary review</title><main style="max-width:1400px;margin:auto;font-family:system-ui"><h1>Input boundary review</h1><p>'+html.escape(limitation)+'</p><p><a href="timeline.html">Full timeline</a> · <a href="input-boundaries.json">Measurements</a></p><audio controls src="room.wav"></audio>'+''.join(cards)+'</main>')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    render(parser.parse_args().directory)

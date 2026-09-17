#!/usr/bin/env python3
"""Measure terminal-word/mic boundaries without turning missing evidence into a pass."""
import argparse
import json
from pathlib import Path
import re


def normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def assess(rows, words, terminal_phrase, asr_uncertainty_ms=400, stimulus_index=None,
        origin_event='playback_process_end'):
    ends = [r['capture_relative_s'] for r in rows if r['event'] == origin_event
        and (stimulus_index is None or r.get('index') == stimulus_index)]
    if not ends:
        return {'status': 'harness_error', 'finding': f'No observed {origin_event}'}
    input_end = max(ends)
    next_inputs = [r['capture_relative_s'] for r in rows if r['event'] == 'playback_process_start'
        and r['capture_relative_s'] > input_end]
    window_end = min(next_inputs) if next_inputs else float('inf')
    phrase = [normalized(t) for t in terminal_phrase.split()]
    candidates = []
    for index in range(len(words) - len(phrase) + 1):
        span = words[index:index + len(phrase)]
        if span[0]['start'] / 1000 > input_end and span[-1]['end'] / 1000 < window_end and [normalized(w['text']) for w in span] == phrase:
            candidates.append(span)
    result = {'terminal_phrase': terminal_phrase,
        'host_stimulus_end_s': input_end if origin_event == 'playback_process_end' else None,
        'origin_event': origin_event, 'origin_s': input_end,
        'stimulus_index': stimulus_index, 'response_window_end_s': None if not next_inputs else window_end,
        'asr_boundary_uncertainty_ms': asr_uncertainty_ms,
        'limitation': 'ASR ±400 ms is an approximate analysis allowance, not a guaranteed bound. Negative boundaries require waveform/independent alignment review. A missing marker alone does not prove TTS truncation.'}
    if not candidates:
        return {**result, 'status': 'terminal_marker_not_observed'}
    terminal = candidates[-1]
    end = terminal[-1]['end'] / 1000
    result.update(terminal_word_end_s=end, terminal_occurrences=len(candidates))
    mutes = [r for r in rows if r['event'] == 'applied mute state'
        and str(r.get('metadata', {}).get('microphone_enabled')).lower() == 'false'
        and input_end < r['capture_relative_s'] < window_end]
    if not mutes:
        return {**result, 'status': 'complete_marker_missing_native_mute_evidence'}
    live = [r for r in rows if r['source'] == mutes[-1]['source'] and r['event'] == 'applied mute state'
        and str(r.get('metadata', {}).get('microphone_enabled')).lower() == 'true'
        and mutes[-1]['capture_relative_s'] < r['capture_relative_s'] < window_end]
    if not live:
        return {**result, 'status': 'complete_marker_unmute_not_observed'}
    unmute = live[0]
    gap = 1000 * (unmute['capture_relative_s'] - end)
    result.update(native_unmute_s=unmute['capture_relative_s'], unmute_after_word_ms=gap)
    if 'clock_uncertainty_ms' not in unmute:
        return {**result, 'status': 'complete_marker_unmute_clock_uncalibrated'}
    uncertainty = unmute['clock_uncertainty_ms'] + asr_uncertainty_ms
    result.update(phone_clock_uncertainty_ms=unmute['clock_uncertainty_ms'],
        unmute_gap_lower_ms=gap - uncertainty, unmute_gap_upper_ms=gap + uncertainty)
    if gap + uncertainty < 0:
        status = 'premature_unmute_candidate_requires_waveform_review'
    elif gap - uncertainty > 0:
        status = 'complete_marker_and_protected_unmute_observed'
    else:
        status = 'complete_marker_unmute_boundary_uncertain'
    return {**result, 'status': status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--terminal-phrase', required=True)
    parser.add_argument('--stimulus-index', type=int, help='Assess only the response before the next host stimulus')
    parser.add_argument('--origin-event', choices=('playback_process_end', 'announcement_command_start'),
        default='playback_process_end', help='Announcement submission is not acoustic onset')
    args = parser.parse_args()
    path = args.directory
    rows = json.loads((path / 'timeline-events.json').read_text())
    words = json.loads((path / 'transcript.json').read_text()).get('words') or []
    result = assess(rows, words, args.terminal_phrase, stimulus_index=args.stimulus_index,
        origin_event=args.origin_event)
    prior = path / 'assessment.json'
    prior_status = json.loads(prior.read_text()).get('status', '') if prior.exists() else ''
    if prior_status == 'harness_error' or 'harness' in prior_status:
        result.update(status=prior_status, finding='Retained original harness failure; timing measurements cannot override it')
    filename = 'timing-assessment.json' if args.stimulus_index is None else f'timing-assessment-stimulus-{args.stimulus_index}.json'
    if args.origin_event == 'announcement_command_start':
        filename = f'timing-assessment-announcement-{args.stimulus_index}.json'
    (path / filename).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

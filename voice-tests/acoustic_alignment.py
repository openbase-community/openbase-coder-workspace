#!/usr/bin/env python3
"""Estimate where immutable host stimulus waveforms actually reach the room mic.

Correlation is corroboration, not calibrated acoustic latency or speaker
diarization. Low-scoring matches must never establish an input boundary.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy.signal import fftconvolve

RATE = 8000


def samples(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
        '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'])
    return np.frombuffer(raw, dtype='<f4').astype(np.float64)


def match(reference, observed):
    if len(observed) < len(reference) or not np.any(reference):
        return None
    correlation = fftconvolve(observed, reference[::-1], mode='valid')
    cumulative = np.concatenate(([0.0], np.cumsum(observed ** 2)))
    energy = cumulative[len(reference):] - cumulative[:-len(reference)]
    denominator = np.sqrt(np.maximum(energy, 0) * np.dot(reference, reference))
    score = np.divide(np.abs(correlation), denominator,
        out=np.zeros_like(correlation), where=denominator > 0)
    index = int(np.argmax(score))
    return {'offset_samples': index, 'normalized_correlation': float(score[index])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    directory = args.directory
    clock = json.loads((directory/'capture-clock.json').read_text())
    origin = clock['first_sample_unix_ms']
    room_path = directory/'room.wav'
    room = samples(room_path)
    host = [json.loads(line) for line in (directory/'host-events.jsonl').read_text().splitlines()]
    starts = {row['index']: row for row in host if row['event'] == 'playback_process_start'}
    results = []
    for index, start in sorted(starts.items()):
        path = directory/f'stimulus-{index}.wav'
        reference = samples(path)
        predicted = (start['unix_ms']-origin)/1000
        lower = max(0, int((predicted-.3)*RATE))
        upper = min(len(room), int((predicted+len(reference)/RATE+1.0)*RATE))
        alignment = match(reference, room[lower:upper])
        record = {'index':index, 'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'process_start_s':predicted, 'sample_rate':RATE, 'trusted':False}
        if alignment:
            observed_start = (lower+alignment['offset_samples'])/RATE
            energetic = np.flatnonzero(np.abs(reference) > max(.001, np.max(np.abs(reference))*.01))
            record.update(alignment, fixture_start_s=observed_start,
                process_to_fixture_ms=1000*(observed_start-predicted),
                trusted=alignment['normalized_correlation'] >= .2)
            if len(energetic):
                record.update(signal_start_s=observed_start+energetic[0]/RATE,
                    signal_end_s=observed_start+(energetic[-1]+1)/RATE)
        results.append(record)
    output = {'room_sha256':hashlib.sha256(room_path.read_bytes()).hexdigest(),
        'display_allowance_ms':10,
        'limitation':'Waveform-match estimates; 10 ms display allowance is an analysis assumption, not a calibrated physical bound. Not speaker diarization. Correlation below 0.2 is untrusted. Signal boundaries use fixture amplitude, not exact semantic word boundaries.',
        'stimuli':results}
    (directory/'acoustic-alignment.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()

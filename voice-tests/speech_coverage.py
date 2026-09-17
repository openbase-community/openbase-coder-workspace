#!/usr/bin/env python3
"""Compare complete probe text with timed ASR, without equating ASR to audibility."""
import argparse
import json
from pathlib import Path
import re


def token(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def align(expected, words):
    actual = [token(w['text']) for w in words]
    lengths = [[0] * (len(actual) + 1) for _ in range(len(expected) + 1)]
    for i, wanted in enumerate(expected, 1):
        for j, heard in enumerate(actual, 1):
            lengths[i][j] = lengths[i-1][j-1] + 1 if wanted == heard else max(lengths[i-1][j], lengths[i][j-1])
    pairs = []
    i, j = len(expected), len(actual)
    while i and j:
        if expected[i-1] == actual[j-1]:
            pairs.append((i-1, j-1)); i -= 1; j -= 1
        elif lengths[i-1][j] >= lengths[i][j-1]:
            i -= 1
        else:
            j -= 1
    matches = dict(reversed(pairs))
    return [{'expected_index': i, 'expected_word': word,
        'asr_start_ms': words[matches[i]]['start'] if i in matches else None,
        'asr_end_ms': words[matches[i]]['end'] if i in matches else None}
        for i, word in enumerate(expected)]


def coverage(probes, words, origin_ms):
    markers = []
    results = []
    for index, probe in enumerate(probes):
        phrase = [token(w) for w in probe['terminal_phrase'].split()]
        candidates = [words[i:i+len(phrase)] for i in range(len(words)-len(phrase)+1)
            if words[i]['start'] >= origin_ms
            and [token(w['text']) for w in words[i:i+len(phrase)]] == phrase]
        if not candidates:
            results.append({'probe_index':index,'thread':probe['thread'],'status':'terminal_marker_not_observed','coverage_percent':None})
        else:
            markers.append((candidates[-1][-1]['end'],index,probe))
    start = origin_ms
    for end,index,probe in sorted(markers):
        span = [w for w in words if start <= w['start'] and w['end'] <= end]
        expected = [token(w) for w in probe['text'].split() if token(w)]
        alignment = align(expected,span)
        matched = sum(w['asr_start_ms'] is not None for w in alignment)
        results.append({'probe_index':index,'thread':probe['thread'],
            'status':'all_expected_words_aligned_by_asr' if matched == len(expected) else 'some_expected_words_not_aligned_by_asr',
            'window_start_ms':start,'window_end_ms':end,'expected_word_count':len(expected),
            'matched_word_count':matched,'coverage_percent':100*matched/len(expected),
            'alignment':alignment})
        start = end
    return sorted(results,key=lambda r:r['probe_index'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args();p=args.directory
    clock=json.loads((p/'capture-clock.json').read_text())['first_sample_unix_ms']
    events=[json.loads(line) for line in (p/'host-events.jsonl').read_text().splitlines()]
    origin=min(r['unix_ms'] for r in events if r['event']=='announcement_command_start')-clock
    probes=json.loads((p/'announcement-scenario.json').read_text())['announcements']
    words=json.loads((p/'transcript.json').read_text()).get('words') or []
    result={'probes':coverage(probes,words,origin),
        'limitation':'ASR lexical alignment is diagnostic, not acoustic ground truth. Missing matches can be recognition errors; matches can borrow repeated words within the probe window. End markers alone do not prove the middle played. Verify suspected omissions with the waveform and actual audio.'}
    (p/'speech-coverage.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'probes':[{k:v for k,v in r.items() if k!='alignment'} for r in result['probes']], 'limitation':result['limitation']},indent=2))


if __name__=='__main__':
    main()

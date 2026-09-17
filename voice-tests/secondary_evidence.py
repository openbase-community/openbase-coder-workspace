"""Keep every independent ASR attempt distinct, including empty readings."""
import json


def secondary_readings(directory):
    attempts, words = [], []
    lane = 3
    for path in sorted(directory.glob('secondary*transcript.json')):
        evidence = json.loads(path.read_text())
        if evidence.get('provider') != 'Deepgram':
            continue
        gain = evidence.get('analysis_gain_db', 0)
        label = 'DG' + (f' +{gain:g} dB' if gain else '')
        attempts.append({**evidence, 'artifact':path.name})
        incoming = evidence.get('words', [])
        words.extend({**word, 'analysis_label':label, 'analysis_file':path.name,
                      'analysis_lane':lane} for word in incoming)
        if incoming:
            lane += 1
    return attempts, words

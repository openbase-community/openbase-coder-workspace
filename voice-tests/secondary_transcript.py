#!/usr/bin/env python3
"""Retain an independent ASR reading of a bounded room-audio interval."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import urllib.request
import wave
from audio_gain import pcm16_gain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--start-s', type=float, required=True)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--credentials-file', type=Path)
    parser.add_argument('--gain-db', type=float, default=0, help='Explicit gain for this ASR request only; original WAV remains unchanged')
    parser.add_argument('--output-name', default='secondary-transcript.json', help='Distinct JSON artifact basename inside the case')
    args = parser.parse_args()
    if args.start_s < 0 or not 0 < args.seconds <= 60:
        raise ValueError('Select a nonnegative start and at most sixty seconds')
    if Path(args.output_name).name != args.output_name or not args.output_name.endswith('.json'):
        raise ValueError('Output must be a JSON basename inside the case directory')
    key = os.environ.get('DEEPGRAM_API_KEY')
    if not key and args.credentials_file:
        for line in args.credentials_file.read_text().splitlines():
            name, sep, value = line.removeprefix('export ').partition('=')
            if sep and name.strip() == 'DEEPGRAM_API_KEY':
                key = value.strip().strip('\"\'')
    if not key:
        raise RuntimeError('Deepgram credentials unavailable')
    source = args.directory / 'room.wav'
    with wave.open(str(source)) as wav:
        rate = wav.getframerate()
        if args.start_s * rate >= wav.getnframes():
            raise ValueError('Interval starts after the recorded audio')
        params = wav.getparams()
        wav.setpos(int(args.start_s * rate))
        frames = wav.readframes(int(args.seconds * rate))
    original_clip_sha256 = hashlib.sha256(frames).hexdigest()
    if params.sampwidth != 2:
        raise ValueError('This analysis requires PCM16 input')
    frames, clipped_samples = pcm16_gain(frames, args.gain_db)
    body = io.BytesIO()
    with wave.open(body, 'wb') as wav:
        wav.setparams(params)
        wav.writeframes(frames)
    request = urllib.request.Request('https://api.deepgram.com/v1/listen?model=nova-3&smart_format=false&punctuate=true',
        data=body.getvalue(), headers={'Authorization':'Token '+key,'Content-Type':'audio/wav'})
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    alternative = result['results']['channels'][0]['alternatives'][0]
    words = [{'text':w.get('punctuated_word',w['word']), 'start':1000*(args.start_s+w['start']),
        'end':1000*(args.start_s+w['end']), 'confidence':w['confidence']} for w in alternative.get('words',[])]
    evidence = {'provider':'Deepgram','model':result.get('metadata',{}).get('model_info'),
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'clip_start_s':args.start_s,
        'actual_clip_seconds':len(frames)/(rate*params.nchannels*params.sampwidth),
        'provider_processed_seconds':result.get('metadata',{}).get('duration'),
        'analysis_gain_db':args.gain_db, 'clipped_samples':clipped_samples,
        'original_clip_pcm_sha256':original_clip_sha256,
        'submitted_clip_wav_sha256':hashlib.sha256(body.getvalue()).hexdigest(),
        'requested_seconds':args.seconds,'text':alternative['transcript'],'words':words,
        'limitation':'Independent ASR corroboration; agreement does not establish exact acoustic boundaries. Primary transcript remains unchanged.',
        'api_documentation':'https://developers.deepgram.com/docs/pre-recorded-audio'}
    (args.directory/args.output_name).write_text(json.dumps(evidence,indent=2)+'\n')
    print(evidence['text'])


if __name__ == '__main__':
    main()

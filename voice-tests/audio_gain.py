"""Explicit ASR-only PCM gain; original acoustic evidence stays unchanged."""
from array import array
import sys


def pcm16_gain(data, gain_db):
    if not 0 <= gain_db <= 30 or len(data) % 2:
        raise ValueError('Select 0–30 dB gain and complete PCM16 samples')
    samples = array('h')
    samples.frombytes(data)
    if sys.byteorder != 'little':
        samples.byteswap()
    factor = 10 ** (gain_db / 20)
    clipped = 0
    for index, sample in enumerate(samples):
        scaled = round(sample * factor)
        clipped += scaled < -32768 or scaled > 32767
        samples[index] = min(32767, max(-32768, scaled))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes(), clipped

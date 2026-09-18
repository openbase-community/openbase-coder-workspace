"""Compose acoustic sentence fragments with sample-exact pauses."""
import hashlib
import subprocess
import wave


def synthesize_fixture(stimulus, target, synthesize):
    segments = stimulus.get("segments")
    if not segments:
        synthesize(stimulus["text"], target)
        return []
    if " ".join(segment["text"] for segment in segments) != stimulus["text"]:
        raise ValueError("Segment text must exactly match the complete stimulus")
    rate = 24000
    parts = []
    cursor = 0
    with wave.open(str(target), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for index, segment in enumerate(segments):
            gap = float(segment.get("gap_after_s", 0))
            if not 0 <= gap <= 10 or (index == len(segments) - 1 and gap):
                raise ValueError("Pauses must be zero to ten seconds and separate fragments")
            source = target.with_name(target.stem + f"-segment-{index}.wav")
            converted = source.with_suffix(".pcm.wav")
            synthesize(segment["text"], source)
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(converted)], check=True)
            with wave.open(str(converted)) as audio:
                frames = audio.readframes(audio.getnframes())
                count = len(frames) // 2
            output.writeframes(frames)
            silence = round(gap * rate)
            output.writeframes(bytes(silence * 2))
            parts.append({"index": index, "text": segment["text"], "start_s": cursor / rate,
                "end_s": (cursor + count) / rate, "gap_after_s": silence / rate,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
            cursor += count + silence
            converted.unlink()
    return parts

"""Render the same Kindled Iron lines in several calm, warm Kokoro voices so the owner can pick one.

    python -m kindled_iron.voice_samples --out storage/kindled_iron/voices

Writes <voice>.mp3 for each voice plus all_voices.mp3 (every voice in order, 1 s apart,
same order as the list printed in the log). Put the chosen name in the scene's "voice".
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from kindled_iron import kokoro_tts

# Calm, warm voices (am_michael is the current default and is left out on purpose).
VOICES = ["af_heart", "af_bella", "bf_emma", "bm_george", "bm_fable", "am_fenrir"]
SAMPLE = ("The Bible doesn't begin with Adam. It begins with God. Why? Because before there was "
          "anything, no sky, no sea, no people, God was already there.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="storage/kindled_iron/voices")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--voices", default=",".join(VOICES))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(kokoro_tts.SAMPLE_RATE, np.float32)
    joined = []
    for v in a.voices.split(","):
        lang = "b" if v.startswith("b") else "a"   # British voices need the British G2P
        audio = kokoro_tts.synthesize(SAMPLE, voice=v, speed=a.speed, lang=lang)
        wav = out / f"{v}.wav"
        sf.write(wav, audio, kokoro_tts.SAMPLE_RATE)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "128k", str(wav.with_suffix(".mp3"))], check=True)
        wav.unlink()
        joined += [audio, gap]
        print(f"[voices] {v}: {len(audio) / kokoro_tts.SAMPLE_RATE:.1f} s")
    allwav = out / "all_voices.wav"
    sf.write(allwav, np.concatenate(joined), kokoro_tts.SAMPLE_RATE)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(allwav), "-b:a", "128k", str(out / "all_voices.mp3")], check=True)
    allwav.unlink()
    print(f"[voices] order in all_voices.mp3: {a.voices}")


if __name__ == "__main__":
    main()

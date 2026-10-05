"""Kokoro TTS for Kindled Iron (Linux, CPU).

Needs: pip install kokoro soundfile (pulls torch) and the system package espeak-ng
(Kokoro's phonemizer fallback). The model (hexgrad/Kokoro-82M) downloads from
Hugging Face on first use and is cached in ~/.cache/huggingface.

CLI:  python -m kindled_iron.kokoro_tts "Some text" out.wav --voice am_michael
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 24000
_PIPELINES: dict[str, object] = {}


def _pipeline(lang: str):
    if shutil.which("espeak-ng") is None:
        raise RuntimeError("espeak-ng is not installed (apt-get install espeak-ng)")
    if lang not in _PIPELINES:
        from kokoro import KPipeline  # imported late: heavy (torch)

        _PIPELINES[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
    return _PIPELINES[lang]


def _trim(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Cut leading/trailing silence so beat timings start on the first word."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if loud.size == 0:
        return audio
    pad = int(0.04 * SAMPLE_RATE)
    return audio[max(0, loud[0] - pad): loud[-1] + pad]


def synthesize(text: str, voice: str = "am_michael", speed: float = 1.0, lang: str = "a") -> np.ndarray:
    """Return mono float32 audio at 24 kHz for one piece of text."""
    chunks = [np.asarray(audio, dtype=np.float32)
              for _, _, audio in _pipeline(lang)(text, voice=voice, speed=speed)
              if audio is not None]
    if not chunks:
        raise RuntimeError(f"Kokoro returned no audio for: {text[:60]!r}")
    return _trim(np.concatenate(chunks))


def synthesize_beats(texts: list[str], out_wav: Path, voice: str = "am_michael", speed: float = 1.0,
                     lang: str = "a", gap: float = 0.3, lead: float = 0.15) -> list[tuple[float, float]]:
    """Voice each beat separately, join them with `gap` seconds of silence.

    Returns (start, end) seconds of every beat inside out_wav.
    """
    parts: list[np.ndarray] = [np.zeros(int(lead * SAMPLE_RATE), np.float32)]
    spans: list[tuple[float, float]] = []
    t = lead
    for i, text in enumerate(texts):
        audio = synthesize(text, voice, speed, lang)
        dur = len(audio) / SAMPLE_RATE
        spans.append((round(t, 3), round(t + dur, 3)))
        parts.append(audio)
        t += dur
        if i < len(texts) - 1:
            parts.append(np.zeros(int(gap * SAMPLE_RATE), np.float32))
            t += gap
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, np.concatenate(parts), SAMPLE_RATE)
    return spans


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="a")
    a = ap.parse_args()
    spans = synthesize_beats([a.text], Path(a.out), a.voice, a.speed, a.lang)
    print(f"wrote {a.out} ({spans[-1][1]:.2f} s)")


if __name__ == "__main__":
    main()

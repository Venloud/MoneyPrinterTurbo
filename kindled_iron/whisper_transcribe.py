"""Word timings with faster-whisper (CPU, int8).

The script text is known, so whisper is only used for WHEN each word is said:
`align()` matches whisper's words to the script words and gives every script word
a start/end (unmatched words are interpolated between their matched neighbours).
Captions therefore always show the script's spelling, never whisper's guesses.

CLI:  python -m kindled_iron.whisper_transcribe narration.wav
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

_MODELS: dict[str, object] = {}


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower().replace("’", "'"))


def transcribe(wav: Path, model_name: str = "base.en") -> list[dict]:
    """Return [{"word", "start", "end"}] from faster-whisper."""
    from faster_whisper import WhisperModel  # imported late: heavy

    if model_name not in _MODELS:
        _MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = _MODELS[model_name].transcribe(str(wav), word_timestamps=True, language="en",
                                                 beam_size=5, vad_filter=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            if norm(w.word):
                words.append({"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
    return words


def align(script_words: list[str], heard: list[dict], span: tuple[float, float]) -> list[dict]:
    """Give each script word a start/end, using whisper words inside `span` (seconds)."""
    lo, hi = span
    heard = [w for w in heard if w["end"] > lo - 0.2 and w["start"] < hi + 0.2]
    a = [norm(w) for w in script_words]
    b = [norm(w["word"]) for w in heard]
    times: list[tuple[float, float] | None] = [None] * len(a)
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        # equal words, and same-length substitutions (whisper heard "In" for "And"): take whisper's times
        if op == "equal" or (op == "replace" and a1 - a0 == b1 - b0):
            for k in range(a1 - a0):
                h = heard[b0 + k]
                times[a0 + k] = (max(lo, h["start"]), min(hi, h["end"]))
        elif op == "replace":
            # different word counts ("That is" heard as "That's"): spread the heard span evenly
            s0, s1 = max(lo, heard[b0]["start"]), min(hi, heard[b1 - 1]["end"])
            step = max(0.0, s1 - s0) / (a1 - a0)
            for k in range(a1 - a0):
                times[a0 + k] = (s0 + step * k, s0 + step * (k + 1))
    # Interpolate the gaps (numbers spoken as words, contractions split differently...)
    i = 0
    while i < len(a):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(a) and times[j] is None:
            j += 1
        start = times[i - 1][1] if i > 0 else lo
        end = times[j][0] if j < len(a) else hi
        step = max(0.0, end - start) / (j - i)
        for k in range(i, j):
            times[k] = (start + step * (k - i), start + step * (k - i + 1))
        i = j
    out = []
    for w, (s, e) in zip(script_words, times):
        out.append({"word": w, "start": round(s, 3), "end": round(max(e, s + 0.05), 3)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wav")
    ap.add_argument("--model", default="base.en")
    a = ap.parse_args()
    print(json.dumps(transcribe(Path(a.wav), a.model), indent=1))


if __name__ == "__main__":
    main()

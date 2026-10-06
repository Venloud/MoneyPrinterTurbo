"""Pauses between sentences, the same for every voice provider.

1. plan(): split every beat into sentences (and at manual "[pause 0.8]" tags), and give each a
   pause after it: pause_sentence (~0.35 s) after a normal sentence, pause_beat (~0.7 s) after the
   hook (first sentence), a question, a one/two-word punch line ("Wrong."), a "Day N" line, and
   before the last line. A "[pause x]" tag sets that pause exactly. Tags are never spoken or captioned.
2. Providers voice the plan (Kokoro/Chatterbox per sentence + silence; ElevenLabs one request with
   <break> tags when the model supports them).
3. enforce(): on the FINAL audio, measure every sentence gap from the word timings and insert or
   trim silence so each gap matches its target (scaled to aim at 140-150 words a minute). Word
   timings are shifted to match, so captions and animation follow the audio, pauses included.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

TAG = re.compile(r"\[pause\s+([\d.]+)\s*s?\]", re.I)
REF = re.compile(r"\[(?!pause\b)[^\]]+\]", re.I)      # [Psalm 90:2]: written on screen, never spoken or captioned
DAY = re.compile(r"^\s*day\s+(one|two|three|four|five|six|seven|\d+)\b", re.I)
WPM_RANGE = (140.0, 150.0)
MIN_SPEED = 0.92                       # never slow the voice below this to gain length


@dataclass
class Segment:
    text: str          # what is spoken (no tags)
    beat: int
    n_words: int
    pause: float       # silence after this segment
    why: str = ""


def strip_tags(text: str) -> str:
    return re.sub(r"\s{2,}", " ", REF.sub(" ", TAG.sub(" ", text))).strip()


def refs_of(text: str) -> list[str]:
    return [m.group(0)[1:-1].strip() for m in REF.finditer(text)]


def words_of(text: str) -> list[str]:
    return strip_tags(text).split()


def _sentences(text: str) -> list[tuple[str, float | None]]:
    """Split at sentence ends and at pause tags; returns (sentence, manual pause or None)."""
    out: list[tuple[str, float | None]] = []
    pos = 0
    for m in list(TAG.finditer(text)) + [None]:
        chunk = REF.sub(" ", text[pos:m.start()] if m else text[pos:])
        # a sentence also ends after a closing quote: ...you are God." Think about it.
        parts = [p for p in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”’])\s+", chunk.strip()) if p.strip()]
        for i, ptxt in enumerate(parts):
            out.append((ptxt.strip(), None))
        if m:
            if out:
                out[-1] = (out[-1][0], float(m.group(1)))
            pos = m.end()
    return out


def plan(beats: list[str], profile: dict) -> list[Segment]:
    ps = float(profile.get("pause_sentence", 0.35))
    pb = float(profile.get("pause_beat", 0.7))
    segs: list[Segment] = []
    for b, text in enumerate(beats):
        for s, manual in _sentences(text):
            segs.append(Segment(s, b, len(s.split()), ps, "sentence"))
            if manual is not None:
                segs[-1].pause, segs[-1].why = manual, "tag"
    for i, s in enumerate(segs):
        if s.why == "tag":
            continue
        reason = None
        if i == 0:
            reason = "hook"
        elif s.text.endswith("?"):
            reason = "question"
        elif s.n_words <= 2:
            reason = "punch"
        elif DAY.match(s.text):
            reason = "day"
        elif i == len(segs) - 2:
            reason = "before last line"
        if reason:
            s.pause, s.why = pb, reason
    if segs:
        segs[-1].pause, segs[-1].why = 0.0, "end"
    return segs


def provider_text(segs: list[Segment]) -> list[tuple[str, float]]:
    return [(s.text, s.pause) for s in segs]


# --------------------------------------------------------------------- enforce on the final audio
def _quietest(audio: np.ndarray, sr: int, a: float, b: float) -> int:
    """Sample index of the quietest 20 ms window between a and b seconds."""
    lo, hi = int(max(0.0, a) * sr), int(min(len(audio) / sr, b) * sr)
    win = int(0.02 * sr)
    if hi - lo <= win:
        return max(0, min(len(audio), (lo + hi) // 2))
    seg = audio[lo:hi] ** 2
    energy = np.convolve(seg, np.ones(win), mode="valid")
    return lo + int(np.argmin(energy)) + win // 2


def _refine_edges(audio: np.ndarray, sr: int, words: list[dict], bounds) -> list[dict]:
    """Whisper often stretches a word over the silence next to it. For every sentence boundary, find
    the longest silent run between the last word's start and the next sentence's first word's end,
    and use its edges as the real end / start."""
    hop = int(0.01 * sr)
    n = len(audio) // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    thr = max(1e-4, 0.06 * float(np.percentile(rms, 90)))
    quiet = rms <= thr
    words = [dict(w) for w in words]
    for i in range(len(bounds) - 1):
        last, first = words[bounds[i][1]], words[bounds[i + 1][0]]
        f0, f1 = int(last["start"] / 0.01), min(n, int(first["end"] / 0.01) + 1)
        best, run_start = (0, 0), None
        for f in range(f0, f1 + 1):
            q = f < f1 and quiet[f]
            if q and run_start is None:
                run_start = f
            elif not q and run_start is not None:
                if f - run_start > best[1] - best[0]:
                    best = (run_start, f)
                run_start = None
        if best[1] - best[0] >= 8:                    # >= 80 ms of silence found
            last["end"] = round(max(last["start"] + 0.05, best[0] * 0.01), 3)
            first["start"] = round(best[1] * 0.01, 3)
            if first["end"] <= first["start"]:
                first["end"] = round(first["start"] + 0.08, 3)
    return words


def enforce(audio: np.ndarray, sr: int, words: list[dict], segs: list[Segment], profile: dict,
            log) -> tuple[np.ndarray, list[dict], dict]:
    """Make every sentence gap match its target pause; returns new audio, shifted words, stats."""
    bounds, k = [], 0
    for s in segs:                                   # word index ranges per segment
        bounds.append((k, k + s.n_words - 1))
        k += s.n_words
    assert k == len(words), f"plan has {k} words, timings {len(words)}"
    words = _refine_edges(audio, sr, words, bounds)
    speech_end = words[-1]["end"]
    total_words = len(words)
    hold = float(profile.get("_end_hold", 1.4))

    # aim at 140-150 wpm by scaling the pauses (never the voice speed)
    gaps = [words[bounds[i + 1][0]]["start"] - words[bounds[i][1]]["end"] for i in range(len(segs) - 1)]
    targets = [s.pause for s in segs[:-1]]
    natural = speech_end - sum(gaps)                 # time spent talking
    def duration(scale: float) -> float:
        return natural + sum(t * scale for t in targets) + hold + words[0]["start"]
    lo_wpm, hi_wpm = WPM_RANGE
    scale = 1.0
    wpm = total_words / duration(1.0) * 60
    if wpm > hi_wpm:                                 # too fast: longer pauses, up to 1.8x
        need = total_words * 60 / hi_wpm
        scale = min(1.8, max(1.0, (need - natural - hold - words[0]["start"]) / max(0.01, sum(targets))))
    elif wpm < lo_wpm:                               # too slow: shorter pauses, down to 0.6x
        need = total_words * 60 / lo_wpm
        scale = max(0.6, min(1.0, (need - natural - hold - words[0]["start"]) / max(0.01, sum(targets))))
    max_pause = float(profile.get("max_pause", 1.2))

    edits = []                                       # (sample position, +insert / -remove samples)
    for i in range(len(segs) - 1):
        prev_end = words[bounds[i][1]]["end"]
        next_start = words[bounds[i + 1][0]]["start"]
        target = min(max_pause, targets[i] * scale) if segs[i].why != "tag" else targets[i]
        delta = target - (next_start - prev_end)
        if abs(delta) < 0.03:
            continue
        if delta < 0 and (next_start - prev_end) - target < 0.15:
            continue                                 # never shave a natural gap by tiny amounts
        at = _quietest(audio, sr, prev_end - 0.03, next_start + 0.03)
        if delta < 0:                                # trim only inside the gap, keep 0.12 s around words
            room = max(0.0, (next_start - prev_end) - 0.24)
            delta = -min(-delta, room)
            if delta > -0.03:
                continue
        edits.append((at, int(round(delta * sr)), i))

    out, shift_at, last = [], [], 0
    for at, n, i in sorted(edits):
        if n > 0:
            out += [audio[last:at], np.zeros(n, audio.dtype)]
            last = at
        else:
            cut = -n
            a = max(last, at - cut // 2)
            out.append(audio[last:a])
            last = min(len(audio), a + cut)
        shift_at.append((at / sr, n / sr))
    out.append(audio[last:])
    new = np.concatenate(out)

    shifted = []
    for w in words:                                  # every word moves by the edits before it
        d = sum(dt for t, dt in shift_at if t <= w["start"])
        shifted.append({**w, "start": round(w["start"] + d, 3), "end": round(w["end"] + d, 3)})
    stats = {"pause_scale": round(scale, 2), "pauses_edited": len(edits),
             "inserted_s": round(sum(n for _, n, _ in edits if n > 0) / sr, 2),
             "trimmed_s": round(-sum(n for _, n, _ in edits if n < 0) / sr, 2)}
    log(f"pauses: {len(segs) - 1} gaps, {len(edits)} adjusted (+{stats['inserted_s']} s / -{stats['trimmed_s']} s), "
        f"pause scale {scale:.2f}")
    return new, shifted, stats

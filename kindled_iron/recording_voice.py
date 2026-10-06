"""The owner's own reading as a SILENT timing guide: his recording is never heard in a video.

The recording lives ONLY in the private repo (Venloud/kindled-iron-voice, recordings/). It is measured
(words per minute, every pause and its length, the words he leans on) and the cloned voice reads the
script with normal ElevenLabs text-to-speech, ONE request, with tts_text punctuated the way he spoke:
- a sentence he ran straight into the next one ends with a comma, not a full stop;
- a real pause inside a sentence gets a full stop (a long one an ellipsis); a short one a comma;
- speed chosen to land near his pace (0.90-1.05).
The result is never cut, re-spaced or time-stretched. If the clone's pauses at the big beats (his longest
pauses) are far off, the punctuation there is strengthened and the script is regenerated ONCE.
Word timings for captions and animation come from whisper on the final audio (render.py).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from kindled_iron import elevenlabs_tts as el

CLEAN_AF = ("highpass=f=70,afftdn=nf=-25,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,"
            "loudnorm=I=-16:TP=-1.5:LRA=11")
SPEED_RANGE = (0.90, 1.05)
KEEP_CAPS = {"I", "God", "God's", "He", "He's", "His", "Him", "Bible", "Bible's", "Moses", "Minecraft", "AM"}
BIG_BEATS = 4


def _dur(f: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                          str(f)]).decode().strip())


def clean(src: Path, out: Path) -> Path:
    """Only for MEASURING (whisper hears it better); this audio is never used in a video."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", CLEAN_AF, "-ac", "1", "-ar", "44100", str(out)],
                   check=True)
    return out


def _used(before: int | None = None) -> int | None:
    """Characters used this month. After a request the count can lag a few seconds: wait for it to move."""
    import time
    n = None
    for _ in range(6 if before is not None else 1):
        try:
            n = int(el._get("/user/subscription").get("character_count", 0))
        except Exception:  # noqa: BLE001
            return None
        if before is None or n != before:
            return n
        time.sleep(2)
    return n


def _align(wav: Path, script_words: list[str], whisper_model: str) -> list[dict]:
    from kindled_iron import whisper_transcribe as wt

    return wt.align(script_words, wt.transcribe(wav, whisper_model), (0.0, _dur(wav)))


def gaps(al: list[dict]) -> list[float]:
    return [round(al[i + 1]["start"] - al[i]["end"], 2) for i in range(len(al) - 1)]


def measure(clean_wav: Path, script_words: list[str], whisper_model: str = "small.en") -> dict:
    """Words per minute, every pause (after which word, how long) and the words he leans on."""
    import numpy as np
    import soundfile as sf

    length = _dur(clean_wav)
    al = _align(clean_wav, script_words, whisper_model)
    g = gaps(al)
    pauses = [{"after": al[i]["word"], "i": i, "s": s} for i, s in enumerate(g) if s >= 0.18]
    x, sr = sf.read(clean_wav, dtype="float32")
    x = x if x.ndim == 1 else x.mean(axis=1)
    loud = []
    for i, w in enumerate(al):
        seg = x[int(w["start"] * sr):int(max(w["end"], w["start"] + 0.05) * sr)]
        loud.append((float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0, i))
    thr = sorted(r for r, _ in loud)[int(len(loud) * 0.9)] if loud else 1
    stressed = [al[i]["word"] for r, i in loud if r >= thr and len(re.sub(r"[^A-Za-z]", "", al[i]["word"])) > 2]
    return {"duration": round(length, 2), "words": len(script_words), "wpm": round(len(script_words) / length * 60, 1),
            "gaps": g, "pauses": pauses, "stressed": stressed}


def spoken_text(script_words: list[str], g: list[float], boost: set[int] | None = None) -> str:
    """The script punctuated the way it was spoken (quote marks dropped; the words never change).
    boost = word indexes whose pause must come out longer (one step stronger)."""
    boost = boost or set()
    out = []
    for i, w in enumerate(script_words):
        word = w.replace('"', "").replace("“", "").replace("”", "")
        core = word.rstrip(",.;:?!")
        end = word[len(core):]
        if i == len(script_words) - 1:
            out.append(word)
            continue
        p = g[i] if i < len(g) else 0.0
        level = 0 if p < 0.2 else 1 if p < 0.45 else 2 if p < 0.8 else 3      # none, comma, full stop, ellipsis
        if i in boost:
            level = min(3, max(level, 1) + 1)
        if "?" in end and level >= 1:
            mark = "?" if level < 3 else "? ..."
        elif level == 3:
            mark = "..."
        elif level == 2:
            mark = "."
        elif level == 1 or (end and end[0] in ".?!"):        # a sentence he ran into the next: a comma
            mark = ","
        else:
            mark = end if end in (",",) else ""
        out.append(core + mark)
    # a sentence that became a comma: the next word is lower case again (names stay capitalised)
    for i in range(1, len(out)):
        if not re.search(r"[.?!]$", out[i - 1]) and out[i][:1].isupper() and re.sub(r"[^A-Za-z']", "", out[i]) not in KEEP_CAPS:
            out[i] = out[i][0].lower() + out[i][1:]
    text = " ".join(out)
    text = re.sub(r"\bAM\b", "am", text)             # "I AM" must not be read as "A.M."
    return re.sub(r"([.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)   # sentence starts


def _speed(rec_wpm: float) -> tuple[float, float]:
    # this voice reads ~196 wpm at speed 1.0 and ~172 at 0.9 (rounds 7-8): wpm ~ 196 * speed^1.25
    want = (rec_wpm / 196.0) ** (1 / 1.25)
    return round(max(SPEED_RANGE[0], min(SPEED_RANGE[1], want)), 3), want


def _tts(text: str, out_wav: Path, profile: dict, speed: float, log) -> dict:
    prof = json.loads(json.dumps(profile))
    cfg = prof["elevenlabs"]
    cfg["use_break_tags"] = False
    cfg["voice_settings"]["speed"] = speed
    if el._key():
        before = _used()
        meta = el.synthesize([(text, 0.0)], out_wav, prof)
        after = _used(before)
        diff = (after - before) if before is not None and after is not None else 0
        meta["credits"] = diff if diff > 0 else meta.get("chars")      # usage can show up late: text-to-speech bills characters
        meta["provider_used"] = "elevenlabs"
        return meta
    # local preview without the key: Kokoro reads the same tts_text (never the recording)
    from kindled_iron import kokoro_tts
    log("voice: no ElevenLabs key here: Kokoro reads the same tts_text (local preview only)")
    meta = kokoro_tts.synthesize([(text, 0.0)], out_wav, prof)
    meta.update({"provider_used": "kokoro", "credits": 0, "fallback": True, "voice_label": "fallback voice"})
    return meta


def voice(recording: Path, script_words: list[str], out_wav: Path, profile: dict, work: Path, log, **_) -> dict:
    cleaned = clean(recording, work / "pace_reference.wav")
    m = measure(cleaned, script_words)
    big = sorted(range(len(m["gaps"])), key=lambda i: -m["gaps"][i])[:BIG_BEATS]
    log(f"pacing reference (silent): {recording.name}, {m['duration']:.1f} s, {m['wpm']:.0f} wpm, "
        f"{len(m['pauses'])} pauses; big beats: " +
        ", ".join(f"after '{script_words[i]}' {m['gaps'][i]:.2f} s" for i in sorted(big)))
    log(f"pacing reference: words he leans on: {', '.join(m['stressed'][:14])}")
    speed, want = _speed(m["wpm"])
    q = el.quota(profile.get("elevenlabs") or {}) if el._key() else None
    if q and "remaining" in q:
        log(f"ElevenLabs quota: {q['remaining']}/{q['budget']} characters left this month ({q['remaining_fraction']:.0%})")
    text = spoken_text(script_words, m["gaps"])
    log(f"text-to-speech, one request, speed {speed} (his pace wants {want:.2f}, range {SPEED_RANGE[0]}-{SPEED_RANGE[1]})")
    log(f"tts_text: {text}")
    meta = _tts(text, out_wav, profile, speed, log)
    credits = meta.get("credits") or 0
    # compare the clone's pauses with his at the big beats; strengthen the punctuation there and regenerate ONCE
    al = _align(out_wav, script_words, "small.en")
    cg = gaps(al)
    report = [{"after": script_words[i], "his": m["gaps"][i], "clone": cg[i] if i < len(cg) else None} for i in sorted(big)]
    off = [i for i in big if i < len(cg) and (cg[i] < 0.5 * m["gaps"][i] or abs(cg[i] - m["gaps"][i]) > 0.5)]
    log("big beats (his / clone): " + ", ".join(f"'{r['after']}' {r['his']:.2f}/{r['clone']:.2f} s" for r in report))
    regenerated = False
    if off and meta.get("provider_used") == "elevenlabs":
        text2 = spoken_text(script_words, m["gaps"], boost={i for i in off if cg[i] < m["gaps"][i]})
        if text2 != text:
            log(f"clone's pauses are off at {len(off)} big beat(s): stronger punctuation there, regenerating once")
            meta2 = _tts(text2, out_wav, profile, speed, log)
            credits += meta2.get("credits") or 0
            meta, text, regenerated = meta2, text2, True
            cg = gaps(_align(out_wav, script_words, "small.en"))
            report = [{"after": script_words[i], "his": m["gaps"][i], "clone": cg[i] if i < len(cg) else None} for i in sorted(big)]
            log("big beats after regenerating (his / clone): " +
                ", ".join(f"'{r['after']}' {r['his']:.2f}/{r['clone']:.2f} s" for r in report))
    dur = _dur(out_wav)
    log(f"voice: ElevenLabs text-to-speech paced from the recording: {dur:.1f} s, "
        f"{len(script_words) / dur * 60:.0f} wpm, speed {speed}, credits {credits}")
    meta.update({"path": "tts_paced_by_recording", "tts_text": text, "speed": speed, "credits": credits,
                 "regenerated": regenerated, "big_beats": report,
                 "recording": {"file": recording.name, "duration": m["duration"], "wpm": m["wpm"],
                               "pauses": m["pauses"], "stressed": m["stressed"]}})
    meta.setdefault("fallback", meta.get("provider_used") != "elevenlabs")
    return meta

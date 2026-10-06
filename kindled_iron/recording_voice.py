"""The owner's own reading as the voice track (his delivery, in his cloned voice).

The recording itself lives ONLY in the private repo (Venloud/kindled-iron-voice, recordings/); the
workflow checks it out at render time. Steps:
1. clean(): noise reduction, trim the silence at the very start and end, loudness normalise. Nothing
   else: no pause insertion, no trimming inside, no time-stretch.
2. a) speech_to_speech(): ElevenLabs Speech to Speech with the owner's voice id on the cleaned
      recording: keeps his exact pace, pauses and emphasis.
   b) if (a) fails: match_tts(): measure the recording (words per minute, every pause and its length,
      the stressed words) and send ONE text-to-speech request whose text is punctuated the way he
      spoke it, at the closest speed (never below the channel's min_speed). No post-processing.
Word timings for captions and animation always come from whisper on the FINAL audio (render.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from kindled_iron import elevenlabs_tts as el

CLEAN_AF = ("highpass=f=70,afftdn=nf=-25,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,"
            "loudnorm=I=-16:TP=-1.5:LRA=11")
STS_MODEL = "eleven_multilingual_sts_v2"


def _dur(f: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                          str(f)]).decode().strip())


def clean(src: Path, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", CLEAN_AF, "-ac", "1", "-ar", "44100", str(out)],
                   check=True)
    return out


def _cache(name: str) -> Path:
    d = Path(os.environ.get("KI_TTS_CACHE", Path.home() / ".cache" / "kindled_iron" / "tts"))
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _used(before: int | None = None) -> int | None:
    """Characters used this month. After a request the count can lag a few seconds: wait for it to move."""
    import time
    for k in range(6 if before is not None else 1):
        try:
            n = int(el._get("/user/subscription").get("character_count", 0))
        except Exception:  # noqa: BLE001
            return None
        if before is None or n != before:
            return n
        time.sleep(2)
    return n


def speech_to_speech(clean_wav: Path, out_wav: Path, profile: dict, log) -> dict:
    cfg = profile.get("elevenlabs") or {}
    if not el._key():
        raise RuntimeError("no ELEVENLABS_API_KEY")
    settings = {k: v for k, v in (cfg.get("voice_settings") or {}).items() if k != "speed"}   # pace = the recording's
    blob = clean_wav.read_bytes()
    key = hashlib.sha256(blob + json.dumps([cfg.get("voice_id"), STS_MODEL, settings], sort_keys=True).encode()).hexdigest()[:24]
    cached = _cache(f"sts_{key}.wav")
    if cached.exists():
        shutil.copy(cached, out_wav)
        log("voice: ElevenLabs speech-to-speech (cached audio, 0 credits)")
        return {"path": "speech_to_speech", "model": STS_MODEL, "cached": True, "credits": 0}
    before = _used()
    bnd = uuid.uuid4().hex
    parts = []
    for name, val in (("model_id", STS_MODEL), ("voice_settings", json.dumps(settings)), ("remove_background_noise", "false")):
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="audio"; filename="take.wav"\r\n'
                 f'Content-Type: audio/wav\r\n\r\n'.encode() + blob + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    req = urllib.request.Request(f"{el.API}/speech-to-speech/{cfg['voice_id']}?output_format=mp3_44100_128",
                                 data=b"".join(parts), method="POST",
                                 headers={"xi-api-key": el._key() or "", "Accept": "audio/mpeg",
                                          "Content-Type": f"multipart/form-data; boundary={bnd}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            d = json.loads(e.read().decode()).get("detail", {})
            detail = (d.get("status", "") + " " + str(d.get("message", ""))[:160]) if isinstance(d, dict) else str(d)[:160]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"ElevenLabs speech-to-speech HTTP {e.code} {detail}".strip()) from None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        mp3 = f.name
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3, "-ac", "1", "-ar", "44100", str(out_wav)], check=True)
    finally:
        os.unlink(mp3)
    shutil.copy(out_wav, cached)
    after = _used(before)
    credits = (after - before) if before is not None and after is not None else None
    return {"path": "speech_to_speech", "model": STS_MODEL, "cached": False, "credits": credits}


def measure(clean_wav: Path, script_words: list[str], whisper_model: str = "base.en") -> dict:
    """Words per minute, every pause (after which word, how long) and the stressed words of the recording."""
    import numpy as np
    import soundfile as sf

    from kindled_iron import whisper_transcribe as wt

    length = _dur(clean_wav)
    heard = wt.transcribe(clean_wav, whisper_model)
    al = wt.align(script_words, heard, (0.0, length))
    pauses = [{"after": al[i]["word"], "i": i, "s": round(al[i + 1]["start"] - al[i]["end"], 2)}
              for i in range(len(al) - 1) if al[i + 1]["start"] - al[i]["end"] >= 0.18]
    x, sr = sf.read(clean_wav, dtype="float32")
    x = x if x.ndim == 1 else x.mean(axis=1)
    loud = []
    for i, w in enumerate(al):
        seg = x[int(w["start"] * sr):int(max(w["end"], w["start"] + 0.05) * sr)]
        loud.append((float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0, i))
    thr = sorted(r for r, _ in loud)[int(len(loud) * 0.9)] if loud else 1
    stressed = [al[i]["word"] for r, i in loud if r >= thr and len(re.sub(r"[^A-Za-z]", "", al[i]["word"])) > 2]
    return {"duration": round(length, 2), "words": len(script_words), "wpm": round(len(script_words) / length * 60, 1),
            "pauses": pauses, "stressed": stressed, "aligned": al}


def spoken_text(script_words: list[str], m: dict) -> str:
    """The script punctuated the way it was spoken: a long pause gets a full stop or an ellipsis, a short one
    a comma; a comma the reader ran straight through is dropped."""
    gap = {p["i"]: p["s"] for p in m["pauses"]}
    out = []
    for i, w in enumerate(script_words):
        g = gap.get(i, 0.0)
        core = w.rstrip(",;:")
        if i == len(script_words) - 1 or re.search(r"[.?!\"”]$", w):
            out.append(w + (" ..." if g >= 0.9 else ""))
        elif g >= 0.7:
            out.append(core + "...")
        elif g >= 0.3:
            out.append(core + ",")
        else:
            out.append(core if w.endswith(",") and g < 0.12 else w)
    return " ".join(out)


def match_tts(script_words: list[str], clean_wav: Path, out_wav: Path, profile: dict, log) -> dict:
    m = measure(clean_wav, script_words)
    text = spoken_text(script_words, m)
    prof = json.loads(json.dumps(profile))
    cfg = prof["elevenlabs"]
    cfg["use_break_tags"] = False
    # ElevenLabs reads this voice at ~196 wpm at speed 1.0 (round 7) and ~172 at 0.9: wpm ~ 196 * speed^1.25
    want = (m["wpm"] / 196.0) ** (1 / 1.25)
    floor = float(prof.get("min_speed", 0.7))
    cfg["voice_settings"]["speed"] = round(max(floor, min(1.2, want)), 3)
    log(f"recording: {m['duration']:.1f} s, {m['wpm']:.0f} wpm, {len(m['pauses'])} pauses "
        f"(longest {max([p['s'] for p in m['pauses']] or [0]):.2f} s), stressed: {', '.join(m['stressed'][:12])}")
    log(f"text-to-speech matched to the recording: speed {cfg['voice_settings']['speed']} "
        f"(wanted {want:.2f}), punctuated as spoken: {text[:160]}...")
    before = _used()
    meta = el.synthesize([(text, 0.0)], out_wav, prof)
    after = _used(before)
    meta.update({"path": "tts_matched", "tts_text": text, "recording": {k: v for k, v in m.items() if k != "aligned"},
                 "credits": (after - before) if before is not None and after is not None else meta.get("chars")})
    return meta


def apply_edits(wav: Path, edits: list[dict], log) -> None:
    """Owner-approved word fixes, ONLY into silence (nothing moves, nothing is stretched):
    {"copy": [start, end], "paste_at": t, "why": "..."} copies his own word (times in the CLEANED recording)
    into a pause."""
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(wav, dtype="float32")
    for ed in edits:
        a, b = int(ed["copy"][0] * sr), int(ed["copy"][1] * sr)
        seg = x[a:b].copy()
        f = int(0.015 * sr)
        seg[:f] *= np.linspace(0, 1, f)
        seg[-f:] *= np.linspace(1, 0, f)
        # the quietest spot within 0.2 s of the planned one (cleaning can shift times by a few ms)
        cands = [int((ed["paste_at"] + d) * sr) for d in np.arange(-0.2, 0.201, 0.01)]
        t = min(cands, key=lambda c: float(np.sqrt(np.mean(x[c:c + len(seg)] ** 2))))
        room = float(np.sqrt(np.mean(x[t:t + len(seg)] ** 2)))
        if room > 0.01:
            log(f"WARNING: recording edit skipped: no pause near {ed['paste_at']} s (level {room:.3f})")
            continue
        ed["paste_at"] = round(t / sr, 3)
        x[t:t + len(seg)] += seg
        log(f"recording edit: copied {ed['copy'][0]:.2f}-{ed['copy'][1]:.2f} s into the pause at {ed['paste_at']:.2f} s"
            f" ({ed.get('why', '')})")
    sf.write(wav, x, sr)


def voice(recording: Path, script_words: list[str], out_wav: Path, profile: dict, work: Path, log,
          edits: list | None = None) -> dict:
    cleaned = clean(recording, work / "recording_clean.wav")
    log(f"recording: {recording.name} cleaned (noise reduction, start/end trim, loudness), {_dur(cleaned):.1f} s")
    if edits:
        apply_edits(cleaned, edits, log)
    q = el.quota(profile.get("elevenlabs") or {}) if el._key() else None
    if q and "remaining" in q:
        log(f"ElevenLabs quota: {q['remaining']}/{q['budget']} characters left this month ({q['remaining_fraction']:.0%})")
    try:
        meta = speech_to_speech(cleaned, out_wav, profile, log)
        log(f"voice: ElevenLabs speech-to-speech ({STS_MODEL}) on the recording, credits {meta['credits']}")
    except Exception as e:  # noqa: BLE001
        log(f"WARNING: speech-to-speech failed ({e}); falling back to text-to-speech matched to the recording")
        try:
            meta = match_tts(script_words, cleaned, out_wav, profile, log)
            meta["sts_error"] = str(e)[:200]
            log(f"voice: ElevenLabs text-to-speech matched to the recording, credits {meta['credits']}")
        except Exception as e2:  # noqa: BLE001
            if el._key():
                raise SystemExit(f"FAIL: no cloned-voice path worked: speech-to-speech ({e}); text-to-speech ({e2})")
            # local preview without the key: the cleaned recording itself (his real voice), never uploaded
            shutil.copy(cleaned, out_wav)
            log("voice: NO ElevenLabs key: the cleaned recording itself (local preview only)")
            meta = {"path": "recording_only", "credits": 0}
    meta.update({"provider_used": "elevenlabs" if meta["path"] != "recording_only" else "recording",
                 "recording": meta.get("recording") or {"file": recording.name}, "fallback": False})
    return meta

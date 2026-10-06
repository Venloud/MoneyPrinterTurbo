"""Sound design: few effects, each one meaning something (owner, round 6: 88 cues was spam).

  - a big hit on the key moments only (events marked "hit": true, max 3)
  - a soft chime when each scripture reference appears
  - a soft whoosh on every other scene change
  - one short pencil sound per scene, on its main drawing only ("main": true)
  Hard cap 15 effects, never two within 0.8 s. No per-stroke sounds (no marker, scribble, eraser,
  scratch), no ambience beds. "sound": "<role>" / "sound": false on an event overrides.

Music: one track per channel (voice_profiles.json music_track -> vendor/sfx/lib/music_<name>.ogg),
from frame 0, ducked under the voice, a small lift at the ending.
Levels (sound_levels.json, dB relative to the voice): pencil -20, pops/chime -18, big sounds -14 (never
peaking above the voice), music -24; everything 4 dB lower while someone speaks. The voice alone is set to
-14 LUFS; effects and music are never boosted to reach it.
"""
from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LIB = HERE / "vendor" / "sfx" / "lib"
SR = 44100

BIG_ROLES = {"rumble", "thud", "whoosh_fall", "boom", "riser", "burst", "water_rush", "whoosh_slow"}
BOOMS = {"boom", "thud"}
# level of each role relative to the voice (dB under the voice's speech RMS)
CONFIG = json.loads((HERE / "sound_levels.json").read_text())
LEVELS = CONFIG["sfx_levels"]                 # dB relative to the voice
SFX_GAIN = float(CONFIG.get("sfx_gain_db", 0.0))
DUCK_DB = float(CONFIG.get("duck_db", 4.0))
VOICE_LUFS = float(CONFIG.get("voice_lufs", -14.0))
ROLE_FILES = {"chime": "burst"}              # a soft chime = the gentlest burst variants, at chime level


class Picker:
    """Rotates the variants of each role (never the same file twice in a row) with a slight random pitch."""

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.files = {}
        for f in sorted(LIB.glob("*.ogg")):
            self.files.setdefault(f.stem.rsplit("_", 1)[0], []).append(f)
        self.files["chime"] = [f for f in self.files.get("burst", []) if f.stem.endswith("_1")] or self.files.get("burst", [])
        self.order = {r: self.rng.sample(v, len(v)) for r, v in self.files.items()}
        self.k = {r: 0 for r in self.files}

    def pick(self, role: str) -> tuple[Path | None, float]:
        fs = self.order.get(role)
        if not fs:
            return None, 1.0
        f = fs[self.k[role] % len(fs)]
        self.k[role] += 1
        return f, 1.0 + self.rng.uniform(-0.04, 0.04)


MAX_EFFECTS, MIN_SPACING, MAX_HITS = 15, 0.8, 3


def plan(events: list[dict], objects: list[dict], scene: dict, spans: list, picker: Picker | None = None) -> list[dict]:
    """Few, meaningful effects (a cap of 15, never two within 0.8 s), in priority order:
      1. a big hit on the key moments: events marked "hit": true (max 3)
      2. a soft chime when each scripture reference appears
      3. a soft whoosh on some scene changes (every other one)
      4. one short pencil sound per scene, only on the drawing marked "main": true
    No per-stroke sounds, no ambience. "sound": "<role>" on an event forces one, "sound": false mutes it."""
    picker = picker or Picker()
    objs = {o["id"]: o for o in objects}
    cand: list[dict] = []

    def add(prio, t, role, why, dur=None):
        cand.append({"prio": prio, "t": round(max(0.0, t), 3), "role": role, "why": why, "dur": dur,
                     "weight": "big" if role in BIG_ROLES else "small", "group": None})

    hits, scene_changes, pencil_beats = 0, 0, set()
    for e in events:
        t, do, o = e["t"], e["do"], objs.get(e.get("id"))
        if e.get("sound") is False:
            continue
        if e.get("sound"):
            add(2, t, e["sound"], f"override on {do} {e.get('id', '')}", e.get("sound_dur"))
            continue
        if e.get("hit") and hits < MAX_HITS:
            hits += 1
            add(1, t, e.get("hit_sound", "boom"), f"key moment: {e.get('why') or (o or {}).get('text') or do}")
        if do == "draw" and o and o["type"] == "scripture":
            add(2, t + float(e.get("dur") or 1.5) + 0.1, "chime", f"reference {o.get('ref')} appears")
        elif do == "camera" and e.get("transition"):
            scene_changes += 1
            if scene_changes % 2 == 1:
                add(3, t - 0.05, "whoosh_slow", f"scene change ({e['transition']})", 0.7)
        elif do == "draw" and o and e.get("main"):
            beat = next((b for b, (a, z) in enumerate(spans) if a - 0.3 <= t <= z + 0.3), None)
            if beat not in pencil_beats:
                pencil_beats.add(beat)
                add(4, t, "pencil_long", f"draws {o['type']} {o['id']}", min(0.8, float(e.get("dur") or 0.8)))
    kept: list[dict] = []
    for c in sorted(cand, key=lambda c: (c["prio"], c["t"])):
        if len(kept) >= MAX_EFFECTS:
            break
        if any(abs(c["t"] - k["t"]) < MIN_SPACING for k in kept):
            continue
        kept.append(c)
    kept.sort(key=lambda c: c["t"])
    for c in kept:
        f, pitch = picker.pick(c["role"])
        c["file"], c["pitch"] = (f.name if f else None), round(pitch, 3)
    return [c for c in kept if c["file"]]


# --------------------------------------------------------------- mix
def _decode(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"])
    return np.frombuffer(raw, np.float32).copy()


def _repitch(x: np.ndarray, r: float) -> np.ndarray:
    if abs(r - 1) < 1e-3:
        return x
    n = int(len(x) / r)
    return np.interp(np.arange(n) * r, np.arange(len(x)), x).astype(np.float32)


def _fit(x: np.ndarray, dur: float | None, fade_out: float = 0.06) -> np.ndarray:
    """Stops with the stroke: cut to dur (fade out); too short = repeat with a small crossfade."""
    if not dur:
        return x
    n = int(dur * SR)
    if len(x) < n:
        xf = int(0.03 * SR)
        out = x.copy()
        while len(out) < n:
            k = min(xf, len(out), len(x))
            ramp = np.linspace(0, 1, k, dtype=np.float32)
            out[-k:] = out[-k:] * (1 - ramp) + x[:k] * ramp
            out = np.concatenate([out, x[k:]])
        x = out
    x = x[:n].copy()
    k = min(len(x), int(fade_out * SR))
    if k:
        x[-k:] *= np.linspace(1, 0, k, dtype=np.float32)
    return x


def _loop(x: np.ndarray, n: int, xf: float = 1.0) -> np.ndarray:
    if len(x) >= n:
        return x[:n].copy()
    k = int(xf * SR)
    out = x.copy()
    while len(out) < n:
        ramp = np.linspace(0, 1, k, dtype=np.float32)
        out[-k:] = out[-k:] * (1 - ramp) + x[:k] * ramp
        out = np.concatenate([out, x[k:]])
    return out[:n]


def _speech_rms(voice: np.ndarray) -> float:
    hop = int(0.05 * SR)
    fr = voice[: len(voice) // hop * hop].reshape(-1, hop)
    r = np.sqrt(np.mean(fr ** 2, axis=1))
    loud = r[r > np.percentile(r, 60) * 0.5]
    return float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 0.05


def _speech_mask(words: list[dict], n: int) -> np.ndarray:
    m = np.zeros(n, np.float32)
    for w in words:
        a, b = int(max(0, w["start"] - 0.08) * SR), int(min(n / SR, w["end"] + 0.12) * SR)
        m[a:b] = 1
    k = int(0.15 * SR)
    return np.convolve(m, np.ones(k, np.float32) / k, mode="same")


def mix(narration: Path, cues: list[dict], scene: dict, spans: list, words: list[dict], duration: float,
        out: Path, out_novoice: Path, music: dict | None, log) -> dict:
    """music = {"track": name (vendor/sfx/lib/music_<name>.ogg), "lift_at": seconds} or None."""
    voice = _decode(narration)
    n = max(len(voice), int(duration * SR)) + SR // 2
    v = np.zeros(n, np.float32)
    v[:len(voice)] = voice
    vr = _speech_rms(voice)
    vpeak = float(np.percentile(np.abs(voice), 99.95)) or 0.5
    fx = np.zeros(n, np.float32)
    for c in cues:
        x = _repitch(_decode(LIB / c["file"]), c["pitch"])
        x = _fit(x, c.get("dur"))
        g = vr * 10 ** ((LEVELS.get(c["role"], -20) + SFX_GAIN) / 20) / 0.1      # library files sit at 0.1 RMS
        seg = x * g
        pk = float(np.max(np.abs(seg))) if len(seg) else 0.0
        if c["role"] in BIG_ROLES and pk > 0.8 * vpeak:                        # never peaks above the voice
            seg *= 0.8 * vpeak / pk
        i = int(c["t"] * SR)
        seg = seg[: max(0, n - i)]
        fx[i:i + len(seg)] += seg
    bed = np.zeros(n, np.float32)
    duck = (10 ** (-DUCK_DB / 20)) ** _speech_mask(words, n)
    beds = []
    track = (music or {}).get("track")
    if track and (LIB / f"music_{track}.ogg").exists():
        x = _loop(_decode(LIB / f"music_{track}.ogg"), n, xf=2.0)
        x = x * (0.1 / (float(np.sqrt(np.mean(x[: SR * 20] ** 2))) or 0.1))     # same reference level as the effects
        env = np.ones(n, np.float32)
        lift = music.get("lift_at")
        if lift is not None:                                                   # a small lift at the ending (+3 dB)
            a = int(lift * SR)
            ramp = min(n - a, int(0.4 * SR))
            if ramp > 0:
                env[a:a + ramp] = np.linspace(1, 1.41, ramp)
                env[a + ramp:] = 1.41
        k2 = int(1.2 * SR)
        env[-k2:] *= np.linspace(1, 0, k2)
        bed += x * env * (vr * 10 ** ((LEVELS["music"] + SFX_GAIN) / 20) / 0.1)
        beds.append({"t": 0.0, "to": round(n / SR, 2), "role": "music", "file": f"music_{track}.ogg"})
    bed *= duck
    fx *= duck                                    # everything ducks under speech
    # the VOICE alone is set to the target (gentle compressor, then gain + limiter at -1 dBFS); effects, ambience
    # and music follow by the same factor, so they keep their offsets and are never boosted to reach loudness
    vc = _ff(v, "acompressor=threshold=-24dB:ratio=4:attack=5:release=100:knee=6")   # tame the peaks first
    g = VOICE_LUFS - _measure_lufs_arr(vc)
    for _ in range(6):
        vn = _ff(vc, f"volume={g:.2f}dB,alimiter=limit=0.89:attack=3:release=60:level=disabled")
        err = VOICE_LUFS - _measure_lufs_arr(vn)
        if abs(err) < 0.2:
            break
        g += err
    k = _speech_rms(vn) / (_speech_rms(v) or 1e-6)
    voice_lufs = _measure_lufs_arr(vn)
    _write(vn + (fx + bed) * k, out, 0.0)
    _write((fx + bed) * k, out_novoice, 0.0)
    lufs = _measure_lufs(out)
    log(f"mix: {len(cues)} effects + music {track or 'none'}, voice {voice_lufs:.1f} LUFS "
        f"(target {VOICE_LUFS:.0f}), final mix {lufs:.1f} LUFS")
    return {"lufs": lufs, "voice_lufs": voice_lufs, "beds": beds}


def _ff(x: np.ndarray, af: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                          "-af", af, "-ar", str(SR), "-f", "f32le", "-ac", "1", "-"],
                         input=x.astype(np.float32).tobytes(), capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.float32).copy()
    return np.pad(y, (0, max(0, len(x) - len(y))))[: len(x)]


def _write(x: np.ndarray, path: Path, gain_db: float) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-af", f"volume={gain_db:.2f}dB,alimiter=limit=0.89:attack=3:release=60:level=disabled",
                    "-ar", str(SR), str(path)], input=x.astype(np.float32).tobytes(), check=True)


def _measure_lufs_arr(x: np.ndarray) -> float:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-af", "ebur128", "-f", "null", "-"], input=x.astype(np.float32).tobytes(), capture_output=True)
    import re
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr.decode())
    return float(m[-1]) if m else -23.0


def _measure_lufs(path: Path) -> float:
    return _measure_lufs_arr(_decode(path))




def report(cues: list[dict], beds: list[dict], duration: float) -> dict:
    """The owner's listen-check list: every sound with its time, plus the longest stretch without one."""
    src = {s["file"]: s for s in json.loads((LIB / "sources.json").read_text())}
    rows = []
    for c in cues:
        s = src.get(c["file"], {})
        rows.append({"t": c["t"], "role": c["role"], "file": c["file"], "why": c["why"], "weight": c["weight"],
                     "source": s.get("source"), "id": s.get("id"), "title": s.get("title"), "author": s.get("author"),
                     "url": s.get("url"), "license": s.get("license")})
    for b in beds:
        s = src.get(b["file"], {})
        rows.append({"t": b["t"], "to": b["to"], "role": b["role"], "file": b["file"], "why": "ambience/music bed",
                     "source": s.get("source"), "id": s.get("id"), "title": s.get("title"), "author": s.get("author"),
                     "url": s.get("url"), "license": s.get("license")})
    rows.sort(key=lambda r: r["t"])
    starts = sorted({0.0, duration} | {c["t"] for c in cues})
    gap = max((b - a, a) for a, b in zip(starts, starts[1:]))
    return {"cues": len(cues), "longest_gap": round(gap[0], 2), "longest_gap_at": round(gap[1], 2), "sounds": rows}

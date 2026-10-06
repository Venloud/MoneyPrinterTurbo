"""Sound design, driven automatically by the scene's events (event type + weight), with a manual
override per event ("sound": "<role>" or "sound": false).

  DRAWN things      -> pencil / pen on paper, starting and stopping with the stroke:
                       outlines = long pencil strokes, short marks = quick scribbles, colour fill = soft marker,
                       text = fast handwriting, cross-outs = two sharp scratches, removals = eraser rub
  BIG things ANIMATED in -> a physical sound that starts BEFORE they appear, then the impact:
                       rise from the ground = rumble + soft thud, drop from above = falling whoosh + landing boom,
                       light / sun bursting in = riser + bright burst, water filling = water rush,
                       big text ("GOD", "VERY GOOD") = riser + deep soft boom, sky lifting = slow whoosh
  SMALL / background -> no sound (the guide's little actions, birds, waves, clouds, stars, sparkles)
  Also: a soft pop for things that appear already finished (insets, the DAY counter tick),
  low ambience per scene, a soft music bed.

"Big" = the main subject or over ~25 % of the safe box ("weight": "big" | "small" on the event or the
object; otherwise estimated from its size). One big sound at a time; never two booms within 1.5 s.
Mix: voice on top; pencil + hits ~13 dB under it, ambience + music ~20 dB under and ducking further
under speech; final -14 LUFS. Every sound used is listed with its time, file and source.
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

SAFE_AREA = 840 * 1280
BACKGROUND = {"birds", "waves", "cloud", "stars", "star", "sparkle", "splash", "line", "darkness", "rays"}
OUTLINE = {"book", "tree", "hill", "animal", "sun", "moon", "globe", "fish", "frame", "light", "figure", "blob", "cloud", "waves"}
FILLED = {"book", "tree", "hill", "animal", "sun", "moon", "globe", "fish", "light", "cloud", "waves"}
MARKS = {"plant", "check", "voice", "arrow", "star", "circle", "underline"}
BIG_ROLES = {"rumble", "thud", "whoosh_fall", "boom", "riser", "burst", "water_rush", "whoosh_slow"}
BOOMS = {"boom", "thud"}
# level of each role relative to the voice (dB under the voice's speech RMS)
LEVEL = {"pencil_long": 14, "scribble": 14, "marker": 16, "handwriting": 14, "scratch": 12, "eraser": 14,
         "pop": 15, "rumble": 12, "thud": 12, "whoosh_fall": 13, "boom": 12, "riser": 14, "burst": 13,
         "water_rush": 13, "whoosh_slow": 14}
AMB_UNDER, AMB_DUCK = 20.0, 6.0          # ambience + music: 20 dB under, 6 dB more while someone speaks
AMBIENCE = {"hum": "amb_hum", "wind": "amb_wind", "waves": "amb_waves", "birds": "amb_birds", "crickets": "amb_crickets"}


def area(o: dict) -> float:
    t, s = o.get("type"), float(o.get("scale", 1) or 1)
    if t == "word":
        size = o.get("size", 120)
        return len(o.get("text", "")) * size * 0.5 * size
    if t in ("waves",):
        return o.get("w", 600) * ((o.get("rows", 3) - 1) * 42 + 34) * s * s
    if t in ("hill", "darkness", "frame", "inset"):
        return o.get("w", 420) * o.get("h", 160) * s * s
    size = {"cloud": (330, 140), "tree": (230, 300), "book": (380, 200), "animal": (240, 180), "sun": (236, 236),
            "moon": (120, 135), "globe": (2 * o.get("r", 90), 2 * o.get("r", 90)), "fish": (165, 80), "plant": (80, 100),
            "light": (2 * (o.get("r", 80) + 155),) * 2, "check": (240 * o.get("k", 1), 190 * o.get("k", 1))}.get(t, (100, 100))
    return size[0] * size[1] * s * s


def weight(e: dict, o: dict | None) -> str:
    w = e.get("weight") or (o or {}).get("weight")
    if w:
        return w
    return "big" if o and area(o) > 0.25 * SAFE_AREA else "small"


class Picker:
    """Rotates the variants of each role (never the same file twice in a row) with a slight random pitch."""

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.files = {}
        for f in sorted(LIB.glob("*.ogg")):
            self.files.setdefault(f.stem.rsplit("_", 1)[0], []).append(f)
        self.order = {r: self.rng.sample(v, len(v)) for r, v in self.files.items()}
        self.k = {r: 0 for r in self.files}

    def pick(self, role: str) -> tuple[Path | None, float]:
        fs = self.order.get(role)
        if not fs:
            return None, 1.0
        f = fs[self.k[role] % len(fs)]
        self.k[role] += 1
        return f, 1.0 + self.rng.uniform(-0.04, 0.04)


def plan(events: list[dict], objects: list[dict], scene: dict, spans: list, picker: Picker | None = None) -> list[dict]:
    """Cues: {t, role, dur?, weight, why, file, pitch}. Build-ups are scheduled BEFORE their event."""
    picker = picker or Picker()
    objs = {o["id"]: o for o in objects}
    cues: list[dict] = []

    def add(t, role, why, w="small", dur=None, group=None):
        cues.append({"t": round(max(0.0, t), 3), "role": role, "why": why, "weight": w, "dur": dur, "group": group})

    big_drawn = {e["id"] for e in events if e["do"] in ("rise", "drop") or (e["do"] == "move" and e.get("weight") == "big")}
    for i, e in enumerate(events):
        do, t = e["do"], e["t"]
        if e.get("sound") is False:
            continue
        if e.get("sound"):                                   # manual override
            add(t, e["sound"], f"override on {do}", e.get("weight", "small"), e.get("sound_dur"), group=i)
            continue
        o = objs.get(e.get("id")) if do in ("draw", "rise", "drop", "move", "fade") else None
        if do == "draw" and o:
            typ, w = o["type"], weight(e, o)
            if typ in ("sparkle", "splash"):
                continue
            if typ == "inset":
                add(t, "pop", "inset appears (already finished)")
                continue
            if e.get("instant"):
                continue                                     # pre-set, or animated in by rise / drop / move
            if typ == "word" and w == "big":
                add(t - 1.0, "riser", f"big text {o.get('text')!r}: build-up", "big", 1.05, group=i)
                add(t + 0.05, "boom", f"big text {o.get('text')!r}: deep soft boom", "big", group=i)
                continue
            if w == "small" and typ in BACKGROUND:
                continue
            d = float(e.get("dur") or o.get("dur") or 1.1)
            if typ == "word":
                add(t, "handwriting", f"writes {o.get('text')!r}", w, d)
            elif typ in ("cross", "strike"):
                add(t, "scratch", f"crosses out {o.get('target', '')}", w, 0.25)
                add(t + 0.14, "scratch", "second scratch", w, 0.25)
            elif typ in MARKS or (typ not in OUTLINE and w == "small"):
                add(t, "scribble", f"quick marks: {typ} {o['id']}", w, min(0.6, d))
            else:
                add(t, "pencil_long", f"outline: {typ} {o['id']}", w, d * 0.8)
                if typ in FILLED:
                    add(t + d * 0.8, "marker", f"colour fill: {typ} {o['id']}", w, 0.5)
        elif do == "rise" and o:
            d = float(e.get("dur") or 0.9)
            if o["type"] == "waves":
                add(t - 0.3, "water_rush", f"water fills: {o['id']}", "big", d + 0.8, group=i)
            else:
                add(t - 0.6, "rumble", f"{o['type']} rises from the ground: rumble", "big", d + 0.5, group=i)
                add(t + d * 0.8, "thud", f"{o['type']} settles: soft thud", "big", group=i)
        elif do == "drop" and o:
            d = float(e.get("dur") or 0.6)
            add(t - 0.25, "whoosh_fall", f"{o['type']} falls in: whoosh", "big", d + 0.25, group=i)
            add(t + d, "boom", f"{o['type']} lands: boom", "big", group=i)
        elif do == "move" and e.get("weight") == "big":
            add(t - 0.15, "whoosh_slow", f"{(o or {}).get('type', 'drawing')} {e.get('id')} sweeps away/up: slow whoosh",
                "big", float(e.get("dur") or 1.2) + 0.3, group=i)
        elif do == "light_burst":
            add(t - 1.0, "riser", "light bursts in: build-up", "big", 1.05, group=i)
            add(t, "burst", "light bursts in: bright burst", "big", group=i)
        elif do == "fade" and e.get("erase"):
            add(t, "eraser", f"erases {', '.join(e.get('ids', []))[:40]}", "small", 0.6)
        elif do == "counter" and e.get("day"):
            add(t, "pop", f"DAY {e['day']} tick")
        elif do == "enter":
            add(t, "pencil_long", f"draws {e.get('who')}", "small", float(e.get("dur") or 1.0) * 0.9)

    cues.sort(key=lambda c: c["t"])
    # one big sound at a time; never two booms within 1.5 s; pencil sounds never pile up
    kept, big_end, last_boom, last_small = [], -9.0, -9.0, {}
    for c in cues:
        if c["role"] in BIG_ROLES:
            if c["role"] in BOOMS and c["t"] - last_boom < 1.5:
                continue                                     # never two booms within 1.5 s
            if c["t"] < big_end - 0.15 and c["role"] not in BOOMS and c["role"] != "burst":
                if c["role"] in ("riser", "rumble", "whoosh_fall"):
                    c["t"] = round(big_end - 0.15, 3)        # a build-up waits for the big sound before it
                    if c["dur"]:
                        c["dur"] = max(0.3, c["dur"] - 0.3)
                else:
                    continue
            length = c["dur"] or 1.2
            big_end = max(big_end, c["t"] + length)
            if c["role"] in BOOMS:
                last_boom = c["t"]
        else:
            fam = c["role"]
            if c["t"] - last_small.get(fam, -9) < 0.12:
                continue
            last_small[fam] = c["t"]
        kept.append(c)
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
        out: Path, out_novoice: Path, music_from: float | None, log) -> dict:
    voice = _decode(narration)
    n = max(len(voice), int(duration * SR)) + SR // 2
    v = np.zeros(n, np.float32)
    v[:len(voice)] = voice
    vr = _speech_rms(voice)
    fx = np.zeros(n, np.float32)
    for c in cues:
        x = _repitch(_decode(LIB / c["file"]), c["pitch"])
        x = _fit(x, c.get("dur"))
        g = vr * 10 ** (-LEVEL.get(c["role"], 14) / 20) / 0.1           # library files sit at 0.1 RMS
        i = int(c["t"] * SR)
        seg = x[: max(0, n - i)] * g
        fx[i:i + len(seg)] += seg
    # ambience per scene (crossfaded) + the music bed, both ducked under speech
    bed = np.zeros(n, np.float32)
    duck = (10 ** (-AMB_DUCK / 20)) ** _speech_mask(words, n)
    amb_used = []
    for b, beat in enumerate(scene["beats"]):
        role = AMBIENCE.get(beat.get("ambience") or "")
        if not role or not (LIB / f"{role}_0.ogg").exists():
            continue
        a = spans[b][0] - 0.3
        z = (spans[b + 1][0] if b + 1 < len(spans) else duration) + 0.5
        ia, iz = int(max(0, a) * SR), min(n, int(z * SR))
        x = _loop(_decode(LIB / f"{role}_0.ogg"), iz - ia)
        k = min(len(x) // 2, int(0.6 * SR))
        x[:k] *= np.linspace(0, 1, k, dtype=np.float32)
        x[-k:] *= np.linspace(1, 0, k, dtype=np.float32)
        bed[ia:iz] += x * (vr * 10 ** (-AMB_UNDER / 20) / 0.1)
        amb_used.append({"t": round(max(0, a), 2), "to": round(z, 2), "role": role, "file": f"{role}_0.ogg"})
    if music_from is not None and (LIB / "music_0.ogg").exists():
        ia = int(max(0, music_from - 0.5) * SR)
        x = _loop(_decode(LIB / "music_0.ogg"), n - ia, xf=2.0)
        k1, k2 = int(2.5 * SR), int(1.5 * SR)
        x[:k1] *= np.linspace(0, 1, k1, dtype=np.float32)
        x[-k2:] *= np.linspace(1, 0, k2, dtype=np.float32)
        bed[ia:] += x * (vr * 10 ** (-(AMB_UNDER + 2) / 20) / 0.1)
        amb_used.append({"t": round(ia / SR, 2), "to": round(n / SR, 2), "role": "music", "file": "music_0.ogg"})
    bed *= duck
    full = v + fx + bed
    # loudness to -14 LUFS with a soft limiter (true peak about -1.5 dBFS); the muted copy gets the
    # exact same gain, so its levels are the real ones under the voice
    gain_db = -14.0 - _measure_lufs_arr(full)
    for _ in range(3):
        _write(full, out, gain_db)
        err = -14.0 - _measure_lufs(out)
        if abs(err) < 0.3:
            break
        gain_db += err
    _write(fx + bed, out_novoice, gain_db)
    lufs = _measure_lufs(out)
    log(f"mix: {len(cues)} sound cues + {len(amb_used)} ambience/music beds, final {lufs:.1f} LUFS")
    return {"lufs": lufs, "beds": amb_used}


def _write(x: np.ndarray, path: Path, gain_db: float) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-af", f"volume={gain_db:.2f}dB,alimiter=limit=0.84:attack=3:release=60:level=disabled",
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

#!/usr/bin/env python3
"""Create a restrained cinematic music bed and scene transition SFX for Kindled Iron.

Everything is synthesized locally with Python's standard library so GitHub Actions
does not need another paid audio service.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import wave
from pathlib import Path

SR = 44100


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for x in samples:
        value = int(clamp(x) * 32767)
        frames += struct.pack("<h", value)
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(frames)


def envelope(t: float, duration: float, attack: float = 0.8, release: float = 1.2) -> float:
    a = min(1.0, t / max(attack, 0.001))
    r = min(1.0, max(0.0, (duration - t) / max(release, 0.001)))
    return a * r


def tone(freq: float, t: float, detune: float = 0.0) -> float:
    return math.sin(2.0 * math.pi * (freq + detune) * t)


def scene_durations(scene_file: Path, total_duration: float) -> list[float]:
    data = json.loads(scene_file.read_text(encoding="utf-8"))
    scenes = data.get("scenes", [])
    weights = []
    for scene in scenes:
        text = f"{scene.get('narration', '')} {scene.get('overlay', '')}".strip()
        weights.append(max(1, len(text.split())))
    if not weights:
        return [total_duration]
    total = sum(weights)
    return [total_duration * w / total for w in weights]


def make_music(duration: float, boundaries: list[float]) -> list[float]:
    # A slow orchestral-style pad progression. Major harmony arrives when Genesis 1
    # moves from darkness into light, then broadens through life and creation.
    chords = [
        (73.42, 87.31, 110.00),
        (73.42, 87.31, 130.81),
        (73.42, 92.50, 110.00),
        (98.00, 123.47, 146.83),
        (110.00, 138.59, 164.81),
        (123.47, 146.83, 185.00),
        (98.00, 123.47, 146.83),
        (73.42, 92.50, 110.00, 146.83),
    ]
    samples: list[float] = []
    boundary_index = 0
    rng = random.Random(17)
    for n in range(int(duration * SR)):
        t = n / SR
        while boundary_index + 1 < len(boundaries) and t >= boundaries[boundary_index + 1]:
            boundary_index += 1
        chord = chords[min(boundary_index, len(chords) - 1)]
        local = t - boundaries[boundary_index]
        scene_len = max(0.1, boundaries[min(boundary_index + 1, len(boundaries) - 1)] - boundaries[boundary_index]) if len(boundaries) > 1 else duration
        e = envelope(local, scene_len, 2.0, 2.5)
        pad = 0.0
        for j, freq in enumerate(chord):
            pad += tone(freq, t, (j - 1) * 0.08) * (0.12 if j == 0 else 0.075)
            pad += tone(freq * 2.0, t, (j - 1) * 0.05) * 0.025
        bass = tone(chord[0] / 2.0, t) * 0.10
        shimmer = tone(chord[-1] * 2.0, t * 0.997) * (0.018 + 0.012 * math.sin(t * 0.17))
        pulse = tone(chord[0] * 2.0, t) * (0.012 if int(t * 2) % 2 == 0 else 0.006)
        samples.append((pad + bass + shimmer + pulse) * (0.55 + 0.45 * e) * 0.42)
    return samples


def add_event(buf: list[float], start: float, duration: float, kind: str, level: float) -> None:
    start_i = max(0, int(start * SR))
    count = min(len(buf) - start_i, max(1, int(duration * SR)))
    if count <= 0:
        return
    seed = int(start * 1000) + sum(ord(c) for c in kind)
    rng = random.Random(seed)
    for j in range(count):
        t = j / SR
        p = j / max(1, count - 1)
        if kind == "whoosh":
            noise = rng.uniform(-1, 1)
            carrier = math.sin(2 * math.pi * (240 + 1600 * p) * t)
            env = (math.sin(math.pi * p) ** 1.8) * (1 - 0.35 * p)
            value = (0.55 * noise + 0.45 * carrier) * env
        elif kind == "rise":
            freq = 90 + 1100 * (p * p)
            value = math.sin(2 * math.pi * freq * t) * (p ** 0.6) * (1 - p)
        elif kind == "impact":
            value = (math.sin(2 * math.pi * 70 * t) * math.exp(-7 * t)
                     + 0.25 * rng.uniform(-1, 1) * math.exp(-18 * t))
        elif kind == "shimmer":
            value = (math.sin(2 * math.pi * 1500 * t)
                     + 0.5 * math.sin(2 * math.pi * 2300 * t)) * math.exp(-4.5 * t)
        else:
            value = math.sin(2 * math.pi * 1300 * t) * math.exp(-22 * t)
        buf[start_i + j] += value * level


def make_sfx(duration: float, boundaries: list[float]) -> list[float]:
    buf = [0.0] * int(duration * SR)
    for idx, boundary in enumerate(boundaries[1:], start=1):
        add_event(buf, boundary - 0.42, 0.55, "whoosh", 0.18)
        if idx in (2, 4, 6, 8):
            add_event(buf, boundary + 0.03, 0.18, "click", 0.08)
    if len(boundaries) > 2:
        add_event(buf, boundaries[2] + 0.05, 0.75, "rise", 0.22)
        add_event(buf, boundaries[2] + 0.76, 0.65, "impact", 0.20)
    if len(boundaries) > 6:
        add_event(buf, boundaries[5] + 0.15, 0.9, "shimmer", 0.13)
    return buf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-file", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--music-out", required=True)
    parser.add_argument("--sfx-out", required=True)
    args = parser.parse_args()

    duration = max(1.0, args.duration)
    lengths = scene_durations(Path(args.scene_file), duration)
    boundaries = [0.0]
    for length in lengths:
        boundaries.append(boundaries[-1] + length)
    boundaries[-1] = duration

    music = make_music(duration, boundaries)
    sfx = make_sfx(duration, boundaries)
    write_wav(Path(args.music_out), music)
    write_wav(Path(args.sfx_out), sfx)
    print(f"Created cinematic music and scene SFX for {duration:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

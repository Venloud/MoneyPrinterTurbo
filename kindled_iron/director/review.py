"""Vision review: the 8 review stills of the finished MP4, each with its script line, judged by Gemini vision.

For every still: does the picture match the line, is everything readable, is anything empty, does anything overlap?
The verdict and every issue go to review.json; failed stills feed one automatic fix round of the planner.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from kindled_iron.director import gemini

QUESTION = (
    "These are {n} stills from a vertical educational short (hand-drawn whiteboard style: a clip box at the top, "
    "captions under it, drawings in the middle, a guide character at the bottom). Still k was taken while the "
    "narrator says LINE k. For each still answer strictly: matches (the drawings and clip-box media illustrate that "
    "line's meaning), readable (labels and captions legible, nothing cut off), empty (a blank card, empty frame or "
    "large empty area), overlap (text on text, text on the character, drawings colliding). Return JSON: "
    "{{\"stills\": [{{\"k\": 1, \"matches\": true, \"readable\": true, \"empty\": false, \"overlap\": false, "
    "\"issues\": \"...\", \"fix\": \"what to change in the plan for that line\"}}], \"verdict\": \"pass\"|\"fail\", "
    "\"summary\": \"...\"}}. LINES: {lines}")


def stills(mp4: Path, times: list[float], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for k, t in enumerate(times):
        f = out_dir / f"still_{k + 1}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1",
                        "-vf", "scale=540:960", "-q:v", "4", str(f)], check=True)
        files.append(f)
    return files


def review(mp4: Path, times: list[float], frame_lines: list[str], work: Path) -> dict:
    imgs = stills(mp4, times, work / "review_stills")
    q = QUESTION.format(n=len(imgs), lines=json.dumps({str(k + 1): l for k, l in enumerate(frame_lines)}, ensure_ascii=False))
    r = gemini.call_json("review", q, images=imgs, temperature=0.1)
    st = r.get("stills") or []
    bad = [s for s in st if not (s.get("matches") and s.get("readable") and not s.get("empty") and not s.get("overlap"))]
    r["verdict"] = "pass" if st and not bad else "fail"
    r["times"] = times
    return r


def fixes(r: dict, frame_beats: list[str]) -> list[str]:
    out = []
    for s in r.get("stills", []):
        if s.get("matches") and s.get("readable") and not s.get("empty") and not s.get("overlap"):
            continue
        k = int(s.get("k", 0)) - 1
        where = frame_beats[k] if 0 <= k < len(frame_beats) else f"still {k + 1}"
        out.append(f"vision review, {where}: {s.get('issues', '')} -> {s.get('fix', '')}".strip())
    return out

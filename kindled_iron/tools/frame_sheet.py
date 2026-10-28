"""8-frame review sheet of a finished render (2 x 4 grid, each frame labelled with its time).

    python -m kindled_iron.tools.frame_sheet video.mp4 --work <render work dir> --out sheet.jpg

With the work dir of a media-box scene, the frames include the opening frame, a moment inside every verse
(typed half way, so the typing and the caret show) and evenly spread clip moments; otherwise 8 even frames.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def pick_times(duration: float, work: Path | None, n: int = 8) -> list[float]:
    if work and (work / "preview_times.json").exists():         # the render's own choice (verses, memes, bullets...)
        return json.loads((work / "preview_times.json").read_text())[:n]
    times = [0.5]
    segs = []
    if work and (work / "box_segments.json").exists():
        segs = json.loads((work / "box_segments.json").read_text())
    for s in segs:
        if s["kind"] == "verse":
            for p in s["pages"]:
                times.append(round(p["t"] + (s["ref_t"] - p["t"]) * 0.5 if len(s["pages"]) == 1 else p["t"] + 2.0, 2))
    clip_mid = [round((s["t0"] + s["t1"]) / 2, 2) for s in segs if s["kind"] == "clip"]
    rest = n - len(times)
    if clip_mid and rest > 0:
        step = len(clip_mid) / rest
        times += [clip_mid[min(len(clip_mid) - 1, int(step * (k + 0.5)))] for k in range(rest)]
    while len(times) < n:
        times.append(round(duration * len(times) / n, 2))
    return sorted(times[:n])


def tile_stills(d: Path, out: str) -> None:
    files = sorted(d.glob("frame_*.png"), key=lambda f: float(f.stem.split("_")[-1]))[:8]
    font = (Path(__file__).resolve().parents[1] / "vendor" / "fonts" / "Caveat.ttf").as_posix()
    inputs, chains = [], []
    for i, f in enumerate(files):
        t = float(f.stem.split("_")[-1])
        inputs += ["-i", str(f)]
        chains.append(f"[{i}:v]scale=360:640,drawtext=fontfile='{font}':text='{t:.1f} s':fontsize=44:x=12:y=8:"
                      f"fontcolor=white:box=1:boxcolor=black@0.55[v{i}]")
    grid = "".join(f"[v{i}]" for i in range(len(files))) + f"xstack=inputs={len(files)}:layout=" + \
        "|".join(f"{(i % 4) * 360}_{(i // 4) * 640}" for i in range(len(files)))
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains) + ";" + grid,
                    "-frames:v", "1", "-q:v", "3", out], check=True)
    print(f"sheet: {out} ({len(files)} stills)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", nargs="?", default=None)
    ap.add_argument("--work", default=None)
    ap.add_argument("--stills", default=None, help="dir of frame_<t>.png stills (render --frames-only): tile those instead")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.stills:
        tile_stills(Path(a.stills), a.out)
        return
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                         a.video]).decode().strip())
    times = pick_times(dur, Path(a.work) if a.work else None)
    font = (Path(__file__).resolve().parents[1] / "vendor" / "fonts" / "Caveat.ttf").as_posix()
    inputs, chains = [], []
    for i, t in enumerate(times):
        inputs += ["-ss", f"{t:.2f}", "-i", a.video]
        chains.append(f"[{i}:v]scale=360:640,drawtext=fontfile='{font}':text='{t:.1f} s':fontsize=44:x=12:y=8:"
                      f"fontcolor=white:box=1:boxcolor=black@0.55[v{i}]")
    grid = "".join(f"[v{i}]" for i in range(len(times))) + f"xstack=inputs={len(times)}:layout=" + \
        "|".join(f"{(i % 4) * 360}_{(i // 4) * 640}" for i in range(len(times)))
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains) + ";" + grid,
                    "-frames:v", "1", "-q:v", "3", a.out], check=True)
    print(f"sheet: {a.out} (frames at {', '.join(f'{t:.1f}' for t in times)} s)")


if __name__ == "__main__":
    main()

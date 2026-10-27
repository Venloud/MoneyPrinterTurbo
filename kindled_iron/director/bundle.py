"""The saved preview: one video and the evidence that belongs to it, replaced together or not at all.

previews/<id>/ (the same folder for every run; no per-attempt folders) holds the video and its evidence:
<id>.mp4, review.json, gates.json, scene.json, plan.json, media.json, doodle_misses.json, guide_actions.json, the
frame sheet, and video.json (a manifest: the MP4's sha256, size, duration, streams, run, director commit, narration
sha, review verdict, accepted). They are written ONLY with a new MP4 that was fully rendered and verified (ffprobe
streams + duration, a full decode without errors), staged in a hidden temporary folder (removed afterwards) and
moved in place file by file, video.json last, so an interrupted save never leaves a manifest describing another
video. status.json, rounds.json, ai_calls.json, story.json, checkpoint.json and fail_report.md describe the latest
run, as before.

A failed or incomplete render therefore never replaces a complete MP4: the run writes no bundle and status.json
says the previous video was kept (and which one, from its manifest).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "video.json"
MIN_BYTES = 50_000


class BundleError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_mp4(path: Path, expect_seconds: float | None = None, decode: bool = True) -> dict:
    """A complete, playable video: exists, not tiny, a 1080x1920 video stream and an audio stream, the expected
    duration (when given: at least expect - 0.5 s, at most expect + 6 s), and (decode=True) every frame decodes."""
    path = Path(path)
    if not path.is_file():
        raise BundleError(f"{path.name} does not exist")
    size = path.stat().st_size
    if size < MIN_BYTES:
        raise BundleError(f"{path.name} is only {size} bytes")
    try:
        probe = json.loads(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
             "-of", "json", str(path)], stderr=subprocess.STDOUT))
    except (subprocess.CalledProcessError, ValueError) as e:
        raise BundleError(f"{path.name} is not a readable video ({str(e)[:200]})")
    streams = probe.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not video:
        raise BundleError(f"{path.name} has no video stream")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise BundleError(f"{path.name} has no audio stream")
    w, h = video[0].get("width"), video[0].get("height")
    if (w, h) != (1080, 1920):
        raise BundleError(f"{path.name} is {w}x{h}, not 1080x1920")
    dur = float((probe.get("format") or {}).get("duration") or 0)
    if expect_seconds is not None and not (expect_seconds - 0.5 <= dur <= expect_seconds + 6.0):
        raise BundleError(f"{path.name} lasts {dur:.2f} s; the narration needs about {expect_seconds:.2f} s (incomplete render?)")
    if decode:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
        if p.returncode or p.stderr.strip():
            raise BundleError(f"{path.name} does not decode cleanly: {(p.stderr or '').strip()[:300]}")
    return {"bytes": size, "duration": round(dur, 3), "width": w, "height": h, "sha256": sha256(path)}


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write(out: Path, vid: str, mp4: Path, data: dict, extra: dict | None = None, manifest: dict | None = None,
          expect_seconds: float | None = None, decode: bool = True) -> dict:
    """Replace the video bundle in `out` with this render, or raise BundleError and change nothing.
    data: {"review.json": obj, ...} JSON files; extra: {"<id>-8-frames.jpg": Path, ...} files to copy.
    -> the manifest written to video.json."""
    out = Path(out)
    info = verify_mp4(mp4, expect_seconds, decode)
    stage = out / ".staging"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        staged = stage / f"{vid}.mp4"
        shutil.copyfile(mp4, staged)
        if sha256(staged) != info["sha256"]:
            raise BundleError("the copied video differs from the render (interrupted copy?)")
        names = [staged.name]
        for name, obj in data.items():
            (stage / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            names.append(name)
        for name, src in (extra or {}).items():
            if src and Path(src).is_file():
                shutil.copyfile(src, stage / name)
                names.append(name)
        man = {**(manifest or {}), "video": f"{vid}.mp4", **info, "files": sorted(names),
               "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (stage / MANIFEST).write_text(json.dumps(man, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        old = read_manifest(out)                   # files of the previous bundle this one does not have go too
        for name in (old or {}).get("files", []):
            if name not in names and (out / name).is_file():
                (out / name).unlink()
        for name in names:                         # the video and its evidence first ...
            os.replace(stage / name, out / name)
        os.replace(stage / MANIFEST, out / MANIFEST)   # ... the manifest last: it only ever describes what is there
        return man
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def read_manifest(out: Path) -> dict | None:
    f = Path(out) / MANIFEST
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except ValueError:
        return None


def consistent(out: Path, vid: str) -> tuple[bool, str]:
    """Does video.json describe the MP4 that is actually there?"""
    man = read_manifest(out)
    mp4 = Path(out) / f"{vid}.mp4"
    if not man:
        return (not mp4.exists(), "no manifest" + (" but an MP4 is there" if mp4.exists() else ""))
    if not mp4.is_file():
        return False, "the manifest names a video that is not there"
    if sha256(mp4) != man.get("sha256"):
        return False, "the MP4 is not the one the manifest describes"
    missing = [n for n in man.get("files", []) if not (Path(out) / n).is_file()]
    return (not missing, "missing: " + ", ".join(missing) if missing else "ok")

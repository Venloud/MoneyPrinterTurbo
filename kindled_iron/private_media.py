"""Third-party media: meme images, reaction clips and film/TV references. NEVER stored in this public repo.

Where they come from, in order:
1. the owner's PRIVATE repo (Venloud/kindled-iron-voice): folders reactions/ (meme images and reaction
   clips, tagged by emotion) and movie_reference/ (film/TV clips, tagged by scene). The workflow checks
   them out at render time with VOICE_REPO_TOKEN into $KI_PRIVATE_MEDIA. A file is found by the words
   in its name (god_did.mp4 -> "god did"); the folder's index.json can add tags, the words said in a
   clip and its start/end seconds.
2. reaction images only: github.com/cheesits456/ReactionPics (file name = emotion), downloaded at render
   time into the clip cache, never copied into this repo.
3. clips only: yt-dlp from the workflow (KI_YTDLP=1), only when the request names the video
   ("yt": URL or exact search words, "start": second); a blind search would grab the wrong moment.
   YouTube often blocks runners: then kindled_iron/tools/fetch_clip.py does it from the owner's PC.
GIPHY is not used in videos (its API terms require a "Powered By GIPHY" mark and creator credit).
Nothing found = the scene's pinned fallback (stock clip / guide action); a missing clip never fails a render.

One switch turns all of it off: voice_profiles.json -> use_third_party_clips (env KI_THIRD_PARTY=0/1 wins).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

FOLDERS = ("reactions", "movie_reference")
CLIP_EXT = {".mp4", ".mov", ".webm", ".mkv"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
UA = {"User-Agent": "KindledIronBot/1.0 (https://github.com/Venloud/MoneyPrinterTurbo)"}
REACTIONPICS = "https://raw.githubusercontent.com/cheesits456/ReactionPics/master/images/"
# emotion -> ReactionPics file names (checked by eye; crude / off-brand images are never listed)
REACTIONPICS_TAGS = {
    "confused": ["confused.jpeg", "wat.jpeg", "what.jpeg"],
    "confused_math": ["confused.jpeg"],
    "mind_blown": ["woah.jpeg", "oh.jpeg"],
    "surprised": ["oh.jpeg", "woah.jpeg"],
    "smart": ["smart.jpeg"],
    "celebration": ["yay.jpeg"],
}


def enabled(profile: dict) -> bool:
    env = os.environ.get("KI_THIRD_PARTY")
    if env in ("0", "1", "true", "false"):
        return env in ("1", "true")
    return bool(profile.get("use_third_party_clips", False))


def root() -> Path | None:
    r = os.environ.get("KI_PRIVATE_MEDIA")
    return Path(r) if r and Path(r).is_dir() else None


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _index(folder: Path) -> dict:
    f = folder / "index.json"
    try:
        return {it["file"]: it for it in json.loads(f.read_text(encoding="utf-8")).get("items", [])} if f.exists() else {}
    except (ValueError, KeyError):
        return {}


def find(query: str, kind: str, folders=FOLDERS) -> dict | None:
    """Best file in the private folders whose name/tags contain every word of the query."""
    base = root()
    if not base:
        return None
    want = _words(query)
    best = None
    for name in folders:
        folder = base / name
        if not folder.is_dir():
            continue
        idx = _index(folder)
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in (CLIP_EXT if kind == "clip" else IMG_EXT):
                continue
            meta = idx.get(f.name, {})
            tags = _words(f.stem.replace("_", " ")) | set().union(*[_words(t) for t in meta.get("tags", [])] or [set()])
            score = len(want & tags)
            if want and want <= tags and (not best or score > best[0]):
                best = (score, {**meta, "path": f, "origin": f"private:{name}/{f.name}"})
    return best[1] if best else None


def _cache() -> Path:
    c = Path(os.environ.get("KI_CLIP_CACHE", Path.home() / ".cache" / "kindled_iron" / "clips")) / "third_party"
    c.mkdir(parents=True, exist_ok=True)
    return c


def reaction_image(emotion: str) -> dict | None:
    hit = find(emotion.replace("_", " "), "image", ("reactions",))
    if hit:
        return hit
    for name in REACTIONPICS_TAGS.get(emotion, []):
        f = _cache() / f"reactionpics_{name}"
        try:
            if not f.exists():
                with urllib.request.urlopen(urllib.request.Request(REACTIONPICS + name, headers=UA), timeout=20) as r:
                    f.write_bytes(r.read())
            return {"path": f, "origin": f"ReactionPics/{name}", "source": REACTIONPICS + name}
        except Exception:  # noqa: BLE001 - offline / gone: try the next one
            continue
    return None


def _ytdlp(query: str, start: float, dur: float, log) -> dict | None:
    if os.environ.get("KI_YTDLP") != "1" or not shutil.which("yt-dlp"):
        return None
    out = _cache() / ("yt_" + hashlib.sha1(f"{query}|{start}|{dur}".encode()).hexdigest()[:16] + ".mp4")
    if not out.exists():
        target = query if query.startswith("http") else f"ytsearch1:{query}"
        try:
            subprocess.run(["yt-dlp", "-q", "--no-playlist", "-f", "mp4[height<=720]/best[height<=720]",
                            "--download-sections", f"*{start:.2f}-{start + dur:.2f}", "--force-keyframes-at-cuts",
                            "-o", str(out), target], check=True, timeout=120, capture_output=True)
        except Exception as e:  # noqa: BLE001
            msg = getattr(e, "stderr", b"") or b""
            log(f"meme clip {query!r}: yt-dlp failed ({(msg.decode(errors='ignore').strip().splitlines() or [type(e).__name__])[-1][:120]})")
            return None
    return {"path": out, "origin": f"yt-dlp:{query}", "start": 0.0, "end": dur} if out.exists() else None


def _frames(src: Path, start: float, dur: float, w: int, h: int, out_dir: Path, still: bool, crop=None) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    inp = (["-loop", "1"] if still and src.suffix.lower() != ".gif" else ["-stream_loop", "-1"] if still else ["-ss", f"{start:.2f}"])
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inp, "-i", str(src), "-t", f"{dur:.2f}", "-an",
                    "-vf", (f"crop=iw*{crop[2]}:ih*{crop[3]}:iw*{crop[0]}:ih*{crop[1]}," if crop else "") +
                    f"fps=30,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                    "-q:v", "4", str(out_dir / "f_%04d.jpg")], check=True)
    return [p.as_uri() for p in sorted(out_dir.glob("f_*.jpg"))]


def _audio(src: Path, start: float, dur: float, out: Path) -> Path | None:
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}", "-vn",
                        "-ac", "1", "-ar", "44100", "-af", "afade=t=out:st=%.2f:d=0.12" % max(0.0, dur - 0.12), str(out)],
                       check=True)
        return out if out.exists() and out.stat().st_size > 1000 else None
    except subprocess.CalledProcessError:
        return None


def resolve_scene(scene: dict, profile: dict, work: Path, log) -> list[dict]:
    """Replaces every {"meme_clip": {...}} event in the scene by a ready inset (frames, optional audio)
    or by its pinned "fallback" event(s). Returns what was used (for meta + the private-upload rule)."""
    use = enabled(profile)
    used = []
    for beat in scene["beats"]:
        new = []
        for ev in beat.get("events", []):
            spec = ev.get("meme_clip")
            if not isinstance(spec, dict):
                new.append(ev)
                continue
            max_s = min(2.0, float(spec.get("max_s", 2.0)))
            hit = None
            if use:
                hit = find(spec.get("query", ""), "clip", spec.get("folders", FOLDERS))
                if not hit and spec.get("yt"):       # only with a known video (URL or exact search) + start second
                    hit = _ytdlp(spec["yt"], float(spec.get("start", 0)), max_s, log)
            if not hit:
                why = "third-party clips are off" if not use else "not in the private folders" + \
                    ("" if spec.get("yt") and os.environ.get("KI_YTDLP") == "1" else " (no yt-dlp source given)")
                fb = ev.get("fallback") or []
                fb = fb if isinstance(fb, list) else [fb]
                log(f"meme clip {spec.get('query')!r}: {why}; using the fallback ({len(fb)} event(s))")
                new += fb
                continue
            start = float(hit.get("start", spec.get("start", 0.0)))
            end = float(hit.get("end", start + max_s))
            dur = round(min(max_s, end - start), 2)
            w, h = int(ev.get("w", 820)), int(ev.get("h", 470))
            iid = ev.get("id", f"meme{len(used) + 1}")
            # crop [x, y, w, h] in fractions: the scene's wins, else the folder index.json entry
            frames = _frames(hit["path"], start, dur, w, h, work / "insets" / iid, still=False, crop=ev.get("crop") or hit.get("crop"))
            e = {k: v for k, v in ev.items() if k not in ("meme_clip", "fallback")}
            e.update({"do": "draw", "type": "inset", "id": iid, "frames": frames, "fps": 30, "clip_dur": round(len(frames) / 30, 3)})
            if spec.get("audio", hit.get("audio", False)):
                a = _audio(hit["path"], start, dur, work / f"{iid}_audio.wav")
                if a:
                    e["audio_file"] = str(a)
            new.append(e)
            used.append({"id": iid, "query": spec.get("query"), "origin": hit["origin"], "source": hit.get("source", ""),
                         "start": start, "duration": dur, "audio": "audio_file" in e})
            log(f"meme clip {iid}: {hit['origin']} {start:.2f}-{start + dur:.2f} s{' with its audio' if 'audio_file' in e else ''}")
        beat["events"] = new
    return used


def reaction_card(emotion: str, at_t: float, dur: float, pos: dict, work: Path, n: int) -> tuple[dict, dict, dict] | None:
    """A meme image for a {"reaction": ...} request: (object, draw event, record) or None."""
    hit = reaction_image(emotion)
    if not hit:
        return None
    w, h = int(pos.get("w", 400)), int(pos.get("h", 300))
    iid = f"react{n}"
    frames = _frames(hit["path"], 0.0, dur, w, h, work / "insets" / iid, still=True)
    obj = {"id": iid, "type": "inset", "x": pos.get("x", 540), "y": pos.get("y", 560), "w": w, "h": h, "rotate": pos.get("rotate", -4),
           "frames": frames, "fps": 30, "clip_dur": round(len(frames) / 30, 3)}
    return obj, {"t": round(at_t, 3), "do": "draw", "id": iid, "pop": False}, \
        {"id": iid, "emotion": emotion, "origin": hit["origin"], "source": hit.get("source", "")}

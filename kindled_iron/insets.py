"""Real footage insets: fetched BEFORE the render (the render itself uses no network and no AI).

Sources, all free with no attribution required: NASA Image and Video Library (public domain,
https://www.nasa.gov/nasa-brand-center/images-and-media/), Pexels (Pexels License,
PEXELS_API_KEY), Pixabay (Pixabay Content License, PIXABAY_API_KEY). Never CC BY.
A clip that can't be found or downloaded is skipped silently (the inset is dropped).
Each clip becomes a short JPEG sequence the page swaps frame by frame. sources.json records
source page, file URL and licence for every clip used.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

MAX_INSETS = 6
UA = {"User-Agent": "KindledIronBot/1.0 (test renders)"}
LICENSES = {
    "nasa": "NASA media: public domain, not copyrighted (NASA images and media guidelines)",
    "pexels": "Pexels License: free to use, no attribution required",
    "pixabay": "Pixabay Content License: free to use, no attribution required",
}


def _json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _nasa(query: str, pin: str | None) -> list[dict]:
    q = urllib.parse.urlencode({"q": query, "media_type": "video"} if not pin else {"nasa_id": pin, "media_type": "video"})
    items = _json(f"https://images-api.nasa.gov/search?{q}")["collection"]["items"][:8]
    out = []
    for it in items:
        d = it["data"][0]
        text = (d.get("description", "") + " " + " ".join(d.get("keywords", []))).lower()
        if "copyright" in text or "©" in text:          # third-party material inside NASA items: skip
            continue
        files = _json(urllib.parse.quote(it["href"], safe=":/~%"))
        mp4 = [f for f in files if f.endswith(".mp4")]
        pick = next((f for f in mp4 if "~small" in f), None) or next((f for f in mp4 if "~mobile" in f), None) \
            or next((f for f in mp4 if "~medium" in f), None) or (mp4[0] if mp4 else None)
        if pick:
            out.append({"source": "nasa", "file_url": urllib.parse.quote(pick.replace("http://", "https://"), safe=":/~%"), "title": d.get("title", ""),
                        "page": f"https://images.nasa.gov/details/{d['nasa_id']}", "id": d["nasa_id"]})
    return out


def _pexels(query: str, pin: str | None) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    url = f"https://api.pexels.com/videos/videos/{pin}" if pin else \
        "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": query, "per_page": 8, "orientation": "landscape"})
    data = _json(url, {"Authorization": key})
    vids = [data] if pin else data.get("videos", [])
    out = []
    for v in vids:
        files = sorted([f for f in v.get("video_files", []) if f.get("width") and 640 <= f["width"] <= 1920],
                       key=lambda f: abs(f["width"] - 1280))
        if files:
            out.append({"source": "pexels", "file_url": files[0]["link"], "title": v.get("url", ""), "page": v.get("url", ""),
                        "id": str(v["id"])})
    return out


def _pixabay(query: str, pin: str | None) -> list[dict]:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    params = {"key": key, "safesearch": "true", "per_page": 8}
    params.update({"id": pin} if pin else {"q": query})
    hits = _json("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(params)).get("hits", [])
    out = []
    for h in hits:
        v = h.get("videos", {})
        f = v.get("small") or v.get("medium") or v.get("tiny")
        if f and f.get("url"):
            out.append({"source": "pixabay", "file_url": f["url"], "title": h.get("tags", ""), "page": h.get("pageURL", ""),
                        "id": str(h["id"])})
    return out


SEARCH = {"nasa": _nasa, "pexels": _pexels, "pixabay": _pixabay}


def _download(url: str) -> Path:
    cache = Path(os.environ.get("KI_CLIP_CACHE", Path.home() / ".cache" / "kindled_iron" / "clips"))
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".mp4")
    if not f.exists():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r, open(f, "wb") as out:
            out.write(r.read())
    return f


def _frames(clip: Path, start: float, dur: float, w: int, h: int, fps: int, out_dir: Path, crop=None) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(clip), "-t", f"{dur:.2f}",
                    "-vf", (f"crop=iw*{crop[2]}:ih*{crop[3]}:iw*{crop[0]}:ih*{crop[1]}," if crop else "") +
                    f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},eq=saturation=1.08",
                    "-q:v", "4", str(out_dir / "f_%04d.jpg")], check=True)
    return [p.as_uri() for p in sorted(out_dir.glob("f_*.jpg"))]


def fetch(scene: dict, work: Path, log) -> dict:
    """Returns {inset_id: {"frames": [...], "fps": 30, "clip_dur": s} } and writes sources.json."""
    found, sources = {}, []
    wanted = [ev for b in scene["beats"] for ev in b.get("events", []) if ev.get("do") == "draw" and ev.get("type") == "inset"]
    if len(wanted) > MAX_INSETS:
        log(f"WARNING: {len(wanted)} insets requested, keeping the first {MAX_INSETS}")
        wanted = wanted[:MAX_INSETS]
    for ev in wanted:
        dur = max(1.5, min(3.0, float(ev.get("clip_dur", 2.2))))
        fps = 30
        w, h = int(ev.get("w", 380)), int(ev.get("h", 260))
        order = ev.get("sources", ["nasa", "pexels", "pixabay"])
        pins = ev.get("pin", {})
        hit = None
        for src in order:
            try:
                cands = SEARCH[src](ev.get("query", ""), pins.get(src))
            except Exception:  # noqa: BLE001 - a source being down is not an error
                cands = []
            for c in cands[:3]:
                try:
                    clip = _download(c["file_url"])
                    length = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                            "-of", "csv=p=0", str(clip)]).decode().strip() or 0)
                    if length < dur + 0.2:
                        continue
                    start = min(float(ev.get("start", 1.0)), max(0.0, length - dur - 0.1))
                    frames = _frames(clip, start, dur, w, h, fps, work / "insets" / ev["id"], ev.get("crop"))
                    if len(frames) >= int(dur * fps * 0.8):
                        hit = (c, start, frames)
                        break
                except Exception:  # noqa: BLE001
                    continue
            if hit:
                break
        if not hit:
            log(f"inset {ev['id']}: no clip found for {ev.get('query')!r}, skipped")
            continue
        c, start, frames = hit
        found[ev["id"]] = {"frames": frames, "fps": fps, "clip_dur": round(len(frames) / fps, 3)}
        sources.append({"inset": ev["id"], "query": ev.get("query"), "source": c["source"], "id": c["id"], "title": c["title"],
                        "page": c["page"], "file_url": c["file_url"], "license": LICENSES[c["source"]],
                        "start": start, "duration": round(len(frames) / fps, 2)})
        log(f"inset {ev['id']}: {c['source']} {c['id']} ({c['title'][:50]})")
    (work / "sources.json").write_text(json.dumps(sources, indent=1))
    return found

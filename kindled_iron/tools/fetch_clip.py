"""Cut a short clip on YOUR PC and put it in the PRIVATE repo (never in this public one).

    python kindled_iron/tools/fetch_clip.py "<youtube url or search words>" --start 12.5 --dur 2 \
        --name burning_bush --folder movie_reference [--tags "moses,fire"] [--say "..."] [--audio]

Needs: yt-dlp and ffmpeg on your PATH (pip install yt-dlp), and a GitHub token that can write to
Venloud/kindled-iron-voice: set GITHUB_TOKEN (fine-grained, Contents: read and write on that repo), or
be logged in with the gh CLI (the script then uses `gh auth token`).
What it does: downloads only the needed seconds, cuts them to an MP4 (max 720p, max 5 s), uploads
<folder>/<name>.mp4 to the private repo and adds the clip to that folder's index.json (tags, words,
source link). The next render finds it by its name. Nothing is kept in this repo.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("KI_VOICE_REPO", "Venloud/kindled-iron-voice")
API = f"https://api.github.com/repos/{REPO}/contents"


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("VOICE_REPO_TOKEN")
    if not t and shutil.which("gh"):
        t = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    if not t:
        sys.exit("No token: set GITHUB_TOKEN (Contents: read and write on %s) or log in with `gh auth login`." % REPO)
    return t


def gh(method: str, path: str, tok: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{API}/{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return {}
        sys.exit(f"GitHub {method} {path}: HTTP {e.code} {e.read()[:200]!r}")


def put(path: str, data: bytes, msg: str, tok: str) -> None:
    old = gh("GET", path, tok)
    body = {"message": msg, "content": base64.b64encode(data).decode()}
    if old.get("sha"):
        body["sha"] = old["sha"]
    gh("PUT", path, tok, body)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="YouTube URL, or search words (first result is used)")
    ap.add_argument("--start", type=float, default=0.0, help="start second in the source video")
    ap.add_argument("--dur", type=float, default=2.0, help="length in seconds (max 5)")
    ap.add_argument("--name", required=True, help="file name = what it shows, e.g. burning_bush, god_did")
    ap.add_argument("--folder", choices=["reactions", "movie_reference"], default="movie_reference")
    ap.add_argument("--tags", default="", help="extra tags, comma separated")
    ap.add_argument("--say", default="", help="the words spoken in the clip, if any")
    ap.add_argument("--audio", action="store_true", help="the render should play the clip's own sound")
    a = ap.parse_args()
    for tool in ("yt-dlp", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found: install it first (pip install yt-dlp; ffmpeg from ffmpeg.org)")
    dur = max(0.5, min(5.0, a.dur))
    tok = token()
    target = a.source if a.source.startswith("http") else f"ytsearch1:{a.source}"
    with tempfile.TemporaryDirectory() as tmp:
        raw, out = Path(tmp) / "raw.mp4", Path(tmp) / "clip.mp4"
        # a little extra around the cut, then an exact re-encode
        lo = max(0.0, a.start - 1.0)
        subprocess.run(["yt-dlp", "--no-playlist", "-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4",
                        "--download-sections", f"*{lo:.2f}-{a.start + dur + 1.0:.2f}", "-o", str(raw), target], check=True)
        url = subprocess.run(["yt-dlp", "--no-playlist", "--get-id", target], capture_output=True, text=True).stdout.strip()
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a.start - lo:.2f}", "-i", str(raw), "-t", f"{dur:.2f}",
                        "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)
        name = f"{a.name}.mp4"
        put(f"{a.folder}/{name}", out.read_bytes(), f"Add {a.folder}/{name}", tok)
    idx = gh("GET", f"{a.folder}/index.json", tok)
    data = json.loads(base64.b64decode(idx["content"])) if idx.get("content") else {"items": []}
    data["items"] = [it for it in data.get("items", []) if it.get("file") != name] + [{
        "file": name, "tags": [t.strip() for t in a.tags.split(",") if t.strip()], "say": a.say, "start": 0.0, "end": dur,
        "audio": a.audio, "source": f"https://www.youtube.com/watch?v={url}" if url else a.source}]
    put(f"{a.folder}/index.json", (json.dumps(data, indent=2) + "\n").encode(), f"Index {a.folder}/{name}", tok)
    print(f"Uploaded {a.folder}/{name} ({dur:.1f} s) to the private repo {REPO}. The next render can use it.")


if __name__ == "__main__":
    main()

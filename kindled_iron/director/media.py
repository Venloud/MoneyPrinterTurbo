"""Clip-box media for the director: stock footage found by each line's meaning, and the owner's meme library.

- Stock: the plan's query goes to Pexels, then Pixabay (repo secrets, Actions only). A result is kept only when
  its own title / page words share a word with the query (a "hammer" query never takes a paint-brush clip
  whose page says nothing about hammers); a clip is never shown twice in a row nor more than twice per video.
  Nothing found -> an error the planner gets back ("give another concrete query or use a meme").
- Memes: kindled-iron-voice/movie_reference/ (index.json tags + the file name's own words).
- Every pick is logged in media.json (line, word, query/file, source, id, page, why).
Offline (no keys, KI_BOX_PLACEHOLDER=1) stock queries resolve to placeholders so tests can run.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from kindled_iron import insets

MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"}
STOP = {"the", "and", "with", "from", "into", "over", "under", "for", "person", "people", "close", "view", "video",
        "shot", "slow", "motion", "footage", "stock"}


def _words(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", s.lower()):
        if len(w) >= 3 and w not in STOP:
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def library(root: Path | None) -> list[dict]:
    """The owner's shared meme / clip library: every media file in movie_reference/ with its tags."""
    if not root or not (root / "movie_reference").is_dir():
        return []
    d = root / "movie_reference"
    idx = {}
    if (d / "index.json").exists():
        idx = {i["file"]: i for i in json.loads((d / "index.json").read_text(encoding="utf-8")).get("items", [])}
    out = []
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in MEDIA_EXT:
            continue
        it = idx.get(f.name, {})
        name_words = " ".join(re.findall(r"[A-Za-z]+", f.stem)).lower()
        out.append({"file": f.name, "kind": "video" if f.suffix.lower() in (".mp4", ".mov", ".webm") else
                    ("gif" if f.suffix.lower() == ".gif" else "image"),
                    "tags": sorted(set(it.get("tags", [])) | set(name_words.split())),
                    "note": it.get("note") or it.get("cue") or ""})
    return out


def stock(query: str, avoid: list[str], counts: dict, log) -> dict | None:
    """First Pexels/Pixabay video whose own words match the query, not the previous clip, used < 2 times."""
    if os.environ.get("KI_BOX_PLACEHOLDER") == "1" and not os.environ.get("PEXELS_API_KEY"):
        pid = "ph" + str(abs(hash(query)) % 10 ** 6)
        return {"source": "pexels", "id": pid, "title": f"placeholder for {query!r}", "page": "", "why": "offline placeholder"}
    want = _words(query)
    for search in (insets._pexels, insets._pixabay):
        try:
            cands = search(query, None)
        except Exception as e:  # noqa: BLE001 - one provider failing never stops the other
            log(f"media: {search.__name__} failed for {query!r}: {type(e).__name__}: {e}")
            continue
        for c in cands:
            have = _words(c.get("title", "") + " " + c.get("page", ""))
            if not want & have:
                continue
            ident = f"{c['source']}:{c['id']}"
            if (avoid and avoid[-1] == ident) or counts.get(ident, 0) >= 2:
                continue
            return {"source": c["source"], "id": c["id"], "title": c.get("title", ""), "page": c.get("page", ""),
                    "why": "shares " + ", ".join(sorted(want & have)) + " with the query"}
    return None


def resolve(plan: dict, lib: list[dict], log) -> tuple[list[list[dict]], list[dict], list[str]]:
    """-> (per-line resolved box items, media.json records, errors for the planner)."""
    files = {m["file"] for m in lib}
    per_line, records, errors = [], [], []
    order: list[str] = []
    counts: dict[str, int] = {}
    for i, L in enumerate(plan["lines"]):
        items = []
        for b in L.get("box") or []:
            rec = {"line": i + 1, "word": b.get("word"), "kind": b.get("kind")}
            if L.get("verse"):
                rec.update({"skipped": "verse line: the typed verse card fills the box"})
                records.append(rec)
                continue
            if b.get("kind") == "meme":
                f = b.get("file")
                ident = f"meme:{f}"
                if f not in files:
                    errors.append(f"line {i + 1}: meme {f!r} is not in the library")
                    continue
                if (order and order[-1] == ident) or counts.get(ident, 0) >= 2:
                    errors.append(f"line {i + 1}: meme {f!r} would repeat (twice in a row or a third time): pick another")
                    continue
                items.append({"kind": "meme", "file": f, "word": b["word"]})
                rec.update({"file": f, "source": "owner upload (private)", "why": "planner matched the meme's tags"})
            else:
                q = b.get("query", "")
                hit = stock(q, order, counts, log)
                if not hit:
                    errors.append(f"line {i + 1}: no stock video matches {q!r}: give a different concrete query "
                                  "(things a camera films) or a meme from the library")
                    rec.update({"query": q, "result": "nothing matched"})
                    records.append(rec)
                    continue
                ident = f"{hit['source']}:{hit['id']}"
                items.append({"kind": "stock", "word": b["word"], **hit})
                rec.update({"query": q, **hit})
            records.append(rec)
            order.append(ident)
            counts[ident] = counts.get(ident, 0) + 1
        per_line.append(items)
    if not any(it for line in per_line for it in line):
        errors.append("the video has no clip-box media at all: give stock queries or memes")
    return per_line, records, errors

"""Merge a curated media pack (a ZIP with catalog.json) into the private kindled-iron-voice library, safely.

    python kindled_iron/tools/import_media.py --zip pack.zip --private ../kindled-iron-voice [--meta extra.json] [--dry-run]

Where things go (the existing library is reused, never a second one):
  meme                    -> reactions/<id><ext>                     (shown: clip box / pop-up)
  still / footage         -> movie_reference/<id><ext>               (shown: clip box)
  guide_action reference  -> movie_reference/guide_actions/<id><ext> (NOT shown: the guide performs the action)

Rules: every existing file is kept; a file whose bytes are already in the library (sha256) is skipped; a target
name that exists with other bytes gets a numbered name, never overwritten; the catalog's own sha256 is checked;
visually near-identical images (8x8 average hash) are imported but flagged near_duplicate_of. index.json entries
are appended, existing entries are never changed. Licence/source fields are copied as given, never invented.
Prints (and writes --report) what was imported, skipped and renamed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MEDIA = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"}
DEST = {"meme": "reactions", "still": "movie_reference", "footage": "movie_reference",
        "guide_action": "movie_reference/guide_actions"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ahash(p: Path) -> int | None:
    """8x8 average hash of the first frame (None when ffmpeg cannot read it)."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-frames:v", "1", "-vf", "scale=8:8,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    if len(raw) < 64:
        return None
    px = list(raw[:64])
    avg = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v >= avg)


def load_index(folder: Path) -> dict:
    f = folder / "index.json"
    if not f.exists():
        return {"_help": "Optional. Files are found by their name alone; entries add tags and metadata.", "items": []}
    d = json.loads(f.read_text(encoding="utf-8"))
    if not isinstance(d.get("items"), list):
        raise SystemExit(f"FAIL: {f} has no 'items' list; not touching it")
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--private", type=Path, required=True)
    ap.add_argument("--meta", type=Path, default=None, help="extra metadata per asset id (description, tone, ...)")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = a.private
    for need in ("reactions", "movie_reference"):
        if not (root / need).is_dir():
            raise SystemExit(f"FAIL: {root / need} missing: is --private the kindled-iron-voice checkout?")
    extra = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta else {}
    existing = {}                                   # sha256 -> relative path, every media file already there
    hashes = {}                                     # relative path -> average hash (images)
    for folder in ("reactions", "movie_reference"):
        for f in sorted((root / folder).rglob("*")):
            if f.is_file() and f.suffix.lower() in MEDIA:
                rel = f.relative_to(root).as_posix()
                existing.setdefault(sha256(f), rel)
                hashes[rel] = ahash(f)
    report = {"imported": [], "skipped_duplicates": [], "renamed": [], "near_duplicates": [], "errors": []}
    indexes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(a.zip) as z:
            z.extractall(tmp)
        cats = list(Path(tmp).rglob("catalog.json"))
        if not cats:
            raise SystemExit("FAIL: the pack has no catalog.json")
        base = cats[0].parent
        cat = json.loads(cats[0].read_text(encoding="utf-8"))
        for asset in cat.get("assets", []):
            src = base / asset.get("path", "")
            kind = asset.get("type")
            if kind not in DEST or not src.is_file():
                report["errors"].append({"id": asset.get("id"), "why": f"unknown type {kind!r} or missing file {asset.get('path')}"})
                continue
            h = sha256(src)
            if asset.get("sha256") and asset["sha256"] != h:
                report["errors"].append({"id": asset["id"], "why": "sha256 differs from the pack's catalog"})
                continue
            if h in existing:
                report["skipped_duplicates"].append({"id": asset["id"], "same_as": existing[h]})
                continue
            folder = DEST[kind]
            target = root / folder / f"{asset['id']}{src.suffix.lower()}"
            n = 2
            while target.exists():
                report["renamed"].append({"id": asset["id"], "taken": target.name})
                target = root / folder / f"{asset['id']}_{n}{src.suffix.lower()}"
                n += 1
            rel = target.relative_to(root).as_posix()
            ah = ahash(src)
            near = sorted(p for p, v in hashes.items() if ah is not None and v is not None and bin(ah ^ v).count("1") <= 5)
            if near:
                report["near_duplicates"].append({"id": asset["id"], "looks_like": near})
            idx_folder = folder.split("/")[0]
            idx = indexes.setdefault(idx_folder, load_index(root / idx_folder))
            name_in_index = target.relative_to(root / idx_folder).as_posix()
            if any(i.get("file") == name_in_index for i in idx["items"]):
                report["errors"].append({"id": asset["id"], "why": f"{name_in_index} already has an index entry"})
                continue
            meta = extra.get(asset["id"], {})
            item = {"file": name_in_index, "id": asset["id"], "type": "guide_action_reference" if kind == "guide_action" else kind,
                    "category": "/".join(Path(asset["path"]).parent.parts), "tags": asset.get("tags", []),
                    **{k: meta[k] for k in ("description", "tone", "purpose", "guide_action", "use", "same_meme_as") if k in meta},
                    "media_type": "gif" if src.suffix.lower() == ".gif" else
                    ("video" if src.suffix.lower() in (".mp4", ".mov", ".webm") else "image"),
                    "show": kind != "guide_action", "source": asset.get("source", "unknown"),
                    "license": asset.get("license", "unknown"), "sha256": h, "imported_from": a.zip.name}
            if near:
                item["near_duplicate_of"] = near
            idx["items"].append(item)
            existing[h] = rel
            hashes[rel] = ah
            report["imported"].append({"id": asset["id"], "path": rel})
            if not a.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
    if not a.dry_run:
        for folder, idx in indexes.items():
            (root / folder / "index.json").write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")   # same escaping as before
    out = json.dumps(report, indent=1)
    if a.report:
        a.report.write_text(out, encoding="utf-8")
    print(out)
    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Clip-box media for the director: stock footage found by each line's meaning, and the owner's meme library.

- Stock: the plan's query goes to Pexels, then Pixabay (repo secrets, Actions only). A result is kept only when
  its own title / page words share a word with the query (a "hammer" query never takes a paint-brush clip
  whose page says nothing about hammers); a clip is never shown twice in a row nor more than twice per video.
  Nothing found -> an error the planner gets back ("give another concrete query or use a meme").
- Library: kindled-iron-voice/movie_reference/ and reactions/ (index.json tags, description, tone, purpose + the
  file name's own words); show: false entries (guide-action references) are never shown.
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


WRITING = {"chalkboard", "blackboard", "whiteboard", "sign", "signboard", "poster", "newspaper", "headline", "text",
           "letter", "word", "writing", "handwriting", "typing", "book", "page", "note", "notebook", "menu", "banner",
           "billboard", "screen", "phone", "laptop", "calendar", "map"}


def _words(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", s.lower()):
        if len(w) >= 3 and w not in STOP:
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


FOLDERS = ("movie_reference", "reactions")       # the owner's private library; subfolders (guide_actions/) are not media
META = ("description", "tone", "purpose", "use")


def _index(d: Path, log=print) -> dict:
    """index.json items by file name; a missing or malformed index only loses the extra tags, never the files."""
    f = d / "index.json"
    if not f.exists():
        return {}
    try:
        items = json.loads(f.read_text(encoding="utf-8")).get("items", [])
        return {i["file"]: i for i in items if isinstance(i, dict) and isinstance(i.get("file"), str)}
    except (ValueError, AttributeError) as e:
        log(f"media: {f} is not valid JSON ({e}); using file names only")
        return {}


def library(root: Path | None, log=print) -> list[dict]:
    """The owner's shared library: every top-level media file in movie_reference/ and reactions/ with its tags,
    description, tone and purpose. Entries marked show: false (guide-action references: the guide acts them out,
    they are never shown) and files in subfolders are left out. 'file' is the name the planner uses (the bare file
    name, or folder/name when two folders hold the same name); 'path' is what the renderer loads; 'group' links a
    meme to its look-alikes (same_meme_as), so the same meme is never shown twice in one video."""
    if not root:
        return []
    found = []
    for folder in FOLDERS:
        d = root / folder
        if not d.is_dir():
            continue
        idx = _index(d, log)
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.suffix.lower() not in MEDIA_EXT:
                continue
            it = idx.get(f.name, {})
            if it.get("show") is False:
                continue
            name_words = " ".join(re.findall(r"[A-Za-z]+", f.stem)).lower()
            role = "still" if it.get("type") in ("still", "footage") else "meme"
            e = {"file": f.name, "path": f"{folder}/{f.name}", "role": role,
                 "kind": "video" if f.suffix.lower() in (".mp4", ".mov", ".webm") else
                 ("gif" if f.suffix.lower() == ".gif" else "image"),
                 "tags": sorted(set(it.get("tags") or []) | set(name_words.split())),
                 "note": it.get("note") or it.get("cue") or "", "same_as": list(it.get("same_meme_as") or [])}
            e.update({k: it[k] for k in META if it.get(k)})
            found.append(e)
    names = {}
    for e in found:
        names[e["file"]] = names.get(e["file"], 0) + 1
    for e in found:
        if names[e["file"]] > 1:
            e["file"] = e["path"]
    group = {e["path"]: e["path"] for e in found}            # union-find over same_meme_as links

    def top(x):
        while group.setdefault(x, x) != x:
            x = group[x]
        return x
    for e in found:
        for o in e.pop("same_as"):
            group[top(o)] = top(e["path"])
    for e in found:
        e["group"] = top(e["path"])
    return found


# ------------------------------------------------------------------ is this meme / still about this line?
# word families: a line word and a meme word in the same family mean the same reaction ("crazy" ~ "wait what")
FAMILIES = {
    "disbelief": ("crazy", "wait", "what", "huh", "really", "disbelief", "confus", "question", "puzzl", "weird",
                  "strange", "nonsense", "blink", "awkward", "uncertain", "shrug", "reverse"),
    "surprise": ("surpris", "shock", "wow", "whoa", "realiz", "aha", "sudden", "unexpected", "pikachu"),
    "happy": ("happy", "celebrat", "joy", "laugh", "hype", "smile", "amused", "winner", "victory", "grin"),
    "sad": ("sad", "cry", "suffer", "distress", "pain", "mourn", "death", "dying", "tragedy", "disappoint", "sorrow"),
    "think": ("think", "smart", "clever", "idea", "wonder", "wrestle", "consider", "temple", "argument", "reason"),
    "suspicion": ("susp", "skeptic", "doubt", "side", "lie", "stare", "judg", "evil", "trick", "steal"),
    "nervous": ("nervous", "anxiety", "pressure", "sweat", "fear", "worry", "scared", "stress", "overwhelm", "panic"),
    "money": ("money", "cash", "rich", "wealth", "greed", "dollar", "cent", "broke", "bill", "paid", "price", "poor"),
    "phone": ("phone", "scroll", "notification", "social", "screen", "apps"),
    "help": ("help", "rescue", "care", "compassion", "hospital", "heal", "assist"),
    "disaster": ("earthquake", "disaster", "destruct", "collapse", "storm", "crack", "damage", "flood", "ruin"),
    "hope": ("hope", "light", "relief", "promise", "forever", "future", "heaven"),
    "justice": ("justice", "court", "judgment", "gavel", "scale", "law", "punish", "fair"),
}
EXPRESSION_FAMILY = {"confused": "disbelief", "confused_math": "disbelief", "puzzled": "disbelief",
                     "wait_what": "disbelief", "surprised": "surprise", "shocked": "surprise", "mind_blown": "surprise",
                     "happy": "happy", "crying_laughing": "happy", "sad": "sad", "thinking": "think", "curious": "think",
                     "focused": "think", "side_eye": "suspicion", "awe": "hope", "look_up": "hope"}
VAGUE = {"what", "this", "that", "meme", "your", "have", "just", "about", "they", "them", "when", "then"}


def _hit(w: str, k: str) -> bool:
    """A word belongs to a family by its start ("confused" ~ "confus"); a long run-together file name
    ("doglookingatphoneshocked") also by a family word inside it."""
    return w.startswith(k) or (len(w) >= 14 and len(k) >= 5 and k in w)


def _families(words: set[str]) -> set[str]:
    return {f for f, keys in FAMILIES.items() for w in words for k in keys if _hit(w, k)}


def relevance(item: dict, line: str, expression: str | None = None) -> str | None:
    """Why this library item fits the line (shared word or reaction family with the line or its expression),
    None when nothing connects them. Uses the item's tags, description, purpose, tone and file name."""
    have = _words(" ".join(item.get("tags", []) + [item.get(k, "") for k in META] + [item["file"]])) - VAGUE
    said = _words(line) - VAGUE
    shared = sorted(have & said)
    if shared:
        return "shares " + ", ".join(shared[:3]) + " with the line"
    fam = _families(have) & (_families(said) | {EXPRESSION_FAMILY.get(expression or "", "")})
    if fam:
        return "same reaction as the line (" + ", ".join(sorted(fam)) + ")"
    return None


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
            if (have & WRITING) - want:                # footage whose subject is writing (a chalkboard, a sign...)
                continue                               # shows words the line does not say
            ident = f"{c['source']}:{c['id']}"
            if (avoid and avoid[-1] == ident) or counts.get(ident, 0) >= 2:
                continue
            return {"source": c["source"], "id": c["id"], "title": c.get("title", ""), "page": c.get("page", ""),
                    "why": "shares " + ", ".join(sorted(want & have)) + " with the query"}
    return None


def resolve(plan: dict, lib: list[dict], log, lines: list[str] | None = None) -> tuple[list[list[dict]], list[dict], list[str]]:
    """-> (per-line resolved box items, media.json records, errors for the planner). lines: the script lines
    (only for the media.json reason a library item fits its line)."""
    text = lambda i: lines[i] if lines and i < len(lines) else ""
    files = {m["file"]: m for m in lib}
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
                m = files[f]
                items.append({"kind": "meme", "file": f, "path": m.get("path") or "movie_reference/" + f, "word": b["word"]})
                rec.update({"file": f, "path": m.get("path") or "movie_reference/" + f, "role": m.get("role", "meme"), "source": "owner upload (private)",
                            "why": relevance(m, text(i), L.get("expression")) or "planner's pick"})
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
        p = L.get("pop")
        if isinstance(p, dict) and p.get("file") in files:
            m = files[p["file"]]
            p["path"] = m.get("path") or "movie_reference/" + p["file"]
            records.append({"line": i + 1, "word": p.get("word"), "kind": "pop", "file": p["file"], "path": p["path"],
                            "source": "owner upload (private)",
                            "why": relevance(m, text(i), L.get("expression")) or "planner's pick"})
        elif isinstance(p, dict):
            errors.append(f"line {i + 1}: pop meme {p.get('file')!r} is not in the library")
    if not any(it for line in per_line for it in line):
        errors.append("the video has no clip-box media at all: give stock queries or memes")
    return per_line, records, errors

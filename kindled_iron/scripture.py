"""Scripture cards are checked against the World English Bible (WEB, public domain) bundled in
data/web_bible.json.gz (the 66 books only). A card's text must be the verse, or a contiguous part of
it, word for word (case, punctuation and quotation marks are ignored). A mismatch fails the render,
so no verse is ever misquoted.

    python -m kindled_iron.scripture "Psalm 90:2"                      # print the WEB verse
    python -m kindled_iron.scripture "John 1:3" "All things were made through him."
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "web_bible.json.gz"
REF_RE = re.compile(r"^\s*((?:[123]\s)?[A-Za-z][A-Za-z ]*?)\s+(\d+):(\d+)(?:\s*[-–]\s*(\d+))?\s*$")
ALIASES = {"psalms": "Psalm", "song of songs": "Song of Solomon", "revelations": "Revelation"}


@lru_cache(maxsize=1)
def bible() -> dict:
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        return json.load(f)


def parse_ref(ref: str) -> tuple[str, int, int, int]:
    """'Psalm 90:2' -> ('Psalm', 90, 2, 2). Only the 66 books; format Book Chapter:Verse[-Verse]."""
    m = REF_RE.match(ref)
    if not m:
        raise ValueError(f"reference {ref!r} is not in the form 'Book Chapter:Verse'")
    name = re.sub(r"\s+", " ", m.group(1)).strip()
    books = bible()["books"]
    canon = {b.lower(): b for b in books}
    book = canon.get(name.lower()) or canon.get(ALIASES.get(name.lower(), "").lower())
    if not book:
        raise ValueError(f"{name!r} is not one of the Bible's 66 books")
    c, v1 = int(m.group(2)), int(m.group(3))
    return book, c, v1, int(m.group(4) or v1)


def verse_text(ref: str) -> str:
    book, c, v1, v2 = parse_ref(ref)
    vs = bible()["books"][book]
    parts = []
    for v in range(v1, v2 + 1):
        key = f"{c}:{v}"
        if key not in vs:
            raise ValueError(f"{book} {key} does not exist")
        parts.append(vs[key])
    return " ".join(parts)


def words(text: str) -> list[str]:
    text = text.replace("’", "'").replace("‘", "'").lower()
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)


def check(ref: str, text: str) -> tuple[bool, str]:
    """(ok, WEB verse). ok = the card's words are the verse's words or a contiguous run of them."""
    verse = verse_text(ref)
    cw, vw = words(text), words(verse)
    if not cw:
        return False, verse
    n = len(cw)
    ok = any(vw[i:i + n] == cw for i in range(len(vw) - n + 1))
    return ok, verse


def canonical(ref: str) -> str:
    book, c, v1, v2 = parse_ref(ref)
    return f"{book} {c}:{v1}" + (f"-{v2}" if v2 != v1 else "")


def check_scene(scene: dict, log) -> list[dict]:
    """Every scripture card must match WEB; every [Ref] written in the narration needs a card.
    Raises SystemExit on any mismatch (the render stops)."""
    from kindled_iron.pacing import refs_of

    results, problems = [], []
    cards = [(b, ev["scripture"]) for b, beat in enumerate(scene["beats"]) for ev in beat.get("events", [])
             if isinstance(ev.get("scripture"), dict)]
    for b, card in cards:
        try:
            ok, verse = check(card["ref"], card["text"])
            ref = canonical(card["ref"])
        except ValueError as e:
            ok, verse, ref = False, str(e), card.get("ref")
        results.append({"ref": ref, "text": card["text"], "web": verse, "ok": ok})
        log(f"verse check {ref}: {'OK' if ok else 'MISMATCH'} - card \"{card['text']}\" / WEB \"{verse}\"")
        if not ok:
            problems.append(f"{ref}: card text is not the WEB verse (or a contiguous part of it)")
    written = [canonical(r) for beat in scene["beats"] for r in refs_of(beat["narration"])]
    carded = {r["ref"] for r in results}
    for r in written:
        if r not in carded:
            problems.append(f"[{r}] is in the narration but has no scripture card")
    if problems:
        raise SystemExit("FAIL: scripture check: " + "; ".join(problems))
    return results


if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(f"{canonical(sys.argv[1])} (WEB): {verse_text(sys.argv[1])}")
    else:
        ok, verse = check(sys.argv[1], sys.argv[2])
        print(("OK" if ok else "MISMATCH") + f": {verse}")
        sys.exit(0 if ok else 1)

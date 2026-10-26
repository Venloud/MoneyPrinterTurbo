"""The director's shot plan: what Gemini writes (meaning only, never coordinates) and how it is checked.

A plan has one entry per script line (paragraph). Gemini picks WHAT is on screen and WHEN (a spoken word);
compile.py decides WHERE (zones, slots, guide spots) from the catalog's measured sizes.

    {"freeze": {"line": 3, "word": "free"},                      # one record-scratch freeze, the biggest twist
     "lines": [{"line": 1,
                "expression": "curious",                         # the guide's face for this line (catalog list)
                "gesture": {"do": "point", "word": "graph"},      # point | shrug | present | look | wave | none
                "box": [{"word": "graph", "kind": "stock", "query": "philosophy chalkboard diagram"},
                        {"word": "crazy", "kind": "meme", "file": "Wait-What-meme-kevin-hart.jpg"}],
                "verse": {"ref": "Revelation 21:4", "word": "Revelation", "quoted": false},
                "pop": {"word": "crazy", "file": "suspisious-fry-futurama.webp"},
                "drawings": [{"word": "graph", "type": "triangle",
                              "fields": {"labels": ["ALL POWERFUL", "ALL KNOWING", "ALL GOOD"], "center": "EVIL?"}}]}]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from kindled_iron import scripture

HERE = Path(__file__).resolve().parent
KI = HERE.parent
GOLDEN = ("where-did-god-come-from.json", "love-of-money-v3.json")
GESTURES = {"point", "shrug", "present", "look", "wave", "none"}
REF = re.compile(r"\b((?:[1-3]\s)?[A-Z][a-z]+)\s(\d{1,3}):(\d{1,3})(?:\s?[-–]\s?(\d{1,3}))?")
MAX_POPS = 3
LABEL_MAX = 28                       # characters per label (it wraps onto two lines of ~14)


def key(word: str) -> str:
    """How the renderer matches an anchor word (render.resolve_at)."""
    return re.sub(r"[^a-z0-9]", "", str(word).lower().replace("’", "'"))


def catalog() -> dict:
    return json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))


def director_types(cat: dict) -> dict:
    return {n: o for n, o in cat["objects"].items() if o.get("director")}


def shapes(cat: dict) -> dict:
    """{type: "wide" | "tall" | "both"}: where each drawing can be shown big enough (>= 254 px) with readable labels:
    the drawing band (wide) and/or the guide-lane slot beside him (tall). A type that fits neither is left out."""
    from kindled_iron.director.compile import FILL, LANES, MIN_LABEL_SCALE
    dz = cat["zones"]["draw"]
    lx0, ly0, lx1, ly1 = LANES["left"]
    slots = {"wide": (min(dz["x1"], 775) - dz["x0"], dz["y1"] - dz["y0"]), "tall": (lx1 - lx0, ly1 - ly0)}
    out = {}
    for n, o in director_types(cat).items():
        w, h = o.get("size") or (1, 1)
        ok = [k for k, (sw, sh) in slots.items()
              if (lambda sc: sc >= MIN_LABEL_SCALE and max(w, h) * sc >= 254)(min(sw * FILL / w, sh * FILL / h, 2.4))]
        if ok:
            out[n] = ok[0] if len(ok) == 1 else "both"
    return out


def scripture_refs(text: str) -> list[str]:
    """Bible references written in a line ("Revelation 21:4"), only books the WEB bundle knows."""
    out = []
    for m in REF.finditer(text):
        ref = m.group(0)
        try:
            scripture.verse_text(ref)
            out.append(ref)
        except (ValueError, KeyError):
            continue
    return out


def quoted_spans(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[\"“]([^\"”]{8,})[\"”]", text)]


# ------------------------------------------------------------------ golden examples (few-shot)
def summarize_golden(scene: dict) -> list[dict]:
    """A golden scene, beat by beat, in plan terms: what each line shows (so Gemini sees density and pacing)."""
    out = []
    for b in scene["beats"]:
        evs = b.get("events", [])
        draws = [{"word": e.get("at"), "type": e.get("type"), **{k: e[k] for k in ("text", "labels", "query") if k in e}}
                 for e in evs if e.get("do") == "draw" and e.get("type") not in ("strike", "cross", "sparkle")]
        box = [{"word": e.get("at"), "kind": e["box"], **({"file": e["file"]} if "file" in e else {}),
                **({"clip": e["clip"]} if "clip" in e else {}), **({"ref": e["scripture"]["ref"]} if "scripture" in e else {})}
               for e in evs if "box" in e]
        out.append({"line": re.sub(r"\s*\[[^\]]*\]", "", b.get("narration", "")),
                    "drawings": draws, "box": box,
                    "pop": [{"word": e.get("at"), "file": e.get("file") or e.get("reaction")} for e in evs if "reaction" in e],
                    "guide": [e["do"] for e in evs if e.get("who") == "guide" and e.get("do") not in ("place", "size")]})
    return out


def golden_examples() -> list[dict]:
    out = []
    for name in GOLDEN:
        f = KI / "scenes" / name
        if f.exists():
            s = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": name, "per_line": summarize_golden(s), "full_scene_json": s})
    return out


# ------------------------------------------------------------------ the prompt
RULES = [
    "Return ONLY JSON: {\"freeze\": {\"line\": n, \"word\": w}, \"lines\": [...]} with exactly one entry per script line, in order.",
    "Never change, add or drop narration words. Every 'word' you give must be a word spoken in THAT line (copy it exactly).",
    "Imitate the golden scenes' density and pacing: something new on screen every 2-3 seconds, the drawing appears on the word that names it.",
    "EVERY line gets TWO new real illustrations in 'drawings': first the main diagram of the idea, shown in a WIDE band (650 x 270 px), so pick a wide type (see 'shape' in the catalog: flow, timeline, scales, signpost, crossout, bars, venn...); second a concrete object or person from the line, shown big beside the guide (a tall or square type). Pick types from the catalog only; fill their fields.",
    "Concrete nouns become drawn objects: a graph -> 'bars' or 'triangle' with labeled parts; an earthquake -> 'ground'; a child -> 'person' with kid true; the Bible -> 'openbook'; a disease -> 'germ'.",
    "Abstract ideas become diagrams: cause/effect -> 'flow'; two options -> 'signpost' or 'scales'; overlap -> 'venn'; a rejected idea -> 'crossout'; past/future -> 'timeline'; a question -> 'question'; control -> 'puppet'.",
    "Words appear only as LABELS inside a drawing (labels, title, center, label, text fields), short and in CAPS (max 28 characters).",
    "EVERY line gets clip-box media in 'box' (1-3 items): kind 'stock' with a concrete 2-4 word footage search query that literally shows the line's meaning (real things a camera can film), or kind 'meme' with a file from the meme library whose tags fit the line's meaning.",
    "Stock queries must name filmable things (e.g. 'earthquake rubble street', 'hospital patient bed', 'person praying'), never abstract words alone. No God depicted as a person, no occult imagery.",
    "No identical box media twice in a row; no file or query used more than twice in the video.",
    "A line that quotes scripture word for word, or names a reference like 'Revelation 21:4', gets 'verse': {ref, word (the first word of the quote or the reference), quoted: true|false}. That line's box shows the typed verse card, so give it no other box media.",
    "'pop' (optional): a meme from the library that pops up beside the guide on a reaction word; at most 3 in the video, at least 3 lines apart, never on line 1 (the hook), never on a verse line, never on the word 'God'.",
    "'gesture': point at the drawing being named (word = that drawing's word), or shrug on a question, present/look/wave otherwise. Use a gesture on at least every second line.",
    "'expression' every line, from the catalog's expressions, matching the line's emotion.",
    "'freeze': exactly one, on the line with the biggest twist or surprise, on its key word (a record-scratch freeze-frame).",
    "If fix_errors is not empty, your previous plan failed these checks: fix every one of them.",
]


def prompt(lines: list[str], memes: list[dict], cat: dict, feedback: list[str], words_heard: list[list[str]],
           compact: bool = False) -> str:
    """The planner prompt. compact=True (small-request providers): the golden scenes as their per-line summary
    only, the meme library without notes, and the script lines without the separate word lists."""
    sh = shapes(cat)
    types = {n: {"what": o["doc"], "fields": o["params"], "shape": sh[n]} for n, o in director_types(cat).items() if n in sh}
    return json.dumps({
        "task": "You direct a Kindled Iron short: a hand-drawn whiteboard explainer with a guide character, a clip box at "
                "the top, captions under it, drawings in the middle, the guide walking at the bottom. Write the shot plan.",
        "rules": RULES,
        "script_lines": [{"line": i + 1, "text": t} if compact else {"line": i + 1, "text": t, "spoken_words": w}
                         for i, (t, w) in enumerate(zip(lines, words_heard))],
        "drawing_catalog": types,
        "expressions": cat["expressions"],
        "meme_library": [{"file": m["file"], "tags": m.get("tags", [])[:6]} for m in memes] if compact else memes,
        "golden_examples": [{"name": g["name"], "per_line": g["per_line"]} for g in golden_examples()][:1 if compact else 2]
                           if compact else golden_examples(),
        "fix_errors": feedback,
        "output_example": {"freeze": {"line": 2, "word": "word"}, "lines": [{
            "line": 1, "expression": "curious", "gesture": {"do": "point", "word": "graph"},
            "box": [{"word": "graph", "kind": "stock", "query": "chalkboard diagram classroom"}],
            "drawings": [{"word": "graph", "type": "flow", "fields": {"labels": ["ALL POWERFUL", "ALL GOOD", "EVIL?"]}},
                         {"word": "evil", "type": "question", "fields": {"label": "WHY?"}}]}]},
    }, ensure_ascii=False)


# ------------------------------------------------------------------ checks
OBJ_FIELDS = ("gesture", "verse", "pop")      # one object or null
LIST_FIELDS = ("drawings", "box")             # a list of objects


def shape_errors(plan) -> list[str]:
    """The JSON shape (objects, lists) before any rule is checked. A one-item list where one object belongs (a
    common model habit) is unwrapped in place; anything else malformed becomes an error for the next try."""
    if not isinstance(plan, dict) or not isinstance(plan.get("lines"), list):
        return ["the plan must be an object with a 'lines' list"]
    errs = []
    if isinstance(plan.get("freeze"), list) and len(plan["freeze"]) == 1:
        plan["freeze"] = plan["freeze"][0]
    if plan.get("freeze") is not None and not isinstance(plan["freeze"], dict):
        errs.append("'freeze' must be one object {line, word}")
    for i, L in enumerate(plan["lines"]):
        n = i + 1
        if not isinstance(L, dict):
            errs.append(f"line {n}: each entry of 'lines' must be an object")
            continue
        for f in OBJ_FIELDS:
            v = L.get(f)
            if isinstance(v, list) and len(v) <= 1:
                L[f] = v[0] if v else None
            elif v is not None and not isinstance(v, dict):
                errs.append(f"line {n}: '{f}' must be one object or null, not {type(v).__name__}")
        for f in LIST_FIELDS:
            v = L.get(f)
            if isinstance(v, dict):
                L[f] = [v]
            elif v is not None and not (isinstance(v, list) and all(isinstance(x, dict) for x in v)):
                errs.append(f"line {n}: '{f}' must be a list of objects")
        for d in L.get("drawings") or []:
            if isinstance(d, dict) and d.get("fields") is not None and not isinstance(d["fields"], dict):
                errs.append(f"line {n}: a drawing's 'fields' must be an object")
        if L.get("expression") is not None and not isinstance(L["expression"], str):
            errs.append(f"line {n}: 'expression' must be a string")
    return errs


def repair(plan: dict, lines: list[str], line_keys: list[list[str]], cat: dict) -> list[str]:
    """Fix in code what needs no new idea (no Gemini call is spent on it); returns notes of what was changed.
    Two drawings in the wrong order are swapped; an unknown expression becomes the closest listed one (else
    neutral); an unknown gesture becomes none; pop-ups that break a pop rule are dropped."""
    import difflib
    notes: list[str] = []
    if shape_errors(plan):
        return notes
    sh, exprs = shapes(cat), list(cat["expressions"])
    pops = []
    for i, L in enumerate(plan["lines"]):
        n = i + 1
        dr = L.get("drawings") or []
        if len(dr) == 2 and all(isinstance(d, dict) for d in dr):
            a, b = (sh.get(d.get("type")) for d in dr)
            if a == "tall" and b in ("wide", "both") or a in ("both",) and b == "wide":
                L["drawings"] = [dr[1], dr[0]]
                notes.append(f"line {n}: drawings swapped (wide first)")
        e = L.get("expression")
        if e not in exprs:
            close = difflib.get_close_matches(str(e or ""), exprs, n=1, cutoff=0.6)
            L["expression"] = close[0] if close else "neutral"
            notes.append(f"line {n}: expression {e!r} -> {L['expression']!r}")
        g = L.get("gesture")
        if isinstance(g, dict) and g.get("do") not in GESTURES:
            notes.append(f"line {n}: gesture {g.get('do')!r} -> none")
            L["gesture"] = {"do": "none"}
        p = L.get("pop")
        if isinstance(p, dict):
            why = ("the first line is the hook" if i == 0 else "verse line" if L.get("verse") or scripture_refs(lines[i])
                   else "on the word God" if key(p.get("word", "")) == "god"
                   else "too close to the previous pop-up" if pops and i - pops[-1] < 2
                   else "more than %d pop-ups" % MAX_POPS if len(pops) >= MAX_POPS else "")
            if why:
                L["pop"] = None
                notes.append(f"line {n}: pop-up dropped ({why})")
            else:
                pops.append(i)
    return notes


def validate(plan: dict, lines: list[str], line_keys: list[list[str]], memes: list[dict], cat: dict) -> list[str]:
    """Every error is phrased so Gemini can fix it in the next round. Never raises on a malformed plan."""
    errs = shape_errors(plan)
    if errs:
        return errs
    try:
        return _rules(plan, lines, line_keys, memes, cat)
    except (AttributeError, TypeError, KeyError, ValueError) as e:     # a shape the checks above did not foresee
        return [f"the plan's JSON has an unexpected shape ({type(e).__name__}: {e}); follow output_example exactly"]


def _rules(plan: dict, lines: list[str], line_keys: list[list[str]], memes: list[dict], cat: dict) -> list[str]:
    errs: list[str] = []
    P = plan["lines"]
    if len(P) != len(lines):
        return [f"the plan has {len(P)} lines but the script has {len(lines)}: give exactly one entry per script line"]
    types = director_types(cat)
    files = {m["file"] for m in memes}
    exprs = set(cat["expressions"])
    pops = 0

    def word_ok(i: int, w, what: str) -> None:
        if not w or key(w) not in line_keys[i]:
            errs.append(f"line {i + 1}: {what} word {w!r} is not spoken in this line")

    for i, L in enumerate(P):
        n = i + 1
        if L.get("expression") not in exprs:
            errs.append(f"line {n}: expression {L.get('expression')!r} is not one of {sorted(exprs)}")
        g = L.get("gesture") or {"do": "none"}
        if g.get("do") not in GESTURES:
            errs.append(f"line {n}: gesture {g.get('do')!r} is not one of {sorted(GESTURES)}")
        elif g.get("do") != "none":
            word_ok(i, g.get("word"), "gesture")
        dr = L.get("drawings") or []
        if not dr:
            errs.append(f"line {n}: no drawing; every line needs at least one new illustration")
        if len(dr) > 2:
            errs.append(f"line {n}: {len(dr)} drawings; at most 2 per line")
        sh = shapes(cat)
        for j, d in enumerate(dr[:2]):
            t = d.get("type")
            if t in types and t not in sh:
                errs.append(f"line {n}: {t} cannot be shown readably in any slot; pick another type")
            elif t in sh and len(dr) == 2 and sh[t] not in ("both", ("wide", "tall")[j]):
                errs.append(f"line {n}: drawing {j + 1} ({t}) is {sh[t]}; the first drawing must be wide (or both), "
                            "the second tall (or both)")
        for d in dr:
            t = d.get("type")
            if t not in types:
                errs.append(f"line {n}: drawing type {t!r} is not in the catalog")
                continue
            word_ok(i, d.get("word"), f"drawing {t}")
            fields = d.get("fields") or {}
            bad = set(fields) - set(types[t]["params"])
            if bad:
                errs.append(f"line {n}: drawing {t} has unknown fields {sorted(bad)}; it takes {types[t]['params']}")
            for k, v in fields.items():
                for s in (v if isinstance(v, list) else [v]):
                    if isinstance(s, str) and len(s) > LABEL_MAX:
                        errs.append(f"line {n}: label {s!r} is longer than {LABEL_MAX} characters")
            if "labels" in types[t]["params"] and not fields.get("labels"):
                errs.append(f"line {n}: drawing {t} needs 'labels'")
        refs = scripture_refs(lines[i])
        v = L.get("verse")
        if refs and not v:
            errs.append(f"line {n}: names {refs[0]}: give it a 'verse' (the typed verse card)")
        if v:
            try:
                scripture.verse_text(v.get("ref", ""))
            except (ValueError, KeyError):
                errs.append(f"line {n}: verse ref {v.get('ref')!r} is not a World English Bible reference")
            word_ok(i, v.get("word"), "verse")
            if v.get("quoted"):
                q = next((q for q in quoted_spans(lines[i])), "")
                ok, _ = scripture.check(v.get("ref", ""), q) if q else (False, "")
                if not ok:
                    errs.append(f"line {n}: verse marked quoted but the line has no quote that matches {v.get('ref')} in the WEB; set quoted false")
        box = L.get("box") or []
        if not box and not v:
            errs.append(f"line {n}: no clip-box media; give 1-3 'box' items (stock query or meme file)")
        for b in box:
            word_ok(i, b.get("word"), "box")
            if b.get("kind") == "meme" and b.get("file") not in files:
                errs.append(f"line {n}: meme file {b.get('file')!r} is not in the meme library")
            elif b.get("kind") == "stock" and len(str(b.get("query", "")).split()) < 2:
                errs.append(f"line {n}: stock query {b.get('query')!r} needs 2-4 concrete words")
            elif b.get("kind") not in ("stock", "meme"):
                errs.append(f"line {n}: box kind {b.get('kind')!r} must be 'stock' or 'meme'")
        p = L.get("pop")
        if p:
            pops += 1
            word_ok(i, p.get("word"), "pop")
            if p.get("file") not in files:
                errs.append(f"line {n}: pop file {p.get('file')!r} is not in the meme library")
            if v:
                errs.append(f"line {n}: no pop on a verse line")
            if key(p.get("word", "")) == "god":
                errs.append(f"line {n}: never pop on the word 'God'")
    if pops > MAX_POPS:
        errs.append(f"{pops} pops: at most {MAX_POPS} in the video")
    last = [i for i, L in enumerate(P) if L.get("pop")]
    for a, b in zip(last, last[1:]):
        if b - a < 2:
            errs.append(f"pops on lines {a + 1} and {b + 1} are too close: keep them at least 2 lines apart")
    fz = plan.get("freeze")
    if not fz or not isinstance(fz.get("line"), int) or not 1 <= fz["line"] <= len(lines):
        errs.append("give exactly one 'freeze': {line, word} on the biggest twist")
    else:
        word_ok(fz["line"] - 1, fz.get("word"), "freeze")
        if P[fz["line"] - 1].get("verse"):
            errs.append("no freeze on a verse line")
    return errs

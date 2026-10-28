"""The director's shot plan: what Gemini writes (meaning only, never coordinates) and how it is checked.

A plan has one entry per script line (paragraph). Gemini picks WHAT is on screen and WHEN (a spoken word);
compile.py decides WHERE (zones, slots, guide spots) from the catalog's measured sizes.

    {"freeze": {"line": 3, "word": "free"},                      # one record-scratch freeze, the biggest twist
     "lines": [{"line": 1,
                "expression": "curious",                         # the guide's face for this line (catalog list)
                "gesture": {"do": "point", "word": "graph"},      # point | shrug | present | look | wave | none
                "box": [{"word": "storm", "kind": "stock", "query": "storm clouds lightning"},
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
from kindled_iron.director import actions

GESTURES = set(actions.ACTED)

HERE = Path(__file__).resolve().parent
KI = HERE.parent
GOLDEN = ("where-did-god-come-from.json", "love-of-money-v3.json")
REF = re.compile(r"\b((?:[1-3]\s)?[A-Z][a-z]+)\s(\d{1,3}):(\d{1,3})(?:\s?[-–]\s?(\d{1,3}))?")
MAX_POPS = 3
MAX_MEMES = 4           # memes in one video (clip box + pop-ups): a meme is for a laugh or a feeling, never filler
LABEL_MAX = 28
LIB_COMPACT = 60
STRIP = 2.6                          # a built-in drawing this many times wider than tall is a thin strip: not used
# thin built-in diagrams -> the library illustration that says the same (labels moved into its slots)
STRIP_SWAP = {"flow": ("flow_arrows", lambda f: dict(zip(("a", "b", "c"), f.get("labels") or []))),
              "scales": ("scales_big", lambda f: dict(zip(("left", "right"), f.get("labels") or []))),
              "crossout": ("x_mark", lambda f: {"label": f["text"]} if f.get("text") else {}),
              "timeline": ("line_graph", lambda f: {"label": " / ".join((f.get("labels") or [])[:2])[:28]} if f.get("labels") else {}),
              "cloud": ("rain_cloud", lambda f: {}), "hill": ("mountain", lambda f: {}), "fish": ("fishing", lambda f: {}),
              "birds": ("dove", lambda f: {})}                     # library doodles listed in the compact prompt (the best matches to the script)                       # characters per label (it wraps onto two lines of ~14)


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
    cz = cat["zones"]["caption"]               # tall: the full-height side slot, from under the (middle) caption
    slots = {"wide": (min(dz["x1"], 775) - dz["x0"], dz["y1"] - dz["y0"]), "tall": (lx1 - lx0, ly1 - (cz["y"] + cz["h"] + 15))}
    out = {}
    for n, o in director_types(cat).items():
        w, h = o.get("size") or (1, 1)
        if w >= STRIP * h and not o.get("doodle"):     # a thin strip leaves the drawing area empty
            continue
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
    "The house style is drawing-led: hand-drawn illustrations of what is said, the guide acting it out, captions. 'drawings' (0-3 per line): give a line the illustrations that SHOW its ideas (the thing, the comparison, the turn of the argument), each on the word that names it; a line with one strong idea gets one drawing, a list or a comparison may get 2-3. Never add a decorative drawing to fill space: the code lays out whatever you give (one big drawing, two side by side or stacked, one beside the guide). A line may have no drawing only when its box media (or the verse card, or a diagram already decided) is its visual. Pick types from the catalog only; fill their fields.",
    "Prefer the drawing library: the catalog entries with 'tags' are finished illustrations. For each drawing pick the one whose tags best match what the line MEANS, not a word it uses: an earthquake -> earthquake, a child -> child, the Bible -> bible, money -> money, a choice -> road_fork; 'this graph' about an argument is the argument (its claims, its question), never a bar chart (bar_chart / line_graph only for numbers that go up or down). When a line names several parallel things (three claims, a list), show each of them or none. Put the idea it shows in 'concept' (1-3 words, e.g. 'free will').",
    "Compose from the built-in diagrams (entries without tags: flow, timeline, scales, venn, crossout...) only when no library illustration fits the idea; then also set 'miss': the concept you could not find in the library (it is logged so the library can grow).",
    "Abstract ideas become diagrams: cause/effect -> 'flow'; two options -> 'signpost' or 'scales'; overlap -> 'venn'; a rejected idea -> 'crossout'; past/future -> 'timeline'; a question -> 'question'; control -> 'puppet'.",
    "Words appear only as LABELS inside a drawing (labels, title, center, label, text fields), short and in CAPS (max 28 characters).",
    "Read the WHOLE script first: know its argument, its turns and its feeling before picking anything for a line.",
    "'box' (0-3 items): kind 'stock' with a concrete 2-4 word footage search query that literally shows what the line says (real things a camera can film: the person, event, object or action named), or kind 'meme' with a 'file' from media_library. Give box media only when real footage or a library picture truly shows the line; otherwise leave 'box' empty: the box then disappears and the drawings take its place (no filler footage, no frame without media). A box item shows only during its own line. Never stock footage of writing (chalkboards, signs, screens, documents, charts on monitors): it shows words the narration does not say.",
    "media_library has two roles: 'still' = a real-looking picture of a subject (use it like stock when it shows what the line is about); 'meme' = a reaction. Use a meme ONLY where it genuinely adds humor or emotional emphasis to what is said (its description/purpose must fit the line); at most 4 memes in the whole video, and each meme (with its look-alikes) once. Most lines need no meme.",
    "Stock queries must name filmable things (e.g. 'earthquake rubble street', 'hospital patient bed', 'person praying'), never abstract words alone. No God depicted as a person, no occult imagery.",
    "No identical box media twice in a row; no file or query used more than twice in the video.",
    "A line that quotes scripture word for word, or names a reference like 'Revelation 21:4', gets 'verse': {ref, word (the first word of the quote or the reference), quoted: true|false}. That line's box shows the typed verse card, so give it no other box media.",
    "'pop' (optional): a meme from the library that pops up beside the guide on a reaction word; at most 3 in the video, at least 2 lines apart, never in the hook (the first sentence), never on a verse line, never on the word 'God', never a joke on a grave line (suffering, death, children, grief): a meme must fit the line's tone, not just a word.",
    "'gesture': the guide ACTS the line (word = the word the action lands on; for point, the drawing's word). Pick from guide_actions: point at the drawing being named, shrug on a question, think, realize on a twist, confused, celebrate good news, choose_path between two options, frustrated_at_screen... Use an action on at least every second line; a line may be the guide's moment alone (a strong action, no meme).",
    "'expression' every line, from the catalog's expressions, matching the line's emotion.",
    "'freeze': exactly one, on the line with the biggest twist or surprise, on its key word (a record-scratch freeze-frame).",
    "already_decided lists what the director has already chosen from the narration (e.g. a whole diagram on screen for some lines): respect it.",
    "If fix_errors is not empty, your previous plan failed these checks: fix every one of them.",
]


def _lib_entry(m: dict, compact: bool) -> dict:
    e = {"file": m["file"], "role": m.get("role", "meme"), "tags": m.get("tags", [])[:6]}
    if not compact:
        e.update({k: m[k] for k in ("description", "tone", "purpose", "note") if m.get(k)})
    elif m.get("description"):
        e["what"] = m["description"][:70]
    return e


def prompt(lines: list[str], memes: list[dict], cat: dict, feedback: list[str], words_heard: list[list[str]],
           compact: bool = False, context: list[str] | None = None) -> str:
    """The planner prompt. compact=True (small-request providers): the golden scenes as their per-line summary
    only, the meme library without notes, and the script lines without the separate word lists."""
    sh = shapes(cat)
    def entry(n, o):
        e = {"shape": sh[n], "fields": o["params"]}
        if o.get("doodle"):                       # library illustrations: picked by tag
            e["tags"] = o["tags"][:6] if compact else o["tags"]
            if not compact:
                e["what"] = o["doc"]
        else:
            e["what"] = o["doc"]
        return e
    types = {n: entry(n, o) for n, o in director_types(cat).items() if n in sh}
    if compact:                       # small requests: the diagrams in full, the library as one line per doodle,
        said = {key(w) for l in lines for w in l.split()}           # only the ones nearest to the script's words
        lib = [(n, o) for n, o in director_types(cat).items() if o.get("doodle") and n in sh]
        rel = lambda n, o: sum(1 for t in o["tags"] + [n.replace("_", " ")] for w in t.split() if key(w) in said)
        lib = sorted(lib, key=lambda x: -rel(*x))[:LIB_COMPACT]
        types = {n: e for n, e in types.items() if "tags" not in e}
        types["library"] = [f"{n}: {', '.join(o['tags'][:4])} [{', '.join(o['params'])}] {sh[n]}" for n, o in lib]
    return json.dumps({
        "task": "You direct a Kindled Iron short: a hand-drawn whiteboard explainer with a guide character, a clip box at "
                "the top, captions under it, drawings in the middle, the guide walking at the bottom. Write the shot plan.",
        "rules": RULES,
        "script_lines": [{"line": i + 1, "text": t} if compact else {"line": i + 1, "text": t, "spoken_words": w}
                         for i, (t, w) in enumerate(zip(lines, words_heard))],
        "drawing_catalog": types,
        "expressions": cat["expressions"],
        "media_library": [_lib_entry(m, compact) for m in memes],
        "guide_actions": actions.for_prompt(),
        "golden_examples": [{"name": g["name"], "per_line": g["per_line"]} for g in golden_examples()][:1 if compact else 2]
                           if compact else golden_examples(),
        "fix_errors": feedback,
        "already_decided": context or [],
        "output_example": {"freeze": {"line": 2, "word": "word"}, "lines": [{
            "line": 1, "expression": "curious", "gesture": {"do": "point", "word": "graph"},
            "box": [{"word": "storm", "kind": "stock", "query": "storm clouds lightning"}],
            "drawings": [{"word": "graph", "type": "triangle_diagram", "concept": "three claims",
                          "fields": {"top": "ALL POWERFUL", "left": "ALL GOOD", "right": "ALL KNOWING", "center": "EVIL?"}},
                         {"word": "evil", "type": "question_big", "concept": "why evil", "fields": {"label": "WHY?"}}]}]},
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


def misses(plan: dict, cat: dict) -> list[dict]:
    """Drawings composed from built-in diagrams instead of a library doodle: the concept the planner wanted (its
    'miss', else its 'concept' when no doodle tag mentions it). Logged per video so the library can grow."""
    types = director_types(cat)
    tags = {w for o in types.values() if o.get("doodle") for t in o["tags"] for w in [t.lower()]}
    out = []
    for i, L in enumerate(plan.get("lines") or []):
        for d in L.get("drawings") or []:
            if not isinstance(d, dict) or types.get(d.get("type"), {}).get("doodle"):
                continue
            c = str(d.get("miss") or d.get("concept") or "").strip().lower()
            if d.get("miss") or (c and c not in tags):
                out.append({"line": i + 1, "concept": c or d.get("word"), "used": d.get("type")})
    return out


def repair(plan: dict, lines: list[str], line_keys: list[list[str]], cat: dict, lib: list[dict] | None = None) -> list[str]:
    """Fix in code what needs no new idea (no Gemini call is spent on it); returns notes of what was changed.
    Two drawings in the wrong order are swapped; an unknown expression becomes the closest listed one (else
    neutral); a guide action the rig cannot perform is reported (plan['unsupported_actions']) and becomes a point;
    an unknown gesture becomes none; pop-ups that break a pop rule are dropped. With the library (lib): a meme or
    still that has nothing to do with its line, a meme already shown (or its look-alike), and memes beyond
    MAX_MEMES are dropped."""
    import difflib
    notes: list[str] = []
    if shape_errors(plan):
        return notes
    sh, exprs = shapes(cat), list(cat["expressions"])
    if len(plan["lines"]) == len(lines):
        notes += _repair_box_and_verse(plan, lines, line_keys)
        notes += _repair_unknown_drawings(plan, lines, cat, lib)
    pops = []
    for i, L in enumerate(plan["lines"]):
        n = i + 1
        dr = L.get("drawings") or []
        for d in dr:                                   # thin strips -> the library illustration of the same idea
            if isinstance(d, dict) and d.get("type") in STRIP_SWAP and d["type"] not in sh:
                new, conv = STRIP_SWAP[d["type"]]
                notes.append(f"line {n}: {d['type']} (a thin strip) -> {new}")
                d["type"], d["fields"] = new, conv(d.get("fields") or {})
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
        if isinstance(g, dict) and g.get("do") in actions.UNSUPPORTED:
            a = actions.ACTIONS[g["do"]]
            plan.setdefault("unsupported_actions", []).append(
                {"line": n, "action": g["do"], "status": "unsupported", "performed": False, "why": "the rig cannot " + a["cannot"],
                 "instead": "point"})
            notes.append(f"line {n}: guide action {g['do']!r} is not supported by the rig (reported) -> point")
            L["gesture"] = {"do": "point", "word": g.get("word")}
        elif isinstance(g, dict) and g.get("do") not in GESTURES:
            notes.append(f"line {n}: gesture {g.get('do')!r} -> none")
            L["gesture"] = {"do": "none"}
        p = L.get("pop")
        if isinstance(p, dict):
            why = ("the hook (the first sentence)" if i == 0 and in_hook(lines[0], p.get("word")) else "verse line" if L.get("verse") or scripture_refs(lines[i])
                   else "on the word God" if key(p.get("word", "")) == "god"
                   else "too close to the previous pop-up" if pops and i - pops[-1] < 2
                   else "more than %d pop-ups" % MAX_POPS if len(pops) >= MAX_POPS else "")
            if why:
                L["pop"] = None
                notes.append(f"line {n}: pop-up dropped ({why})")
            else:
                pops.append(i)
    if lib is not None:
        notes += _repair_media(plan, lines, lib)
        if len(plan["lines"]) == len(lines):
            notes += propose_media(plan, lines, lib)
    return notes


def in_hook(line: str, word) -> bool:
    """Is this word (first occurrence) in the line's first sentence: the hook, which stays clean?"""
    first = re.split(r"(?<=[.!?])\s+", line.strip(), maxsplit=1)[0]
    return key(str(word or "")) in [key(w) for w in first.split()]


# words with which the narrator voices the viewer's own reaction ("Sounds crazy, right?", "Think about it.",
# "Wait, what?"): said as a short aside, that is the beat a reaction meme lands on. A cue inside a long sentence is
# part of the argument, not a reaction, and gets no meme.
REACTION_CUES = {"crazy": "nonsense", "insane": "nonsense", "wild": "nonsense", "wait": "nonsense", "huh": "nonsense",
                 "weird": "nonsense", "strange": "nonsense", "seriously": "nonsense", "ridiculous": "nonsense",
                 "wow": "surprise", "whoa": "surprise", "surprise": "surprise", "surprising": "surprise",
                 "shocking": "surprise", "think": "think", "imagine": "think", "wonder": "think", "really": "doubt",
                 "suspicious": "doubt", "doubt": "doubt", "funny": "happy", "hilarious": "happy"}
# what a meme must show for that aside (its tags / description / purpose words), and its family in media.FAMILIES
CUE_SENSE = {"nonsense": (("disbelief", "believ", "sense", "confus", "crazy", "weird", "strange", "blink", "puzzl",
                           "question", "what"), "disbelief"),
             "surprise": (("surpris", "shock", "wow", "whoa", "realiz", "unexpected"), "surprise"),
             "think": (("think", "smart", "clever", "idea", "wonder", "temple", "consider"), "think"),
             "doubt": (("skeptic", "doubt", "susp", "squint", "stare", "side"), "suspicion"),
             "happy": (("laugh", "amused", "funny", "hilarious", "joy"), "happy")}
ASIDE_WORDS = 6        # a sentence this short is an aside to the viewer, not a step of the argument


def reaction_cue(line: str) -> tuple[str, str] | None:
    """(spoken word, reaction sense) of the line's reaction aside, None when it has none."""
    for sent in re.split(r"(?<=[.!?])\s+", line.strip()):
        toks = sent.split()
        if len(toks) > ASIDE_WORDS:
            continue
        for t in toks:
            fam = REACTION_CUES.get(key(t))
            if fam:
                return t, fam
    return None


def propose_media(plan: dict, lines: list[str], lib: list[dict]) -> list[str]:
    """The director's own media judgement, in code, for lines the planner left without media: a reaction meme on a
    reaction aside (the meme's own tags/description carry that reaction, nothing else it shows is off the line), and
    a library still where the line names the subject a still shows. Every rule the planner's picks obey applies
    (hook, verse lines, the word God, grave lines, pop spacing, MAX_POPS, MAX_MEMES, one use per look-alike group);
    no line gets media just to have some. Returns notes of what was added and why."""
    from kindled_iron.director.media import best_still, _item_words, _families, _words as _mwords
    by_file = {m["file"]: m for m in lib}
    P = plan["lines"]
    files = [b.get("file") for L in P for b in L.get("box") or []] + \
            [L["pop"].get("file") for L in P if isinstance(L.get("pop"), dict)]
    groups = {by_file[f].get("group", f) for f in files if f in by_file}
    memes = sum(1 for f in files if f in by_file and by_file[f].get("role", "meme") == "meme")
    pops = [i for i, L in enumerate(P) if isinstance(L.get("pop"), dict)]
    notes = []
    for i, L in enumerate(P):
        if L.get("verse") or scripture_refs(lines[i]):
            continue
        cue = reaction_cue(lines[i])
        if (cue and not L.get("pop") and not grave(lines[i]) and key(cue[0]) != "god" and len(pops) < MAX_POPS
                and memes < MAX_MEMES and all(abs(i - j) >= 2 for j in pops) and not (i == 0 and in_hook(lines[0], cue[0]))):
            word, sense = cue
            sense_keys, fam = CUE_SENSE[sense]
            said = _families(set(re.findall(r"[a-z]+", lines[i].lower())))
            best = None
            for m in lib:
                if m.get("role", "meme") != "meme" or m.get("group", m["file"]) in groups:
                    continue
                have = _item_words(m)
                hits = sum(1 for w in have for k in sense_keys if w.startswith(k))
                off = _families(have) - said - {fam}         # it also shows money, a phone...: not this line's reaction
                if hits and not off and (best is None or hits > best[0] or hits == best[0] and m["file"] < best[1]["file"]):
                    best = (hits, m)
            if best:
                m = best[1]
                L["pop"] = {"word": word, "file": m["file"]}
                groups.add(m.get("group", m["file"])); memes += 1; pops = sorted(pops + [i])
                notes.append(f"line {i + 1}: pop-up {m['file']!r} added on {word!r} (a {sense} aside; the meme shows {sense})")
        if not (L.get("box") or []):
            got = best_still(lib, lines[i], used=groups, literal=True)
            if got:
                m, why, shown = got
                w = next((t for t in lines[i].split() if _mwords(t) & set(shown)), None)    # the first word it shows
                if w:
                    L["box"] = [{"word": w, "kind": "meme", "file": m["file"]}]
                    groups.add(m.get("group", m["file"]))
                    notes.append(f"line {i + 1}: library still {m['file']!r} added on {w!r} ({why})")
    return notes


def _tokens(*parts) -> set[str]:
    out = set()
    for part in parts:
        for w in re.findall(r"[a-z]+", str(part).lower().replace("_", " ")):
            if len(w) >= 3:
                out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def _anchor_word(line: str, keys: list[str], hint: set[str]) -> str | None:
    """The spoken word of the line a box item belongs on: the first one that shares a word with the item's
    query / file / tags, else the line's first spoken word."""
    spoken = [w for w in line.split() if key(w) in keys]
    for w in spoken:
        if _tokens(w) & hint:
            return w
    return spoken[0] if spoken else None


def _repair_box_and_verse(plan: dict, lines: list[str], line_keys: list[list[str]]) -> list[str]:
    """Box items and verse cards fixed in code:
      - an empty box item (no query, no file) is dropped: a line may have no box at all;
      - a box item 'verse' / with a 'ref' becomes the line's verse card;
      - a box item with no kind gets one from what it has (query -> stock, file -> meme);
      - a real box item whose word is missing or not spoken in its line is anchored on a spoken word;
      - a line that names a reference (Revelation 21:4) but has no verse card gets one; a verse marked quoted
        whose line has no quote that matches the WEB text is set to quoted false (the card then types the WEB
        text itself). The scripture checks in validate stay as they are."""
    notes = []
    for i, L in enumerate(plan["lines"]):
        n, text, keys = i + 1, lines[i], line_keys[i]
        box = L.get("box")
        if box is None:
            L["box"] = box = []
        keep = []
        for b in box:
            if b.get("kind") == "verse" or (b.get("ref") and not b.get("query") and not b.get("file")):
                if not L.get("verse") and b.get("ref"):
                    L["verse"] = {"ref": b["ref"], "word": b.get("word"), "quoted": bool(b.get("quoted"))}
                    notes.append(f"line {n}: verse moved from the box to the verse card ({b['ref']})")
                continue
            if not b.get("query") and not b.get("file"):
                notes.append(f"line {n}: an empty box item dropped")
                continue
            if b.get("kind") not in ("stock", "meme"):
                b["kind"] = "stock" if b.get("query") else "meme"
            if not b.get("word") or key(b["word"]) not in keys:
                w = _anchor_word(text, keys, _tokens(b.get("query", ""), b.get("file", "")))
                if w:
                    notes.append(f"line {n}: box word {b.get('word')!r} -> {w!r} (a word spoken in the line)")
                    b["word"] = w
            keep.append(b)
        L["box"] = keep
        refs = scripture_refs(text)
        if refs and not L.get("verse"):
            L["verse"] = {"ref": refs[0], "word": None, "quoted": False}
            notes.append(f"line {n}: names {refs[0]}: verse card added")
        v = L.get("verse")
        if isinstance(v, dict) and v.get("ref"):
            if not v.get("word") or key(v["word"]) not in keys:
                book = str(v["ref"]).split()[-2] if len(str(v["ref"]).split()) > 2 else str(v["ref"]).split()[0]
                w = next((w for w in text.split() if key(w) == key(book)), None) or \
                    next((w for w in text.split() if key(w) in keys), None)
                if w:
                    v["word"] = w
            if v.get("quoted"):
                ok = any(scripture.check(v["ref"], q)[0] for q in quoted_spans(text)) if quoted_spans(text) else False
                if not ok:
                    v["quoted"] = False
                    notes.append(f"line {n}: verse {v['ref']} is named, not quoted word for word: quoted -> false")
            if L["box"]:
                notes.append(f"line {n}: box media dropped (the verse card fills the box)")
                L["box"] = []
    return notes


def _repair_unknown_drawings(plan: dict, lines: list[str], cat: dict, lib: list[dict] | None) -> list[str]:
    """A drawing type that is not in the catalog becomes the verified catalog drawing closest to it (its name,
    concept and labels against the catalog's names, tags and descriptions; never one already on that line), its
    fields carried over where the new type takes them. With no close match it is dropped when the line keeps
    another drawing; otherwise validate rejects it."""
    types, sh, notes = director_types(cat), shapes(cat), []
    media_names = {Path(m["file"]).stem.lower() for m in (lib or [])}
    for i, L in enumerate(plan["lines"]):
        dr = L.get("drawings") or []
        used = {d.get("type") for d in dr if isinstance(d, dict)}
        for d in list(dr):
            t = d.get("type") if isinstance(d, dict) else None
            if not t or t in types:
                continue
            fields = d.get("fields") if isinstance(d.get("fields"), dict) else {}
            labels = [v for v in fields.values() if isinstance(v, str)]
            want_name, want = _tokens(t), _tokens(t, d.get("concept", ""), *labels)
            best, score = None, 0
            for n, o in types.items():
                if n in used or n not in sh:
                    continue
                have = _tokens(n, *(o.get("tags") or []), o.get("doc", ""))
                sc = 3 * len(_tokens(n) & want_name) + len(have & want)
                if sc > score:
                    best, score = n, sc
            why = " (a media file name, not a drawing)" if t.lower() in media_names else ""
            if best and score >= 2:
                params = types[best]["params"]
                new_f = {k: v for k, v in fields.items() if k in params}
                if "label" in params and "label" not in new_f and labels:
                    new_f["label"] = labels[0]
                if "labels" in params and "labels" not in new_f and labels:
                    new_f["labels"] = labels[:3]
                d["type"], d["fields"] = best, new_f
                used.add(best)
                notes.append(f"line {i + 1}: drawing {t!r} is not in the catalog{why} -> {best}")
            elif len(dr) > 1:
                dr.remove(d)
                notes.append(f"line {i + 1}: drawing {t!r} is not in the catalog{why} and nothing close is: dropped")
    return notes




GRAVE = ("suffer", "death", "dead", "dying", "die", "died", "kill", "murder", "abuse", "grief", "griev", "mourn", "cancer",
         "tragedy", "funeral", "innocent", "children", "child", "pain", "cry", "crying", "tears", "disease")


def grave(line: str) -> bool:
    """A line about suffering, death or harm to people: a joke meme there reads as mockery, whatever its words."""
    return any(w.startswith(g) for w in re.findall(r"[a-z]+", line.lower()) for g in GRAVE)


def _repair_media(plan: dict, lines: list[str], lib: list[dict]) -> list[str]:
    from kindled_iron.director.media import relevance, _words as _mwords
    by_file = {m["file"]: m for m in lib}
    notes, groups, memes = [], set(), 0

    def keep(i: int, f, where: str, expression) -> bool:
        nonlocal memes
        m = by_file.get(f)
        if not m:
            return True                                # validate reports unknown files
        why = ("it has nothing to do with the line" if not relevance(m, lines[i], expression)
               else "a reaction meme does not fit a grave line" if m.get("role", "meme") == "meme" and grave(lines[i])
               else "it (or a look-alike) is already in the video" if m.get("group", f) in groups
               else f"more than {MAX_MEMES} memes" if m.get("role", "meme") == "meme" and memes >= MAX_MEMES else "")
        if why:
            notes.append(f"line {i + 1}: {where} {f!r} dropped ({why})")
            return False
        groups.add(m.get("group", f))
        memes += m.get("role", "meme") == "meme"
        return True

    for i, L in enumerate(plan["lines"]):
        if i >= len(lines):
            break
        box = L.get("box") or []
        L["box"] = [b for b in box if b.get("kind") != "meme" or keep(i, b.get("file"), "box", L.get("expression"))]
        p = L.get("pop")
        if isinstance(p, dict) and not keep(i, p.get("file"), "pop-up", L.get("expression")):
            L["pop"] = None
    return notes


def validate(plan: dict, lines: list[str], line_keys: list[list[str]], memes: list[dict], cat: dict,
             covered: set[int] | None = None) -> list[str]:
    """Every error is phrased so Gemini can fix it in the next round. Never raises on a malformed plan."""
    errs = shape_errors(plan)
    if errs:
        return errs
    try:
        return _rules(plan, lines, line_keys, memes, cat, covered or set())
    except (AttributeError, TypeError, KeyError, ValueError) as e:     # a shape the checks above did not foresee
        return [f"the plan's JSON has an unexpected shape ({type(e).__name__}: {e}); follow output_example exactly"]


def _rules(plan: dict, lines: list[str], line_keys: list[list[str]], memes: list[dict], cat: dict,
           covered: set[int] = frozenset()) -> list[str]:
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
            errs.append(f"line {n}: gesture {g.get('do')!r} is not one of the guide_actions {sorted(GESTURES)}")
        elif g.get("do") != "none":
            word_ok(i, g.get("word"), "gesture")
        dr = L.get("drawings") or []
        if not dr and not (L.get("box") or L.get("verse")) and i not in covered:
            errs.append(f"line {n}: nothing on screen shows this line: give it a drawing of what it says (or box media "
                        "that truly shows it)")
        if len(dr) > 3:
            errs.append(f"line {n}: {len(dr)} drawings; at most 3 per line")
        sh = shapes(cat)
        for j, d in enumerate(dr[:3]):
            t = d.get("type")
            if t in types and t not in sh:
                errs.append(f"line {n}: {t} cannot be shown big and readable here (too small or a thin strip); "
                            "pick a library illustration")

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
        box = L.get("box") or []                     # may be empty: no media, no frame
        for b in box:
            word_ok(i, b.get("word"), "box")
            if b.get("kind") == "meme" and b.get("file") not in files:
                errs.append(f"line {n}: file {b.get('file')!r} is not in media_library")
            elif b.get("kind") == "stock" and len(str(b.get("query", "")).split()) < 2:
                errs.append(f"line {n}: stock query {b.get('query')!r} needs 2-4 concrete words")
            elif b.get("kind") not in ("stock", "meme"):
                errs.append(f"line {n}: box kind {b.get('kind')!r} must be 'stock' or 'meme'")
        p = L.get("pop")
        if p:
            pops += 1
            word_ok(i, p.get("word"), "pop")
            if p.get("file") not in files:
                errs.append(f"line {n}: pop file {p.get('file')!r} is not in media_library")
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

"""Diagrams, charts, maps, flowcharts and infographics: complete compositions, never collections of drawings.

When the narration introduces a diagram from the library and walks through what it shows, the director presents
the WHOLE image as one object for that stretch of narration:

  1. the source image is preserved (never cropped, split, redrawn, rearranged or stretched);
  2. it is scaled uniformly: scale = min(available_width / image_width, available_height / image_height);
  3. it fits inside the platform safe area, with the caption band kept clear beside / under it;
  4. no media frame around it; the guide may be covered only while it is up (he steps out and back in);
  5. when it goes, the normal layout (guide, drawings, clip box) comes back.

Region focus (a camera/view move over the intact image, never a cut file) exists only for assets whose library
entry says region_rendering: true AND has regions; it is used only when a sentence names that region's content
after the whole diagram has been seen. Assets with region_rendering false always show whole.

Selection is by meaning, not by a trigger phrase: a run of consecutive sentences that (a) starts where the
narration points at a visual ("this graph", "the map", "look at...") or names the diagram's subject, and (b) keeps
talking about what the diagram contains (its subject, topics, aliases, description and region text).

How LONG it stays is a separate decision (attention, not topic): the whole picture is the visual while the
narration is looking AT it, i.e. through the last clause that points at the picture itself ("according to this
graph,") or, for an asset that allows region focus, names one of its regions; never shorter than the time to take
it in (MIN_VIEW, or the asset's own reading_seconds); then it goes at the next pause. When the narration only goes
on discussing the subject (the argument the chart summarises), one idea at a time is clearer than a dense chart, so
the drawings take over. The same rule gives a quick reference ~3-5 s and a chart the narration walks through much
longer. (Owner, 2026-10-27: a flowchart stayed 25.4 s while the narration only discussed its subject.)
"""
from __future__ import annotations

from kindled_iron.director import story as st

DIAGRAM_TYPES = {"diagram", "flowchart", "chart", "map", "infographic"}
MIN_SUPPORT = 3            # sentences that talk about the diagram before it is worth showing
MAX_GAP = 2                # short sentences in between that do not ("Sounds crazy, right?")
MAX_SECONDS = 30.0         # it never stays longer than this
HOLD = 0.4                 # after the last sentence about it
MIN_WHOLE = 2.0            # the whole diagram is seen this long before any region focus
MIN_VIEW = 3.0             # the least time to take in a whole diagram (an asset may say more: reading_seconds)
MIN_READABLE_PX = 18       # smallest text (cap height, px on the 1920-tall frame) a phone viewer can read
CAPTION_BAND = 140         # the caption line box (110 px for 88 px text) + its outline + gap, under the diagram


def is_diagram(item: dict) -> bool:
    return (item.get("type") or item.get("media_type") or "") in DIAGRAM_TYPES or item.get("role") == "diagram"


def vocabulary(d: dict) -> tuple[set[str], list[str]]:
    """(content words, phrases) the diagram is about: its subject, topics, aliases, description, region text."""
    phrases = [p for p in [d.get("subject", "")] + list(d.get("topics") or []) + list(d.get("aliases") or []) if p]
    text = " ".join(phrases + [d.get("description", "")] + list(d.get("tags") or []))
    for r in (d.get("regions") or {}).values() if isinstance(d.get("regions"), dict) else d.get("regions") or []:
        text += " " + " ".join([r.get("text", "")] + list(r.get("keywords") or []))
    return st.content(text), [p.lower() for p in phrases if len(st.tokens(p)) >= 2]


def support(s: dict, vocab: set[str], phrases: list[str], subject: str) -> tuple[int, list[str]]:
    """How strongly one sentence is about the diagram, and the words that show it."""
    hits = sorted(st.content(s["text"]) & vocab)
    ph = [p for p in phrases if st.phrase_in(p, s["text"])]
    score = len(hits) + 2 * len(ph)
    why = hits + [f'"{p}"' for p in ph]
    intents = set(s.get("intent") or st.intent(s["text"]))
    if subject and st.phrase_in(subject, s["text"]):
        score += 3
        why.append("names the subject")
    if intents & {"refers_visual", "attention"}:
        score += 2
        why.append("points at a visual")
    return score, why


def select(sentences: list[dict], lib: list[dict]) -> dict | None:
    """The best diagram presentation for this narration, or None when no diagram is introduced and explained.
    -> {file, path, size, t0, t1, sentences: [evidence], views, why, score}"""
    best = None
    for d in (m for m in lib if is_diagram(m) and m.get("size")):
        vocab, phrases = vocabulary(d)
        subj = (d.get("subject") or "").lower()
        scored = [support(s, vocab, phrases, subj) for s in sentences]
        for a, s in enumerate(sentences):
            intents = set(s.get("intent") or st.intent(s["text"]))
            anchor = bool(intents & {"refers_visual"}) or (subj and st.phrase_in(subj, s["text"]))
            if not anchor:
                continue
            run, gap, last = [a], 0, a
            for b in range(a + 1, len(sentences)):
                if "quote" in (sentences[b].get("intent") or st.intent(sentences[b]["text"])):
                    break                                  # a verse / quote has its own card: the diagram goes first
                sc = scored[b][0]
                if sc >= 2:
                    run.append(b)
                    last, gap = b, 0
                else:
                    gap += 1
                    if gap > MAX_GAP:
                        break
            while last > a and sentences[last]["t1"] - s["t0"] > MAX_SECONDS:
                run = [k for k in run if k < last]
                last = run[-1]
            n_support = len([k for k in run if scored[k][0] >= 2])
            total = sum(scored[k][0] for k in run)
            if n_support < MIN_SUPPORT:
                continue
            if best is None or total > best["score"]:          # the same total: the earlier introduction wins
                t0 = round(max(0.0, s["t0"] - 0.05), 3)
                t1, upto = attention_end(d, sentences, a, last, t0)
                best = {"file": d["file"], "path": d.get("path"), "size": list(d["size"]), "score": total,
                        "t0": t0, "t1": t1, "topic_until": round(sentences[last]["t1"], 3), "support": n_support,
                        "first": a, "last": upto,
                        "sentences": [dict(st.evidence(sentences[k]), why=scored[k][1]) for k in range(a, upto + 1)],
                        "_asset": d}
    if not best:
        return None
    d = best.pop("_asset")
    best["views"] = views(d, sentences[best.pop("first"): best.pop("last") + 1], best["t0"])
    best["why"] = (f"the narration introduces {d.get('subject') or d['file']} and talks about what it shows for "
                   f"{len(best['sentences'])} sentences")
    return best


def clauses(s: dict) -> list[dict]:
    """A sentence's clauses (split after , ; : and the sentence end), with their words and times."""
    out, cur = [], []
    for w in s.get("words") or []:
        cur.append(w)
        if w["word"].rstrip("\"'”’)").endswith((",", ";", ":", ".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"text": " ".join(w["word"] for w in c), "t0": c[0]["start"], "t1": c[-1]["end"], "words": c} for c in out]


def attention_end(d: dict, sentences: list[dict], a: int, last: int, t0: float) -> tuple[float, int]:
    """When the whole diagram stops being the visual -> (exit time, index of the last sentence it covers).
    It stays through the last clause that points at the picture itself (a visual noun with a determiner: "this
    graph"; for a region-focus asset also a clause naming one of its regions), at least MIN_VIEW (or the asset's
    reading_seconds) from its start, and leaves in the pause after that clause. Pointing again more than MAX_GAP
    sentences later does not keep it up through everything in between."""
    keys = [k for r in ((d.get("regions") or {}).values() if isinstance(d.get("regions"), dict) else d.get("regions") or [])
            for k in r.get("keywords") or []] if d.get("region_rendering") else []
    need = t0 + float(d.get("reading_seconds") or MIN_VIEW)
    flat = [(k, c) for k in range(a, last + 1) for c in clauses(sentences[k])]
    att, gap_from = None, a
    for k, c in flat:
        points = "refers_visual" in st.intent(c["text"]) or any(st.phrase_in(x, c["text"]) for x in keys)
        if points and k - gap_from <= MAX_GAP:
            att, gap_from = (k, c), k
    k_end, c_end = att if att else flat[0]
    for k, c in flat:                                  # never shorter than the time to take it in
        if (k, c["t1"]) >= (k_end, c_end["t1"]) and c["t1"] >= need:
            k_end, c_end = k, c
            break
    else:
        k_end, c_end = flat[-1]
    nxt = next((w["start"] for kk in range(k_end, len(sentences)) for w in sentences[kk]["words"] if w["start"] > c_end["t1"]), None)
    t1 = c_end["t1"] + HOLD if nxt is None else min(c_end["t1"] + HOLD, (c_end["t1"] + nxt) / 2 + 0.05)
    return round(t1, 3), k_end


def views(d: dict, ss: list[dict], t0: float) -> list[dict]:
    """[{t, view: 'whole'} | {t, view: 'region', region, rect}]: the whole diagram first; region focus only for an
    asset that allows it and a sentence that names one region's content, after the whole was seen MIN_WHOLE s."""
    out = [{"t": t0, "view": "whole"}]
    regions = d.get("regions") or {}
    if not d.get("region_rendering") or not regions:
        return out
    items = list(regions.items()) if isinstance(regions, dict) else [(r.get("id"), r) for r in regions]
    for s in ss:
        if s["t0"] < t0 + MIN_WHOLE:
            continue
        intents = set(s.get("intent") or st.intent(s["text"]))
        if intents & {"refers_visual"}:
            if out[-1]["view"] != "whole":
                out.append({"t": round(s["t0"], 3), "view": "whole"})
            continue
        hits = []
        for rid, r in items:
            found = [(at, k) for k in r.get("keywords") or [] for at in [_word_at(s, k)] if at is not None]
            if found:
                hits.append((len(found), -min(found)[0], rid, r, min(found)[0]))
        hits.sort(reverse=True)
        if hits and (len(hits) == 1 or hits[0][0] > hits[1][0]):
            _, _, rid, r, at = hits[0]
            if out[-1].get("region") != rid:
                out.append({"t": round(at - 0.1, 3), "view": "region", "region": rid, "rect": list(r["rect"])})
        elif out[-1]["view"] != "whole":
            out.append({"t": round(s["t0"], 3), "view": "whole"})
    return out


def _word_at(s: dict, phrase: str) -> float | None:
    """When the phrase starts being spoken in this sentence (its first word's start), None if it is not said."""
    p = [st.stem(w) for w in st.tokens(phrase)]
    ws = s.get("words") or []
    toks = [(st.stem(t), w["start"]) for w in ws for t in st.tokens(w["word"])[:1]]
    for i in range(len(toks) - len(p) + 1):
        if p and [t for t, _ in toks[i:i + len(p)]] == p:
            return toks[i][1]
    return None


def fit(size: list[int] | tuple[int, int], safe: dict, caption_band: int = CAPTION_BAND) -> dict:
    """Where the whole diagram goes: the largest uniform scale that fits a usable safe rectangle with the caption band
    under it (x 120-780 for anything that reaches below the button column's top). Never crops, never stretches.
    -> {rect: [x, y, w, h], scale, caption: {x, y, w}}"""
    w0, h0 = size
    col = safe["column"]
    cands = [  # (x0, y0, x1, y1): beside the button column the full height; above it the full width
        (safe["x0"], safe["y0"], col["x0"], safe["y1"] - caption_band),
        (safe["x0"], safe["y0"], safe["x1"], col["y0"]),
    ]
    best = None
    for x0, y0, x1, y1 in cands:
        s = min((x1 - x0) / w0, (y1 - y0) / h0)
        if best is None or s > best[0]:
            best = (s, x0, y0, x1, y1)
    s, x0, y0, x1, y1 = best
    w, h = int(w0 * s), int(h0 * s)
    x = x0 + ((x1 - x0) - w) // 2
    cap_x0, cap_x1 = safe["x0"], col["x0"]             # the caption band is always clear of the button column
    return {"rect": [x, y0, w, h], "scale": round(s, 4),
            "caption": {"x": (cap_x0 + cap_x1) // 2, "y": y0 + h + 28, "w": cap_x1 - cap_x0}}


def readability(item: dict, scale: float) -> dict:
    """Smallest text on screen. A limitation is reported (never fixed by cropping or splitting the diagram)."""
    px = item.get("min_text_px")
    if not px:
        return {"smallest_text_px": None, "ok": None, "note": "smallest text size unknown (no min_text_px in the library)"}
    on = round(px * scale, 1)
    ok = on >= MIN_READABLE_PX
    return {"smallest_text_px": on, "ok": ok,
            "note": "" if ok else (f"its smallest text is {on} px tall on screen (under {MIN_READABLE_PX} px): hard to read on a "
                                   "phone at full-diagram size; shown whole anyway (cropping or splitting it needs the owner's approval)")}


def _word_time(ws: list[dict], word: str) -> float | None:
    from kindled_iron.director.plan import key
    k = key(word or "")
    return next((w["start"] for w in ws if key(w["word"]) == k), None)


def clear_plan(plan: dict, words: list[list[dict]], dg: dict) -> list[str]:
    """While the whole diagram is up it is the visual: box media and meme cards the planner put there are taken out
    (in code, no AI call). Drawings stay in the plan: the compiler shows them after the diagram when their line is
    still being spoken, else leaves them out."""
    notes = []
    for i, L in enumerate(plan.get("lines") or []):
        if i >= len(words):
            break
        inside = lambda w: (lambda t: t is not None and dg["t0"] - 0.2 <= t < dg["t1"])(_word_time(words[i], w))
        box = L.get("box") or []
        keep = [b for b in box if not inside(b.get("word"))]
        if len(keep) < len(box):
            notes.append(f"line {i + 1}: box media left out (the diagram is on screen there)")
            L["box"] = keep
        p = L.get("pop")
        if isinstance(p, dict) and inside(p.get("word")):
            L["pop"] = None
            notes.append(f"line {i + 1}: pop-up left out (the diagram is on screen there)")
    return notes


def planner_note(dg: dict) -> list[str]:
    """What the planner is told: which narration the whole diagram already covers."""
    lines = sorted({s["line"] for s in dg["sentences"]})
    return [f"From {dg['t0']:.1f}s to {dg['t1']:.1f}s (script lines {', '.join(map(str, lines))}: \"{dg['sentences'][0]['sentence'][:60]}\" "
            f"to \"{dg['sentences'][-1]['sentence'][:60]}\") the whole diagram {dg['file']} fills the screen: give those "
            "words no box media, no pop and no freeze; drawings for these lines appear only after it, so give them for "
            "what the line says after the diagram."]

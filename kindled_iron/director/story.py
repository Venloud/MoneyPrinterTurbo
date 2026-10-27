"""Story understanding: the script as sentences on the narration's own clock, each with what it is doing.

This runs before any visual is chosen, on the aligned words (no AI call), so every later stage can say which spoken
sentence a visual supports and why. Topic-independent: it knows English sentence structure and a few kinds of
intent, never a particular video.

    sentences(lines, words) -> [{line, n, text, t0, t1, words}]      one per spoken sentence, in order
    intent(text)            -> set of intents (below)
    analyze(lines, words)   -> {"sentences": [...with "intent"], "content_words": [...]}

Intents (decision hints, not templates):
  refers_visual   points the viewer at a visual: a determiner + a visual noun ("this graph", "the map", "that chart")
  attention       tells the viewer to look ("look at", "check out", "notice")
  question        asks something
  example         lists concrete cases ("earthquakes, diseases, ...")
  quote           quotes or cites a source (a reference or quotation marks)
"""
from __future__ import annotations

import re

STOP = set("""a an the and or but if so then than that this these those there here is are was were be been being am
do does did done have has had having i i'm im you your y'all yall he she it its it's we they them their his her him our
us me my of in on at to for from by with about as into out over under up down off again just only very really also too
not no nor can could would should will shall may might must what which who whom whose why how when where all any both
each every some such own same other more most few well now even still yet ever let let's s t don't doesn't didn't
isn't aren't wasn't weren't won't wouldn't can't couldn't shouldn't you'd you're you've he's she's we're they're""".split())
VAGUE = {"god", "lord", "jesus", "christ", "people", "person", "thing", "things", "something", "anything", "everything",
         "way", "lot", "kind", "sort", "sure", "seen", "say", "said", "think", "know", "right", "really", "actually",
         "maybe", "make", "made", "get", "got", "go", "going", "come", "look"}
VISUAL_NOUNS = {"graph", "chart", "diagram", "flowchart", "map", "infographic", "table", "figure", "illustration",
                "picture", "image", "timeline", "photo", "screenshot", "slide"}
DETERMINERS = {"this", "that", "the", "these", "those", "our"}    # "a graph" talks about graphs, it points at none
ATTENTION = ("look at", "check out", "take a look", "notice", "see how", "you can see", "as you can see", "here's")
END = re.compile(r"[.?!]['\"”’)]*$")


def stem(w: str) -> str:
    """A light stem so 'exists' ~ 'exist', 'diseases' ~ 'disease', 'knowing' ~ 'know' (no dictionary needed)."""
    w = w.lower().strip("'’")
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z'’]*", text.lower())


def content(text: str) -> set[str]:
    """The words that carry meaning: no function words, no vague words, stemmed."""
    return {stem(w) for w in tokens(text) if w not in STOP and w not in VAGUE and len(w) > 2}


def phrase_in(phrase: str, text: str) -> bool:
    """A multi-word phrase spoken in order (stemmed: 'evil exist' matches 'evil exists')."""
    p, t = [stem(w) for w in tokens(phrase)], [stem(w) for w in tokens(text)]
    return bool(p) and any(t[i:i + len(p)] == p for i in range(len(t) - len(p) + 1))


def intent(text: str) -> set[str]:
    out, toks, low = set(), tokens(text), text.lower()
    for i, w in enumerate(toks):
        if stem(w) in {stem(v) for v in VISUAL_NOUNS} and any(t in DETERMINERS for t in toks[max(0, i - 2):i]):
            out.add("refers_visual")
    if any(a in low for a in ATTENTION):
        out.add("attention")
    if text.strip().endswith("?"):
        out.add("question")
    if text.count(",") >= 2 and len(toks) <= 12:
        out.add("example")
    if re.search(r"[“\"]|\b\d+:\d+\b", text):
        out.add("quote")
    return out


def sentences(lines: list[str], words: list[list[dict]]) -> list[dict]:
    """Split every line's aligned words at sentence ends; times are the narration's."""
    out = []
    for li, ws in enumerate(words):
        cur: list[dict] = []
        for k, w in enumerate(ws):
            cur.append(w)
            if END.search(w["word"]) or k == len(ws) - 1:
                out.append({"line": li, "n": len(out), "text": " ".join(x["word"] for x in cur),
                            "t0": cur[0]["start"], "t1": cur[-1]["end"], "words": cur})
                cur = []
    return out


def analyze(lines: list[str], words: list[list[dict]]) -> dict:
    ss = sentences(lines, words)
    for s in ss:
        s["intent"] = sorted(intent(s["text"]))
    return {"sentences": ss, "content_words": sorted(set().union(*(content(s["text"]) for s in ss)) if ss else set())}


def evidence(s: dict) -> dict:
    """What a log / media.json says about a sentence (no word timing lists)."""
    return {"line": s["line"] + 1, "sentence": s["text"], "from": round(s["t0"], 2), "to": round(s["t1"], 2)}

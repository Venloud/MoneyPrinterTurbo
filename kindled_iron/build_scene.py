"""Turn a finished script (kindled_iron/queue/*.json) into a render-ready scene, with NO AI at run time.

    python -m kindled_iron.build_scene kindled_iron/queue/001-why-did-god-rest.json [--out scene.json]

A script is a list of lines; each line names a block from kindled_iron/blocks/ and fills its slots:

    {"id": "why-did-god-rest", "title": "Why Did God Rest?",
     "post": {"caption": "If God never gets tired, why did he rest? #bible #god #faith",
              "threads": "...", "description": "..."},
     "lines": [{"block": "hook_question", "say": "[curious] If God never gets tired, why did he rest on day seven?",
                "slots": {"question_text": "GOD... TIRED?", "clip_query": "night sky stars",
                          "point_word": "tired", "reaction_word": "rest"}}, ...]}

"say" is exactly what the voice reads. [tags] are voice directions for v3 / v4 (never shown or captioned).
Every check that can fail later is done here first, so a bad script never spends voice credits:
blocks and slots exist, every anchor word is in its own line, every scripture card is spoken word for word and
matches the World English Bible, the caption is the hook question plus 3-5 hashtags, the length is plausible.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCKS = HERE / "blocks"
TAG = re.compile(r"\[[^\]]*\]")
SLOT = re.compile(r"\{\{([^}]+)\}\}")
WPM_GUESS = 165                     # eleven_v4 measured 167 wpm on the approved render
GESTURE_EVERY = 5                   # words between guide gestures (~1.8 s): the render's pacing check wants news every ~2 s
PULSE_TYPES = {"word", "popup", "frame", "book", "clock", "controller"}


class ScriptError(Exception):
    pass


def strip_tags(text: str) -> str:
    return re.sub(r"\s{2,}", " ", TAG.sub(" ", text)).strip()


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower().replace("’", "'"))


def load_block(name: str) -> dict:
    f = BLOCKS / f"{name}.json"
    if not f.is_file() or name.startswith("_"):
        known = sorted(p.stem for p in BLOCKS.glob("*.json") if not p.stem.startswith("_"))
        raise ScriptError(f"unknown block {name!r} (blocks: {', '.join(known)})")
    return json.loads(f.read_text(encoding="utf-8"))


def _lookup(key: str, ctx: dict):
    """'name', 'item.word', 'items.0.word', or a small sum like '960+140*n'."""
    if re.fullmatch(r"[\d\s+*n-]+", key) and "n" in key:
        return eval(key, {"__builtins__": {}}, {"n": ctx["n"]})   # noqa: S307 - digits, n, + - * only
    cur = ctx
    for part in key.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = None
        if cur is None:
            return None
    return cur


class Missing(Exception):
    pass


def fill(obj, ctx: dict):
    if isinstance(obj, str):
        whole = SLOT.fullmatch(obj)
        if whole:
            v = _lookup(whole.group(1).strip(), ctx)
            if v is None:
                raise Missing(whole.group(1))
            return v
        def rep(m):
            v = _lookup(m.group(1).strip(), ctx)
            if v is None:
                raise Missing(m.group(1))
            return str(v)
        return SLOT.sub(rep, obj)
    if isinstance(obj, list):
        return [fill(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, ctx) for k, v in obj.items()}
    return obj


def expand(events: list, ctx: dict, optional: set) -> list:
    out = []
    for ev in events:
        if "each" in ev:
            items = ctx.get(ev["each"]) or []
            for n, item in enumerate(items, 1):
                out += expand(ev["events"], {**ctx, "item": item, "n": n}, optional)
            continue
        try:
            out.append(fill(copy.deepcopy(ev), ctx))
        except Missing as m:
            if m.args[0].split(".")[0] in optional:      # an optional slot left empty drops its events
                continue
            raise ScriptError(f"slot {m.args[0]!r} is missing") from None
    return out


def check_anchor(at, spoken: str, where: str) -> None:
    if not isinstance(at, str) or re.fullmatch(r"end([+-][\d.]+)?|pause(#\d+)?([+-][\d.]+)?", at.strip()):
        return
    m = re.fullmatch(r"(.+?)(?:#(\d+))?([+-][\d.]+)?", at.strip())
    word, nth = m.group(1), int(m.group(2) or 1)
    hits = [w for w in spoken.split() if norm(w) == norm(word)]
    if len(hits) < nth:
        raise ScriptError(f"{where}: anchor word {word!r}{f' #{nth}' if nth > 1 else ''} is not in the line: {spoken!r}")


def _word_index(at, words: list[str]) -> int | None:
    """Index (in the line) of the word an anchor points at; None for numbers / end / pause."""
    if not isinstance(at, str):
        return 0 if isinstance(at, (int, float)) else None
    m = re.fullmatch(r"(.+?)(?:#(\d+))?([+-][\d.]+)?", at.strip())
    if not m or re.fullmatch(r"end|pause", m.group(1)):
        return None
    hits = [k for k, w in enumerate(words) if norm(w) == norm(m.group(1))]
    nth = int(m.group(2) or 1)
    return hits[nth - 1] if len(hits) >= nth else None


def add_gestures(events: list, spoken: str) -> list:
    """Deterministic in-between motion so nothing sits still for more than ~2 s: on every 5th word that is
    at least 3 words from an authored event, the guide looks up / reacts / points at or pulses what is
    already drawn. Never on short filler words."""
    words = spoken.split()
    used = {i for i in (_word_index(e.get("at"), words) for e in events) if i is not None}
    drawn = []                                  # (word index, id, type)
    for e in events:
        if e.get("do") == "draw" and e.get("id") and e.get("type") not in ("strike", "inset"):
            k = _word_index(e.get("at"), words)
            if k is not None:
                drawn.append((k, e["id"], e.get("type")))
    cycle = ["look", "point", "express", "pulse", "look_viewer"]
    out, last, n = list(events), -99, 0
    for k, w in enumerate(words):
        if k < 2 or len(norm(w)) < 4 or k - last < GESTURE_EVERY or any(abs(k - u) < 3 for u in used):
            continue
        nth = sum(1 for x in words[:k + 1] if norm(x) == norm(w))
        at = re.sub(r"[^\w']", "", w) + (f"#{nth}" if nth > 1 else "")
        seen = [(i, t) for j, i, t in drawn if j < k - 1]
        kind = cycle[n % len(cycle)]
        if kind in ("point", "pulse") and not seen:
            kind = "look"
        if kind == "pulse" and seen[-1][1] not in PULSE_TYPES:
            kind = "point"
        ev = {"look": {"do": "look", "who": "guide", "dir": "up", "expression": "curious", "hold": 0.5},
              "point": {"do": "point", "who": "guide", "toward": seen[-1][0] if seen else "", "hold": 0.5},
              "express": {"do": "express", "who": "guide", "expression": "happy"},
              "pulse": {"do": "pulse", "id": seen[-1][0] if seen else ""},
              "look_viewer": {"do": "look_viewer", "who": "guide"}}[kind]
        out.append({"at": at, **ev, "auto": True})
        last, n = k, n + 1
    return out


def build(script: dict) -> dict:
    from kindled_iron import scripture

    base = json.loads((BLOCKS / "_scene.json").read_text(encoding="utf-8"))
    transitions = base.pop("transitions")
    base.pop("_help", None)
    sid = script.get("id") or ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", sid):
        raise ScriptError("id must be lowercase words joined by '-' (e.g. why-did-god-rest)")
    if not script.get("title"):
        raise ScriptError("title is missing")
    lines = script.get("lines") or []
    if not 4 <= len(lines) <= 14:
        raise ScriptError(f"{len(lines)} lines: a script has 4-14 lines")
    scene = {"id": sid, "title": script["title"], **base, "post": dict(script.get("post") or {}), "beats": []}
    spoken_all, tagged_all, any_tag = [], [], False
    for i, line in enumerate(lines):
        where = f"line {i + 1} ({line.get('block')})"
        block = load_block(line.get("block", ""))
        say = (line.get("say") or "").strip()
        if not say:
            raise ScriptError(f"{where}: 'say' is empty")
        spoken = strip_tags(say)
        any_tag = any_tag or bool(TAG.search(say))
        slots = dict(line.get("slots") or {})
        optional = {k for k, v in block["slots"].items() if str(v).startswith("optional")}
        unknown = set(slots) - set(block["slots"])
        if unknown:
            raise ScriptError(f"{where}: unknown slot(s) {sorted(unknown)}; this block takes {sorted(block['slots'])}")
        missing = [k for k in block["slots"] if k not in optional and slots.get(k) in (None, "", [])]
        if missing:
            raise ScriptError(f"{where}: missing slot(s) {missing}")
        bid = f"b{i + 1}"
        cards_before = sum(1 for b in scene["beats"] for e in b["events"] if isinstance(e.get("scripture"), dict))
        ctx = {**slots, "id": bid, "card_id": f"card{cards_before + 1}"}
        try:
            events = expand(block["events"], ctx, optional)
            beat_extra = fill(copy.deepcopy(block.get("beat", {})), ctx)
        except ScriptError as e:
            raise ScriptError(f"{where}: {e}") from None
        except Missing as m:
            raise ScriptError(f"{where}: slot {m.args[0]!r} is missing") from None
        narration = spoken
        for ev in events:
            check_anchor(ev.get("at"), spoken, where)
            card = ev.get("scripture")
            if isinstance(card, dict):
                ok, verse = scripture.check(card["ref"], card["text"])
                if not ok:
                    raise ScriptError(f"{where}: card {card['text']!r} is not {card['ref']} in the WEB: {verse!r}")
                cw, sw = scripture.words(card["text"]), scripture.words(spoken)
                if not any(sw[k:k + len(cw)] == cw for k in range(len(sw) - len(cw) + 1)):
                    raise ScriptError(f"{where}: the quote {card['text']!r} must be spoken word for word in the line")
                narration += f" [{scripture.canonical(card['ref'])}]"
        events = add_gestures(events, spoken)
        if isinstance(beat_extra.get("music_lift"), str):
            check_anchor(beat_extra["music_lift"], spoken, where)
        beat = {"id": bid, "panel": i, "narration": narration, "camera_start": False}
        if i:
            beat["transition"] = transitions[(i - 1) % len(transitions)]
        beat.update(beat_extra)
        beat["events"] = events
        scene["beats"].append(beat)
        spoken_all.append(spoken)
        tagged_all.append(say)
    scene["tts_text"] = " ".join(spoken_all)
    if any_tag:
        scene["tts_text_tagged"] = "\n".join(tagged_all)
    check_post(scene, spoken_all[0])
    words = len(scene["tts_text"].split())
    est = words / WPM_GUESS * 60
    if not 130 <= words <= 230 or not 55 <= est <= 90:
        raise ScriptError(f"{words} words (~{est:.0f} s at {WPM_GUESS} wpm): aim for 150-200 words (60-75 s)")
    return scene


def check_post(scene: dict, first_line: str) -> None:
    post = scene["post"]
    cap = (post.get("caption") or "").strip()
    q = re.match(r"[^#]*?\?", cap)
    tags = re.findall(r"#\w+", cap)
    if not q:
        raise ScriptError("post.caption must start with the hook question (ending in '?')")
    if not 3 <= len(tags) <= 5:
        raise ScriptError(f"post.caption has {len(tags)} hashtags: use 3-5")
    if norm(q.group(0)) not in norm(first_line):
        print(f"[build_scene] note: the caption question is not word for word in line 1 ({q.group(0)!r})")
    post.setdefault("title", scene["title"])
    post.setdefault("youtube_title", f"{scene['title']} #shorts")
    post.setdefault("threads", (q.group(0) + " " + " ".join(tags[:3])).strip())
    post.setdefault("description", q.group(0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--out", default=None, help="scene JSON to write (default: kindled_iron/scenes/<id>.json)")
    a = ap.parse_args()
    script = json.loads(Path(a.script).read_text(encoding="utf-8"))
    try:
        scene = build(script)
    except ScriptError as e:
        sys.exit(f"SCRIPT ERROR in {a.script}: {e}")
    out = Path(a.out) if a.out else HERE / "scenes" / f"{scene['id']}.json"
    out.write_text(json.dumps(scene, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    words = len(scene["tts_text"].split())
    print(f"[build_scene] {scene['id']}: {len(scene['beats'])} lines, {words} words (~{words / WPM_GUESS * 60:.0f} s), "
          f"{sum(1 for b in scene['beats'] for e in b['events'] if 'scripture' in e)} scripture card(s) WEB-checked -> {out}")


if __name__ == "__main__":
    main()

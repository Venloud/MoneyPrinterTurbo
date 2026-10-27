"""Generate kindled_iron/director/catalog.json from the renderer itself, so the director never drifts from it.

    python -m kindled_iron.director.catalog            # parse + measure in Chrome, write catalog.json
    python -m kindled_iron.director.catalog --check    # CI: fail if catalog.json is stale (parse-only part)

What it records:
- every drawing primitive in runtime.js (OBJ.<name>), its comment, the o.<field> parameters it reads, and its
  bounding box at scale 1 measured in headless Chrome (so the compiler can scale it into a zone);
- every event type (`case '<name>'` in runtime.js) and the e.<field> values it reads;
- the media-box request kinds (mediabox.py), the guide's expressions, and the guide's measured geometry
  (body at rest, how far the arm reaches when pointing, how wide a shrug is);
- the director's fixed layout zones (ZONES below).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KI = HERE.parent
RUNTIME = KI / "runtime" / "runtime.js"
OUT = HERE / "catalog.json"
DOODLES = KI / "doodles" / "library.json"     # built once by kindled_iron/doodles/build.py

# Fixed layout (1080x1920, inside the safe box x 120-960, y 160-1440; the right button column x >= 780 at y >= 840
# stays free). The director picks zones and slots; only the compiler turns them into coordinates.
ZONES = {
    "box": {"x": 540, "y": 360, "w": 820, "h": 360, "use": "clip box: footage, memes, verse cards"},
    # the captions sit at the middle of the frame (their default anchor, about the frame's centre line); the media box
    # and the drawings are arranged above them and the guide below; across, they are centred on the width left of the
    # right-hand button column (x 150-750, like the renderer's own caption), which starts at this height. The runtime
    # still shifts or shrinks a caption that would cover a face or a drawing; a diagram brings its own caption band
    "caption": {"x": 150, "y": 900, "w": 600, "h": 110, "size": 88, "use": "one caption line, 1-3 words, spoken word orange, at the middle of the frame"},
    # the drawing area: the band between the clip box and the caption, 30 px clear of it so a drawing's label never
    # reads as part of the caption ("draw"; with no box the drawings get the whole
    # space above the caption) plus the guide lane beside him ("lane")
    "draw": {"x0": 125, "x1": 775, "y0": 555, "y1": 870, "use": "drawing area: the band above the caption (the whole top when there is no clip box)"},
    "guide": {"ground": 1570, "spots": [230, 340, 560, 650], "size": 0.85, "use": "guide lane: the guide walks between spots"},
    "pop": {"y": 1250, "w": 380, "use": "meme pop-up card in the guide lane beside the guide (guide at an outer spot)"},
    "lane": {"y0": 1045, "y1": 1432, "use": "the drawing area beside the guide, on the side away from him"},
}
# Drawing primitives the director may use (the others are renderer internals: frames, media box, cards, effects).
NOT_FOR_DIRECTOR = {"mediabox", "inset", "scripture", "strike", "circle", "cross", "rays", "darkness", "light", "sparkle",
                    "splash", "shards", "frame", "popup", "line", "dot", "word", "blob", "waves", "voice", "cracks",
                    "cursor", "voxel", "blockfolk", "scribble", "stars", "hammer", "coins", "arrow", "doodle"}


def _block(src: str, start: int) -> str:
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise ValueError("unbalanced braces")


def parse_objects(src: str) -> dict:
    body = _block(src, src.index("var OBJ = {"))
    out = {}
    heads = list(re.finditer(r"\n    ([a-z_0-9]+): function \((o?)\) \{([^\n]*)", body))
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(body)
        chunk = body[m.start():end]
        doc = re.search(r"//\s*(.+)$", m.group(3))
        out[m.group(1)] = {"doc": doc.group(1).strip() if doc else "",
                           "params": sorted(set(re.findall(r"\bo\.([a-zA-Z_]+)", chunk)) - {"id"})}
    return out


def parse_events(src: str) -> dict:
    i = src.index("switch (e.do) {")
    body = _block(src, i)
    out = {}
    parts = re.split(r"\n\s*case '", body)
    for part in parts[1:]:
        names = [part.split("'", 1)[0]] + re.findall(r"^\s*case '([a-z_]+)'", part, flags=re.M)
        names += re.findall(r":\s*case '([a-z_]+)'", part.split("\n", 1)[0])
        fields = sorted(set(re.findall(r"\be\.([a-zA-Z_]+)", part)) - {"t", "do"})
        for n in names:
            cur = out.setdefault(n, {"fields": []})
            cur["fields"] = sorted(set(cur["fields"]) | set(fields))
    return out


def parse_box_kinds() -> list[str]:
    src = (KI / "mediabox.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'ev\["box"\] == "([a-z_]+)"', src)))


def parse_expressions(src: str) -> list[str]:
    names = set()
    for var in ("var FACES = {", "var REACT = {"):
        names |= set(re.findall(r"\n    ([a-z_]+):", _block(src, src.index(var))))
    alias = _block(src, src.index("var FACE_ALIAS = {"))
    names |= set(re.findall(r"([a-z_]+):", alias))
    return sorted(names - {"blink"})


def parse_part(src: str) -> dict:
    objs = parse_objects(src)
    for name, d in json.loads(DOODLES.read_text(encoding="utf-8")).items():     # the doodle library
        if name in objs:
            raise SystemExit(f"FAIL: doodle {name!r} has the name of a runtime drawing")
        objs[name] = {"director": True, "doodle": True, "doc": d["doc"], "tags": d["tags"], "params": list(d["slots"])}
    for name, o in objs.items():
        o["director"] = name not in NOT_FOR_DIRECTOR
    return {"runtime_sha256": hashlib.sha256(src.encode()).hexdigest(), "zones": ZONES, "objects": objs,
            "doodles_sha256": hashlib.sha256(DOODLES.read_bytes()).hexdigest(),
            "events": parse_events(src), "box_kinds": parse_box_kinds(), "expressions": parse_expressions(src)}


# ------------------------------------------------------------------ measuring in Chrome
SAMPLE = {"bars": {"labels": ["ONE", "TWO", "THREE"], "values": [0.4, 0.9, 0.6], "title": "TITLE"},
          "triangle": {"labels": ["TOP", "LEFT", "RIGHT"], "center": "MIDDLE"}, "venn": {"labels": ["LEFT", "RIGHT"], "center": "BOTH"},
          "scales": {"labels": ["LEFT", "RIGHT"]}, "flow": {"labels": ["CAUSE", "STEP", "EFFECT"], "title": "TITLE"},
          "crossout": {"text": "A WRONG IDEA"}, "openbook": {"left": "PAGE ONE", "right": "PAGE TWO", "label": "LABEL"},
          "signpost": {"labels": ["THIS WAY", "THAT WAY"]}, "timeline": {"labels": ["THEN", "NOW", "LATER"], "title": "TITLE"}}
LABELED = {"ground", "germ", "person", "people", "openbook", "question", "puppet", "heart", "bolt", "eye_check"}


_LIB: dict = {}


def _library() -> dict:
    if not _LIB:
        _LIB.update(json.loads(DOODLES.read_text(encoding="utf-8")))
    return _LIB


def doodle_spec(name: str, labels: dict, lib: dict | None = None) -> dict:
    """The renderer's draw fields for a library doodle: its strokes, label slots and the labels to write."""
    d = (lib or _library())[name]
    return {"type": "doodle", "doodle": name, "parts": d["parts"], "slots": d["slots"],
            "labels": {k: v for k, v in (labels or {}).items() if k in d["slots"]}}


def measure_specs(specs: list[dict], chrome: str | None = None, guide: bool = False) -> tuple[dict, dict | None]:
    """Real bounding boxes, at scale 1, of drawings with their actual fields (labels change a drawing's width):
    specs = [{"id", "type", **fields}] -> {id: {"size": [w, h], "center": [dx, dy]}}. guide=True also measures the
    guide: body at rest, the arm's reach when pointing, the width of a shrug."""
    import tempfile
    from playwright.sync_api import sync_playwright
    from kindled_iron import render
    events = [{"at": 0.1, "do": "draw", "id": f"m_{d['id']}", "x": 540, "y": 900, "instant": True, "pop": False,
               **{k: v for k, v in d.items() if k not in ("id", "x", "y", "scale")}} for d in specs]
    if guide:
        events += [{"at": 0, "do": "size", "who": "guide", "value": ZONES["guide"]["size"], "dur": 0.01},
                   {"at": 2.0, "do": "point", "who": "guide", "tx": 100, "ty": 1150, "hold": 1.0},
                   {"at": 4.0, "do": "point", "who": "guide", "tx": 540, "ty": 600, "hold": 1.0},
                   {"at": 6.0, "do": "shrug", "who": "guide"}]
    scene = {"id": "measure", "cast": {"guide": {"panel": 0, "x": 540, "scale": 2.1, "facing": -1, "accent": True}},
             "ground": ZONES["guide"]["ground"], "camera_y": 960, "exact_narration": True,
             "beats": [{"id": "b1", "narration": "measure", "interaction": False, "events": events}]}
    data = render.build_data(scene, [(0.0, 8.0)], [[{"word": "measure", "start": 0.0, "end": 0.5}]], 8.0)
    data["paper"] = None
    sizes, g = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        page_file = render.write_page(data, Path(tmp))
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=render.find_chrome(chrome), args=["--allow-file-access-from-files"])
            page = b.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(Path(page_file).resolve().as_uri())
            page.wait_for_function("window.kiSeek !== undefined", timeout=60000)
            page.evaluate("document.fonts.ready.then(function () { return 1; })")
            page.wait_for_timeout(1200)
            for t, k in ((1.0, "rest"), (2.7, "point_side"), (4.7, "point_up"), (6.4, "shrug")):
                page.evaluate(f"window.kiSeek({t})")
                if guide:
                    r = page.evaluate("() => { var r = window.kiRects().guide; return r && [r.left, r.top, r.right, r.bottom]; }")
                    g[k] = [round(v) for v in r]
                if k == "rest":
                    for d in specs:
                        r = page.evaluate(f"() => {{ var el = document.getElementById('obj-m_{d['id']}'); if (!el) return null;"
                                          " var q = el.getBoundingClientRect(); return [q.left, q.top, q.right, q.bottom]; }")
                        if r and r[2] > r[0]:
                            sizes[d["id"]] = {"size": [round(r[2] - r[0]), round(r[3] - r[1])],
                                              "center": [round((r[0] + r[2]) / 2 - 540), round((r[1] + r[3]) / 2 - 900)]}
                if not guide:
                    break
            b.close()
    if not guide:
        return sizes, None
    rest = g["rest"]
    gd = {"x": 540, "size": ZONES["guide"]["size"], "rest": rest, "half_width": max(540 - rest[0], rest[2] - 540),
          "top": rest[1], "reach_side": 540 - g["point_side"][0], "reach_up": rest[1] - g["point_up"][1],
          "shrug_half_width": max(540 - g["shrug"][0], g["shrug"][2] - 540)}
    return sizes, gd


def measure(objs: dict, chrome: str | None = None) -> tuple[dict, dict]:
    """Every director primitive at scale 1 with sample labels, plus the guide's geometry."""
    names = [n for n, o in objs.items() if o["director"]]
    lib = json.loads(DOODLES.read_text(encoding="utf-8"))
    specs = [doodle_spec(n, {s: "LABEL" for s in lib[n]["slots"]}, lib) | {"id": n} if objs[n].get("doodle") else
             {"id": n, "type": n, **SAMPLE.get(n, {}), **({"label": "LABEL"} if n in LABELED else {})} for n in names]
    sizes, guide = measure_specs(specs, chrome, guide=True)
    for n in names:
        if n in sizes:
            objs[n].update(sizes[n])
    return objs, guide


def build(chrome: str | None = None) -> dict:
    src = RUNTIME.read_text(encoding="utf-8")
    cat = parse_part(src)
    cat["objects"], cat["guide"] = measure(cat["objects"], chrome)
    missing = [n for n, o in cat["objects"].items() if o["director"] and "size" not in o]
    if missing:
        raise SystemExit(f"FAIL: could not measure {missing}")
    return cat


def stale(existing: dict) -> list[str]:
    """Differences between the committed catalog and what the renderer has now (parse-only, no Chrome)."""
    now = parse_part(RUNTIME.read_text(encoding="utf-8"))
    out = []
    if existing.get("runtime_sha256") != now["runtime_sha256"]:
        out.append("runtime.js changed since catalog.json was generated")
    if existing.get("doodles_sha256") != now["doodles_sha256"]:
        out.append("the doodle library changed since catalog.json was generated")
    for n, o in now["objects"].items():
        e = existing.get("objects", {}).get(n)
        if not e:
            out.append(f"object {n} missing")
        elif o["director"] and "size" not in e:
            out.append(f"object {n} not measured")
    for k in ("events", "box_kinds", "expressions"):
        if existing.get(k) != now[k]:
            out.append(f"{k} differ")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    if a.check:
        problems = stale(json.loads(OUT.read_text(encoding="utf-8"))) if OUT.exists() else ["catalog.json missing"]
        if problems:
            sys.exit("catalog.json is stale: " + "; ".join(problems) + " (run python -m kindled_iron.director.catalog)")
        print("catalog.json is current")
        return
    cat = build(a.chrome)
    OUT.write_text(json.dumps(cat, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    n = sum(1 for o in cat["objects"].values() if o["director"])
    print(f"catalog: {n} director drawings, {len(cat['events'])} events, guide {cat['guide']} -> {OUT}")


if __name__ == "__main__":
    main()

"""Offline checks for the Kindled Iron director (no network, no Gemini, no MP3, no Chrome)."""
import json
import unittest
from pathlib import Path

from kindled_iron.director import catalog, compile as compiler, media, plan as planmod
from kindled_iron.director.direct import split_beats

HERE = Path(__file__).resolve().parent
LINES = ["If God is all powerful, He can stop evil. So why does evil exist?",
         "Revelation 21:4 describes a future without death, pain, or mourning."]
LIB = [{"file": "Ideas_Surprised_Pikachu_HD.webp", "kind": "image", "tags": ["surprised"], "note": ""},
       {"file": "side-eye.webp", "kind": "image", "tags": ["side", "eye"], "note": ""}]


def words(lines):
    out, t = [], 0.0
    for line in lines:
        ws = []
        for w in line.split():
            ws.append({"word": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
        t += 0.6
        out.append(ws)
    return out


def good_plan():
    return {"freeze": {"line": 1, "word": "why"}, "lines": [
        {"line": 1, "expression": "curious", "gesture": {"do": "point", "word": "powerful"},
         "box": [{"word": "evil", "kind": "stock", "query": "storm lightning sky"}],
         "pop": None,
         "drawings": [{"word": "powerful", "type": "triangle_diagram", "concept": "three claims",
                       "fields": {"top": "ALL POWERFUL", "left": "ALL GOOD", "right": "ALL KNOWING"}},
                      {"word": "evil", "type": "question_big", "fields": {"label": "WHY?"}}]},
        {"line": 2, "expression": "happy", "gesture": {"do": "point", "word": "future"},
         "verse": {"ref": "Revelation 21:4", "word": "Revelation", "quoted": False}, "box": [],
         "drawings": [{"word": "future", "type": "rainbow", "fields": {"label": "NO MORE PAIN"}},
                      {"word": "death", "type": "heart", "fields": {"label": "NO PAIN"}}]}]}


class Director(unittest.TestCase):
    def setUp(self):
        self.cat = planmod.catalog()
        self.keys = [[planmod.key(w["word"]) for w in ws] for ws in words(LINES)]

    def test_split_paragraphs(self):
        self.assertEqual(split_beats("One sentence.\n\nSecond sentence."), ["One sentence.", "Second sentence."])

    def test_catalog_is_current(self):
        self.assertEqual(catalog.stale(json.loads(catalog.OUT.read_text())), [])

    def test_catalog_has_measured_labeled_drawings(self):
        objs = planmod.director_types(self.cat)
        for name in ("bars", "triangle", "flow", "timeline", "ground", "germ", "person", "openbook", "crossout"):
            self.assertIn(name, objs)
            self.assertEqual(len(objs[name]["size"]), 2)

    def test_scripture_reference_found(self):
        self.assertEqual(planmod.scripture_refs(LINES[1]), ["Revelation 21:4"])

    def test_valid_plan_passes(self):
        self.assertEqual(planmod.validate(good_plan(), LINES, self.keys, LIB, self.cat), [])

    def test_plan_errors_are_specific(self):
        p = good_plan()
        p["lines"][0]["drawings"] = []
        p["lines"][1].pop("verse")
        p["lines"][0]["box"] = [{"word": "nowhere", "kind": "meme", "file": "missing.jpg"}]
        errs = " | ".join(planmod.validate(p, LINES, self.keys, LIB, self.cat))
        self.assertNotIn("line 1: nothing on screen", errs)     # drawings are not a quota: its box media is its visual
        p["lines"][0]["box"] = []                                # with nothing at all, the line is reported
        self.assertIn("line 1: nothing on screen shows this line", " | ".join(planmod.validate(p, LINES, self.keys, LIB, self.cat)))
        p["lines"][0]["box"] = [{"word": "nowhere", "kind": "meme", "file": "missing.jpg"}]
        errs = " | ".join(planmod.validate(p, LINES, self.keys, LIB, self.cat))
        self.assertIn("line 2: names Revelation 21:4", errs)
        self.assertIn("not in media_library", errs)
        self.assertIn("'nowhere' is not spoken", errs)

    def test_drawing_shapes_follow_the_slots(self):
        sh = planmod.shapes(self.cat)
        self.assertNotIn("flow", sh)                        # a thin strip: never used, the library has flow_arrows
        self.assertIn(sh["person"], ("tall", "both"))
        self.assertEqual(sh["bar_chart"], "both")
        p = good_plan()
        p["lines"][0]["drawings"][0] = {"word": "powerful", "type": "flow", "fields": {"labels": ["A", "B", "C"]}}
        notes = planmod.repair(p, LINES, self.keys, self.cat)     # repaired in code, no new AI call
        self.assertEqual(p["lines"][0]["drawings"][0]["type"], "flow_arrows")
        self.assertEqual(p["lines"][0]["drawings"][0]["fields"], {"a": "A", "b": "B", "c": "C"})
        self.assertTrue(any("thin strip" in n for n in notes))

    def test_malformed_plan_is_an_error_not_a_crash(self):
        p = good_plan()
        p["lines"][0]["pop"] = [{"word": "evil", "file": "side-eye.webp"}]      # one-item list: unwrapped
        self.assertEqual(planmod.validate(p, LINES, self.keys, LIB, self.cat), [])
        p["lines"][0]["pop"] = [{"word": "evil"}, {"word": "why"}]
        p["lines"][1]["box"] = "storm"
        errs = " | ".join(planmod.validate(p, LINES, self.keys, LIB, self.cat))
        self.assertIn("'pop' must be one object", errs)
        self.assertIn("'box' must be a list of objects", errs)
        p = good_plan()
        p["lines"][0]["gesture"] = {"do": ["point"]}
        self.assertIn("unexpected shape", planmod.validate(p, LINES, self.keys, LIB, self.cat)[0])

    def test_repair_fixes_what_needs_no_new_idea(self):
        p = good_plan()
        p["lines"][0]["drawings"] = [{"word": "evil", "type": "thinker", "fields": {"label": "WHY?"}},   # tall first,
                                     {"word": "powerful", "type": "scales_big", "fields": {}}]           # wide second
        p["lines"][0]["expression"] = "serious"                # not listed: closest or neutral
        p["lines"][0]["pop"] = {"word": "evil", "file": "side-eye.webp"}   # pop on the hook line: dropped
        notes = planmod.repair(p, LINES, self.keys, self.cat)
        self.assertEqual(p["lines"][0]["drawings"][0]["type"], "scales_big")          # swapped back
        self.assertIn(p["lines"][0]["expression"], self.cat["expressions"])
        self.assertIsNone(p["lines"][0]["pop"])
        self.assertEqual(len(notes), 3)
        self.assertEqual(planmod.validate(p, LINES, self.keys, LIB, self.cat), [])

    def test_pop_never_on_god_or_verse(self):
        p = good_plan()
        p["lines"][1]["pop"] = {"word": "future", "file": "side-eye.webp"}
        p["lines"][0]["pop"] = {"word": "God", "file": "side-eye.webp"}
        errs = " | ".join(planmod.validate(p, LINES, self.keys, LIB, self.cat))
        self.assertIn("no pop on a verse line", errs)
        self.assertIn("never pop on the word 'God'", errs)

    def test_compile_zones_and_rules(self):
        import os
        os.environ["KI_BOX_PLACEHOLDER"] = "1"
        os.environ.pop("PEXELS_API_KEY", None)
        p = good_plan()
        per_line, records, errs = media.resolve(p, LIB, lambda m: None)
        self.assertEqual(errs, [])
        scene, frames = compiler.compile_scene(p, LINES, words(LINES), self.cat, per_line,
                                               {"id": "t", "audio_path": "approved_audio/t/narration.mp3", "sha256": "x", "align": 1})
        Z = self.cat["zones"]
        evs = [e for b in scene["beats"] for e in b["events"]]
        draws = [e for e in evs if e.get("do") == "draw"]
        self.assertEqual(len(draws), 4)
        for d in draws:                                   # every drawing inside the drawing area or a guide-lane slot
            self.assertTrue(Z["draw"]["y0"] - 5 <= d["y"] <= 1430, d)
        self.assertTrue(any(e.get("do") == "freeze" and e.get("sound") == "record_scratch" for e in evs))
        self.assertTrue(any(e.get("do") == "look_viewer" for e in scene["beats"][-1]["events"]))
        verse = [e for e in evs if e.get("box") == "verse"]
        self.assertEqual(len(verse), 1)
        self.assertTrue(verse[0]["paced"])                # named, not quoted: the WEB text types across the line
        self.assertTrue(any(e.get("box") == "clip" for e in evs))
        self.assertEqual(scene["voice_file"]["path"], "approved_audio/t/narration.mp3")
        self.assertTrue(scene["voice_as_is"] and scene["pencil"])
        self.assertFalse(scene["preview"]["public_artifacts"])
        self.assertEqual(len(scene["preview"]["frames"]), 8)

    def test_media_rejects_unrelated_stock(self):
        import os
        from kindled_iron import insets
        os.environ.pop("KI_BOX_PLACEHOLDER", None)
        real = insets._pexels, insets._pixabay
        insets._pexels = lambda q, pin: [{"source": "pexels", "id": "1", "title": "", "page": "https://www.pexels.com/video/paint-brush-on-wood/"}]
        insets._pixabay = lambda q, pin: []
        try:
            self.assertIsNone(media.stock("hammer nail", [], {}, lambda m: None))
            insets._pexels = lambda q, pin: [{"source": "pexels", "id": "2", "title": "", "page": "https://www.pexels.com/video/hammer-hitting-a-nail/"}]
            self.assertEqual(media.stock("hammer nail", [], {}, lambda m: None)["id"], "2")
            self.assertIsNone(media.stock("hammer nail", ["pexels:2"], {}, lambda m: None))      # never twice in a row
        finally:
            insets._pexels, insets._pixabay = real

    def test_mock_plan_fixture_is_valid(self):
        """The offline end-to-end fixture (Epicurean Paradox) passes the plan checks."""
        script = HERE / "mock_epicurean" / "plan.json"
        p = json.loads(script.read_text())
        self.assertEqual(len(p["lines"]), 8)


if __name__ == "__main__":
    unittest.main()

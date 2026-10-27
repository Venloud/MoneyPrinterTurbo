"""Regression tests for Director run 40434188836 (epicurean-paradox, 3 plan attempts, all failed):
attempt 1 drawings under meme cards + a drawing over another, attempt 2 a verse in the box + a media file used as a
drawing type, attempt 3 box items without a word. Offline: no AI, no render, no Chrome."""
import json
import os
import unittest
from pathlib import Path

from kindled_iron.director import compile as compiler, media, plan as planmod

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "run40434188836" / "attempt1_anonymized.json"
LINES = ["Sounds crazy, right? Look at this graph of the argument.",
         "If God is all powerful, why does evil exist?",
         "Revelation 21:4 describes a future without death, pain, or mourning."]
FAKE_LIB = [{"file": "meme_a.png", "path": "reactions/meme_a.png", "role": "meme", "group": "a", "tags": ["crazy"]},
            {"file": "meme_b.gif", "path": "reactions/meme_b.gif", "role": "meme", "group": "b", "tags": []},
            {"file": "sunlight_through_storm_clouds.png", "path": "movie_reference/sunlight_through_storm_clouds.png",
             "role": "still", "group": "s", "tags": ["hope", "light", "storm"]}]


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


def plan():
    dr = lambda w, t, f: {"word": w, "type": t, "fields": f}
    return {"freeze": {"line": 2, "word": "why"}, "lines": [
        {"expression": "curious", "gesture": {"do": "point", "word": "graph"},
         "box": [{"word": "graph", "kind": "stock", "query": "chalkboard graph"}],
         "drawings": [dr("graph", "bar_chart", {"label": "GRAPH"}), dr("argument", "question_big", {"label": "WHY?"})]},
        {"expression": "thinking", "gesture": {"do": "shrug", "word": "why"}, "box": [],
         "drawings": [dr("powerful", "storm", {"label": "EVIL"}), dr("evil", "question_big", {"label": "WHY?"})]},
        {"expression": "happy", "gesture": {"do": "look", "word": "future"}, "box": [],
         "verse": {"ref": "Revelation 21:4", "word": "Revelation", "quoted": False},
         "drawings": [dr("future", "rainbow", {"label": "PROMISE"}), dr("death", "grave", {"label": "GRAVE"})]}]}


class Repair(unittest.TestCase):
    def setUp(self):
        self.cat = planmod.catalog()
        self.keys = [[planmod.key(w["word"]) for w in ws] for ws in words(LINES)]

    def errs(self, p):
        return planmod.validate(p, LINES, self.keys, FAKE_LIB, self.cat)

    # attempt 3: box items without a word
    def test_box_items_without_a_word_are_anchored_on_a_spoken_word(self):
        p = plan()
        p["lines"][0]["box"] = [{"kind": "stock", "query": "chalkboard graph"}]          # no word (as in the run)
        notes = planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual(p["lines"][0]["box"][0]["word"], "graph")                     # the word its query names
        self.assertTrue(any("box word None" in n for n in notes))
        self.assertEqual(self.errs(p), [])
        p["lines"][0]["box"] = [{"kind": "stock", "query": "storm clouds"}]            # nothing shared: first word
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual(planmod.key(p["lines"][0]["box"][0]["word"]), "sounds")

    def test_a_line_without_media_is_valid_and_a_real_box_still_needs_a_spoken_word(self):
        p = plan()
        p["lines"][1]["box"] = [{"word": None}]                                        # an empty, optional item
        p["lines"][1].pop("box")                                                       # ... or no box key at all
        self.assertEqual(self.errs(p), [])
        p = plan()
        p["lines"][1]["box"] = [{"word": None}]
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual(p["lines"][1]["box"], [])
        self.assertEqual(self.errs(p), [])
        p = plan()                                                    # without the repair, validate stays strict
        p["lines"][0]["box"] = [{"word": "nowhere", "kind": "stock", "query": "chalkboard graph"}]
        self.assertIn("box word 'nowhere' is not spoken", " ".join(self.errs(p)))
        p["lines"][0]["box"] = []                                     # and the hook still needs box media
        self.assertIn("hook line needs clip-box media", " ".join(self.errs(p)))

    # attempt 2: the verse put in the box, quoted when it is only named
    def test_verse_in_the_box_becomes_the_verse_card(self):
        p = plan()
        p["lines"][2].pop("verse")
        p["lines"][2]["box"] = [{"word": "Revelation", "kind": "verse", "ref": "Revelation 21:4", "quoted": True}]
        notes = " | ".join(planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB))
        v = p["lines"][2]["verse"]
        self.assertEqual((v["ref"], v["word"], v["quoted"]), ("Revelation 21:4", "Revelation", False))
        self.assertEqual(p["lines"][2]["box"], [])
        self.assertIn("named, not quoted", notes)
        self.assertEqual(self.errs(p), [])

    def test_a_named_reference_without_a_verse_card_gets_one(self):
        p = plan()
        p["lines"][2].pop("verse")
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual(p["lines"][2]["verse"]["ref"], "Revelation 21:4")
        self.assertEqual(self.errs(p), [])

    def test_scripture_rules_are_not_weakened(self):
        p = plan()
        p["lines"][2]["verse"] = {"ref": "Revelation 99:4", "word": "Revelation", "quoted": False}
        self.assertIn("not a World English Bible reference", " ".join(self.errs(p)))
        p = plan()
        p["lines"][2].pop("verse")                                 # no repair: a named reference still needs a card
        self.assertIn("names Revelation 21:4", " ".join(self.errs(p)))
        p = plan()
        p["lines"][2]["verse"]["quoted"] = True                    # no repair: quoted without a quote is an error
        self.assertIn("marked quoted", " ".join(self.errs(p)))
        lines = LINES[:2] + ['He says, "He will wipe away every tear from their eyes." Revelation 21:4.']
        keys = [[planmod.key(w["word"]) for w in ws] for ws in words(lines)]
        p = plan()
        p["lines"][2]["verse"] = {"ref": "Revelation 21:4", "word": "Revelation", "quoted": True}
        p["lines"][2]["drawings"] = [{"word": "tear", "type": "rainbow", "fields": {"label": "PROMISE"}},
                                     {"word": "eyes", "type": "grave", "fields": {"label": "GRAVE"}}]
        p["lines"][2]["gesture"] = {"do": "look", "word": "tear"}
        planmod.repair(p, lines, keys, self.cat, FAKE_LIB)
        self.assertTrue(p["lines"][2]["verse"]["quoted"])          # a real word-for-word quote stays quoted
        self.assertEqual(planmod.validate(p, lines, keys, FAKE_LIB, self.cat), [])

    # attempt 2: a media file name used as a drawing type
    def test_unknown_drawing_becomes_a_verified_catalog_drawing_or_is_rejected(self):
        p = plan()
        p["lines"][2]["drawings"].append({"word": "mourning", "type": "sunlight_through_storm_clouds",
                                          "concept": "future hope", "fields": {"label": "HOPE"}})
        notes = " | ".join(planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB))
        new = p["lines"][2]["drawings"][-1]["type"]
        self.assertIn(new, planmod.director_types(self.cat))
        self.assertIn(new, planmod.shapes(self.cat))
        self.assertNotIn(new, ("rainbow", "grave"))                               # not one already on that line
        self.assertIn("a media file name, not a drawing", notes)
        self.assertEqual(self.errs(p), [])
        p = plan()                                                                # nothing close, other drawings
        p["lines"][1]["drawings"].append({"word": "evil", "type": "zzqx_unknown", "fields": {}})
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual([d["type"] for d in p["lines"][1]["drawings"]], ["storm", "question_big"])
        p = plan()                                                                # nothing close, nothing else
        p["lines"][1]["drawings"] = [{"word": "evil", "type": "zzqx_unknown", "fields": {}}]
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertIn("'zzqx_unknown' is not in the catalog", " ".join(self.errs(p)))   # rejected cleanly

    def test_meme_relevance_filter_still_applies(self):
        p = plan()
        p["lines"][1]["box"] = [{"word": "evil", "kind": "meme", "file": "meme_b.gif"}]   # no tags: unrelated
        notes = " | ".join(planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB))
        self.assertEqual(p["lines"][1]["box"], [])
        self.assertIn("nothing to do with the line", notes)

    def test_fixable_errors_spend_no_plan_call(self):
        """The three real failure kinds together: repaired in code, so the plan passes without asking the AI."""
        p = plan()
        p["lines"][0]["box"] = [{"kind": "stock", "query": "chalkboard graph"}]
        p["lines"][2].pop("verse")
        p["lines"][2]["box"] = [{"kind": "verse", "ref": "Revelation 21:4", "quoted": True}]
        p["lines"][2]["drawings"].append({"word": "mourning", "type": "sunlight_through_storm_clouds",
                                          "fields": {"label": "HOPE"}})
        self.assertNotEqual(self.errs(json.loads(json.dumps(p))), [])
        planmod.repair(p, LINES, self.keys, self.cat, FAKE_LIB)
        self.assertEqual(self.errs(p), [])


class Timeline(unittest.TestCase):
    def setUp(self):
        os.environ["KI_BOX_PLACEHOLDER"] = "1"
        os.environ.pop("PEXELS_API_KEY", None)
        self.cat = planmod.catalog()

    # attempt 1: drawings under the meme cards, reproduced with the run's own timings (words anonymized)
    def test_run_attempt1_compiles_without_any_collision(self):
        d = json.loads(FIXTURE.read_text())
        per_line, _, errs = media.resolve(d["plan"], FAKE_LIB, lambda m: None, d["lines"])
        self.assertEqual(errs, [])
        scene, _ = compiler.compile_scene(d["plan"], d["lines"], d["words"], self.cat, per_line,
                                          {"id": "t", "audio_path": "x", "sha256": "x", "align": 1})
        # the side-drawing refill makes way for the meme cards itself: the safety net has nothing left to fix
        # (before the fix it had to: "l2_question_big1 makes way for the meme card at 12.78s")
        self.assertEqual(scene["director"]["timeline_fixes"], [])
        self.assertEqual(sum(1 for b in scene["beats"] for e in b["events"] if "reaction" in e), 2)

    def _compile(self, p, lines=LINES, lib=FAKE_LIB):
        planmod.repair(p, lines, [[planmod.key(w["word"]) for w in ws] for ws in words(lines)], self.cat, lib)
        self.assertEqual(planmod.validate(p, lines, [[planmod.key(w["word"]) for w in ws] for ws in words(lines)], lib,
                                          self.cat), [])
        per_line, _, errs = media.resolve(p, lib, lambda m: None, lines)
        self.assertEqual(errs, [])
        return compiler.compile_scene(p, lines, words(lines), self.cat, per_line,
                                      {"id": "t", "audio_path": "x", "sha256": "x", "align": 1})[0]

    # attempt 3: the renderer dropped a meme card placed right after the word "God"
    def test_pop_never_lands_within_the_renderers_god_gap(self):
        p = plan()
        p["lines"][1]["pop"] = {"word": "is", "file": "meme_why.png"}               # 0.35 s after "God"
        lib = FAKE_LIB + [{"file": "meme_why.png", "path": "reactions/meme_why.png", "role": "meme", "group": "w",
                           "tags": ["why"]}]
        scene = self._compile(p, lib=lib)
        ws = words(LINES)[1]
        god = next(w["start"] for w in ws if w["word"] == "God")
        pops = [e for b in scene["beats"] for e in b["events"] if "reaction" in e]
        self.assertEqual(len(pops), 1)
        t = compiler._anchor_time(ws, pops[0]["at"])
        self.assertGreaterEqual(abs(t - god), 0.4)                                # effects.py's own rule
        self.assertTrue(any("moved off the word God" in n for n in scene["director"]["notes"]))
        self.assertEqual(scene["require_memes"], 1)

    def test_pops_closer_than_3_seconds_are_dropped_before_rendering(self):
        # 2 lines apart (the plan rule passes) but only ~1.9 s apart in time (the renderer's 3 s rule would drop it)
        lines = ["Hook words here for the start.", "One two three four five six seven eight nine ten.", "Okay.",
                 "Alpha beta gamma delta epsilon zeta eta theta."]
        dr = lambda w, t: {"word": w, "type": t, "fields": {"label": "X"}}
        p = {"freeze": {"line": 4, "word": "eta"}, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [{"word": "Hook", "kind": "stock", "query": "fishing hook water"}],
             "drawings": [dr("words", "question_big"), dr("start", "bar_chart")]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "pop": {"word": "ten", "file": "m1.png"}, "drawings": [dr("two", "bar_chart"), dr("three", "question_big")]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [], "drawings": [dr("Okay", "check_big")]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "pop": {"word": "Alpha", "file": "m2.png"}, "drawings": [dr("gamma", "storm"), dr("delta", "heart")]}]}
        lib = [{"file": f, "path": f"reactions/{f}", "role": "meme", "group": f, "tags": [t]}
               for f, t in (("m1.png", "ten"), ("m2.png", "alpha"))]
        scene = self._compile(p, lines, lib)
        pops = [compiler._anchor_time(words(lines)[k], e["at"]) for k, b in enumerate(scene["beats"])
                for e in b["events"] if "reaction" in e]
        self.assertEqual(len(pops), scene["require_memes"])                # the renderer must place every card asked
        self.assertEqual(len(pops), 1)
        self.assertTrue(any("line 4: pop-up dropped" in n for n in scene["director"]["notes"]))

    # attempt 2: the freeze on the hook line kept its drawings off screen until after it (an empty first frame)
    def test_hook_drawings_show_before_a_freeze_and_come_back_after_it(self):
        lines = ["One two three four five six seven eight nine ten eleven twelve.", LINES[1]]
        dr = lambda w, t: {"word": w, "type": t, "fields": {"label": "X"}}
        p = {"freeze": {"line": 1, "word": "four"}, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [{"word": "One", "kind": "stock", "query": "one number sign"}],
             "drawings": [dr("two", "bar_chart"), dr("three", "question_big")]},
            {"expression": "thinking", "gesture": {"do": "none"}, "box": [],
             "drawings": [dr("powerful", "storm"), dr("evil", "heart")]}]}
        scene = self._compile(p, lines)
        ev = scene["beats"][0]["events"]
        ws = words(lines)[0]
        draws = {e["id"]: compiler._anchor_time(ws, e["at"]) for e in ev if e.get("do") == "draw"}
        self.assertTrue(all(t <= 0.2 for t in draws.values()), draws)            # the hook frame is full at once
        fz = next(compiler._anchor_time(ws, e["at"]) for e in ev if e.get("do") == "freeze")
        back = {i for e in ev if e.get("do") == "fade" and e.get("opacity") == 1 for i in e["ids"]}
        self.assertEqual(back, set(draws))                                         # cleared for the zoom, then back
        self.assertTrue(all(compiler._anchor_time(ws, e["at"]) > fz for e in ev if e.get("do") == "fade" and e.get("opacity") == 1))
        self.assertEqual(scene["director"]["timeline_fixes"], [])

    def test_meme_card_lines_keep_their_drawings_in_the_band(self):
        """Run 40434188836 attempt 1, 12.8 s: a full-height side drawing had to clear for the card and left the
        upper side empty (56% coverage). On a card line the drawings go in the band when it holds two of them."""
        d = json.loads(FIXTURE.read_text())
        per_line, _, _ = media.resolve(d["plan"], FAKE_LIB, lambda m: None, d["lines"])
        measured = d["measured"]                     # the drawings' real sizes, measured in Chrome during the run
        scene, _ = compiler.compile_scene(d["plan"], d["lines"], d["words"], self.cat, per_line,
                                          {"id": "t", "audio_path": "x", "sha256": "x", "align": 1},
                                          measure=lambda specs: {k: measured[k] for k in (s["id"] for s in specs) if k in measured})
        self.assertEqual(scene["director"]["timeline_fixes"], [])
        band_bottom = self.cat["zones"]["draw"]["y1"]
        for b in scene["beats"]:
            if not any("reaction" in e for e in b["events"]):
                continue
            in_band, beside = 0, []
            for e in b["events"]:
                if e.get("do") == "draw":
                    m = next(v for k, v in measured.items() if k.rstrip("0123456789") == e["id"].rstrip("0123456789"))
                    if e["y"] + (m["center"][1] + m["size"][1] / 2) * e["scale"] <= band_bottom + 2:
                        in_band += 1
                    else:
                        beside.append(e["id"])
            self.assertGreaterEqual(in_band, 2, b["id"])                                  # the band holds two
            # a drawing beside him either comes after the card or makes way for it: nothing is under the card
            # (timeline_fixes == [] above: the pre-render check found nothing to fix)

    def test_conflicts_are_found_like_the_audit_finds_them(self):
        card = ((300, 1100, 700, 1400), 10.0, 11.2)
        tl = {"draw": {"a": ((420, 1000, 600, 1300), 9.0), "b": ((100, 700, 400, 1000), 5.0),
                       "c": ((120, 720, 380, 1020), 8.0)},
              "fade": [(20.0, ["b"], 0)], "cards": [card]}
        found = compiler.conflicts(tl)
        self.assertIn("DRAWING a UNDER MEME at 10.00-11.20s", found)
        self.assertTrue(any(f.startswith("b overlaps c at 8.00-") for f in found))
        tl["fade"] += [(9.8, ["a"], 0), (11.2, ["a"], 1), (7.95, ["b"], 0)]
        self.assertEqual(compiler.conflicts(tl), [])

    def test_resolver_fixes_in_code_and_rejects_what_it_cannot(self):
        ws = [[{"word": "w", "start": 0.0, "end": 0.3}, {"word": "x", "start": 9.0, "end": 9.3}]]
        beats = [{"events": [{"at": "w#1+0.00", "do": "draw", "id": "a"}, {"at": "w#1+0.00", "do": "draw", "id": "b"},
                             {"at": "w#1+0.00", "do": "draw", "id": "c"}]}]
        tl = {"draw": {"a": ((420, 1000, 600, 1300), 9.0),                # shown before the card, under it
                       "d": ((420, 1000, 600, 1300), 10.1),               # would appear under the card
                       "b": ((100, 700, 400, 1000), 5.0), "c": ((120, 720, 380, 1020), 8.0)},   # b under c
              "fade": [(12.5, ["a"], 0)], "cards": [((300, 1100, 700, 1400), 10.0, 11.2)]}
        beats[0]["events"].append({"at": "x#1+1.10", "do": "draw", "id": "d"})
        notes, left = compiler.resolve_conflicts(tl, beats, ws)
        self.assertEqual(left, [])
        self.assertEqual(compiler.conflicts(tl), [])
        self.assertTrue(any("a makes way for the meme card" in n for n in notes))
        self.assertTrue(any("d now appears after the meme card" in n for n in notes))
        self.assertTrue(any("b cleared" in n for n in notes))
        tl2 = {"draw": {"e": ((0, 0, 100, 100), 3.0), "f": ((50, 50, 150, 150), 3.0)}, "fade": [], "cards": []}
        _, left = compiler.resolve_conflicts(tl2, [{"events": []}], ws)   # same moment: no order to fix it by
        self.assertTrue(left and "e overlaps f" in left[0])


if __name__ == "__main__":
    unittest.main()

"""The director's general editing rules, on several unrelated topics (offline fixtures: metadata only, no network, no
AI call, no private media). Epicurean Paradox is one case among them, never a special case.

Covered (the owner's regression list, 2026-10-27):
  1 no frame without media            5 large overlays cover the guide without collisions
  2 the frame adapts to the media      6 the guide returns after the overlay
  3 irrelevant text footage rejected   7 alignment uses the approved (updated) recording
  4 diagrams selected by meaning       8 a failed or missing review blocks acceptance (test_direct_budget.Acceptance)
plus: whole diagram (never cropped / stretched), region focus only where the asset allows it and the narration names
the region, three unrelated topics, readability reported (not "fixed" by cropping).
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from kindled_iron.director import diagram, media, story
from kindled_iron.render import SAFE

ROOT = Path(__file__).resolve().parents[2]
FIX = json.loads((Path(__file__).parent / "fixtures" / "diagrams.json").read_text())
LIB = FIX["library"]


def timed(script: str, per_word: float = 0.35, gap: float = 0.5):
    """Script paragraphs -> (lines, aligned words) on an even clock (offline stand-in for the aligner)."""
    lines, out, t = [p for p in script.split("\n\n")], [], 0.0
    for line in lines:
        ws = []
        for w in line.split():
            ws.append({"word": w, "start": round(t, 3), "end": round(t + per_word - 0.05, 3)})
            t += per_word
        out.append(ws)
        t += gap
    return lines, out


def pick(name: str):
    lines, words = timed(FIX["scripts"][name])
    return diagram.select(story.analyze(lines, words)["sentences"], LIB), lines, words


class Story(unittest.TestCase):
    def test_sentences_follow_the_narration_clock(self):
        lines, words = timed(FIX["scripts"]["water"])
        ss = story.sentences(lines, words)
        self.assertEqual(ss[0]["text"], "Ever wonder where rain actually comes from?")
        self.assertTrue(all(a["t1"] <= b["t0"] for a, b in zip(ss, ss[1:])))
        self.assertIn("question", story.intent(ss[0]["text"]))
        self.assertIn("refers_visual", story.intent("Look at this diagram."))
        self.assertIn("attention", story.intent("Look at this diagram."))
        self.assertNotIn("refers_visual", story.intent("A graph of my feelings would be a mess"))  # no determiner: not pointing
        self.assertIn("quote", story.intent("Revelation 21:4 describes a future without death."))


class DiagramSelection(unittest.TestCase):
    """4: diagrams are selected by what the narration does and says, on unrelated topics."""

    def test_four_topics_get_their_own_diagram_and_unrelated_narration_none(self):
        expect = {"epicurean": "epicurean_paradox_problem_of_evil_flowchart.png", "water": "water_cycle_diagram.png",
                  "roman": "roman_roads_map.jpg", "cpr": "cpr_steps_chart.png"}
        for name, f in expect.items():
            dg, _, _ = pick(name)
            self.assertIsNotNone(dg, name)
            self.assertEqual(dg["file"], f, name)
            self.assertGreaterEqual(len(dg["sentences"]), diagram.MIN_SUPPORT)
            self.assertTrue(dg["why"])
        self.assertIsNone(pick("unrelated")[0])

    def test_a_keyword_alone_does_not_select_a_diagram(self):
        # names the topic's words but never introduces a visual nor explains it over several sentences
        lines, words = timed("Evil is real. My dog ate my homework.\n\nThe weather was nice on Tuesday.")
        self.assertIsNone(diagram.select(story.analyze(lines, words)["sentences"], LIB))
        # a meme is never a diagram, whatever its words
        self.assertFalse(diagram.is_diagram(LIB[-1]))

    def test_the_window_follows_the_narration_and_ends_when_it_moves_on(self):
        dg, lines, words = pick("epicurean")
        self.assertEqual(dg["t0"], 0.0)                         # it is introduced by the first sentence
        last = dg["sentences"][-1]["sentence"]
        self.assertEqual(last, "Free will.")                    # ends where the narration stops walking through it
        self.assertLessEqual(dg["t1"] - dg["t0"], diagram.MAX_SECONDS)
        ss = story.sentences(lines, words)
        k = next(i for i, s in enumerate(ss) if s["text"] == last)
        self.assertEqual(ss[k + 1]["text"], "Think about it.")  # the next sentence is not about the diagram ...
        self.assertLessEqual(dg["t1"], ss[k + 1]["t0"] + 0.15)  # ... and the diagram is gone as it starts

    def test_a_quote_ends_the_diagram(self):
        lines, words = timed("Look at this diagram. The sun heats the ocean and water evaporates into vapor. The vapor "
                             "condenses into clouds and falls as rain. Genesis 2:6 says a mist went up from the earth.")
        dg = diagram.select(story.analyze(lines, words)["sentences"], LIB)
        self.assertNotIn("Genesis", " ".join(s["sentence"] for s in dg["sentences"]))


class WholeDiagram(unittest.TestCase):
    """The owner's rule: the complete image, uniformly scaled into the safe area; no crop, split or stretch."""

    def test_uniform_scale_inside_the_safe_area_for_every_shape(self):
        for item in LIB[:4]:
            f = diagram.fit(item["size"], SAFE)
            x, y, w, h = f["rect"]
            w0, h0 = item["size"]
            s = min((660) / w0, (1280 - diagram.CAPTION_BAND) / h0) if h0 > w0 else None
            self.assertAlmostEqual(w / h, w0 / h0, delta=0.01, msg=item["file"])            # never stretched
            self.assertAlmostEqual(w, w0 * f["scale"], delta=1)
            self.assertAlmostEqual(h, h0 * f["scale"], delta=1)
            self.assertGreaterEqual(x, SAFE["x0"]); self.assertGreaterEqual(y, SAFE["y0"])
            self.assertLessEqual(x + w, SAFE["x1"]); self.assertLessEqual(y + h, SAFE["y1"])
            if y + h > SAFE["column"]["y0"]:
                self.assertLessEqual(x + w, SAFE["column"]["x0"])                             # clear of the buttons
            c = f["caption"]
            self.assertGreaterEqual(c["y"], y + h)                                              # captions under it
            self.assertLessEqual(c["x"] + c["w"] / 2, SAFE["column"]["x0"])
            self.assertLessEqual(c["y"] + 112, SAFE["y1"])
            if s:
                self.assertAlmostEqual(f["scale"], s, delta=0.002)                              # the owner's formula

    def test_the_flowchart_is_shown_whole_its_regions_are_metadata_only(self):
        dg, _, _ = pick("epicurean")
        self.assertEqual([v["view"] for v in dg["views"]], ["whole"])        # region_rendering: false

    def test_region_focus_only_when_allowed_and_named(self):
        dg, _, words = pick("water")                                         # region_rendering: true
        views = dg["views"]
        self.assertEqual(views[0]["view"], "whole")
        self.assertGreaterEqual(views[1]["t"] - views[0]["t"], diagram.MIN_WHOLE - 0.1)   # whole first
        regions = [v["region"] for v in views if v["view"] == "region"]
        self.assertIn("condensation", regions)
        self.assertIn("precipitation", regions)
        flat = {w["start"]: w["word"] for ws in words for w in ws}
        for v in views[1:]:
            if v["view"] == "region":                                        # on the spoken word, not the sentence
                said = flat[min(flat, key=lambda t: abs(t - (v["t"] + 0.1)))]
                self.assertTrue(any(story.phrase_in(k, said) for k in LIB[1]["regions"][v["region"]]["keywords"]), said)
        roman, _, _ = pick("roman")                                          # a map without regions: whole only
        self.assertEqual([v["view"] for v in roman["views"]], ["whole"])

    def test_readability_is_reported_not_fixed_by_cropping(self):
        f = diagram.fit(LIB[0]["size"], SAFE)
        r = diagram.readability(LIB[0], f["scale"])
        self.assertFalse(r["ok"])
        self.assertIn("shown whole anyway", r["note"])
        self.assertIsNone(diagram.readability({"size": [10, 10]}, 1.0)["ok"])       # unknown: said so


class Footage(unittest.TestCase):
    """3: footage must show what the LINE says; a related-looking title is not enough."""

    def setUp(self):
        from kindled_iron import insets
        self.insets = insets
        self.real = insets._pexels, insets._pixabay
        self.ph = os.environ.pop("KI_BOX_PLACEHOLDER", None)

    def tearDown(self):
        self.insets._pexels, self.insets._pixabay = self.real
        if self.ph is not None:
            os.environ["KI_BOX_PLACEHOLDER"] = self.ph

    def results(self, *cands):
        self.insets._pexels = lambda q, pin: [{"source": "pexels", "id": str(i), "title": t, "page": ""} for i, t in enumerate(cands)]
        self.insets._pixabay = lambda q, pin: []

    def test_back_to_school_chalkboard_is_rejected_for_a_line_about_a_graph(self):
        self.results("back to school chalkboard with writing in a classroom")
        rej = []
        self.assertIsNone(media.stock("chalkboard diagram classroom", [], {}, print, "I'm sure y'all have seen this graph before.", rej))
        self.assertIn("visible text", rej[0]["why"])

    def test_related_title_with_unrelated_subject_is_rejected(self):
        self.results("viewing graphs on a monitor", "worried woman looking at pregnancy test")
        rej = []
        self.assertIsNone(media.stock("epicurean paradox graph", [], {}, print, "according to this graph, the God of the Bible", rej))
        self.assertIsNone(media.query_fits_line("person looking troubled", "So why does evil exist?"))
        self.assertIsNotNone(media.query_fits_line("earthquake rubble street", "Earthquakes, diseases, innocent children dying?"))

    def test_three_topics_keep_footage_that_shows_them(self):
        cases = [("volcano lava eruption", "The volcano erupted and lava ran into the sea.", "lava flowing from an erupting volcano"),
                 ("roman road stones", "Roman roads were paved with fitted stones.", "ancient roman road stones in italy"),
                 ("chest compressions training", "Push hard and fast on the center of the chest.", "chest compressions on a training dummy")]
        for q, line, title in cases:
            self.results(title)
            self.assertIsNotNone(media.query_fits_line(q, line), q)
            hit = media.stock(q, [], {}, print, line)
            self.assertIsNotNone(hit, q)
            self.assertIn("verified", hit)

    def test_no_result_means_no_frame_not_an_error(self):
        self.results("puppy on a beach")
        plan = {"lines": [{"box": [{"word": "Earthquakes,", "kind": "stock", "query": "earthquake rubble street"}]}]}
        per_line, records, errs = media.resolve(plan, [], lambda m: None, ["Earthquakes, diseases, innocent children dying?"])
        self.assertEqual((per_line, errs), ([[]], []))
        self.assertIn("left out", records[0]["result"])
        self.assertTrue(records[0]["rejected"])


class Frames(unittest.TestCase):
    """1 + 2: the box only while it holds media, shaped like that media."""

    def test_frame_takes_the_media_shape(self):
        from kindled_iron.mediabox import frame_size
        for aspect, want in ((16 / 9, (674, 380)), (1.0, (380, 380)), (9 / 16, (212, 380)), (4.0, (820, 204))):
            w, h = frame_size(aspect, 820, 380)
            self.assertEqual((w, h), want)
            self.assertLessEqual(abs(w / h - aspect) / aspect, 0.02)

    def test_no_media_no_frame(self):
        from kindled_iron import mediabox
        scene = {"mediabox": {"x": 540, "y": 370, "w": 820, "h": 380}, "clips": {"c": {"pexels": "1"}},
                 "beats": [{"events": []}, {"events": [{"at": 0.0, "box": "clip", "clip": "c"}, {"at": 0.5, "box": "off"}]},
                           {"events": []}]}
        at = lambda a, ws, s, e, u, p: s + (a or 0)
        segs = mediabox.plan(scene, [(0, 2), (2, 4), (4, 6)], [[], [], []], [], 6.0, at, lambda m: None)
        self.assertEqual([(s["kind"], s["t0"], s["t1"]) for s in segs], [("clip", 2.0, 2.5)])   # nothing before, nothing after
        js = (ROOT / "kindled_iron" / "runtime" / "runtime.js").read_text()
        self.assertIn("MB.el.setAttribute('visibility', sg ? 'visible' : 'hidden')", js)
        self.assertRegex(js, r"kiRects = function \(\) \{[^\n]*\n\s*var box = MB && MB\.el\.getAttribute\('visibility'\) !== 'hidden'")
        self.assertIn("o.bare ? ''", js)                                 # a diagram has no frame drawn around it


class OverlayAndGuide(unittest.TestCase):
    """5 + 6: the whole diagram covers the guide only while it is up; nothing else is drawn under it; he comes back."""

    @classmethod
    def setUpClass(cls):
        from kindled_iron.director import compile as C, plan as P
        cls.C, cls.cat = C, P.catalog()
        dg, lines, words = pick("epicurean")
        dg["fit"] = diagram.fit(dg["size"], SAFE)
        dg["path"] = "movie_reference/" + dg["file"]
        cls.dg, cls.lines, cls.words = dg, lines, words
        mk = lambda i, a, b: [{"word": a, "type": "question_big", "fields": {"label": "WHY?"}},
                              {"word": b, "type": "heart", "fields": {"label": "LOVE"}}]
        cls.plan = {"freeze": {"line": 4, "word": "choosing"}, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [], "drawings": mk(0, "graph", "argument.")},
            {"expression": "thinking", "gesture": {"do": "none"}, "box": [], "drawings": mk(1, "evil.", "good,")},
            {"expression": "thinking", "gesture": {"do": "none"}, "box": [], "drawings": mk(2, "decision", "choice?")},
            {"expression": "surprised", "gesture": {"do": "none"}, "box": [], "drawings": mk(3, "lie,", "good")}]}
        cls.scene, cls.frames = C.compile_scene(json.loads(json.dumps(cls.plan)), lines, words, cls.cat, [[], [], [], []],
                                                {"id": "t", "audio_path": "a", "sha256": "x"}, diagram=dg)

    def events(self):
        out = []
        for b, beat in enumerate(self.scene["beats"]):
            for e in beat["events"]:
                at = e.get("at")
                t = at if isinstance(at, (int, float)) else self.C._anchor_time(self.words[b], at)
                out.append((t, e))
        return out

    def test_diagram_segment_and_its_end(self):
        box = [(t, e) for t, e in self.events() if "box" in e]
        self.assertEqual(box[0][1]["box"], "diagram")
        self.assertEqual(box[0][1]["rect"], self.dg["fit"]["rect"])
        offs = [t for t, e in box if e["box"] == "off"]
        self.assertTrue(any(abs(t - self.dg["t1"]) < 0.05 for t in offs))

    def test_nothing_drawn_under_it_and_the_guide_steps_out_and_back(self):
        t0, t1 = self.dg["t0"], self.dg["t1"]
        for t, e in self.events():
            if e.get("do") == "draw":
                self.assertGreaterEqual(t, t1, f"{e['id']} would be drawn under the diagram")
            if e.get("do") in ("walk", "point", "shrug", "freeze"):
                self.assertFalse(t0 <= t < t1, f"{e['do']} while the guide is stepped out")
        place = next(e for t, e in self.events() if e.get("do") == "place")
        self.assertTrue(place.get("hidden"))                                 # it opens the video: he starts out of view
        back = [t for t, e in self.events() if e.get("do") == "appear"]
        self.assertEqual(len(back), 1)
        self.assertAlmostEqual(back[0], t1, delta=0.05)                      # and is back the moment it goes
        self.assertEqual(self.scene["caption_windows"][0]["t0"], t0)         # captions under it while it is up

    def test_timeline_check_sees_the_diagram_as_an_obstacle(self):
        x, y, w, h = self.dg["fit"]["rect"]
        tl = {"draw": {"d1": ((200, 800, 500, 1000), self.dg["t0"] + 1)}, "fade": [],
              "cards": [((x, y, x + w, y + h), self.dg["t0"], self.dg["t1"])]}
        self.assertTrue(self.C.conflicts(tl))

    def test_the_layout_returns_after_it(self):
        later = [e for t, e in self.events() if e.get("do") == "draw" and t >= self.dg["t1"]]
        self.assertTrue(later)                                               # drawings again once it is gone
        info = self.scene["director"]["diagram"]
        self.assertTrue(info["guide_hidden"])
        self.assertEqual(info["file"], self.dg["file"])


class NoSpecialCases(unittest.TestCase):
    def test_no_video_id_or_script_phrase_in_the_director(self):
        bad = re.compile(r"epicurean|paradox|seen this graph|problem.of.evil|video_id ?==", re.I)
        for f in (ROOT / "kindled_iron" / "director").glob("*.py"):
            self.assertIsNone(bad.search(f.read_text(encoding="utf-8")), f.name)


class ApprovedRecording(unittest.TestCase):
    """7: the director aligns against the approved recording as it is now; a checkpoint made from an older
    recording is not resumed."""

    def test_checkpoint_of_an_older_recording_is_dropped(self):
        from kindled_iron.director import direct
        d = Path(tempfile.mkdtemp())
        (d / "previews" / "v").mkdir(parents=True)
        (d / "previews" / "v" / "checkpoint.json").write_text(json.dumps({"sha256": "old", "words": [[]], "plan_calls": 2}))
        (d / "previews" / "v" / "status.json").write_text(json.dumps({"state": "waiting_quota"}))
        self.assertEqual(direct.load_checkpoint(d, "v", "new"), {})
        self.assertEqual(direct.load_checkpoint(d, "v", "old").get("plan_calls"), 2)

    def test_the_updated_recording_when_the_private_repo_is_here(self):
        root = os.environ.get("KI_PRIVATE_ROOT") or os.environ.get("KI_PRIVATE_MEDIA")
        mp3 = Path(root or "/nonexistent") / "approved_audio" / "epicurean-paradox" / "narration.mp3"
        if not mp3.exists():
            self.skipTest("private repo not checked out (CI sets KI_PRIVATE_ROOT)")
        import hashlib
        self.assertEqual(hashlib.sha256(mp3.read_bytes()).hexdigest(),
                         "22599b368af08c5532605c390b2c1ec4ecac1eac0eeaad2711e7a1678e66a1c0")


if __name__ == "__main__":
    unittest.main()

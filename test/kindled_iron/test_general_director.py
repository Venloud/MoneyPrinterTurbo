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
            self.assertGreaterEqual(dg["support"], diagram.MIN_SUPPORT)      # chosen because the narration explains it
            self.assertLessEqual(dg["t1"], dg["topic_until"] + diagram.HOLD + 0.01)
            self.assertTrue(dg["why"])
        self.assertIsNone(pick("unrelated")[0])

    def test_a_keyword_alone_does_not_select_a_diagram(self):
        # names the topic's words but never introduces a visual nor explains it over several sentences
        lines, words = timed("Evil is real. My dog ate my homework.\n\nThe weather was nice on Tuesday.")
        self.assertIsNone(diagram.select(story.analyze(lines, words)["sentences"], LIB))
        # a meme is never a diagram, whatever its words
        self.assertFalse(diagram.is_diagram(LIB[-1]))

    def test_it_stays_while_the_narration_looks_at_it_not_while_it_discusses_the_subject(self):
        """Owner, 2026-10-27: the flowchart stayed 25 s while the narration walked through the argument; about 5 s was
        right there. The whole picture stays through the last clause that points at it, then leaves in the pause."""
        dg, lines, words = pick("epicurean")
        self.assertEqual(dg["t0"], 0.0)
        ss = story.sentences(lines, words)
        covered = [s_ for s_ in ss if s_["t0"] < dg["t1"]]                  # (a later "this graph leaves out", far
        cl = [c for s_ in covered for c in diagram.clauses(s_) if "refers_visual" in story.intent(c["text"])][-1]   # on, does not hold it)
        self.assertGreaterEqual(dg["t1"], cl["t1"])                          # through "according to this graph,"
        nxt = next(w["start"] for s_ in ss for w in s_["words"] if w["start"] > cl["t1"])
        self.assertLessEqual(dg["t1"], nxt + 0.05)                          # gone in the pause after it
        self.assertGreaterEqual(dg["t1"] - dg["t0"], diagram.MIN_VIEW)
        self.assertGreater(dg["topic_until"], dg["t1"] + 10)                # the argument goes on: drawings show it

    def test_a_chart_the_narration_keeps_pointing_at_stays_longer(self):
        """Unseen script: a narrator walking the viewer through a chart keeps it up as long as they point at it."""
        lines, words = timed("Look at this diagram of the water cycle. In this diagram the sun heats the ocean and water "
                             "evaporates into vapor. This diagram then shows the vapor cooling into clouds. The clouds "
                             "fall as rain. Rivers carry it back to the sea.\n\nSo the water in your glass is old.")
        dg = diagram.select(story.analyze(lines, words)["sentences"], LIB)
        ss = story.sentences(lines, words)
        third = next(s_ for s_ in ss if s_["text"].startswith("This diagram then"))
        self.assertGreaterEqual(dg["t1"], third["t1"])                      # through the third reference ...
        so = next(s_ for s_ in ss if s_["text"].startswith("So the water"))   # (a region asset also follows the
        self.assertLess(dg["t1"], so["t0"])                                 # regions it names) not into the conclusion

    def test_one_quick_reference_still_gets_time_to_be_seen(self):
        lines, words = timed("This map shows it. Rome built roads to Brindisi. Roads crossed Gaul, Hispania and Britain. "
                             "Milestones marked every Roman mile along the trade routes.", per_word=0.3)
        dg = diagram.select(story.analyze(lines, words)["sentences"], LIB)
        self.assertIsNotNone(dg)
        self.assertGreaterEqual(dg["t1"] - dg["t0"], diagram.MIN_VIEW)     # a 1.2 s mention: seen at least MIN_VIEW

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


class CrossTopic(unittest.TestCase):
    """The same compiler on unrelated topics (philosophy, science, history, instruction, entertainment): a
    deterministic stand-in plan (catalog drawings picked by tag, 1-2 per line, never forced to 3; library media on some
    lines) -> compile. No AI call, no render (the renderer needs a real recording; Epicurean Paradox is rendered)."""

    @classmethod
    def setUpClass(cls):
        from kindled_iron.director import compile as C, plan as P
        cls.C, cls.P, cls.cat = C, P, P.catalog()
        cls.types = {n: o for n, o in P.director_types(cls.cat).items() if o.get("doodle")}

    def stand_in_plan(self, lines, words, media_lines):
        P = self.P
        plan = {"freeze": None, "lines": []}
        for i, (line, ws) in enumerate(zip(lines, words)):
            said = {P.key(w["word"]): w["word"] for w in ws}
            picks = []
            for n, o in self.types.items():
                hit = next((said[k] for k in said if k and any(P.key(t) == k for t in o["tags"])), None)
                if hit and n not in [p_["type"] for p_ in picks]:
                    picks.append({"word": hit, "type": n, "fields": {}})
                if len(picks) == 2:
                    break
            if not picks:
                picks = [{"word": ws[0]["word"], "type": "question_big", "fields": {"label": "WHY?"}}]
            plan["lines"].append({"expression": "curious", "gesture": {"do": "none"}, "box": [], "drawings": picks})
        media = [[{"kind": "meme", "file": "x.png", "path": "movie_reference/x.png", "word": words[i][min(3, len(words[i]) - 1)]["word"]}]
                 if i in media_lines else [] for i in range(len(lines))]
        return plan, media

    def compile(self, name, media_lines=()):
        lines, words = timed(FIX["scripts"][name])
        dg = diagram.select(story.analyze(lines, words)["sentences"], LIB)
        if dg:
            dg["fit"] = diagram.fit(dg["size"], SAFE)
            dg["path"] = "movie_reference/" + dg["file"]
        plan, media = self.stand_in_plan(lines, words, set(media_lines))
        scene, frames = self.C.compile_scene(plan, lines, words, self.cat, media, {"id": name, "audio_path": "a", "sha256": "x"},
                                             diagram=dg)
        return scene, words, dg, plan

    def check(self, scene, words, dg, plan):
        C = self.C
        draws, boxes, ev = [], [], []
        for b, beat in enumerate(scene["beats"]):
            for e in beat["events"]:
                at = e.get("at")
                t = at if isinstance(at, (int, float)) else C._anchor_time(words[b], at)
                ev.append((t, b, e))
        for t, b, e in ev:
            if e.get("do") == "draw":
                draws.append((t, b, e))
                self.assertGreaterEqual(e["x"], SAFE["x0"] - 400)          # (x, y is the drawing's anchor; slots are checked below)
        # every drawing slot inside the safe area, right of nothing: compile records the boxes it checked
        n_planned = sum(len(L["drawings"]) for L in plan["lines"])
        self.assertLessEqual(len(draws), n_planned)                         # never more drawings than asked for
        box_on = [t for t, b, e in ev if e.get("box") in ("media", "clip", "verse")]
        box_off = [t for t, b, e in ev if e.get("box") == "off"]
        self.assertEqual(len(box_off), len(box_on) + (1 if dg else 0))     # every box (and the diagram) also goes
        for w in scene["caption_windows"]:
            if dg and w["t0"] == dg["t0"]:
                continue
            for t in box_on:                                                # never a top caption over a box
                self.assertFalse(w["t0"] < t < w["t1"] - 0.01, (w, t))
        if dg:                                                              # nothing drawn where the diagram (or
            x_, y_, w_, h_ = dg["fit"]["rect"]                              # its caption band) is while it is up;
            cp = dg["fit"]["caption"]                                       # beside the guide, clear of it, is fine
            obst = [(x_, y_, x_ + w_, y_ + h_), (cp["x"] - cp["w"] / 2, cp["y"] - 6, cp["x"] + cp["w"] / 2, cp["y"] + 112)]
            types = self.P.director_types(self.cat)
            for t, b, e in draws:
                o = types[e.get("doodle") or e.get("type")] if (e.get("doodle") or e.get("type")) in types else \
                    next(v for k, v in types.items() if e["id"].split("_", 1)[1].startswith(k))
                (w, h), (cx, cy), s_ = o["size"], o.get("center", [0, 0]), e["scale"]
                r = (e["x"] + (cx - w / 2) * s_, e["y"] + (cy - h / 2) * s_, e["x"] + (cx + w / 2) * s_, e["y"] + (cy + h / 2) * s_)
                hit = any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in obst)
                self.assertFalse(dg["t0"] <= t < dg["t1"] and hit, f"{e['id']} under the diagram")
        return draws

    def test_philosophy_science_history_instruction_entertainment(self):
        for name, media_lines in (("epicurean", (2,)), ("water", (1,)), ("roman", ()), ("cpr", (0,)), ("animation", (1,))):
            with self.subTest(topic=name):
                scene, words, dg, plan = self.compile(name, media_lines)
                draws = self.check(scene, words, dg, plan)
                self.assertTrue(draws or dg, name)
                self.assertEqual(bool(dg), name != "animation")             # the cartoon script introduces no diagram
                self.assertEqual(scene["director"]["timeline_fixes"] is not None, True)

    def test_a_line_may_have_one_drawing_or_none(self):
        lines, words = timed(FIX["scripts"]["animation"])
        plan, media = self.stand_in_plan(lines, words, {1})
        plan["lines"][0]["drawings"] = plan["lines"][0]["drawings"][:1]
        plan["lines"][1]["drawings"] = []                                   # its media is its visual
        plan["lines"][1]["box"] = [{"word": media[1][0]["word"], "kind": "meme", "file": "x.png"}]
        scene, _ = self.C.compile_scene(plan, lines, words, self.cat, media, {"id": "a", "audio_path": "a", "sha256": "x"})
        per = [sum(1 for e in b["events"] if e.get("do") == "draw") for b in scene["beats"]]
        self.assertEqual(per[0], 1)
        self.assertEqual(per[1], 0)
        self.assertTrue(any(e.get("box") == "media" for e in scene["beats"][1]["events"]))
        self.assertEqual(self.P.validate(plan, lines, [[self.P.key(w["word"]) for w in ws] for ws in words], [], self.cat)
                         and [x for x in self.P.validate(plan, lines, [[self.P.key(w["word"]) for w in ws] for ws in words], [], self.cat)
                              if "nothing on screen" in x], [])

    def test_grave_lines_get_no_joke_meme(self):
        self.assertTrue(self.P.grave("Innocent children dying? Free will doesn't explain those things."))
        lib = [{"file": "shrug.png", "path": "reactions/shrug.png", "role": "meme", "group": "s", "tags": ["shrug", "awkward", "wrestle"]}]
        lines = ["Why does He allow innocent people to suffer? That's a question we still wrestle with."]
        plan = {"lines": [{"expression": "sad", "box": [], "drawings": [], "pop": {"word": "wrestle", "file": "shrug.png"}}]}
        notes = self.P._repair_media(plan, lines, lib)
        self.assertIsNone(plan["lines"][0]["pop"])
        self.assertIn("grave line", " ".join(notes))


class ProposedComposition(unittest.TestCase):
    """The proposed replacement for the 60 % coverage floor (report-only until the owner approves it)."""

    def test_drawing_led_frames_pass_unfinished_frames_fail(self):
        from kindled_iron.director import gates
        cap_top, guide = [380, 180, 700, 300], [439, 1068, 642, 1567]
        liked = [cap_top, [130, 330, 420, 690], [450, 330, 770, 690], [125, 1045, 410, 1432], guide]   # two drawings + one beside him
        self.assertEqual(gates.composition(liked, SAFE, 0.22), (True, []))
        only_guide = [guide]
        ok, why = gates.composition(only_guide, SAFE, 0.55)
        self.assertFalse(ok)
        self.assertIn("nothing in the top third", why)
        empty_middle = [cap_top, guide]
        self.assertFalse(gates.composition(empty_middle, SAFE, 0.36)[0])

    def test_report_only_never_decides_acceptance(self):
        from kindled_iron.director import gates
        src = (ROOT / "kindled_iron" / "director" / "gates.py").read_text()
        self.assertIn('res["_proposed_composition"]', src)               # stored under a "_" key ...
        self.assertIn('all(v["ok"] for k, v in res.items() if not k.startswith("_"))', src)   # ... which _passed skips
        self.assertEqual((gates.MIN_COVER, gates.MAX_EMPTY), (0.60, 0.20))   # the existing gate is unchanged


class HiddenBox(unittest.TestCase):
    def test_a_hidden_box_paints_nothing_and_the_audit_checks_it(self):
        """The full render of the drawing-first build showed the Revelation 21:4 text after its card had gone: SVG
        children with their own visibility="visible" ignore a hidden parent. The box is now display:none when it
        is gone, and the per-frame audit fails any box content still painted without its box."""
        js = (ROOT / "kindled_iron" / "runtime" / "runtime.js").read_text()
        self.assertIn("MB.el.style.display = sg ? '' : 'none';", js)
        self.assertIn("BOX CONTENT SHOWN WITHOUT ITS BOX", js)


class Themes(unittest.TestCase):
    """A theme swaps colours and paper only; the default (Kindled Iron) look is untouched."""

    def test_default_is_unchanged_and_unknown_fails(self):
        from kindled_iron import themes
        pal, look = {"board": "#F7F3E9", "ink": "#222"}, {"colors": {"skin": "#8D5A3B"}}
        self.assertIsNone(themes.apply(None, pal, look))
        self.assertIsNone(themes.apply("kindled", pal, look))
        self.assertEqual((pal, look), ({"board": "#F7F3E9", "ink": "#222"}, {"colors": {"skin": "#8D5A3B"}}))
        with self.assertRaises(SystemExit):
            themes.apply("neon", pal, look)

    def test_blueprint_is_white_line_on_blue_grid(self):
        from kindled_iron import themes
        from kindled_iron.render import PALETTE, HOST_LOOK
        pal, look = dict(PALETTE), json.loads(json.dumps(HOST_LOOK))
        t = themes.apply("blueprint", pal, look)
        self.assertEqual((pal["board"], pal["ink"]), (themes.BOARD, themes.WHITE))
        self.assertTrue(all(pal[k] == themes.PANEL for k in ("skin", "robe", "page", "cloud", "water")))   # no colour fills
        self.assertTrue(set(look["colors"].values()) == {themes.PANEL})
        self.assertEqual(t["grid"], {"minor": 40, "major": 200})
        self.assertNotEqual(PALETTE["board"], themes.BOARD)                  # the module palette itself is not touched here

    def test_renderer_applies_the_scene_theme_and_survives_no_box(self):
        src = (ROOT / "kindled_iron" / "render.py").read_text()
        self.assertIn('themes.apply(scene.get("theme"), PALETTE, HOST_LOOK)', src)
        self.assertIn("if box_segs:", src)                                  # a video with no media box renders


class NewDrawings(unittest.TestCase):
    def test_reusable_drawings_for_log_cuts_bugs_are_in_the_catalog(self):
        from kindled_iron.director import plan as P
        types = P.director_types(P.catalog())
        for n in ("wood_log", "chip_log", "moth", "film_strip", "scissors_cut", "code_window", "spin_effect", "old_computer"):
            self.assertTrue(types.get(n, {}).get("doodle"), n)


class FreezeClearsTheBoard(unittest.TestCase):
    """The freeze zooms the whole board: every drawing on screen (open-zone drawings included) is cleared first, and
    the freeze line's next drawing refills the board as soon as the camera is back."""

    def test_freeze_on_open_lines(self):
        from kindled_iron.director import compile as C, plan as P
        cat = P.catalog()
        lines, words = timed(FIX["scripts"]["animation"])
        plan = {"freeze": {"line": 2, "word": "first:"}, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "drawings": [{"word": "cartoon", "type": "film_strip", "fields": {}}]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "drawings": [{"word": "motion.", "type": "film_strip", "fields": {}}]},   # said long after the freeze
            {"expression": "happy", "gesture": {"do": "none"}, "box": [],
             "drawings": [{"word": "eyes", "type": "question_big", "fields": {"label": "?"}}]}]}
        scene, _ = C.compile_scene(plan, lines, words, cat, [[], [], []], {"id": "a", "audio_path": "a", "sha256": "x"})
        ev = []
        for b, beat in enumerate(scene["beats"]):
            for e in beat["events"]:
                at = e.get("at")
                ev.append((at if isinstance(at, (int, float)) else C._anchor_time(words[b], at), e))
        tf = next(t for t, e in ev if e.get("do") == "freeze")
        def visible(t):
            on = set()
            for t_, e in sorted(ev, key=lambda x: x[0]):
                if t_ > t:
                    break
                if e.get("do") == "draw":
                    on.add(e["id"])
                elif e.get("do") == "fade":
                    (on.update if e.get("opacity") else on.difference_update)(e["ids"])
            return on
        self.assertEqual(visible(tf + 0.01), set())                          # nothing on the board during the zoom
        back = tf + C.FREEZE["dur"] + C.FREEZE["after"]
        if words[1][-1]["end"] > back + 1.5:
            self.assertTrue(visible(back + 0.8), "the board stays empty after the freeze")


class CaptionsAtTheMiddle(unittest.TestCase):
    """Owner, 2026-10-27: captions too close to the top. Their default anchor is the middle of the frame, with or
    without a clip box; drawings, media and the guide are arranged around them; only a diagram moves them (to its
    band). No top-of-frame caption windows."""

    def test_caption_anchor_and_layout_around_it(self):
        from kindled_iron.director import compile as C, plan as P
        cat = P.catalog()
        Z = cat["zones"]
        cap0, cap1 = Z["caption"]["y"], Z["caption"]["y"] + Z["caption"]["h"]
        self.assertTrue(880 <= (cap0 + cap1) / 2 <= 960)                  # about the frame's centre line (1920 / 2)
        self.assertLessEqual(Z["box"]["y"] + Z["box"]["h"] / 2, Z["draw"]["y0"])   # box above the band ...
        self.assertLess(Z["draw"]["y1"], cap0)                             # ... the band above the caption ...
        self.assertLess(cap1, cat["guide"]["top"])                         # ... the guide's head below it
        ct = CrossTopic(); ct.setUpClass()
        for name, media_lines in (("animation", (1,)), ("water", (1,)), ("cpr", (0,))):
            with self.subTest(topic=name):
                scene, words, dg, plan = ct.compile(name, media_lines)
                self.assertEqual(scene["captions_box"]["y"], cap0)
                wins = scene["caption_windows"]
                self.assertEqual(len(wins), 1 if dg else 0)               # only the diagram's band
                for b, beat in enumerate(scene["beats"]):
                    for e in beat["events"]:
                        if e.get("do") == "draw" and e["y"] < cap0:     # a drawing above the caption stays above it
                            types = P.director_types(cat)
                            o = types.get(e.get("doodle") or e.get("type")) or {}
                            if o:
                                h, cy = o["size"][1], o.get("center", [0, 0])[1]
                                self.assertLessEqual(e["y"] + (cy + h / 2) * e["scale"], cap0 + 1, e["id"])


class AudioTruePeakTrim(unittest.TestCase):
    """Computer Bugs failed its audio check (-1.9 dBTP over the -2.0 limit): the limiter works on samples and sharp
    transients still overshoot between them. A mix that would fail gets ONE static gain trim to the -2.5 target (no
    compression) and is measured again; a mix that passes is written exactly as before. The -2.0 gate is unchanged."""

    def mix(self, bursts: bool):
        import subprocess
        import numpy as np
        from kindled_iron import sound
        d = Path(tempfile.mkdtemp())
        n = int(3 * sound.SR)
        x = (np.random.default_rng(1).standard_normal(n) * 0.02).astype(np.float32)
        if bursts:                                     # +a +a -a -a: samples 3 dB under the peak between them
            for k in range(1, 6):
                i = int(k * 0.5 * sound.SR)
                x[i:i + 400] = np.tile(np.array([1, 1, -1, -1], np.float32), 100) * 0.9
        src = d / "n.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sound.SR), "-ac", "1", "-i", "-", str(src)],
                       input=x.tobytes(), check=True)
        logs = []
        r = sound.mix(src, [], {"voice_as_is": True}, [], [{"word": "a", "start": 0.1, "end": 2.9}], 3.0, d / "m.wav",
                      d / "mv.wav", None, logs.append, out_nomusic=d / "mn.wav")
        return r, logs, sound

    def test_a_failing_mix_is_trimmed_once_and_passes(self):
        r, logs, sound = self.mix(True)
        self.assertTrue(any("static trim" in l for l in logs), logs)
        self.assertLessEqual(r["true_peak"], sound.TP_FAIL)
        self.assertEqual((sound.TRUE_PEAK, sound.TP_FAIL), (-2.5, -2.0))      # the gate itself is unchanged

    def test_a_passing_mix_is_untouched(self):
        r, logs, sound = self.mix(False)
        self.assertFalse(any("static trim" in l for l in logs), logs)


class LateMediaLead(unittest.TestCase):
    """Epicurean full MP4, 37-41 s: a line whose photo comes late left the top of the frame empty for 3 s (the lead
    drawing was only offered to lines with 2+ drawings). Now one drawing leads where the box will be, above the
    drawing band (never over it, or the band's drawing would clear it), and gives way just before the media."""

    def test_one_drawing_leads_in_the_box_place_until_the_media(self):
        from kindled_iron.director import compile as C, plan as P
        cat = P.catalog()
        lines, words = timed("One two three four five six seven eight earthquakes happen.\n\nThe end of it all comes now.")
        plan = {"freeze": None, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [{"word": "earthquakes", "kind": "meme", "file": "x.png"}],
             "drawings": [{"word": "One", "type": "earthquake", "fields": {}}]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [], "drawings": [{"word": "end", "type": "question_big", "fields": {"label": "?"}}]}]}
        media = [[{"kind": "meme", "file": "x.png", "path": "movie_reference/x.png", "word": "earthquakes"}], []]
        scene, _ = C.compile_scene(plan, lines, words, cat, media, {"id": "a", "audio_path": "a", "sha256": "x"})
        ev = [((e["at"] if isinstance(e["at"], (int, float)) else C._anchor_time(words[b], e["at"])), e)
              for b, beat in enumerate(scene["beats"]) for e in beat["events"]]
        d = next((t, e) for t, e in ev if e.get("do") == "draw" and e["id"].startswith("l1_"))
        box = next(t for t, e in ev if e.get("box") == "media")
        o = P.director_types(cat)["earthquake"]
        bottom = d[1]["y"] + (o.get("center", [0, 0])[1] + o["size"][1] / 2) * d[1]["scale"]
        self.assertLess(d[0], box - 1.0)                                    # it is on screen well before the media
        self.assertLessEqual(bottom, cat["zones"]["draw"]["y0"])           # in the box's place, above the band
        gone = [t for t, e in ev if e.get("do") == "fade" and d[1]["id"] in e["ids"] and not e.get("opacity")]
        self.assertTrue(gone and d[0] < min(gone) <= box)                  # and gives way just before the media


class DrawingLifetimes(unittest.TestCase):
    """A drawing is on screen while the narration is about it: an earlier line's drawing leaves at the line handover
    when the new line moves on (not seconds later when its slot is reused), and stays when the new line still
    talks about it. Unseen script (not one of the four evaluation videos)."""

    def compile(self, second_line):
        from kindled_iron.director import compile as C, plan as P
        cat = P.catalog()
        lines, words = timed("Every lighthouse keeper kept a logbook of passing ships.\n\n" + second_line +
                             "\n\nAnd that is how the coast stayed safe.")
        plan = {"freeze": None, "lines": [
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "drawings": [{"word": "logbook", "type": "openbook", "concept": "logbook", "fields": {"label": "LOGBOOK"}}]},
            {"expression": "curious", "gesture": {"do": "none"}, "box": [],
             "drawings": [{"word": second_line.split()[-1], "type": "question_big", "concept": "question", "fields": {"label": "?"}}]},
            {"expression": "happy", "gesture": {"do": "none"}, "box": [], "drawings": [{"word": "coast", "type": "check_big", "concept": "safe", "fields": {}}]}]}
        scene, _ = C.compile_scene(plan, lines, words, cat, [[], [], []], {"id": "a", "audio_path": "a", "sha256": "x"})
        ev = [((e["at"] if isinstance(e["at"], (int, float)) else C._anchor_time(words[b], e["at"])), e)
              for b, beat in enumerate(scene["beats"]) for e in beat["events"]]
        gone = min([t for t, e in ev if e.get("do") == "fade" and "l1_openbook0" in e["ids"] and not e.get("opacity")] + [1e9])
        return gone, words

    def test_it_leaves_when_the_narration_moves_on(self):
        gone, words = self.compile("Storms still sank many of them anyway, why?")
        self.assertLessEqual(gone, words[1][0]["start"])                   # gone by the time line 2 starts

    def test_it_stays_while_the_narration_still_talks_about_it(self):
        gone, words = self.compile("The logbook told the next keeper what to watch for, right?")
        self.assertGreater(gone, words[1][0]["start"] + 0.5)               # still up during line 2


class NarratorCharacter(unittest.TestCase):
    """A video may ask for a narrator character in its settings (owner-approved: the teen narrator, for the Computer
    Bugs evaluation only). It is a cast spec on the same rig; without the setting nothing changes."""

    def test_only_a_video_that_asks_gets_it(self):
        from kindled_iron import themes
        from kindled_iron.director import compile as C, plan as P
        self.assertEqual(themes.character(None), {})
        with self.assertRaises(SystemExit):
            themes.character("toddler")
        lines, words = timed("A short line about bugs.")
        plan = {"freeze": None, "lines": [{"expression": "curious", "gesture": {"do": "none"}, "box": [],
                                           "drawings": [{"word": "bugs", "type": "moth", "fields": {}}]}]}
        meta = {"id": "a", "audio_path": "a", "sha256": "x"}
        plain, _ = C.compile_scene(plan, lines, words, P.catalog(), [[]], meta)
        teen, _ = C.compile_scene(json.loads(json.dumps(plan)), lines, words, P.catalog(), [[]], dict(meta, character="teen"))
        self.assertNotIn("style", plain["cast"]["guide"])
        self.assertEqual(teen["cast"]["guide"]["style"], "teen")

    def test_the_teen_rig_has_every_expression_and_reaction(self):
        js = (ROOT / "kindled_iron" / "runtime" / "runtime.js").read_text()
        def keys(name):
            body = js.split(f"var {name} = {{", 1)[1].split("\n  };", 1)[0]
            return set(re.findall(r"^\s{4}(\w+):", body, re.M))
        self.assertEqual(keys("TEEN_FACES"), keys("FACES"))                # the director's expressions work unchanged
        self.assertEqual(keys("TEEN_REACT"), keys("REACT"))


class FrameAuditOverlaps(unittest.TestCase):
    """Owner, 2026-10-27: the composition study's misses were a drawing on a drawing and a label on itself. The
    per-frame audit now checks both, and the label wrap that put "EVERYTHING THAT" on "HAPPENED" is fixed."""

    def test_the_audit_checks_drawings_and_labels_and_the_double_wrap_is_gone(self):
        js = (ROOT / "kindled_iron" / "runtime" / "runtime.js").read_text()
        self.assertIn("'DRAWINGS OVERLAP '", js)
        self.assertIn("'LABELS OVERLAP '", js)
        self.assertIn("ln, size, q[3], true)", js)                        # an already wrapped line is not wrapped again

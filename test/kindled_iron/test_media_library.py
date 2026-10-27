"""The director's private media library and story-aware selection (offline: throwaway library, no network, no AI).

KI_PRIVATE_ROOT=<kindled-iron-voice checkout> also checks the real library's indexes (test_real_library_*)."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kindled_iron.director import actions, compile as compiler, gates, media, plan as planmod

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "kindled_iron" / "tools" / "import_media.py"
RUNTIME = (ROOT / "kindled_iron" / "runtime" / "runtime.js").read_text(encoding="utf-8")
LINES = ["Sounds crazy, right? But look at the argument about money.",
         "Earthquakes and diseases hurt people nobody chose.",
         "So why does He allow innocent people to suffer?"]


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


def png(path: Path, color: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=32x32", "-frames:v", "1",
                    str(path)], check=True)


def sha(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class Library(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for d in ("movie_reference", "movie_reference/guide_actions", "reactions", "approved_audio/x", "previews/x"):
            (self.root / d).mkdir(parents=True)
        png(self.root / "movie_reference" / "Wait-What-meme-kevin-hart.jpg", "red")       # legacy: no index entry
        png(self.root / "movie_reference" / "collapsed_house.png", "gray")
        png(self.root / "movie_reference" / "guide_actions" / "helping.png", "white")
        png(self.root / "reactions" / "confused_question_marks.png", "blue")
        png(self.root / "reactions" / "000_love_money_confused.jpg", "green")
        png(self.root / "reactions" / "cash_rabbit.png", "yellow")
        (self.root / "approved_audio" / "x" / "narration.mp3").write_bytes(b"ID3 approved")
        (self.root / "previews" / "x" / "x.mp4").write_bytes(b"preview")
        (self.root / "movie_reference" / "index.json").write_text(json.dumps({"items": [
            {"file": "collapsed_house.png", "type": "still", "tags": ["house", "destruction", "earthquake"],
             "description": "a house collapsed after a disaster", "show": True},
            {"file": "guide_actions/helping.png", "type": "guide_action_reference", "show": False, "guide_action": "help_up"},
            {"file": "gone.png", "tags": ["missing"]}]}))                            # entry without a file
        (self.root / "reactions" / "index.json").write_text(json.dumps({"items": [
            {"file": "000_love_money_confused.jpg", "tags": ["confused"]},
            {"file": "confused_question_marks.png", "type": "meme", "tags": ["confusion", "question", "disbelief"],
             "description": "man smiling in confusion", "purpose": "react to a claim that makes no sense",
             "same_meme_as": ["reactions/000_love_money_confused.jpg"], "show": True},
            {"file": "cash_rabbit.png", "type": "meme", "tags": ["money", "cash", "greed"], "show": True}]}))
        self.lib = media.library(self.root, log=lambda m: None)
        self.by = {m["file"]: m for m in self.lib}
        self.cat = planmod.catalog()
        self.keys = [[planmod.key(w["word"]) for w in ws] for ws in words(LINES)]

    # 1
    def test_existing_assets_remain_discoverable(self):
        self.assertIn("Wait-What-meme-kevin-hart.jpg", self.by)                 # legacy movie_reference, no index entry
        self.assertIn("000_love_money_confused.jpg", self.by)                   # legacy reactions/
        self.assertEqual(self.by["000_love_money_confused.jpg"]["path"], "reactions/000_love_money_confused.jpg")
        self.assertEqual(self.by["Wait-What-meme-kevin-hart.jpg"]["path"], "movie_reference/Wait-What-meme-kevin-hart.jpg")

    # 2
    def test_existing_json_indexes_remain_valid(self):
        before = json.loads((self.root / "reactions" / "index.json").read_text())
        z = self._pack({"new_one": ("memes/n.png", "purple", "meme")})
        subprocess.run([sys.executable, str(TOOL), "--zip", str(z), "--private", str(self.root)], capture_output=True, check=True)
        after = json.loads((self.root / "reactions" / "index.json").read_text())
        self.assertEqual(after["items"][:len(before["items"])], before["items"])
        for folder in ("reactions", "movie_reference"):
            self._valid_index(self.root / folder)

    # 3
    def test_new_assets_are_indexed_with_metadata(self):
        z = self._pack({"sad_cat": ("memes/s.png", "black", "meme")})
        subprocess.run([sys.executable, str(TOOL), "--zip", str(z), "--private", str(self.root)], capture_output=True, check=True)
        m = {x["file"]: x for x in media.library(self.root, log=lambda m: None)}["sad_cat.png"]
        self.assertEqual(m["path"], "reactions/sad_cat.png")
        self.assertIn("sad", m["tags"])
        self.assertEqual(m["role"], "meme")

    # 4
    def test_duplicates_are_not_imported_twice(self):
        z = self._pack({"blue_again": ("memes/b.png", "blue", "meme")})                # same bytes as an existing meme
        out = subprocess.run([sys.executable, str(TOOL), "--zip", str(z), "--private", str(self.root)], capture_output=True, text=True)
        rep = json.loads(out.stdout)
        self.assertEqual([d["id"] for d in rep["skipped_duplicates"]], ["blue_again"])
        self.assertFalse((self.root / "reactions" / "blue_again.png").exists())

    # 5
    def test_missing_files_are_handled_safely(self):
        self.assertNotIn("gone.png", self.by)                                   # index entry without a file: not offered
        (self.root / "reactions" / "cash_rabbit.png").unlink()
        self.assertNotIn("cash_rabbit.png", {m["file"] for m in media.library(self.root, log=lambda m: None)})
        self.assertEqual(media.library(self.root / "nowhere", log=lambda m: None), [])

    # 6
    def test_missing_or_malformed_metadata_does_not_crash(self):
        (self.root / "reactions" / "index.json").write_text("{ not json")
        (self.root / "movie_reference" / "index.json").write_text(json.dumps({"items": ["x", {"file": 3}, {"tags": None}]}))
        logged = []
        lib = media.library(self.root, log=logged.append)
        self.assertIn("confused_question_marks.png", {m["file"] for m in lib})  # found by its name alone
        self.assertTrue(any("not valid JSON" in m for m in logged))
        p = self._plan(box1=[{"word": "crazy", "kind": "meme", "file": "confused_question_marks.png"}])
        planmod.repair(p, LINES, self.keys, self.cat, lib)
        self.assertEqual(planmod.validate(p, LINES, self.keys, lib, self.cat), [])

    # 7
    def test_selection_uses_semantic_relevance(self):
        self.assertIn("disbelief", media.relevance(self.by["Wait-What-meme-kevin-hart.jpg"], LINES[0], "curious"))
        self.assertIn("shares", media.relevance(self.by["cash_rabbit.png"], LINES[0]))
        self.assertIsNotNone(media.relevance(self.by["collapsed_house.png"], LINES[1]))
        self.assertIsNone(media.relevance(self.by["cash_rabbit.png"], LINES[1], "sad"))
        p = self._plan(box1=[{"word": "crazy", "kind": "meme", "file": "Wait-What-meme-kevin-hart.jpg"}])
        os.environ["KI_BOX_PLACEHOLDER"] = "1"
        _, records, errs = media.resolve(p, self.lib, lambda m: None, LINES)
        self.assertEqual(errs, [])
        self.assertIn("same reaction", next(r for r in records if r.get("file"))["why"])

    # 8
    def test_irrelevant_footage_is_rejected(self):
        p = self._plan(box1=[{"word": "money", "kind": "meme", "file": "collapsed_house.png"},
                             {"word": "crazy", "kind": "stock", "query": "chalkboard argument"}])
        notes = planmod.repair(p, LINES, self.keys, self.cat, self.lib)
        self.assertEqual([b.get("file") for b in p["lines"][0]["box"]], [None])   # the still is gone, the stock stays
        self.assertTrue(any("nothing to do with the line" in n for n in notes))
        from kindled_iron import insets
        real = insets._pexels, insets._pixabay
        os.environ.pop("KI_BOX_PLACEHOLDER", None)
        insets._pexels = lambda q, pin: [{"source": "pexels", "id": "9", "title": "puppy on a beach", "page": ""}]
        insets._pixabay = lambda q, pin: []
        try:
            self.assertIsNone(media.stock("earthquake rubble street", [], {}, lambda m: None))
        finally:
            insets._pexels, insets._pixabay = real

    # 9
    def test_doodle_only_lines_pass_the_media_gates(self):
        work = Path(tempfile.mkdtemp())
        (work / "box_segments.json").write_text(json.dumps([{"kind": "clip", "from": 0, "to": 9}]))
        scene = {"beats": [
            {"events": [{"do": "draw", "type": "question_big"}, {"box": "clip", "clip": "s1"}]},
            {"events": [{"do": "draw", "type": "earthquake"}]},                  # drawings + guide only
            {"events": [{"do": "draw", "type": "heart"}, {"do": "look", "who": "guide"}]}]}
        plan = {"lines": [{}, {}, {}]}
        res = gates.run(work, scene, plan, LINES, self.cat, 1.0, False, None)
        self.assertTrue(res["per_line"]["ok"], res["per_line"])
        self.assertTrue(res["box_media"]["ok"])
        scene["beats"][0]["events"].pop()                                       # the hook still needs box media
        res = gates.run(work, scene, plan, LINES, self.cat, 1.0, False, None)
        self.assertFalse(res["per_line"]["ok"])
        self.assertIn("line 1", res["per_line"]["fix"])
        p = self._plan(box1=[{"word": "crazy", "kind": "stock", "query": "chalkboard argument"}])
        self.assertEqual(planmod.validate(p, LINES, self.keys, self.lib, self.cat), [])     # lines 2-3 have no box
        p["lines"][0]["box"] = []
        self.assertIn("hook line needs clip-box media", " ".join(planmod.validate(p, LINES, self.keys, self.lib, self.cat)))

    # 10
    def test_memes_are_not_selected_unnecessarily(self):
        p = self._plan(box1=[{"word": "crazy", "kind": "meme", "file": "confused_question_marks.png"}],
                       box2=[{"word": "Earthquakes", "kind": "meme", "file": "cash_rabbit.png"}],   # irrelevant
                       pop3={"word": "suffer", "file": "000_love_money_confused.jpg"})            # look-alike of line 1
        p["lines"][2]["expression"] = "puzzled"                                  # so the pop fits the line itself
        notes = " | ".join(planmod.repair(p, LINES, self.keys, self.cat, self.lib))
        self.assertEqual(p["lines"][1]["box"], [])
        self.assertIsNone(p["lines"][2]["pop"])
        self.assertIn("nothing to do with the line", notes)
        self.assertIn("look-alike", notes)
        many = [{"file": f"m{k}.png", "role": "meme", "group": f"m{k}", "tags": ["crazy"]} for k in range(6)]
        p = self._plan(box1=[{"word": "crazy", "kind": "meme", "file": m["file"]} for m in many])
        planmod.repair(p, LINES, self.keys, self.cat, many)
        self.assertEqual(len(p["lines"][0]["box"]), planmod.MAX_MEMES)
        self.assertIn("Most lines need no meme", " ".join(planmod.RULES))

    # 11
    def test_guide_action_references_map_to_guide_animations(self):
        self.assertNotIn("guide_actions/helping.png", {m["path"] for m in self.lib})   # references are never shown
        self.assertNotIn("helping.png", self.by)
        for name in ("frustrated_at_screen", "realize", "help_up", "choose_path"):     # the pack's four references
            self.assertIn(name, actions.ACTIONS)
        for name in actions.ACTED - {"none"}:
            evs = actions.rig(name, {"expression": "thinking", "room": True, "target": "d1", "can_point": True})
            if evs is None:
                continue                                    # the plain gestures go through compile's own branch
            for _, e in evs:
                self.assertTrue(re.search(rf"case '{e['do']}'|e\.do === '{e['do']}'", RUNTIME), f"{name}: {e['do']}")
                if "expression" in e:
                    self.assertIn(e["expression"], self.cat["expressions"])

    # 12
    def test_unsupported_actions_are_reported_not_faked(self):
        p = self._plan(box1=[{"word": "crazy", "kind": "stock", "query": "chalkboard argument"}])
        p["lines"][1]["gesture"] = {"do": "help_up", "word": "people"}
        p["lines"][2]["gesture"] = {"do": "carry", "word": "suffer"}
        notes = planmod.repair(p, LINES, self.keys, self.cat, self.lib)
        rep = p["unsupported_actions"]
        self.assertEqual([(r["line"], r["action"], r["performed"]) for r in rep], [(2, "help_up", False), (3, "carry", False)])
        self.assertTrue(all("not supported" in n for n in notes if "guide action" in n))
        scene = self._compile(p)
        logged = scene["director"]["actions"]
        self.assertTrue(any(a["action"] == "help_up" and a["status"] == "unsupported" and not a["performed"] for a in logged))
        self.assertFalse(any(a.get("status") == "unsupported" and a.get("performed") for a in logged))

    # 13
    def test_existing_guide_animations_still_work(self):
        p = self._plan(box1=[{"word": "crazy", "kind": "stock", "query": "chalkboard argument"}])
        p["lines"][0]["gesture"] = {"do": "point", "word": "argument"}
        p["lines"][2]["gesture"] = {"do": "think", "word": "allow"}
        evs = [e for b in self._compile(p)["beats"] for e in b["events"]]
        self.assertTrue(any(e.get("do") in ("point", "look") and e.get("who") == "guide" for e in evs))
        self.assertTrue(any(e.get("do") == "look" and e.get("expression") == "thinking" for e in evs))
        self.assertTrue(any(e.get("do") == "freeze" for e in evs))
        self.assertTrue(any(e.get("do") == "walk" or e.get("do") == "look_viewer" for e in evs))

    # 14
    def test_coverage_and_collision_gates_remain_enforced(self):
        self.assertEqual((gates.MIN_COVER, gates.MAX_EMPTY), (0.60, 0.20))
        work = Path(tempfile.mkdtemp())
        (work / "checks.json").write_text(json.dumps([{"issue": "OVERLAP d1/guide", "from": 3.0}]))
        (work / "audit.json").write_text(json.dumps({"issues": [{"issue": "drawing touches the guide", "from": 4.0}]}))
        (work / "box_segments.json").write_text(json.dumps([{"kind": "clip"}]))
        scene = {"beats": [{"events": [{"do": "draw", "type": "heart"}, {"box": "clip"}]}]}
        res = gates.run(work, scene, {"lines": [{}]}, LINES[:1], self.cat, 1.0, False, None)
        self.assertFalse(res["layout"]["ok"])
        self.assertFalse(res["audit"]["ok"])
        self.assertFalse(res["_passed"])

    # 15
    def test_provider_budget_and_secret_tests_still_pass(self):
        from kindled_iron.director import direct
        self.assertEqual((direct.PLAN_CALLS, direct.VISION_CALLS), (3, 1))
        banned = re.compile(r"\b(CLOUDFLARE_ACCOUNT_ID|CLOUDFLARE_API_TOKEN|OPENAI_API_KEY|MOONSHOT_API_KEY|WAVESPEED_API_KEY)\b")
        for f in [TOOL, *(ROOT / "kindled_iron" / "director").glob("*.py")]:
            self.assertIsNone(banned.search(f.read_text(encoding="utf-8")), f.name)
        r = subprocess.run([sys.executable, "-m", "unittest", "test.kindled_iron.test_llm", "test.kindled_iron.test_direct_budget"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    # 16 + 17
    def test_narration_and_previews_are_untouched_by_an_import(self):
        audio, prev = sha(self.root / "approved_audio"), sha(self.root / "previews")
        z = self._pack({"another": ("memes/a.png", "orange", "meme"), "ref": ("refs/r.png", "pink", "guide_action")})
        subprocess.run([sys.executable, str(TOOL), "--zip", str(z), "--private", str(self.root)], capture_output=True, check=True)
        self.assertEqual(sha(self.root / "approved_audio"), audio)
        self.assertEqual(sha(self.root / "previews"), prev)
        self.assertFalse(re.search(r"approved_audio|previews", TOOL.read_text().split('"""', 2)[2].split("def main")[0]))

    # the record-scratch freeze: the owner's recording + the grey frame
    def test_freeze_is_grey_and_plays_the_owners_scratch(self):
        import numpy as np
        from kindled_iron import sound
        p = self._plan(box1=[{"word": "crazy", "kind": "stock", "query": "chalkboard argument"}])
        fz = [e for b in self._compile(p)["beats"] for e in b["events"] if e.get("do") == "freeze"]
        self.assertEqual(len(fz), 1)
        self.assertTrue(fz[0]["grey"])
        self.assertEqual((fz[0]["sound"], fz[0]["sound_file"]), ("record_scratch", "sfx/record_scratch.mp3"))
        self.assertIn("freezeState.grey > 0.5", RUNTIME)
        self.assertIn("grayscale(1)", RUNTIME)
        (self.root / "sfx").mkdir()
        rec = self.root / "sfx" / "record_scratch.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=0.5", "-f", "lavfi",
                        "-i", "sine=f=900:d=0.6", "-filter_complex", "[0][1]concat=n=2:v=0:a=1", str(rec)], check=True)
        before = hashlib.sha256(rec.read_bytes()).hexdigest()
        old = os.environ.get("KI_PRIVATE_MEDIA")
        os.environ["KI_PRIVATE_MEDIA"] = str(self.root)
        try:
            ev = [{"t": 2.0, "do": "freeze", "sound": "record_scratch", "sound_file": "sfx/record_scratch.mp3"}]
            cues = sound.plan(ev, [], {}, [(0, 9)])
            self.assertEqual((cues[0]["file"], cues[0]["path"]), ("record_scratch.mp3", str(rec)))
            x = sound._own(rec)
            self.assertLess(len(x) / sound.SR, 0.75)                          # the 0.5 s silence is trimmed
            self.assertAlmostEqual(float(np.sqrt(np.mean(x ** 2))), 0.1, places=3)
            self.assertEqual(hashlib.sha256(rec.read_bytes()).hexdigest(), before)   # the file itself is never edited
            ev[0]["sound_file"] = "sfx/missing.mp3"                  # missing -> the library's variants (none built
            self.assertTrue(all("path" not in c for c in sound.plan(ev, [], {}, [(0, 9)])))   # today), never a crash
        finally:
            if old is None:
                os.environ.pop("KI_PRIVATE_MEDIA", None)
            else:
                os.environ["KI_PRIVATE_MEDIA"] = old

    # the real private library (KI_PRIVATE_ROOT)
    @unittest.skipUnless(os.getenv("KI_PRIVATE_ROOT"), "KI_PRIVATE_ROOT not set")
    def test_real_library_indexes_are_valid(self):
        """Counts only in every message: the run's log is public, the private library's file names are not."""
        root = Path(os.environ["KI_PRIVATE_ROOT"])
        problems = sum(len(self._index_problems(root / f)) for f in ("reactions", "movie_reference"))
        self.assertEqual(problems, 0, f"{problems} problem(s) in the private index files (names withheld)")
        logged = []
        lib = media.library(root, log=logged.append)
        self.assertEqual(len(logged), 0, f"{len(logged)} library warning(s) (details withheld)")
        self.assertGreaterEqual(len(lib), 40, f"only {len(lib)} library files")
        self.assertEqual(sum("guide_actions" in m["path"] for m in lib), 0, "a guide-action reference is offered as media")
        refs = [i for i in json.loads((root / "movie_reference" / "index.json").read_text())["items"]
                if i.get("type") == "guide_action_reference"]
        unknown = sum(r.get("guide_action") not in actions.ACTIONS for r in refs)
        self.assertEqual(unknown, 0, f"{unknown} guide-action reference(s) map to no action")
        self.assertGreater(len(refs), 0)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _index_problems(folder: Path) -> list[str]:
        try:
            d = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return [f"{folder.name}/index.json unreadable ({type(e).__name__})"]
        if not isinstance(d.get("items"), list):
            return [f"{folder.name}/index.json has no items list"]
        out, seen = [], set()
        for i in d["items"]:
            f = i.get("file") if isinstance(i, dict) else None
            if not isinstance(f, str):
                out.append("an entry without a file name")
                continue
            if f in seen:
                out.append(f"duplicate entry {f}")
            seen.add(f)
            if i.get("sha256") and not (folder / f).exists():
                out.append(f"indexed file missing: {f}")
        return out

    def _valid_index(self, folder: Path):
        self.assertEqual(self._index_problems(folder), [])

    def _pack(self, assets: dict) -> Path:
        import zipfile
        src = Path(tempfile.mkdtemp()) / "kindled-media-library"
        cat = []
        for aid, (rel, color, kind) in assets.items():
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            png(src / rel, color)
            cat.append({"id": aid, "path": rel, "type": kind, "tags": aid.split("_")})
        (src / "catalog.json").write_text(json.dumps({"assets": cat}))
        z = src.parent / "pack.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in src.rglob("*"):
                zf.write(f, f.relative_to(src.parent))
        return z

    def _plan(self, box1=None, box2=None, pop3=None):
        dr = lambda w, t, f: {"word": w, "type": t, "fields": f}
        return {"freeze": {"line": 2, "word": "Earthquakes"}, "lines": [
            {"expression": "curious", "gesture": {"do": "point", "word": "argument"}, "box": box1 or [],
             "drawings": [dr("argument", "question_big", {"label": "REALLY?"}), dr("money", "coin_pile", {"label": "MONEY"})]},
            {"expression": "sad", "gesture": {"do": "none"}, "box": box2 or [],
             "drawings": [dr("Earthquakes", "earthquake", {"label": "EARTHQUAKE"}), dr("people", "heart", {"label": "PAIN"})]},
            {"expression": "thinking", "gesture": {"do": "shrug", "word": "why"}, "box": [], "pop": pop3,
             "drawings": [dr("suffer", "question_big", {"label": "WHY?"}), dr("innocent", "heart", {"label": "INNOCENT"})]}]}

    def _compile(self, p):
        os.environ["KI_BOX_PLACEHOLDER"] = "1"
        os.environ.pop("PEXELS_API_KEY", None)
        planmod.repair(p, LINES, self.keys, self.cat, self.lib)
        self.assertEqual(planmod.validate(p, LINES, self.keys, self.lib, self.cat), [])
        per_line, _, errs = media.resolve(p, self.lib, lambda m: None, LINES)
        self.assertEqual(errs, [])
        scene, _ = compiler.compile_scene(p, LINES, words(LINES), self.cat, per_line,
                                          {"id": "t", "audio_path": "approved_audio/t/narration.mp3", "sha256": "x", "align": 1})
        return scene


if __name__ == "__main__":
    unittest.main()

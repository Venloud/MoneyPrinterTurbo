"""The director's AI budget and quota wait (no render, no AI: attempt / align / the provider chain are mocked)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from kindled_iron.director import direct, llm
from kindled_iron.director.calls import CALLS

LINES = "One line of the script here.\n\nA second line of the script."


def words():
    return [[{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(line.split())] for line in LINES.split("\n\n")]


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        src = self.tmp / "private" / "approved_audio" / "test-video"
        src.mkdir(parents=True)
        (src / "script.txt").write_text(LINES)
        (src / "narration.mp3").write_bytes(b"not really an mp3")
        self.out = self.tmp / "private" / "previews" / "test-video"
        self.real = (direct.align, direct.attempt, llm.call_json, direct.ntfy, sys.argv)
        self.aligned = []
        direct.align = lambda mp3, lines, work: (self.aligned.append(1) or (words(), 1.0))
        direct.ntfy = lambda title, body: self.alerts.append(title)
        self.alerts, self.plan_calls = [], 0
        direct.ROUNDS.clear()
        CALLS.clear()

    def tearDown(self):
        direct.align, direct.attempt, llm.call_json, direct.ntfy, sys.argv = self.real

    def run_main(self):
        sys.argv = ["direct", "--id", "test-video", "--private", str(self.tmp / "private"), "--out", str(self.out),
                    "--work", str(self.tmp / "work")]
        with self.assertRaises(SystemExit) as e:
            direct.main()
        return e.exception.code

    def test_at_most_three_plan_calls(self):
        def plan(kind, prompt, compact=None, **kw):
            self.plan_calls += 1
            CALLS.append({"kind": kind, "provider": "gemini"})
            return {"lines": []}

        def failing(p, lines, words_, cat, lib, meta, work, rec):
            rec["errors"].append({"stage": "preflight", "errors": ["coverage under 60%"]})
            return None
        llm.call_json, direct.attempt = plan, failing
        code = self.run_main()
        self.assertEqual(self.plan_calls, direct.PLAN_CALLS)
        self.assertIn("FAIL", str(code))
        st = json.loads((self.out / "status.json").read_text())
        self.assertEqual(st["state"], "failed")
        self.assertTrue((self.out / "fail_report.md").exists())

    def test_all_providers_out_waits_and_resumes(self):
        def out_of_quota(kind, prompt, compact=None, **kw):
            raise llm.QuotaWait("gemini: 429 per-day; github: 429; cloudflare: budget")
        llm.call_json = out_of_quota
        direct.attempt = lambda *a: None
        self.assertEqual(self.run_main(), direct.WAIT_EXIT)
        st = json.loads((self.out / "status.json").read_text())
        ck = json.loads((self.out / "checkpoint.json").read_text())
        self.assertEqual(st["state"], "waiting_quota")
        self.assertEqual(st["stage"], "plan")
        self.assertEqual(ck["plan_calls"], 0)
        self.assertEqual(self.alerts, [])                    # no alert before 24 h
        # the scheduled retry: the checkpoint is resumed (no new alignment); 24 h later still out -> one alert
        ck["waiting_since"] = "2000-01-01T00:00:00+00:00"
        (self.out / "checkpoint.json").write_text(json.dumps(ck))
        direct.ROUNDS.clear()
        self.assertEqual(self.run_main(), direct.WAIT_EXIT)
        self.assertEqual(len(self.aligned), 1)
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("waiting for AI quota", self.alerts[0])

    def test_checkpoint_resumes_on_another_runner(self):
        """The CI path: run 1 writes to its own out dir, the workflow's save step commits it to the private repo,
        run 2 starts on a fresh runner (a new clone, a new work dir) and resumes it: same plan budget, no new
        alignment."""
        import shutil
        import subprocess

        def git(*a, cwd=None):
            subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
        origin = self.tmp / "origin.git"
        git("init", "-q", "--bare", "-b", "main", str(origin))
        git("init", "-q", "-b", "main", cwd=self.tmp / "private")
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            git("config", k, v, cwd=self.tmp / "private")
        git("add", ".", cwd=self.tmp / "private")
        git("commit", "-q", "-m", "audio", cwd=self.tmp / "private")
        git("push", "-q", str(origin), "HEAD:main", cwd=self.tmp / "private")

        calls = []

        def first_then_out(kind, prompt, compact=None, **kw):
            if len(calls) < 1:
                calls.append(kind)
                CALLS.append({"kind": kind, "provider": "gemini"})
                return {"lines": []}
            raise llm.QuotaWait("every provider: 429 per-day")
        llm.call_json = first_then_out
        direct.attempt = lambda p, lines, w, cat, lib, meta, work, rec: rec["errors"].append(
            {"stage": "plan", "errors": ["x"]})
        run1_out = self.tmp / "runner1" / "out" / "test-video"
        sys.argv = ["direct", "--id", "test-video", "--private", str(self.tmp / "private"), "--out", str(run1_out),
                    "--work", str(self.tmp / "runner1" / "work")]
        with self.assertRaises(SystemExit) as e:
            direct.main()
        self.assertEqual(e.exception.code, direct.WAIT_EXIT)
        # the workflow's save step: copy out/<id>/ into previews/<id>/, commit, push
        dest = self.tmp / "private" / "previews" / "test-video"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run1_out, dest, dirs_exist_ok=True)
        git("add", "previews", cwd=self.tmp / "private")
        git("commit", "-q", "-m", "waiting", cwd=self.tmp / "private")
        git("push", "-q", str(origin), "HEAD:main", cwd=self.tmp / "private")
        # runner 2: nothing of runner 1 exists except what was pushed
        shutil.rmtree(self.tmp / "runner1")
        shutil.rmtree(self.tmp / "private")
        fresh = self.tmp / "runner2" / "private"
        git("clone", "-q", str(origin), str(fresh))
        direct.ROUNDS.clear()
        CALLS.clear()
        later = []

        def answers(kind, prompt, compact=None, **kw):
            later.append(kind)
            CALLS.append({"kind": kind, "provider": "github"})
            return {"lines": []}
        llm.call_json = answers
        sys.argv = ["direct", "--id", "test-video", "--private", str(fresh), "--out",
                    str(self.tmp / "runner2" / "out" / "test-video"), "--work", str(self.tmp / "runner2" / "work")]
        with self.assertRaises(SystemExit):
            direct.main()
        self.assertEqual(len(self.aligned), 1)                          # the alignment came from the checkpoint
        self.assertEqual(len(later), direct.PLAN_CALLS - len(calls))     # the budget carried over: 3 in total
        st = json.loads((self.tmp / "runner2" / "out" / "test-video" / "status.json").read_text())
        self.assertEqual(st["state"], "failed")                          # resumed, ran out of plan calls honestly


if __name__ == "__main__":
    unittest.main()


class Acceptance(unittest.TestCase):
    """Correction 6 (run #16 said ok: true with verdict fixed_not_rereviewed): only a genuine passing vision review of
    the final video, with every gate passed, is accepted."""
    GATES = {"collisions": True, "coverage": True, "audit": True}

    def test_rule(self):
        self.assertEqual(direct.accepted(self.GATES, {"verdict": "pass"}), (True, ""))
        for rev in ({"verdict": "fail", "summary": "chalkboard held"}, {"verdict": "fixed_not_rereviewed"},
                    {"verdict": "pending"}, {}, None):
            ok, why = direct.accepted(self.GATES, rev)
            self.assertFalse(ok, rev)
            self.assertTrue(why)
        self.assertFalse(direct.accepted(dict(self.GATES, coverage=False), {"verdict": "pass"})[0])
        self.assertFalse(direct.accepted({}, {"verdict": "pass"})[0])


def tiny_video(path: Path, seconds: float = 3.0) -> Path:
    """A real, small 1080x1920 MP4 with audio (what the renderer would leave), for the save tests."""
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-shortest", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


class ReviewBlocks(Budget):
    """The whole main(): every gate passes, then the vision review decides the status, and the saved video, its
    review, gates and status always belong together."""

    def fake_result(self, n: int = 1, times: bool = True, video: bool = True):
        work = self.tmp / f"work_ok{n}"
        work.mkdir(exist_ok=True)
        if times:
            (work / "preview_times.json").write_text("[1.0, 2.0]")
        mp4 = work / "v.mp4"
        if video:
            tiny_video(mp4)
        else:
            mp4.write_bytes(b"not a video")
        return {"plan": {"lines": []}, "scene": {"tag": n}, "frames": [], "media": [], "gates": {"coverage": {"ok": True}},
                "mp4": mp4, "work": work, "attempt": n}

    def run_with_review(self, verdicts, fix_passes=True, first=None, second=None):
        from kindled_iron.director import review as reviewmod
        real = (reviewmod.review, reviewmod.fixes)
        it = iter(verdicts)

        def plan(kind, prompt, compact=None, **kw):
            CALLS.append({"kind": kind, "provider": "gemini"})
            return {"lines": []}
        llm.call_json = plan
        tries = []

        def attempt(*a):
            tries.append(1)
            if len(tries) == 1:
                return first() if first else self.fake_result(1)
            return (second() if second else self.fake_result(2)) if fix_passes else None
        direct.attempt = attempt
        reviewmod.review = lambda *a: {"verdict": next(it), "summary": "the review's words"}
        reviewmod.fixes = lambda rev, beats: ["fix it"]
        sys.argv = ["direct", "--id", "test-video", "--private", str(self.tmp / "private"), "--out", str(self.out),
                    "--work", str(self.tmp / "work")]
        code = None
        try:
            direct.main()
        except SystemExit as e:
            code = e.code
        finally:
            reviewmod.review, reviewmod.fixes = real
        return code, json.loads((self.out / "status.json").read_text())

    def saved(self):
        from kindled_iron.director import bundle
        ok, why = bundle.consistent(self.out, "test-video")
        self.assertTrue(ok, why)
        return bundle.read_manifest(self.out), json.loads((self.out / "review.json").read_text())

    def test_passing_review_is_ok_and_everything_matches_the_saved_video(self):
        code, st = self.run_with_review(["pass"])
        self.assertIsNone(code)
        self.assertTrue(st["ok"])
        self.assertEqual(st["state"], "done")
        man, rev = self.saved()
        self.assertEqual((man["review"], man["accepted"], rev["verdict"]), ("pass", True, "pass"))
        self.assertEqual(st["video"]["sha256"], man["sha256"])
        self.assertFalse((self.out / "fail_report.md").exists())

    def test_failed_review_is_not_ok(self):
        code, st = self.run_with_review(["fail"], fix_passes=False)     # the fix round fails its gates
        self.assertIn("FAIL", str(code))
        self.assertFalse(st["ok"])
        self.assertEqual(st["state"], "failed")
        self.assertIn("vision review failed", (self.out / "fail_report.md").read_text())
        man, rev = self.saved()                   # the reviewed render is saved, with ITS failed review
        self.assertEqual((man["review"], man["accepted"], man["plan_attempt"]), ("fail", False, 1))
        self.assertEqual(json.loads((self.out / "scene.json").read_text()), {"tag": 1})

    def test_a_failed_revision_never_touches_the_reviewed_render(self):
        """Run 40543404619: the fix round deleted the reviewed render's folder and the save crashed on
        preview_times.json. Now the first render stays complete and is saved with its own review."""
        first = self.fake_result(1)
        mp4_before = first["mp4"].read_bytes()
        code, st = self.run_with_review(["fail"], fix_passes=False, first=lambda: first)
        self.assertEqual(first["mp4"].read_bytes(), mp4_before)
        self.assertTrue((first["work"] / "preview_times.json").exists())
        man, rev = self.saved()
        from kindled_iron.director import bundle
        self.assertEqual(man["sha256"], bundle.sha256(first["mp4"]))
        self.assertEqual(rev["verdict"], "fail")
        self.assertFalse(st["ok"])

    def test_revised_after_review_is_saved_but_not_ok(self):
        code, st = self.run_with_review(["fail"])            # the fix round re-renders and passes the gates
        self.assertEqual(st["verdict"], "fixed_not_rereviewed")
        self.assertFalse(st["ok"])
        self.assertIn("not reviewed again", (self.out / "fail_report.md").read_text())
        man, rev = self.saved()                   # the newest complete render, never inheriting the old review
        self.assertEqual((man["plan_attempt"], man["review"], man["accepted"]), (2, "fixed_not_rereviewed", False))
        self.assertEqual(rev["previous_review"]["verdict"], "fail")

    def test_missing_preview_times_is_recorded_not_a_crash(self):
        code, st = self.run_with_review(["pass"], first=lambda: self.fake_result(1, times=False))
        self.assertIn("FAIL", str(code))
        self.assertFalse(st["ok"])
        self.assertEqual(st["verdict"], "not_reviewed")
        man, rev = self.saved()
        self.assertEqual(rev["verdict"], "not_reviewed")
        self.assertIn("preview_times.json missing", " ".join(man["notes"]))

    def test_an_invalid_render_never_replaces_the_complete_preview(self):
        self.run_with_review(["pass"])                                   # a good preview exists
        good, _ = self.saved()
        direct.ROUNDS.clear()
        CALLS.clear()
        direct.ATTEMPTS[0] = 0
        code, st = self.run_with_review(["pass"], first=lambda: self.fake_result(3, video=False))
        self.assertFalse(st["ok"])
        self.assertFalse(st["video_saved"])
        self.assertIn("save_error", st)
        man, rev = self.saved()
        self.assertEqual(man["sha256"], good["sha256"])                 # the old one, untouched and still consistent


class Bundle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "previews" / "v"
        self.out.mkdir(parents=True)

    def test_interrupted_save_changes_nothing(self):
        from kindled_iron.director import bundle
        good = tiny_video(self.tmp / "a.mp4")
        bundle.write(self.out, "v", good, {"review.json": {"verdict": "pass"}}, manifest={"review": "pass"})
        before = bundle.read_manifest(self.out)
        new = tiny_video(self.tmp / "b.mp4", 3.5)
        real = bundle.os.replace
        calls = []

        def boom(a, b):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk full")
            return real(a, b)
        bundle.os.replace = boom
        try:
            with self.assertRaises(OSError):
                bundle.write(self.out, "v", new, {"review.json": {"verdict": "fail"}}, manifest={"review": "fail"})
        finally:
            bundle.os.replace = real
        self.assertEqual(bundle.read_manifest(self.out)["sha256"], before["sha256"])
        self.assertTrue(bundle.consistent(self.out, "v")[0])
        self.assertFalse((self.out / ".staging").exists())

    def test_incomplete_or_wrong_videos_are_refused(self):
        from kindled_iron.director import bundle
        short = tiny_video(self.tmp / "short.mp4", 1.0)
        with self.assertRaises(bundle.BundleError):
            bundle.verify_mp4(short, expect_seconds=10.0)               # stopped early
        (self.tmp / "junk.mp4").write_bytes(b"x" * 60000)
        with self.assertRaises(bundle.BundleError):
            bundle.verify_mp4(self.tmp / "junk.mp4")
        with self.assertRaises(bundle.BundleError):
            bundle.verify_mp4(self.tmp / "missing.mp4")
        self.assertEqual(bundle.verify_mp4(short)["width"], 1080)

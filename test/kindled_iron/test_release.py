"""The release path (generate -> owner approval -> buffer -> publish), offline: every refusal the owner asked for,
2026-10-28. No network, no platform call: the publisher's platforms are replaced by fakes."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kindled_iron import publish, release
from kindled_iron.director import bundle

VID = "why-cats-purr"
META = {"scene": VID, "voice": {"provider_used": "owner", "source_sha256": "ab" * 32, "regenerated": False,
                                "fallback": False},
        "verse_check": [{"ref": "John 11:35", "ok": True}], "audio": {"true_peak": -2.9, "lf_burst": -7.0},
        "checks_failed": None}


HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg (CI runs this in its FFmpeg pass)")
class Release(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = Path(tempfile.mkdtemp())
        cls.mp4 = cls.media / "v.mp4"                  # a real, decodable 1080x1920 video with audio
        ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.mp4))
        cls.mp3 = cls.media / "n.mp3"
        ff("-f", "lavfi", "-i", "sine=f=220:d=8", "-c:a", "libmp3lame", "-b:a", "64k", str(cls.mp3))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        a = self.root / "approved_audio" / VID
        a.mkdir(parents=True)
        shutil.copyfile(self.mp3, a / "narration.mp3")
        (a / "script.txt").write_text("Cats purr when they are happy. And when they heal.")
        self.ledger = self.root / "approved" / "posted.json"
        self.ledger.parent.mkdir()
        self.ledger.write_text("{}")

    def preview(self, accepted=True, meta=None, out=None):
        out = out or self.root / "previews" / VID
        out.mkdir(parents=True, exist_ok=True)
        mp4 = self.root / "render.mp4"
        shutil.copyfile(self.mp4, mp4)
        metaf = self.root / "render_meta.json"
        metaf.write_text(json.dumps(meta or META))
        man = {"id": VID, "accepted": accepted, "review": "pass" if accepted else "fail",
               "not_accepted_because": None if accepted else "the vision review failed: text over the guide",
               "narration_sha256": bundle.sha256(self.root / "approved_audio" / VID / "narration.mp3"),
               "gates": {"render": True}}
        return bundle.write(out, VID, mp4, {"scene.json": {"title": "Why Cats Purr", "post": {"title": "Why Cats Purr"},
                                                           "beats": []}},
                            {f"{VID}-meta.json": metaf}, man)

    def approve(self, **kw):
        args = dict(actor="Venloud", confirm=VID, ledger=self.ledger)
        args.update(kw)
        return release.approve(self.root, VID, **args)

    # ---------------------------------------------------------------- workflow 1 inputs
    def test_no_mp3(self):
        (self.root / "approved_audio" / VID / "narration.mp3").unlink()
        with self.assertRaisesRegex(release.Refused, "no MP3"):
            release.check_input(self.root, VID)

    def test_invalid_mp3(self):
        (self.root / "approved_audio" / VID / "narration.mp3").write_bytes(b"ID3" + os.urandom(20000))
        with self.assertRaisesRegex(release.Refused, "not a readable audio file|holds no MP3"):
            release.check_input(self.root, VID)
        wav = self.root / "x.wav"                       # a real audio file that is not an MP3
        ff("-f", "lavfi", "-i", "sine=d=8", str(wav))
        shutil.copyfile(wav, self.root / "approved_audio" / VID / "narration.mp3")
        with self.assertRaisesRegex(release.Refused, "holds no MP3"):
            release.check_input(self.root, VID)

    def test_valid_input_and_bad_id(self):
        r = release.check_input(self.root, VID)
        self.assertAlmostEqual(r["seconds"], 8.0, delta=0.2)
        with self.assertRaisesRegex(release.Refused, "lowercase"):
            release.check_input(self.root, "Bad Id")

    def test_render_failure_keeps_the_last_valid_preview(self):
        self.preview(accepted=True)
        before = bundle.read_manifest(self.root / "previews" / VID)["sha256"]
        failed = self.root / "out" / VID                # a run that crashed: status + fail report, no video
        failed.mkdir(parents=True)
        (failed / "status.json").write_text('{"state": "failed"}')
        (failed / "fail_report.md").write_text("render crashed")
        msg = release.save_preview(failed, self.root / "previews" / VID)
        self.assertIn("kept the previous video", msg)
        self.assertEqual(bundle.read_manifest(self.root / "previews" / VID)["sha256"], before)
        self.assertTrue((self.root / "previews" / VID / "fail_report.md").is_file())
        # a complete video that was NOT accepted never replaces an accepted one either
        rejected = self.root / "out2" / VID
        self.preview(accepted=False, out=rejected)
        self.assertIn("kept the previous ACCEPTED", release.save_preview(rejected, self.root / "previews" / VID))
        self.assertTrue(bundle.read_manifest(self.root / "previews" / VID)["accepted"])

    def test_new_accepted_video_replaces_the_preview_in_place(self):
        self.preview(accepted=False)
        new = self.root / "out" / VID
        self.preview(accepted=True, out=new)
        self.assertIn("saved the new video", release.save_preview(new, self.root / "previews" / VID))
        self.assertTrue(bundle.read_manifest(self.root / "previews" / VID)["accepted"])
        self.assertEqual(sorted(p.name for p in (self.root / "previews").iterdir()), [VID])   # no attempt folders
        self.assertFalse((self.root / "previews" / VID / ".incoming").exists())

    # ---------------------------------------------------------------- workflow 2 approval
    def test_failed_visual_review_cannot_be_approved(self):
        self.preview(accepted=False)
        with self.assertRaisesRegex(release.Refused, "vision review failed"):
            self.approve()
        self.assertEqual(release.buffered(self.root), [])

    def test_failed_audio_gate_cannot_be_approved(self):
        self.preview(meta=dict(META, audio={"true_peak": -0.3, "lf_burst": -7.0}))
        with self.assertRaisesRegex(release.Refused, "audio check failed"):
            self.approve()
        self.preview(meta=dict(META, voice={"provider_used": "kokoro", "fallback": True}))
        with self.assertRaisesRegex(release.Refused, "fallback voice"):
            self.approve()

    def test_missing_approval_needs_the_owner_and_the_typed_id(self):
        self.preview()
        with self.assertRaisesRegex(release.Refused, "may not approve"):
            self.approve(actor="someone-else")
        with self.assertRaisesRegex(release.Refused, "not confirmed"):
            self.approve(confirm="")
        with self.assertRaisesRegex(release.Refused, "no finished video"):
            release.approve(self.root, "other-video", "Venloud", "other-video")
        e = self.approve()
        self.assertEqual((e["approved_by"], e["sha256"]), ("Venloud", bundle.sha256(self.root / "previews" / VID / f"{VID}.mp4")))
        self.assertTrue(e["approved_at"])
        self.assertEqual(e["post"]["title"], "Why Cats Purr")
        with self.assertRaisesRegex(release.Refused, "already in the buffer"):
            self.approve()

    def test_changed_narration_cannot_be_approved(self):
        self.preview()
        ff("-f", "lavfi", "-i", "sine=f=300:d=9", "-c:a", "libmp3lame", str(self.root / "approved_audio" / VID / "narration.mp3"))
        with self.assertRaisesRegex(release.Refused, "narration MP3 changed"):
            self.approve()

    # ---------------------------------------------------------------- workflow 3 publishing
    def test_empty_buffer(self):
        self.preview()                                   # rendered and accepted, but never approved
        with self.assertRaisesRegex(release.Refused, "buffer is empty"):
            release.select(self.root, VID, self.ledger)

    def test_video_modified_after_approval(self):
        self.preview()
        self.approve()
        with open(self.root / "previews" / VID / f"{VID}.mp4", "ab") as f:
            f.write(b"\0")
        with self.assertRaisesRegex(release.Refused, "changed after approval"):
            release.select(self.root, VID, self.ledger)

    def publish_run(self, sel, platforms, behaviour):
        """publish.main with fake platforms: behaviour[p] = 'ok' | 'fail' | 'no_credentials'."""
        def fake(p):
            def check():
                if behaviour[p] == "no_credentials":
                    raise publish.Fail(f"secret(s) missing: {p.upper()}_TOKEN")
                return {}

            def post(v, post, mode, chk, url=None):
                if behaviour[p] == "fail":
                    raise RuntimeError(f"{p} API error 500")
                self.calls.append(p)
                return {"id": f"{p}-1", "url": f"https://{p}.example/1", "mode": "live"}
            return check, post
        out = self.root / "publish_results.json"
        argv = ["publish", "--video", sel["video_path"], "--meta", sel["meta_path"], "--post", sel["post_path"],
                "--only", ",".join(sel["remaining"]), "--ledger", str(self.ledger), "--render-name", sel["render_name"],
                "--out", str(out)]
        with mock.patch.object(publish, "PLATFORMS", {p: fake(p) for p in platforms}), \
                mock.patch.dict(publish.CONFIG["publish_mode"], {p: "live" for p in platforms}, clear=True), \
                mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}):
            try:
                publish.main()
            except SystemExit:
                pass
        return release.finish(self.root, VID, self.ledger, out)

    def test_partial_failure_then_retry_without_duplicates(self):
        self.calls = []
        self.preview()
        plats = ["tiktok", "youtube", "threads"]
        with mock.patch.dict(publish.CONFIG["publish_mode"], {p: "live" for p in plats}, clear=True), \
                mock.patch.object(publish, "PLATFORMS", {p: None for p in plats}):
            self.approve()
            sel = release.select(self.root, VID, self.ledger)
        r = self.publish_run(sel, plats, {"tiktok": "ok", "youtube": "fail", "threads": "no_credentials"})
        self.assertEqual(r["state"], "approved")                            # not finished: stays in the buffer
        self.assertTrue(r["platforms"]["tiktok"]["ok"])
        self.assertIn("500", r["platforms"]["youtube"]["error"])
        self.assertIn("secret(s) missing", r["platforms"]["threads"]["error"])   # missing credentials: skipped
        with mock.patch.dict(publish.CONFIG["publish_mode"], {p: "live" for p in plats}, clear=True), \
                mock.patch.object(publish, "PLATFORMS", {p: None for p in plats}):
            sel = release.select(self.root, VID, self.ledger)
        self.assertEqual(sel["remaining"], ["youtube", "threads"])          # TikTok is never posted again
        r = self.publish_run(sel, plats, {"tiktok": "ok", "youtube": "ok", "threads": "ok"})
        self.assertEqual(r["state"], "published")
        self.assertEqual(self.calls, ["tiktok", "youtube", "threads"])      # each platform exactly once

    def test_duplicate_publish_attempt(self):
        self.calls = []
        self.preview()
        with mock.patch.dict(publish.CONFIG["publish_mode"], {"youtube": "live"}, clear=True), \
                mock.patch.object(publish, "PLATFORMS", {"youtube": None}):
            self.approve()
            sel = release.select(self.root, VID, self.ledger)
            self.publish_run(sel, ["youtube"], {"youtube": "ok"})
            with self.assertRaisesRegex(release.Refused, "buffer is empty"):    # published: no longer waiting
                release.select(self.root, VID, self.ledger)
            with self.assertRaisesRegex(release.Refused, "already posted"):     # and it cannot be approved again
                self.approve()
        self.assertEqual(self.calls, ["youtube"])
        # even with the buffer entry put back, the ledger alone stops a second post
        e = json.loads((self.root / "buffer" / f"{VID}.json").read_text())
        (self.root / "buffer" / f"{VID}.json").write_text(json.dumps(dict(e, state="approved")))
        with mock.patch.dict(publish.CONFIG["publish_mode"], {"youtube": "live"}, clear=True), \
                mock.patch.object(publish, "PLATFORMS", {"youtube": None}):
            with self.assertRaisesRegex(release.Refused, "already posted"):
                release.select(self.root, VID, self.ledger)


class Workflows(unittest.TestCase):
    """The three workflows are manual only, and only workflow 3 posts."""

    def test_triggers_and_roles(self):
        wf = Path(__file__).resolve().parents[2] / ".github" / "workflows"
        names = {"kindled_iron_director_preview.yml": "Kindled Iron 1 - Generate Video",
                 "kindled_iron_approve.yml": "Kindled Iron 2 - Approve and Add to Buffer",
                 "kindled_iron_publish.yml": "Kindled Iron 3 - Publish Everywhere"}
        for f, name in names.items():
            text = (wf / f).read_text()
            self.assertIn(f'name: "{name}"', text)
            on = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
            self.assertNotRegex(on, r"(?m)^\s+schedule:", f)                     # no active schedule
            self.assertNotRegex(on, r"(?m)^\s+(push|pull_request):", f)
            self.assertEqual(("kindled_iron.publish --video" in text), f == "kindled_iron_publish.yml", f)
        self.assertIn("release select", (wf / "kindled_iron_publish.yml").read_text())
        self.assertIn("release approve", (wf / "kindled_iron_approve.yml").read_text())
        self.assertIn("release save-preview", (wf / "kindled_iron_director_preview.yml").read_text())


if __name__ == "__main__":
    unittest.main()

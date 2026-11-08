"""Openverse still insets (offline: mocked API and download, real ffmpeg for the frame sequence)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kindled_iron import insets


def hit(i, lic, **kw):
    return {"id": f"ov{i}", "title": f"Stoic bust {i}", "url": f"https://img.example/{i}.jpg",
            "foreign_landing_url": f"https://src.example/{i}", "creator": f"maker{i}", "license": lic,
            "license_version": "1.0", "license_url": f"https://creativecommons.org/{lic}", "width": 1200, "height": 900, **kw}


BODY = {"results": [hit(1, "by"), hit(2, "cc0"), hit(3, "by-sa"), hit(4, "pdm", mature=True),
                    hit(5, "pdm", width=300), hit(6, "pdm")]}


class OpenverseInsets(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = patch.dict(os.environ, {"KI_CLIP_CACHE": str(self.tmp / "cache"), "KI_OPENVERSE": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_off_by_default(self):
        with patch.dict(os.environ, {"KI_OPENVERSE": ""}), patch.object(insets, "_json") as j:
            self.assertEqual(insets._openverse("marcus aurelius", None), [])
            j.assert_not_called()

    def test_cc0_and_public_domain_only(self):
        with patch.object(insets, "_json", return_value=BODY) as j:
            got = insets._openverse("marcus aurelius statue", None)
            self.assertIn("license=cc0%2Cpdm", j.call_args.args[0])
        self.assertEqual([g["id"] for g in got], ["ov2", "ov6"], "CC BY, SA, mature and tiny images are refused")
        self.assertTrue(all(g["still"] and g["page"] and g["creator"] for g in got))
        self.assertEqual(got[1]["license_name"], "Public Domain Mark 1.0")
        with patch.object(insets, "_json") as j:  # second search is cached
            self.assertEqual(len(insets._openverse("marcus aurelius statue", None)), 2)
            j.assert_not_called()

    def test_invalid_response(self):
        with patch.object(insets, "_json", return_value={"detail": "throttled"}):
            with self.assertRaises(ValueError):
                insets._openverse("broken", None)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_fetch_holds_still_and_records_rights(self):
        img = self.tmp / "still.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=800x600", "-frames:v", "1",
                        str(img)], check=True)
        scene = {"beats": [{"events": [{"do": "draw", "type": "inset", "id": "i1", "query": "stoic bust",
                                        "sources": ["pexels", "openverse"], "clip_dur": 2.0}]}]}

        def down(url, ext=".mp4"):
            return img

        with patch.object(insets, "_json", return_value=BODY), patch("kindled_iron.openverse_assets.acquire", return_value=(img, {"source_verified": True})), \
                patch.dict(insets.SEARCH, {"pexels": lambda q, p: (_ for _ in ()).throw(RuntimeError("no key"))}), \
                patch.object(insets, "contact_sheet"):
            found = insets.fetch(scene, self.tmp / "work", lambda *a: None)
        self.assertEqual(len(found["i1"]["frames"]), 60)
        src = json.loads((self.tmp / "work" / "sources.json").read_text())[0]
        self.assertEqual((src["source"], src["id"], src["still"]), ("openverse", "ov2", True))
        self.assertIn("CC0", src["license"])
        self.assertTrue(src["creator"] and src["license_url"] and src["page"])

    def test_default_order_unchanged_when_off(self):
        with patch.dict(os.environ, {"KI_OPENVERSE": ""}):
            self.assertEqual(insets.DEFAULT_ORDER, ["pexels", "pixabay", "commons"])


if __name__ == "__main__":
    unittest.main()

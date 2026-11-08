"""Shared local asset library (Venloud/vandam-assets), offline: throwaway library, fake providers, no network.

Skipped when vandam_assets is not importable (CI does not install it)."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from vandam_assets import Library
except ImportError:  # pragma: no cover
    Library = None

from kindled_iron import insets, mediabox
from kindled_iron.director import media


def clip(path: Path, color: str) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x36:d=3", "-r", "30",
                    str(path)], check=True)
    return path


@unittest.skipIf(Library is None, "vandam_assets not installed")
class AssetLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("VANDAM_ASSET_LIBRARY", "KI_BOX_PLACEHOLDER", "KI_CLIP_CACHE")}
        os.environ.update({"VANDAM_ASSET_LIBRARY": str(self.tmp / "lib"), "KI_CLIP_CACHE": str(self.tmp / "cache")})
        os.environ.pop("KI_BOX_PLACEHOLDER", None)
        self.real = insets._pexels, insets._pixabay
        self.calls = []
        insets._pexels = lambda q, pin: self.calls.append(q) or []
        insets._pixabay = lambda q, pin: []
        self.lib = Library(self.tmp / "lib")

    def tearDown(self):
        insets._pexels, insets._pixabay = self.real
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def add(self, name, color, license, video="old-1"):
        return self.lib.add(clip(self.tmp / name, color), {
            "kind": "video", "provider": "pexels", "source_url": f"https://www.pexels.com/video/{name}/",
            "license": license, "title": "hammer hitting a nail", "tags": ["hammer", "nail"]}, "openmontage", video)

    def test_stock_uses_library_before_pexels(self):
        rec = self.add("hammer.mp4", "red", "Pexels License: free to use, no attribution required")
        hit = media.stock("hammer nail", [], {}, lambda m: None)
        self.assertEqual((hit["source"], hit["id"]), ("library", rec["id"]))
        self.assertEqual(self.calls, [], "Pexels is not called when the library has the shot")

    def test_cc_by_is_never_taken(self):
        self.add("hammer_by.mp4", "blue", "CC BY 4.0")
        self.assertIsNone(media.stock("hammer nail", [], {}, lambda m: None))
        self.assertEqual(self.calls, ["hammer nail"], "falls through to Pexels")

    def test_mediabox_fetches_pinned_library_clip_and_records_licence(self):
        rec = self.add("hammer.mp4", "red", "Pixabay Content License")
        c, f, length = mediabox._source({"library": rec["id"]}, "s_library_x", {}, lambda m: None, "ep1")
        self.assertEqual(c["source"], "library")
        self.assertGreater(length, 2.5)
        self.assertIn("Pixabay", insets.LICENSES["library"].format(lic=c["license_name"]))

    def test_downloaded_stock_is_saved_for_next_video(self):
        src = clip(self.tmp / "dl.mp4", "green")
        c = {"source": "pexels", "id": "9", "file_url": src.as_uri(), "page": "https://www.pexels.com/video/storm-9/",
             "title": "https://www.pexels.com/video/storm-9/"}
        insets.save_to_library(c, src, "storm clouds lightning", "ep2")
        hits = self.lib.find("storm clouds", "video", "openmontage")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["license_key"], "pexels")


if __name__ == "__main__":
    unittest.main()

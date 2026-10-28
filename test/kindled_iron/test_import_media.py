"""The private media import tool, on a throwaway library (no real media)."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "kindled_iron" / "tools" / "import_media.py"


def png(path: Path, color: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=32x32", "-frames:v", "1",
                    str(path)], check=True)


class ImportMedia(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = self.tmp / "voice"
        (self.lib / "reactions").mkdir(parents=True)
        (self.lib / "movie_reference").mkdir(parents=True)
        png(self.lib / "reactions" / "old_meme.png", "red")
        (self.lib / "reactions" / "index.json").write_text(json.dumps(
            {"_help": "keep me", "items": [{"file": "old_meme.png", "tags": ["old"]}]}))
        png(self.lib / "movie_reference" / "taken_name.png", "green")

    def pack(self, assets, files):
        src = self.tmp / "pack"
        for rel, color in files.items():
            (src / "kindled-media-library" / rel).parent.mkdir(parents=True, exist_ok=True)
            png(src / "kindled-media-library" / rel, color)
        (src / "kindled-media-library" / "catalog.json").write_text(json.dumps({"assets": assets}))
        z = self.tmp / "pack.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in src.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(src))
        return z

    def run_tool(self, z, *extra):
        p = subprocess.run([sys.executable, str(TOOL), "--zip", str(z), "--private", str(self.lib), *extra],
                           capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    def test_merge_keeps_existing_skips_duplicates_never_overwrites(self):
        assets = [{"id": "dup", "path": "memes/dup.png", "type": "meme", "tags": ["x"]},             # same bytes as old
                  {"id": "new_meme", "path": "memes/new.png", "type": "meme", "tags": ["happy"]},
                  {"id": "taken_name", "path": "stills/t.png", "type": "still", "tags": ["y"]},     # name taken
                  {"id": "helping", "path": "refs/h.png", "type": "guide_action", "tags": ["help"]}]
        z = self.pack(assets, {"memes/dup.png": "red", "memes/new.png": "blue", "stills/t.png": "yellow",
                               "refs/h.png": "white"})
        code, rep = self.run_tool(z)
        self.assertEqual(code, 0)
        self.assertEqual([d["id"] for d in rep["skipped_duplicates"]], ["dup"])
        self.assertTrue((self.lib / "movie_reference" / "taken_name_2.png").exists())   # renamed, not overwritten
        self.assertTrue((self.lib / "movie_reference" / "guide_actions" / "helping.png").exists())
        idx = json.loads((self.lib / "reactions" / "index.json").read_text())
        self.assertEqual(idx["_help"], "keep me")
        self.assertEqual(idx["items"][0], {"file": "old_meme.png", "tags": ["old"]})       # untouched
        self.assertEqual([i["file"] for i in idx["items"]], ["old_meme.png", "new_meme.png"])
        mr = json.loads((self.lib / "movie_reference" / "index.json").read_text())
        ga = next(i for i in mr["items"] if i["id"] == "helping")
        self.assertFalse(ga["show"])
        self.assertEqual(ga["type"], "guide_action_reference")
        code2, rep2 = self.run_tool(z)                      # importing twice changes nothing
        self.assertEqual(rep2["imported"], [])

    def test_missing_file_and_bad_hash_are_reported(self):
        assets = [{"id": "ghost", "path": "memes/none.png", "type": "meme"},
                  {"id": "bad", "path": "memes/b.png", "type": "meme", "sha256": "0" * 64}]
        z = self.pack(assets, {"memes/b.png": "blue"})
        code, rep = self.run_tool(z)
        self.assertEqual(code, 1)
        self.assertEqual({e["id"] for e in rep["errors"]}, {"ghost", "bad"})
        self.assertEqual(rep["imported"], [])

    def test_dry_run_writes_nothing(self):
        z = self.pack([{"id": "n", "path": "m/n.png", "type": "meme"}], {"m/n.png": "blue"})
        before = sorted(p.as_posix() for p in self.lib.rglob("*"))
        self.run_tool(z, "--dry-run")
        self.assertEqual(sorted(p.as_posix() for p in self.lib.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()

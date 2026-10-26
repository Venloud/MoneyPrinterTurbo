"""Offline checks for the Kindled Iron director, no network or MP3 needed."""
import unittest
from kindled_iron.director.direct import norm, split_beats, validate


class DirectorTests(unittest.TestCase):
    def test_split_paragraphs(self):
        self.assertEqual(split_beats("One sentence.\n\nSecond sentence."),
                         ["One sentence.", "Second sentence."])

    def test_normalization(self):
        self.assertEqual(norm("God's power!"), ["god", "s", "power"])

    def test_accept_exact_scene(self):
        lines = ["God is good and powerful."]
        obj = {"beats": [{
            "id": "one", "panel": 0, "narration": lines[0],
            "events": [
                {"at": 0, "do": "draw", "id": "obj1", "type": "word",
                 "text": "GOOD", "x": 350, "y": 1080, "size": 70},
                {"at": "powerful", "do": "point", "who": "guide", "toward": "obj1"},
            ],
        }]}
        self.assertEqual(validate(obj, lines), [])

    def test_reject_rewrite(self):
        self.assertTrue(validate({"beats": [{"narration": "changed", "events": [
            {"at": 0, "do": "express", "who": "guide", "expression": "happy"}]}]},
            ["Original words."]))

    def test_reject_unverified_media(self):
        self.assertTrue(validate({"beats": [{"narration": "Hello", "events": [
            {"at": 0, "box": "clip", "file": "unverified.mp4"}]}]},
            ["Hello"]))

    def test_reject_invented_action(self):
        self.assertTrue(validate({"beats": [{"narration": "Hello", "events": [
            {"at": 0, "do": "publish"}]}]}, ["Hello"]))


if __name__ == "__main__":
    unittest.main()

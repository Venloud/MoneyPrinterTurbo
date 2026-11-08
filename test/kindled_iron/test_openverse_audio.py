"""Offline library-build integration: no provider calls or production audio writes."""
import json
from unittest.mock import patch

import pytest

from kindled_iron import sfx_library as lib
from kindled_iron import openverse_assets as ov


def test_audio_search_maps_milliseconds():
    hit = {"id": "x", "url": "https://cdn.example/x", "foreign_landing_url": "https://source.example/x",
           "license_url": "https://creativecommons.org/publicdomain/zero/1.0/", "duration": 2000}
    with patch.object(ov, "search", return_value=[hit]) as search:
        row = lib.openverse_search("wind")[0]
    assert row["duration"] == 2 and row["openverse_hit"] == hit
    search.assert_called_once_with("audio", "wind", ("cc0",))


@pytest.mark.parametrize("bad_first", [False, True])
def test_library_fallback_verifies_rights_and_skips_bad_candidate(tmp_path, monkeypatch, bad_first):
    monkeypatch.setenv("KI_OPENVERSE_AUDIO", "1")
    monkeypatch.setattr(lib, "LIB", tmp_path / "lib")
    monkeypatch.setattr(lib, "ROLES", {"sample": {"q": ["wind"], "loop": 1, "src": 1, "seg": (.1, .2)}})
    row = {"id": "ov-x", "title": "wind", "author": "maker", "duration": 2, "downloads": 0,
           "url": "https://source.example/x", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
           "mp3": "https://cdn.example/x", "source": "openverse", "openverse_hit": {"id": "x"}}
    candidates = [{**row, "id": "ov-bad"}, row] if bad_first else [row]
    result = (tmp_path / "cached", {"source_verified": True, "license": "cc0", "sha256": "abc"})
    outcomes = [ValueError("unverified source"), result] if bad_first else [result]
    with patch.object(lib, "freesound_search", return_value=[]), patch.object(lib, "openverse_search", return_value=candidates), \
            patch.object(ov, "acquire", side_effect=outcomes), patch.object(lib, "decode", return_value=[0]), \
            patch.object(lib, "make_loop", return_value=[0]), patch.object(lib, "encode"):
        lib.build(["sample"], False, {})
    saved = json.loads((tmp_path / "lib/sources.json").read_text())
    assert len(saved) == 1 and saved[0]["source"] == "openverse"
    assert saved[0]["rights"]["source_verified"]

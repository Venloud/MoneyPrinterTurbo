"""Stock provider compatibility: Openverse still fallback is explicitly opt-in."""
from unittest.mock import patch

import pytest

from app.services import material
from kindled_iron import openverse_assets as ov


@pytest.mark.parametrize("enabled", [False, True])
def test_stock_empty_optional_fallback(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("MPT_OPENVERSE", "1" if enabled else "")
    with patch.object(material, "_search_terms_in_parallel", return_value=[]), \
            patch.object(material, "_persist_material_sources") as persist, \
            patch.object(ov, "first", return_value=(tmp_path / "image", {"license": "cc0", "source_verified": True})) as get, \
            patch.object(material.video, "render_image_zoom_video", return_value=str(tmp_path / "clip.mp4")):
        got = material.download_videos("test", ["ancient statue"], audio_duration=2)
    assert bool(got) == enabled
    assert get.call_count == int(enabled)
    if enabled:
        assert persist.call_args.args[1][0]["license"] == "cc0"


def test_provider_failure_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.setenv("MPT_OPENVERSE", "1")
    with patch.object(material, "_search_terms_in_parallel", return_value=[]), \
            patch.object(material, "_persist_material_sources"), \
            patch.object(ov, "first", side_effect=RuntimeError("rate limit")):
        assert material.download_videos("test", ["statue"], audio_duration=2) == []


def test_sufficient_stock_does_not_call_openverse(monkeypatch):
    monkeypatch.setenv("MPT_OPENVERSE", "1")
    with patch.object(material, "_search_terms_in_parallel", return_value=[]), \
            patch.object(material, "_persist_material_sources"), patch.object(ov, "first") as get:
        material.download_videos("test", ["statue"], audio_duration=0)
    get.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_script_order_empty_optional_fallback(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("MPT_OPENVERSE", "1" if enabled else "")
    with patch.object(material, "_search_terms_in_parallel", return_value=[]):
        with patch.object(material, "_persist_material_sources"), patch.object(ov, "first", return_value=(tmp_path / "image", {"license": "cc0"})) as get, patch.object(material.video, "render_image_zoom_video", return_value=str(tmp_path / "clip.mp4")):
            got = material.download_videos("test", ["ancient statue"], audio_duration=2, match_script_order=True)
    assert bool(got) == enabled
    assert get.call_count == int(enabled)

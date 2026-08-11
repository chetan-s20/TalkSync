"""Boundary and Adversarial Edge Case tests for PyWebView ApiBridge."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

try:
    from app.bridge import ApiBridge
except ImportError:
    from tests.unit.test_bridge_api import ApiBridge


@pytest.fixture
def bridge():
    return ApiBridge(application=MagicMock(), window=MagicMock())


class TestBridgeBoundaryCases:
    """Tier 2 Boundary tests verifying robust handling of invalid inputs and edge cases."""

    @pytest.mark.parametrize("source,target", [
        ("", "HI"),
        ("EN", ""),
        (None, "HI"),
        ("EN", None),
        ("XYZ", "HI"),
        ("EN", "ABC"),
        (123, "HI"),
    ])
    def test_set_languages_invalid_inputs(self, bridge, source, target):
        res = bridge.set_languages(source, target)
        assert res["status"] == "error"
        assert "error" in res

    @pytest.mark.parametrize("mode", [
        "3-way",
        "",
        None,
        123,
        "invalid_mode",
    ])
    def test_set_translation_mode_invalid_inputs(self, bridge, mode):
        res = bridge.set_translation_mode(mode)
        assert res["status"] == "error"
        assert "error" in res

    @pytest.mark.parametrize("panel", [
        "C",
        "",
        None,
        "X",
        123,
    ])
    def test_set_panel_tts_invalid_panel(self, bridge, panel):
        res = bridge.set_panel_tts(panel, True)
        assert res["status"] == "error"
        assert "error" in res

    @pytest.mark.parametrize("limit", [
        -10,
        0,
        "invalid_str",
        None,
        -1,
    ])
    def test_fetch_history_invalid_limit(self, bridge, limit):
        history = bridge.fetch_history(limit=limit)
        assert isinstance(history, list)
        assert len(history) == 0

    @pytest.mark.parametrize("settings", [
        None,
        "not_a_dict",
        12345,
        [1, 2, 3],
    ])
    def test_set_audio_settings_invalid_type(self, bridge, settings):
        res = bridge.set_audio_settings(settings)
        assert res["status"] == "error"

    def test_submit_text_input_empty_or_whitespace(self, bridge):
        res_empty = bridge.submit_text_input("")
        assert res_empty["status"] == "error"

        res_space = bridge.submit_text_input("   \n\t  ")
        assert res_space["status"] == "error"

    def test_update_keywords_invalid_type(self, bridge):
        res = bridge.update_keywords("not_a_list")
        assert res["status"] == "error"

    def test_rapid_start_stop_session_burst(self, bridge):
        """Verify rapid start/stop toggles do not crash or leave bridge in inconsistent state."""
        for _ in range(50):
            res_start = bridge.start_session("EN", "HI")
            assert res_start["status"] == "ok"
            assert bridge.active is True

            res_stop = bridge.stop_session()
            assert res_stop["status"] == "ok"
            assert bridge.active is False

"""Automated unit and integration tests for PyWebView UI Migration (Milestone 3)."""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch
import pytest

from app.bridge import ApiBridge
from ui.webview_window import WebviewWindowManager


class TestWebviewWindowManager:

    def test_get_index_path_exists(self):
        manager = WebviewWindowManager(api_bridge=MagicMock())
        path = manager.get_index_path()
        assert pathlib.Path(path).exists()
        assert path.endswith("index.html")

    def test_create_window_initialization(self):
        bridge = ApiBridge()
        manager = WebviewWindowManager(api_bridge=bridge)

        with patch("webview.create_window") as mock_create:
            mock_win = MagicMock()
            mock_create.return_value = mock_win

            win = manager.create_window("TalkSync AI Test")

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]

            assert call_kwargs["title"] == "TalkSync AI Test"
            assert call_kwargs["js_api"] == bridge
            assert call_kwargs["background_color"] == "#0b0f19"
            assert call_kwargs["width"] == 1280
            assert call_kwargs["height"] == 800
            assert call_kwargs["min_size"] == (900, 600)
            assert bridge._window == mock_win


class TestWebAssetIntegrity:

    @pytest.fixture
    def web_dir(self):
        return pathlib.Path(__file__).parent.parent / "ui" / "web"

    def test_web_assets_exist_and_non_empty(self, web_dir):
        files = ["index.html", "styles.css", "app.js", "waveform.js"]
        for f in files:
            file_path = web_dir / f
            assert file_path.exists(), f"Missing web asset: {f}"
            assert file_path.stat().st_size > 0, f"Empty web asset: {f}"

    def test_index_html_elements(self, web_dir):
        html_path = web_dir / "index.html"
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")

        # Required DOM IDs
        required_ids = [
            "select-source-lang",
            "select-target-lang",
            "btn-session-toggle",
            "btn-mic-toggle",
            "text-input-field",
            "panel-a",
            "panel-b",
            "settings-modal",
            "history-modal",
        ]
        for elem_id in required_ids:
            assert f'id="{elem_id}"' in content, f"Missing DOM ID '{elem_id}' in index.html"

        # Canvas ID check (waveformCanvas or waveform-canvas)
        assert ('id="waveformCanvas"' in content or 'id="waveform-canvas"' in content), "Missing canvas element in index.html"

        # Required Buttons & Features
        assert 'id="btn-tts-a"' in content
        assert 'id="btn-tts-b"' in content
        assert 'id="btn-mode-2way"' in content
        assert 'id="btn-mode-1way"' in content
        assert 'id="latency-pill"' in content
        assert 'id="status-badge"' in content

    def test_app_js_callbacks_and_api_methods(self, web_dir):
        js_path = web_dir / "app.js"
        assert js_path.exists()
        content = js_path.read_text(encoding="utf-8")

        # Required Python-to-JS callback handlers on window.TalkSyncUI
        required_callbacks = [
            "onTranscription",
            "onTranslation",
            "onStatus",
            "onLatency",
            "onAudioLevel",
            "onVADState",
        ]
        for cb in required_callbacks:
            assert cb in content, f"Missing callback handler '{cb}' in app.js"

        # Required pywebview API method bindings
        api_methods = [
            "start_session",
            "stop_session",
            "set_languages",
            "set_translation_mode",
            "toggle_mic_mute",
            "set_panel_tts",
            "set_audio_settings",
            "fetch_history",
            "submit_text_input",
            "list_audio_devices",
        ]
        for method in api_methods:
            assert method in content, f"Missing API method binding '{method}' in app.js"

    def test_styles_css_theme(self, web_dir):
        css_path = web_dir / "styles.css"
        assert css_path.exists()
        content = css_path.read_text(encoding="utf-8")

        assert "#0b0f19" in content
        assert "backdrop-filter" in content
        assert "rgba(15, 23, 42" in content

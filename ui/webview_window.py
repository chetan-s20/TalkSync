"""TalkSync AI — PyWebView Window Manager."""
from __future__ import annotations

import pathlib
from typing import Any, Optional
import webview

from app.bridge import ApiBridge
from utils.logger import get_logger

logger = get_logger("webview")


class WebviewWindowManager:
    """Manages PyWebView window creation, static loading, and signal lifecycle."""

    def __init__(self, api_bridge: ApiBridge, settings: Any = None):
        self.api_bridge = api_bridge
        self.settings = settings
        self.window: Optional[webview.Window] = None

    def get_index_path(self) -> str:
        """Resolve absolute file path to ui/web/index.html."""
        base_dir = pathlib.Path(__file__).parent.resolve()
        html_path = base_dir / "web" / "index.html"
        if not html_path.exists():
            raise FileNotFoundError(f"Web UI entrypoint not found at: {html_path}")
        return str(html_path)

    def create_window(self, title: str = "TalkSync AI") -> webview.Window:
        """Instantiate PyWebView window with ApiBridge binding."""
        html_path_str = self.get_index_path()
        html_url = pathlib.Path(html_path_str).as_uri()
        width = getattr(self.settings, "window_width", 1280) if self.settings else 1280
        height = getattr(self.settings, "window_height", 800) if self.settings else 800

        logger.info(f"Creating PyWebView window loading {html_url} ({width}x{height})")

        self.window = webview.create_window(
            title=title,
            url=html_url,
            js_api=self.api_bridge,
            width=width,
            height=height,
            min_size=(900, 600),
            background_color="#0b0f19",
            resizable=True,
        )

        self.api_bridge.set_window(self.window)
        self.window.events.closed += self._on_closed
        return self.window

    def _on_closed(self) -> None:
        """Handle window close event and stop session workers cleanly."""
        logger.info("PyWebView window closed by user.")
        if self.api_bridge and getattr(self.api_bridge, "active", False):
            self.api_bridge.stop_session()

    def start(self, debug: bool = False) -> None:
        """Launch PyWebView main GUI event loop."""
        if not self.window:
            self.create_window()
        webview.start(debug=debug, private_mode=False)

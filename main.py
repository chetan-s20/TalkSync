"""TalkSync AI — real-time multilingual speech translation."""
from __future__ import annotations

import argparse
import signal
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.application import Application
from app.bridge import ApiBridge
from ui.webview_window import WebviewWindowManager
from utils.logger import get_logger, set_level

logger = get_logger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="TalkSync AI")
    parser.add_argument("--source-lang", default="EN")
    parser.add_argument("--target-lang", default="HI")
    parser.add_argument("--mode", default="two_way", choices=["one_way", "two_way", "1-way", "2-way"])
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.debug:
        set_level("DEBUG")

    app = Application()
    settings = app.settings
    settings.source_lang = args.source_lang
    settings.target_lang = args.target_lang
    settings.translation_mode = args.mode

    pipeline = app.build_pipeline()
    api_bridge = ApiBridge(application=app)

    window_manager = WebviewWindowManager(api_bridge=api_bridge, settings=settings)
    window_manager.create_window()
    app.set_main_window(window_manager.window)

    def shutdown(signum, frame):
        logger.info("Shutdown signal received")
        if api_bridge.active:
            api_bridge.stop_session()
        if window_manager.window:
            try:
                window_manager.window.destroy()
            except Exception:
                pass

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Starting TalkSync AI PyWebView application...")
    window_manager.start(debug=args.debug)


if __name__ == "__main__":
    main()

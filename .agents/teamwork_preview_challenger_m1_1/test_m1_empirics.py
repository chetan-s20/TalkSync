import sys
import os
import unittest
from unittest.mock import MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = r"d:\talksync\talksync"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

class TestMilestone1(unittest.TestCase):

    def test_01_import_main_window(self):
        """1. Empirically verify that from ui.main_window import MainWindow imports cleanly."""
        try:
            from ui.main_window import MainWindow
            self.assertTrue(hasattr(MainWindow, "_on_status"))
            self.assertTrue(hasattr(MainWindow, "_on_latency"))
            self.assertTrue(hasattr(MainWindow, "_on_transcription"))
            self.assertTrue(hasattr(MainWindow, "_on_translation"))
            print("PASS: from ui.main_window import MainWindow imported cleanly.")
        except Exception as e:
            self.fail(f"Importing MainWindow failed with error: {e}")

    def test_02_instantiate_headless(self):
        """2. Test instantiation of MainWindow and application components in headless environment."""
        from ui.main_window import MainWindow
        from config.settings import Settings

        mock_pipeline = MagicMock()
        settings = Settings()

        # Instantiate MainWindow
        window = MainWindow(pipeline=mock_pipeline, settings=settings)
        window.withdraw()  # Keep hidden for headless test

        try:
            # Check pipeline callbacks wiring
            self.assertEqual(mock_pipeline.on_status, window._on_status)
            self.assertEqual(mock_pipeline.on_latency, window._on_latency)
            self.assertEqual(mock_pipeline.on_transcription, window._on_transcription)
            self.assertEqual(mock_pipeline.on_translation, window._on_translation)

            # Check sub-widgets instantiation
            self.assertIsNotNone(window.panel_a)
            self.assertIsNotNone(window.panel_b)
            self.assertIsNotNone(window.status_bar)
            self.assertIsNotNone(window.subtitle_overlay)
            self.assertIsNotNone(window.text_input)

            print("PASS: MainWindow and child components instantiated headlessly without errors.")
        finally:
            window.destroy()

    def test_03_edge_cases_on_status_and_latency(self):
        """3. Test edge cases for _on_status and _on_latency directly."""
        from ui.main_window import MainWindow
        from config.settings import Settings

        mock_pipeline = MagicMock()
        settings = Settings()
        window = MainWindow(pipeline=mock_pipeline, settings=settings)
        window.withdraw()

        try:
            # Task target tests:
            # _on_status("test message", "info")
            window._on_status("test message", "info")
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_status.cget("text"), "test message")

            # _on_status("test message") [1-arg]
            window._on_status("test message")
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_status.cget("text"), "test message")

            # _on_latency({"avg_ms": 12.3}) [dict payload]
            window._on_latency({"avg_ms": 12.3})
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 12ms")

            # _on_latency(15.4) [float payload]
            window._on_latency(15.4)
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 15ms")

            # Additional stress/edge cases
            # Integer latency
            window._on_latency(45)
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 45ms")

            # Dict with missing key
            window._on_latency({})
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 0ms")

            # None
            window._on_latency(None)
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 0ms")

            # String input
            window._on_latency("invalid_latency")
            window.update_idletasks()
            window.update()
            self.assertEqual(window.status_bar.lbl_latency.cget("text"), "Latency: 0ms")

            # _on_status with non-string values
            window._on_status(12345)
            window.update_idletasks()
            window.update()
            self.assertEqual(str(window.status_bar.lbl_status.cget("text")), "12345")

            print("PASS: All target edge cases for _on_status and _on_latency handled robustly without exceptions.")
        finally:
            window.destroy()

    def test_04_transcription_and_translation_callbacks(self):
        """Test _on_transcription and _on_translation callback robustness with mock objects."""
        from ui.main_window import MainWindow
        from config.settings import Settings

        mock_pipeline = MagicMock()
        settings = Settings()
        window = MainWindow(pipeline=mock_pipeline, settings=settings)
        window.withdraw()

        try:
            # Mock transcription segment
            mock_segment = MagicMock()
            mock_segment.text = "Hello world"
            mock_segment.input_source = "VOICE"

            window._on_transcription(mock_segment)
            window.update_idletasks()
            window.update()

            # Mock translation result
            mock_result = MagicMock()
            mock_result.original_text = "Hello world"
            mock_result.translated_text = "Namaste duniya"
            mock_result.input_source = "VOICE"

            window._on_translation(mock_result)
            window.update_idletasks()
            window.update()

            print("PASS: _on_transcription and _on_translation executed cleanly.")
        finally:
            window.destroy()

if __name__ == "__main__":
    unittest.main()

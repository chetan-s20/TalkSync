import pytest
import sys
from unittest.mock import MagicMock, patch

# Define a mock widget base class that returns mocks for any method/attribute
class MockWidgetBase:
    def __init__(self, *args, **kwargs):
        self._kwargs = kwargs
    def __getattr__(self, name):
        return MagicMock()
    def grid(self, *args, **kwargs):
        pass
    def pack(self, *args, **kwargs):
        pass
    def grid_rowconfigure(self, *args, **kwargs):
        pass
    def grid_columnconfigure(self, *args, **kwargs):
        pass
    def configure(self, *args, **kwargs):
        self._kwargs.update(kwargs)
    def cget(self, name):
        return self._kwargs.get(name)

# Create a mock customtkinter module
mock_ctk = MagicMock()
mock_ctk.CTkFrame = MockWidgetBase
mock_ctk.CTkButton = MockWidgetBase
mock_ctk.CTkTextbox = MockWidgetBase
mock_ctk.CTkLabel = MockWidgetBase
mock_ctk.CTk = MockWidgetBase
mock_ctk.CTkToplevel = MockWidgetBase
mock_ctk.CTkFont = MagicMock
mock_ctk.BooleanVar = MagicMock

# Inject mock modules into sys.modules
sys.modules['customtkinter'] = mock_ctk
sys.modules['pywinstyles'] = MagicMock()
sys.modules['services.subtitle.overlay'] = MagicMock()

# Now import panels and main window
from ui.widgets.transcript_panel import TranscriptPanel
from ui.main_window import MainWindow
from app.pipeline import Pipeline
from config.settings import Settings

def test_transcript_panel_mic_toggle_visuals():
    """Verify TranscriptPanel mic button visual state updates and toggle logic."""
    # We patch pack and configure on buttons to check behavior
    with patch('ui.widgets.transcript_panel.ctk.CTkButton') as mock_btn_class:
        mock_btn = MagicMock()
        mock_btn_class.return_value = mock_btn
        
        # Instantiate panel
        panel = TranscriptPanel(
            parent=None,
            title="Left Panel",
            lang_pair="en → hi",
            mic_active=True
        )
        
        # Check initial active state
        assert panel.mic_active is True
        
        # Toggle mic: should mute it (turns color to red "#EF4444")
        active = panel.toggle_mic()
        assert active is False
        assert panel.mic_active is False
        mock_btn.configure.assert_called_with(text_color="#EF4444")
        
        # Toggle mic back: should unmute it (turns color to "#FF5C2B" orange)
        active = panel.toggle_mic()
        assert active is True
        assert panel.mic_active is True
        mock_btn.configure.assert_called_with(text_color="#FF5C2B")

def test_main_window_mic_mute_integration():
    """Verify MainWindow initializes panel_a with mic button and links to pipeline.mute_mic."""
    pipeline_mock = MagicMock(spec=Pipeline)
    settings_mock = MagicMock(spec=Settings)
    settings_mock.window_width = 960
    settings_mock.window_height = 640
    settings_mock.source_lang = "en"
    settings_mock.target_lang = "hi"
    settings_mock.translation_mode = "two_way"
    
    # Instantiate MainWindow with patched ui builders to avoid runtime errors
    with patch('ui.main_window.MainWindow._build_ui'), \
         patch('ui.main_window.MainWindow._bind_shortcuts'):
        app = MainWindow(pipeline=pipeline_mock, settings=settings_mock)
        
        # Assign mock sub-widgets for callback verification
        app.status_bar = MagicMock()
        app.panel_a = MagicMock(spec=TranscriptPanel)
        
        # Mock 'after' method to run callback immediately
        def mock_after(delay, callback):
            callback()
        app.after = mock_after
        
        # Verify app._toggle_microphone triggers pipeline.mute_mic
        app._toggle_microphone(active=False)
        pipeline_mock.mute_mic.assert_called_with(True) # muted=True when active=False
        app.status_bar.set_status.assert_called_with("Microphone Muted")
        
        app._toggle_microphone(active=True)
        pipeline_mock.mute_mic.assert_called_with(False) # muted=False when active=True
        app.status_bar.set_status.assert_called_with("Microphone Unmuted")

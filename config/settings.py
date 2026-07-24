from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="audio_", extra="ignore")
    sample_rate: int = Field(default=16000)
    channels: int = Field(default=1)
    chunk_duration_ms: float = Field(default=30.0)
    input_device_id: Optional[int] = Field(default=None)
    output_device_id: Optional[int] = Field(default=None)
    output_sample_rate: int = Field(default=24000)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    tts_playback_enabled: bool = Field(default=True)
    tts_voice_name: str = Field(default="Warm Man-D")
    playback_delay_s: float = Field(default=0.0)
    virtual_mic_enabled: bool = Field(default=False)


class VADSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="vad_", extra="ignore")
    threshold: float = Field(default=0.55)
    min_speech_duration_ms: int = Field(default=250)
    min_silence_duration_ms: int = Field(default=150)
    speech_frames_to_activate: int = Field(default=3)
    silence_frames_to_deactivate: int = Field(default=5)


class STTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="stt_", extra="ignore")
    model: str = Field(default="Systran/faster-whisper-small")
    beam_size: int = Field(default=1)
    no_speech_threshold: float = Field(default=0.55)
    log_prob_threshold: float = Field(default=-0.8)
    compression_ratio_threshold: float = Field(default=2.4)
    initial_prompt: str = Field(default="This is a Hindi and English conversation.")
    avg_logprob_threshold: float = Field(default=-0.8)
    device: str = Field(default="auto")
    compute_type: str = Field(default="float16")
    vad_filter: bool = Field(default=False)


class TranslationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="translation_", extra="ignore")
    provider: str = Field(default="argos")
    fallback_provider: str = Field(default="deepl")
    model: str = Field(default="argos")
    source_lang: str = Field(default="EN")
    target_lang: str = Field(default="HI")
    deepl_api_key: str = Field(default="")
    proxy_url: str = Field(default="http://192.168.0.1:8090")
    timeout_s: float = Field(default=5.0)


class TTSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="tts_", extra="ignore")
    model: str = Field(default="piper")
    voice: str = Field(default="en_US-lessac-medium")
    speed: float = Field(default=1.0)
    device: str = Field(default="auto")
    streaming: bool = Field(default=True)
    sarvam_api_key: str = Field(default="")
    sarvam_voice: str = Field(default="shubh")
    sarvam_lang: str = Field(default="hi-IN")
    sarvam_timeout_s: float = Field(default=30.0)
    piper_voice_dir: Optional[str] = Field(default=None)


class SubtitleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="subtitle_", extra="ignore")
    enabled: bool = Field(default=True)
    font_size: int = Field(default=20)
    opacity: float = Field(default=0.85)
    auto_hide_seconds: float = Field(default=5.0)
    width: int = Field(default=600)
    height: int = Field(default=120)
    bg_color: str = Field(default="#1E293B")
    original_color: str = Field(default="#94A3B8")
    translated_color: str = Field(default="#F8FAFC")


class DenoiserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="denoiser_", extra="ignore")
    enabled: bool = Field(default=False)
    model: str = Field(default="rnnoise")


class HistorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="history_", extra="ignore")
    db_path: str = Field(default="talksync.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="talksync_", extra="ignore")
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vad: VADSettings = Field(default_factory=VADSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    translation: TranslationSettings = Field(default_factory=TranslationSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    subtitle: SubtitleSettings = Field(default_factory=SubtitleSettings)
    denoiser: DenoiserSettings = Field(default_factory=DenoiserSettings)
    history: HistorySettings = Field(default_factory=HistorySettings)
    source_lang: str = Field(default="EN")
    target_lang: str = Field(default="HI")
    translation_mode: str = Field(default="two_way")
    context_seed: str = Field(default="")
    ai_assistant_enabled: bool = Field(default=True)
    keywords: str = Field(default="")
    context: str = Field(default="")
    theme: str = Field(default="light")
    window_width: int = Field(default=1200)
    window_height: int = Field(default=800)
    log_level: str = Field(default="INFO")
    log_to_file: bool = Field(default=False)
    selected_input_device_name: str = Field(default="")
    selected_output_device_name: str = Field(default="")
    loopback_enabled: bool = Field(default=False)
    mic_enabled: bool = Field(default=True)
    spk_enabled: bool = Field(default=True)

    def to_json(self, path: str) -> None:
        """Write configuration to JSON file."""
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @property
    def subtitles(self) -> SubtitleSettings:
        return self.subtitle


def get_default_config_path() -> Path:
    """Return default configuration path."""
    from pathlib import Path
    return Path(__file__).parent / "models_config.json"


def load_settings(config_path: Optional[str] = None) -> Settings:
    """Load Settings instance from file path or defaults."""
    import json
    from pathlib import Path
    path = Path(config_path) if config_path else get_default_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Settings(**data)
        except Exception:
            pass
    return Settings()

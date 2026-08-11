import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np

from config.settings import Settings
from services.stt.openai_stt import OpenAISTT

@pytest.mark.asyncio
async def test_openai_stt_refinement_valid_speech():
    """Verify that a valid raw transcription is correctly refined by the LLM."""
    settings = Settings()
    settings.stt.refinement = True
    
    stt = OpenAISTT(settings)
    stt._loaded = True
    stt._client = MagicMock()
    
    # Mock the transcription endpoint returning a raw transcription
    mock_transcription = MagicMock()
    mock_transcription.text = "i am uh speaking now"
    mock_transcription.language = "en"
    stt._transcribe_with_retry = AsyncMock(return_value=mock_transcription)
    
    # Mock the chat completion endpoint returning refined clean text
    mock_chat_message = MagicMock()
    mock_chat_message.content = "I am speaking now."
    mock_chat_choice = MagicMock()
    mock_chat_choice.message = mock_chat_message
    mock_chat_response = MagicMock()
    mock_chat_response.choices = [mock_chat_choice]
    
    stt._client.chat.completions.create = AsyncMock(return_value=mock_chat_response)
    
    # Send some active sound data to pass RMS gate
    audio = np.random.randn(16000).astype(np.float32) * 0.1 # RMS ~0.1 (well above 0.0003)
    
    result = await stt.transcribe(audio.tobytes(), is_final=True, language="en")
    
    assert result is not None
    assert result.text == "I am speaking now."
    stt._client.chat.completions.create.assert_called_once()

@pytest.mark.asyncio
async def test_openai_stt_refinement_noise_filtered():
    """Verify that background noise hallucinations resulting in empty LLM response are dropped."""
    settings = Settings()
    settings.stt.refinement = True
    
    stt = OpenAISTT(settings)
    stt._loaded = True
    stt._client = MagicMock()
    
    # Mock the transcription endpoint returning a noise hallucination
    mock_transcription = MagicMock()
    mock_transcription.text = "you" # common whisper hallucination on noise
    mock_transcription.language = "en"
    stt._transcribe_with_retry = AsyncMock(return_value=mock_transcription)
    
    # Mock the chat completion returning empty string (indicating noise)
    mock_chat_message = MagicMock()
    mock_chat_message.content = ""
    mock_chat_choice = MagicMock()
    mock_chat_choice.message = mock_chat_message
    mock_chat_response = MagicMock()
    mock_chat_response.choices = [mock_chat_choice]
    
    stt._client.chat.completions.create = AsyncMock(return_value=mock_chat_response)
    
    audio = np.random.randn(16000).astype(np.float32) * 0.1
    
    result = await stt.transcribe(audio.tobytes(), is_final=True, language="en")
    
    # Text should be filtered to empty and returning None segment
    assert result is None

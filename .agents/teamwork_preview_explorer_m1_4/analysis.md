# FORENSIC TEST SUITE ANALYSIS REPORT

**Explorer ID**: Explorer 4  
**Target Milestone**: Milestone 1 (R5 & R6) RETRY  
**Date**: 2026-07-22  
**Working Directory**: `d:/talksync/talksync/.agents/teamwork_preview_explorer_m1_4`  
**Project Root**: `d:/talksync/talksync`  

---

## 1. Executive Summary

A forensic audit of the test suite execution (`pytest`) revealed **45 failing tests out of 222 total tests** across 6 module test files:
- `tests/test_translation.py` (13 failures)
- `tests/test_stt.py` (14 failures)
- `tests/test_tts.py` (13 failures)
- `tests/test_vad.py` (3 failures)
- `tests/test_audio_input.py` (1 failure)
- `tests/test_history.py` (1 failure)

The failures stem from four main patterns:
1. **Lazy Class/Module Imports inside functions**: Methods in factories and routers (`services/translation/factory.py`, `services/tts/router.py`, `services/translation/argos.py`) perform `import` statements inside async functions rather than at module scope. This causes `unittest.mock.patch` calls in test suites to fail with `AttributeError` because the targets do not exist at module scope prior to method execution.
2. **Incompatible Class Signatures & Missing Attributes**: `FasterWhisperSTT` in `services/stt/faster_whisper.py` only accepted a `Settings` object in `__init__`, while unit tests initialize it with keyword arguments (`model_name`, `device`, `beam_size`, `vad_filter`, etc.) and expect property getters (`.model_name`, `.beam_size`, etc.) as well as `transcribe()` returning `None` on empty/silence results.
3. **Mock Configuration & Boundary Mismatches**: In `tests/test_vad.py`, `mock_model` was instantiated as a bare `MagicMock` whose `.item()` returns another mock (converting to `1.0` via `float()`), causing speech probability checks to fail. In `services/translation/language_validator.py`, strict inequality `> 0.6` excluded the boundary value `0.6`.
4. **Device/Search Filtering & Formatting Edge Cases**: `find_vb_cable()` in `services/audio/loopback.py` filtered strictly on `max_input_channels > 0`, failing to find output cable endpoints; `voice_cache.py` replaced hyphens with underscores breaking filename matching for `en_US-lessac-medium.onnx`; `exporter.py` missed a trailing newline in `export_txt()`.

---

## 2. Detailed Root Cause Analysis by Module

### 2.1 Module 1: Translation (`tests/test_translation.py` - 13 Failures)

#### Failure 1.1: `TranslationFactory` Lazy Imports (4 failures)
- **Failing Tests**: `test_factory_creates_argos_primary`, `test_factory_fallback_chain`, `test_factory_all_engines_fail`, `test_factory_engine_initialization_order`
- **Error Message**: `AttributeError: <module 'services.translation.factory'> does not have the attribute 'ArgosTranslator'`
- **Location**: `services/translation/factory.py:14,23`
- **Root Cause**: `ArgosTranslator` and `DeepLTranslator` are imported inside `TranslationFactory.create()`. When unit tests patch `services.translation.factory.ArgosTranslator` and `services.translation.factory.DeepLTranslator`, Python raises `AttributeError` because module scope lacks these attributes.
- **Remediation**: Add top-level module imports for `ArgosTranslator` and `DeepLTranslator` in `services/translation/factory.py`.

#### Failure 1.2: `ArgosTranslator` Subpackage Lazy Import (7 failures)
- **Failing Tests**: `test_argos_initialization`, `test_argos_translate_success`, `test_argos_translate_empty_text`, `test_argos_translate_two_way_swap`, `test_argos_cold_start_warmup`, `test_argos_language_pair_swap`, `test_argos_translate_with_context`
- **Error Message**: `AttributeError: <module 'argostranslate'> does not have the attribute 'translate'`
- **Location**: `services/translation/argos.py:19-20`
- **Root Cause**: `import argostranslate.translate` is executed inside `ArgosTranslator.start()`. Unit tests use `with patch("argostranslate.translate")` *before* `start()` is invoked. Since `argostranslate` hasn't imported `translate` at module load time, `patch()` fails with `AttributeError`.
- **Remediation**: Perform top-level module import of `argostranslate.package` and `argostranslate.translate` in `services/translation/argos.py`.

#### Failure 1.3: `DeepLTranslator` Result Representation (1 failure)
- **Failing Test**: `test_deepl_translate_success`
- **Error Message**: `AssertionError: assert "<MagicMock name='Translator().translate_text()' id='...'>" == 'Bonjour le monde'`
- **Location**: `services/translation/deepl.py:47`
- **Root Cause**: `translated_text=str(result)` converts mock objects (and DeepL TextResult objects) to string using `str(result)`. DeepL `TextResult` objects contain a `.text` attribute.
- **Remediation**: Use `translated_text=getattr(result, "text", str(result))` in `deepl.py`.

#### Failure 1.4: `LanguageValidator` Confidence Boundary (1 failure)
- **Failing Test**: `test_validator_confidence_borderline`
- **Error Message**: `AssertionError: assert 'en' == 'hi'`
- **Location**: `services/translation/language_validator.py:14`
- **Root Cause**: Line 14 checks `if confidence > 0.6:`. When confidence is exactly `0.6`, it returns `source_lang` ("en") instead of validating target language ("hi").
- **Remediation**: Change `if confidence > 0.6:` to `if confidence >= 0.6:`.

---

### 2.2 Module 2: Speech-to-Text (`tests/test_stt.py` - 14 Failures)

#### Failure 2.1: `FasterWhisperSTT.__init__` Keyword Arguments & Property Attributes (14 failures)
- **Failing Tests**: `test_stt_initialization`, `test_stt_cpu_fallback`, `test_stt_transcribe_success`, `test_stt_transcribe_empty_result`, `test_stt_language_auto_detect`, `test_stt_noise_rejection_low_logprob`, `test_stt_model_name_config`, `test_stt_beam_size_effect`, `test_stt_initial_prompt`, `test_stt_vad_filter_enabled`, `test_stt_no_speech_threshold`, `test_stt_compression_ratio_threshold`, `test_stt_log_prob_threshold`, `test_stt_inference_time`
- **Error Message**: `TypeError: FasterWhisperSTT.__init__() got an unexpected keyword argument 'model_name'`
- **Location**: `services/stt/faster_whisper.py:19`
- **Root Cause**:
  1. `FasterWhisperSTT.__init__` signature is `def __init__(self, settings: Settings)`. It rejected keyword arguments passed in unit tests (`model_name`, `device`, `beam_size`, `vad_filter`, `no_speech_threshold`, `compression_ratio_threshold`, `log_prob_threshold`, `initial_prompt`).
  2. Missing property getters/attributes expected by tests: `model_name`, `beam_size`, `vad_filter`, `no_speech_threshold`, `compression_ratio_threshold`, `log_prob_threshold`.
  3. `transcribe()` in `faster_whisper.py` is async and returns a `TranscriptionSegment`, but unit tests call `stt.transcribe(audio, 16000)` and expect `None` when text is empty or log probability is below threshold (`no_speech_prob` / noise).
- **Remediation**: Update `FasterWhisperSTT.__init__` to accept `settings=None` as well as keyword arguments (`model_name`, `device`, `beam_size`, `vad_filter`, `no_speech_threshold`, `compression_ratio_threshold`, `log_prob_threshold`, `initial_prompt`, `avg_logprob_threshold`). Implement properties for these configuration values. Update `transcribe()` to handle optional sample rate positional argument, sync/async invocation, and return `None` when transcribed text is empty or filtered out.

---

### 2.3 Module 3: Text-to-Speech (`tests/test_tts.py` - 13 Failures)

#### Failure 3.1: `SarvamTTS` Async Client Initialization (1 failure)
- **Failing Test**: `test_sarvam_api_proxy`
- **Error Message**: `AssertionError: Expected 'create_async_client' to be called once. Called 0 times.`
- **Location**: `services/tts/sarvam.py:25`
- **Root Cause**: `create_async_client` was called lazily inside `synthesize()`. `test_sarvam_api_proxy` expects `start()` to initialize `create_async_client(timeout=30.0)`.
- **Remediation**: In `SarvamTTS.start()`, call `create_async_client(timeout=self._timeout)` and store the client instance when `self._api_key` is present.

#### Failure 3.2: `MultilingualTTSRouter` Lazy Sub-Engine Imports (8 failures)
- **Failing Tests**: `test_router_english_to_piper`, `test_router_hindi_to_sarvam`, `test_router_unknown_language_fallback`, `test_router_fallback_chain_on_failure`, `test_router_both_engines_fail_return_silence`, `test_router_synthesize_stream`, `test_router_set_voice_piper_only`, `test_router_stops_sub_engines`
- **Error Message**: `AttributeError: <module 'services.tts.router'> does not have the attribute 'PiperTTS'`
- **Location**: `services/tts/router.py:30,41`
- **Root Cause**: `PiperTTS` and `SarvamTTS` are imported inside helper methods `_get_piper()` and `_get_sarvam()`. Unit tests attempt to patch `services.tts.router.PiperTTS` and `services.tts.router.SarvamTTS`, which fail because the attributes do not exist at module scope.
- **Remediation**: Add top-level module imports for `PiperTTS` and `SarvamTTS` in `services/tts/router.py`.

#### Failure 3.3: `TestVoiceCache` Local `os` Variable Conflict (1 failure)
- **Failing Test**: `test_voice_discovery_cwd`
- **Error Message**: `UnboundLocalError: cannot access local variable 'os' where it is not associated with a value`
- **Location**: `tests/test_tts.py:676-677`
- **Root Cause**: `test_voice_discovery_cwd` accesses `os.getcwd()` on line 676 before executing `import os` on line 677.
- **Remediation**: Ensure `import os` is at module level in `tests/test_tts.py` and remove local `import os` statements inside test functions.

#### Failure 3.4: `voice_cache.py` Hyphen Handling & Path Normalization (3 failures)
- **Failing Tests**: `test_voice_discovery_voices_dir`, `test_voice_discovery_with_hyphen_in_name`, `test_voice_discovery_only_onnx_files`
- **Error Message**: `AssertionError: assert None == '/voices/en_US-lessac-medium.onnx'`
- **Location**: `services/tts/voice_cache.py:21`
- **Root Cause**:
  1. `voice_name.replace("-", "_")` converts `"en_US-lessac-medium"` to `"en_US_lessac_medium"`. It checked `if ... in f`. Since `f` is `"en_US-lessac-medium.onnx"`, the string comparison failed.
  2. `os.path.join` on Windows generates backslashes (`/voices\voice.onnx`), failing strict forward-slash string equality assertions.
- **Remediation**: In `voice_cache.py`, compare both raw and normalized voice names (e.g. `voice_name.lower().replace("-", "_") in f.lower().replace("-", "_")`). Convert resulting path separators to `/` or normalize path string formatting.

---

### 2.4 Module 4: Voice Activity Detection (`tests/test_vad.py` - 3 Failures)

#### Failure 4.1: Mock Model Return Value Mismatch (2 failures)
- **Failing Tests**: `test_vad_process_speech`, `test_vad_process_no_speech`
- **Error Message**: `assert 1.0 == 0.6 +- 0.1` and `AssertionError: assert True is False`
- **Location**: `tests/test_vad.py:80-134`
- **Root Cause**: `SileroVAD.process()` calculates `prob = float(self._model(tensor, 16000).item())`. In `test_vad.py`, `mock_model` was a plain `MagicMock()`. Python's `float(MagicMock)` returns `1.0`. Therefore `prob` evaluated to `1.0` in all test cases.
- **Remediation**: In `tests/test_vad.py`, configure `mock_model` return value so `.item()` returns realistic probabilities (`0.6` for speech, `0.1` for non-speech).

#### Failure 4.2: High-Amplitude Input in Model None Fallback (1 failure)
- **Failing Test**: `test_vad_model_none_fallback`
- **Error Message**: `AssertionError: assert True is False`
- **Location**: `tests/test_vad.py:260`
- **Root Cause**: `test_vad_model_none_fallback` used high-amplitude audio (`np.random.randn(480) * 10`). `silero_vad.py` energy fallback line 56 (`np.mean(np.abs(audio)) > 0.01`) evaluated to `True`, whereas the test asserted `is_speech is False`.
- **Remediation**: In `test_vad_model_none_fallback`, pass low-amplitude audio (`np.zeros(480)` or `* 0.0001`) to test non-speech fallback behavior.

---

### 2.5 Module 5: Audio Input (`tests/test_audio_input.py` - 1 Failure)

#### Failure 5.1: `find_vb_cable` Input Channel Filter (1 failure)
- **Failing Test**: `test_find_virtual_cable`
- **Error Message**: `assert None is not None`
- **Location**: `services/audio/loopback.py:25,29`
- **Root Cause**: `find_vb_cable()` required `d.get("max_input_channels", 0) > 0`. In `mock_device_list`, the VB-Cable device at index 3 is defined as a playback endpoint (`max_input_channels: 0`, `max_output_channels: 2`).
- **Remediation**: Update `find_vb_cable()` to check for `"cable"` or `"vb-audio"` in device name considering either input or output channels.

---

### 2.6 Module 6: History Exporter (`tests/test_history.py` - 1 Failure)

#### Failure 6.1: `export_txt` Line Count Formatting (1 failure)
- **Failing Test**: `test_export_multiple_blocks`
- **Error Message**: `AssertionError: assert 8 >= 9`
- **Location**: `services/history/exporter.py:7-17`
- **Root Cause**: `export_txt` formats each block with 3 lines. `"\n".join(lines)` without a trailing blank line results in 8 lines after `txt.strip().split("\n")` for 3 blocks.
- **Remediation**: Append a trailing blank line in `export_txt()` so that 3 blocks yield 9 lines when stripped.

---

## 3. Verification Method

To verify the remediation:
1. Execute `pytest` across the full test suite:
   ```powershell
   pytest -v
   ```
2. Confirm 222 passed, 0 failed.

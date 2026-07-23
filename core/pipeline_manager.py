"""
Pipeline Orchestration Manager for TalkSync Pro.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

import numpy as np

from core.interfaces import (
    AudioChunk,
    TranscriptionSegment,
    TranslationResult,
    SynthesisResult,
    BaseAudioInput,
    BaseVAD,
    BaseSTT,
    BaseTranslator,
    BaseTTS,
    VADResult,
)
from utils.logger import get_logger
from utils.latency import measure_latency, get_latency_tracker
from utils.keywords import parse_keywords, apply_keywords
from translation.context_engine import ContextEngine
from translation.language_validator import LanguageValidator

logger = get_logger("pipeline_manager")


class PipelineManager:

    def __init__(
        self,
        audio_input: BaseAudioInput,
        vad: BaseVAD,
        stt: BaseSTT,
        translator: BaseTranslator,
        tts: BaseTTS,
        audio_router,
        denoiser=None,
        settings=None,
        context_engine: Optional[ContextEngine] = None,
    ):
        self.audio_input = audio_input
        self.vad = vad
        self.stt = stt
        self.translator = translator
        self.tts = tts
        self.audio_router = audio_router
        self.denoiser = denoiser
        self.settings = settings
        self.context_engine = context_engine or ContextEngine()

        self.running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: list[asyncio.Task] = []

        self.audio_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue(maxsize=256)
        self.audio_loopback_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue(maxsize=256)
        self.stt_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue(maxsize=128)
        self.stt_loopback_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue(maxsize=128)
        self.translation_queue: asyncio.Queue[TranscriptionSegment | None] = asyncio.Queue(maxsize=128)
        self.tts_queue: asyncio.Queue[TranslationResult | None] = asyncio.Queue(maxsize=128)

        self._ignore_mic_until: float = 0.0

        self.on_transcription: Optional[callable] = None
        self.on_translation: Optional[callable] = None
        self.on_status: Optional[callable] = None
        self.on_latency: Optional[callable] = None

        self.translation_mode: str = "two_way"
        self.text_input_mode: bool = False

        self._lang_validator = LanguageValidator()

        self._stt_states: dict[str, dict] = {}
        self._stt_feed_interval_s: float = 0.5
        self._max_segment_s: float = 10.0
        self._stt_in_progress: bool = False

    def _stt_state(self, source: str) -> dict:
        if source not in self._stt_states:
            self._stt_states[source] = {
                "segment_audio": [],
                "segment_samples": 0,
                "last_stt_feed": 0.0,
                "last_final_text": "",
                "last_partial_text": "",
                "partial_offset": 0,
                "partial_accumulated_text": "",
            }
        return self._stt_states[source]

    async def start(self, source_lang: str, target_lang: str, loopback: bool = False) -> None:
        if self.running:
            return
        self.running = True
        self._loop = asyncio.get_running_loop()
        self._source_lang = source_lang.upper()
        self._target_lang = target_lang.upper()
        self._loopback = loopback

        self.audio_queue = asyncio.Queue(maxsize=256)
        self.audio_loopback_queue = asyncio.Queue(maxsize=256)
        self.stt_queue = asyncio.Queue(maxsize=128)
        self.stt_loopback_queue = asyncio.Queue(maxsize=128)
        self.translation_queue = asyncio.Queue(maxsize=128)
        self.tts_queue = asyncio.Queue(maxsize=128)

        logger.info(f"Pipeline manager start: {self._source_lang} -> {self._target_lang}")

        if self.settings:
            seed = getattr(self.settings, "context", "") or ""
            self.context_engine.set_seed_context(seed)

        try:
            if self.on_status:
                self.on_status("Starting audio...", "processing")

            should_capture_audio = loopback or not self.text_input_mode
            if should_capture_audio:
                capture_mic = not self.text_input_mode
                await self.audio_input.start(loopback=loopback, capture_mic=capture_mic)
            else:
                logger.info("Text Input Mode active — skipping audio input startup")
            if not self.running:
                await self.stop(); return

            if self.denoiser is not None:
                if self.on_status:
                    self.on_status("Loading denoiser...", "processing")
                await asyncio.get_event_loop().run_in_executor(None, self.denoiser.start)
                if not self.running:
                    await self.stop(); return

            if self.on_status:
                self.on_status("Loading VAD...", "processing")
            await self.vad.start()
            if not self.running:
                await self.stop(); return

            if self.on_status:
                self.on_status("Loading speech model...", "processing")
            await self.stt.start(language=None)
            if not self.running:
                await self.stop(); return

            if self.on_status:
                self.on_status("Connecting translator...", "processing")
            await self.translator.start()
            if not self.running:
                await self.stop(); return

            try:
                await asyncio.wait_for(
                    self.translator.translate("warm up", self._source_lang, self._target_lang),
                    timeout=15.0,
                )
                logger.info("Translator warm-up completed")
            except Exception:
                logger.debug("Translator warm-up skipped (harmless)")
            if not self.running:
                await self.stop(); return

            if self.on_status:
                self.on_status("Loading voices...", "processing")
            await self.tts.start()
            if not self.running:
                await self.stop(); return

            if self.on_status:
                self.on_status("Opening speakers...", "processing")
            await self.audio_router.start()

            if self.on_status:
                self.on_status("Listening...", "listening")

            self._tasks = [
                asyncio.create_task(self._translation_worker()),
                asyncio.create_task(self._tts_worker()),
                asyncio.create_task(self._stats_worker()),
            ]
            if should_capture_audio:
                self._tasks += [
                    asyncio.create_task(self._capture_worker()),
                    asyncio.create_task(self._vad_worker()),
                    asyncio.create_task(self._stt_worker()),
                ]
                if loopback:
                    self._tasks += [
                        asyncio.create_task(self._capture_loopback_worker()),
                        asyncio.create_task(self._vad_loopback_worker()),
                        asyncio.create_task(self._stt_loopback_worker()),
                    ]
            logger.info(f"Pipeline manager tasks launched (text_input_mode={self.text_input_mode})")
        except Exception as e:
            logger.error(f"Failed to start pipeline manager: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        self.running = False
        for q in (self.audio_queue, self.audio_loopback_queue, self.stt_queue, self.stt_loopback_queue, self.translation_queue, self.tts_queue):
            try:
                await q.put(None)
            except Exception:
                pass

        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        services = [self.audio_router, self.tts, self.translator, self.stt, self.vad, self.audio_input]
        if self.denoiser is not None:
            services.append(self.denoiser)
        for svc in services:
            try:
                await svc.stop()
            except Exception:
                pass

        self._stt_states.clear()
        self._stt_in_progress = False
        self._lang_validator.reset()
        logger.info("Pipeline manager stopped")

    # -- workers --

    async def _capture_worker(self) -> None:
        try:
            async for chunk in self.audio_input.stream():
                if not self.running:
                    break
                if self.text_input_mode and not self._loopback:
                    continue
                if not self._loopback and time.time() < self._ignore_mic_until:
                    continue
                try:
                    await self.audio_queue.put(chunk)
                except asyncio.QueueFull:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Capture worker error: {e}")

    async def _capture_loopback_worker(self) -> None:
        try:
            async for chunk in self.audio_input.stream_loopback():
                if not self.running:
                    break
                try:
                    await self.audio_loopback_queue.put(chunk)
                except asyncio.QueueFull:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Capture loopback worker error: {e}")

    async def _vad_worker(self) -> None:
        try:
            while self.running:
                chunk = await self.audio_queue.get()
                if chunk is None:
                    break
                if self.denoiser is not None and self.denoiser.enabled:
                    chunk = await self.denoiser.process_chunk(chunk)
                async for vad_result in self.vad.process(chunk):
                    if not self.running:
                        break
                    if vad_result.is_speech or self.vad.is_speech_active():
                        try:
                            await self.stt_queue.put(chunk)
                        except asyncio.QueueFull:
                            pass
                    if vad_result.speech_end is not None:
                        try:
                            await self.stt_queue.put(None)
                        except asyncio.QueueFull:
                            pass
                        if self.on_status:
                            self.on_status("Processing speech...", "processing")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"VAD worker error: {e}")
        finally:
            try:
                await self.stt_queue.put(None)
            except Exception:
                pass

    async def _vad_loopback_worker(self) -> None:
        try:
            while self.running:
                chunk = await self.audio_loopback_queue.get()
                if chunk is None:
                    break
                if self.denoiser is not None and self.denoiser.enabled:
                    chunk = await self.denoiser.process_chunk(chunk)
                async for vad_result in self.vad.process(chunk):
                    if not self.running:
                        break
                    if vad_result.is_speech or self.vad.is_speech_active():
                        try:
                            await self.stt_loopback_queue.put(chunk)
                        except asyncio.QueueFull:
                            pass
                    if vad_result.speech_end is not None:
                        try:
                            await self.stt_loopback_queue.put(None)
                        except asyncio.QueueFull:
                            pass
                        if self.on_status:
                            self.on_status("Processing speech...", "processing")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"VAD loopback worker error: {e}")
        finally:
            try:
                await self.stt_loopback_queue.put(None)
            except Exception:
                pass

    async def _stt_worker(self) -> None:
        try:
            while self.running:
                try:
                    item = await asyncio.wait_for(self.stt_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    state = self._stt_state("mic")
                    if state["segment_audio"]:
                        await self._finalize_segment(source="mic", is_final=True)
                    if self.on_status:
                        self.on_status("Listening...", "listening")
                    continue
                audio = np.frombuffer(item.data, dtype=np.float32)
                if audio.size == 0:
                    continue
                state = self._stt_state("mic")
                state["segment_audio"].append(audio)
                state["segment_samples"] += audio.size
                if state["segment_samples"] >= self._max_segment_s * 16000:
                    await self._finalize_segment(source="mic", is_final=True)
                    continue
                now = time.time()
                if state["segment_samples"] >= 16000 and (now - state["last_stt_feed"]) >= self._stt_feed_interval_s:
                    state["last_stt_feed"] = now
                    await self._finalize_segment(source="mic", is_final=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT worker error: {e}")

    async def _stt_loopback_worker(self) -> None:
        try:
            while self.running:
                try:
                    item = await asyncio.wait_for(self.stt_loopback_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    state = self._stt_state("loopback")
                    if state["segment_audio"]:
                        await self._finalize_segment(source="loopback", is_final=True)
                    if self.on_status:
                        self.on_status("Listening...", "listening")
                    continue
                audio = np.frombuffer(item.data, dtype=np.float32)
                if audio.size == 0:
                    continue
                state = self._stt_state("loopback")
                state["segment_audio"].append(audio)
                state["segment_samples"] += audio.size
                if state["segment_samples"] >= self._max_segment_s * 16000:
                    await self._finalize_segment(source="loopback", is_final=True)
                    continue
                now = time.time()
                if state["segment_samples"] >= 16000 and (now - state["last_stt_feed"]) >= self._stt_feed_interval_s:
                    state["last_stt_feed"] = now
                    await self._finalize_segment(source="loopback", is_final=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT loopback worker error: {e}")

    async def _finalize_segment(self, source: str, is_final: bool) -> None:
        state = self._stt_state(source)
        seg_audio = state["segment_audio"]
        seg_samples = state["segment_samples"]
        if not seg_audio or seg_samples < 1600:
            if is_final:
                seg_audio.clear()
                state["segment_samples"] = 0
                state["partial_offset"] = 0
                state["partial_accumulated_text"] = ""
            return
        if not is_final and self._stt_in_progress:
            return
        full = np.concatenate(seg_audio)
        if is_final:
            audio = full
        else:
            if state["partial_offset"] >= seg_samples:
                return
            audio = full[state["partial_offset"]:]
            if len(audio) < 1600:
                return
        if self.on_status and is_final:
            self.on_status("Transcribing...", "processing")
        self._stt_in_progress = True
        try:
            result = await self.stt.transcribe(audio, is_final=is_final)
        except Exception as e:
            logger.error(f"STT error: {e}")
            return
        finally:
            self._stt_in_progress = False
        if self.on_transcription:
            self.on_transcription(result)
        text = (result.text or "").strip()
        if not text:
            return
        if is_final:
            seg_audio.clear()
            state["segment_samples"] = 0
            state["partial_offset"] = 0
            state["partial_accumulated_text"] = ""
            text_to_send = text
            if not text:
                return
            if text.lower() == state["last_final_text"].lower():
                return
            state["last_final_text"] = text
        else:
            state["partial_offset"] = seg_samples
            text_to_send = (state["partial_accumulated_text"] + " " + text).strip()
            state["partial_accumulated_text"] = text_to_send
            if not text_to_send:
                return
            if text_to_send.lower() == state["last_partial_text"].lower():
                return
            state["last_partial_text"] = text_to_send
        if is_final:
            segment_input_src = "COMPUTER_AUDIO" if source == "loopback" else "VOICE"
            segment = TranscriptionSegment(
                text=text_to_send, is_final=True,
                start_time=datetime.now(), end_time=datetime.now(),
                language=result.language or "", confidence=result.confidence,
                input_source=segment_input_src,
            )
            try:
                await self.translation_queue.put(segment)
            except asyncio.QueueFull:
                pass
        else:
            if self.on_translation:
                from core.interfaces import TranslationResult
                try:
                    self.on_translation(TranslationResult(
                        original_text=text_to_send, translated_text="...",
                        source_lang=self._source_lang, target_lang=self._target_lang,
                        is_final=False,
                    ))
                except Exception:
                    pass

    async def _translation_worker(self) -> None:
        try:
            while self.running:
                segment = await self.translation_queue.get()
                if segment is None:
                    break
                if not segment.is_final:
                    await self._translate_and_route(segment, is_final=False, enqueue_tts=False)
                    continue
                await self._translate_and_route(segment, is_final=True, enqueue_tts=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Translation worker error: {e}")

    async def _translate_and_route(self, segment: TranscriptionSegment, is_final: bool, enqueue_tts: bool = True) -> None:
        src = self._source_lang
        tgt = self._target_lang
        detected = (segment.language or "").strip()
        confidence = getattr(segment, "confidence", 0.0)
        if self.translation_mode == "two_way" and detected:
            from utils.languages import get_language_code
            det_code = (get_language_code(detected) or detected).upper()
            src_code = self._source_lang.upper()
            tgt_code = self._target_lang.upper()
            if det_code in (src_code, tgt_code):
                validated = self._lang_validator.validate(
                    detected_lang=det_code, confidence=confidence,
                    source_lang=src_code, target_lang=tgt_code,
                    context_engine=self.context_engine if is_final else None,
                )
                if validated == tgt_code:
                    src, tgt = tgt_code, src_code
                else:
                    src, tgt = src_code, tgt_code
            elif det_code == src_code:
                src, tgt = src_code, tgt_code
        if self.on_status and is_final:
            self.on_status("Translating...", "translating")
        context = self.context_engine.build_context_prompt(src, tgt) if is_final else None
        t_trans_start = time.time()
        try:
            translation = await asyncio.wait_for(
                self.translator.translate(segment.text, src, tgt, context=context),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Translation timed out (>5s via proxy)")
            return
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return
        trans_latency_ms = (time.time() - t_trans_start) * 1000.0
        input_src = getattr(segment, "input_source", "VOICE")
        logger.info(f"[{input_src}] Language detected: {src} -> {tgt} | Translation latency: {trans_latency_ms:.1f}ms")
        translated = (translation.translated_text or "").strip()
        if not translated:
            return
        if self.settings and getattr(self.settings, "ai_assistant_enabled", True):
            keywords_str = getattr(self.settings, "keywords", "")
            if keywords_str:
                kw_map = parse_keywords(keywords_str)
                translated = apply_keywords(translated, kw_map)
        if is_final:
            self.context_engine.add_segment(segment.text, translated, src, tgt)
        result = TranslationResult(
            original_text=segment.text, translated_text=translated,
            source_lang=src, target_lang=tgt,
            is_final=is_final, input_source=input_src,
        )
        if self.on_translation:
            self.on_translation(result)
        if not enqueue_tts:
            return
        try:
            await self.tts_queue.put(result)
        except asyncio.QueueFull:
            pass

    async def _tts_worker(self) -> None:
        try:
            while self.running:
                result = await self.tts_queue.get()
                if result is None:
                    break
                if self.on_status:
                    self.on_status("Speaking...", "speaking")
                t_tts_start = time.time()
                reached_playback = False
                try:
                    async for synth in self.tts.synthesize_stream(
                        self._split_sentences(result.translated_text), result.target_lang,
                    ):
                        if synth is None or not getattr(synth, "audio_data", None):
                            continue
                        reached_playback = True
                        if not self._loopback:
                            playout_delay = getattr(self.audio_router, '_delay_s', 0.0) or 0.0
                            mute_s = (synth.duration_ms / 1000.0) + playout_delay + 0.3
                            self._ignore_mic_until = time.time() + mute_s
                        self.audio_router.enqueue_audio(synth)
                    tts_latency_ms = (time.time() - t_tts_start) * 1000.0
                    input_src = getattr(result, "input_source", "VOICE")
                    logger.info(f"[{input_src}] TTS synthesis latency: {tts_latency_ms:.1f}ms")
                except Exception as e:
                    logger.error(f"TTS/playback error: {e}")
                finally:
                    if not reached_playback:
                        self._ignore_mic_until = 0.0
                    if self.running and self.on_status:
                        self.on_status("Listening...", "listening")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"TTS worker error: {e}")

    @staticmethod
    async def _split_sentences(text: str):
        if not text or not text.strip():
            return
        buf = ""
        for ch in text:
            buf += ch
            if ch in ".!?;:\n" and buf.strip():
                yield buf.strip()
                buf = ""
        if buf.strip():
            yield buf.strip()

    async def _stats_worker(self) -> None:
        while self.running:
            try:
                from utils.latency import get_all_latency_summaries
                summaries = get_all_latency_summaries()
                if self.on_latency and summaries:
                    overall_avg = sum(s["avg_ms"] for s in summaries.values()) / len(summaries)
                    self.on_latency({"avg_ms": overall_avg, "stages": summaries})
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Stats worker error: {e}")

    def set_volume(self, volume: float) -> None:
        self.audio_router.set_volume(volume)

    def set_muted(self, muted: bool) -> None:
        self.audio_router.set_muted(muted)

    def set_delay(self, delay_s: float) -> None:
        self.audio_router.set_delay(delay_s)

    async def process_text_input(self, text: str, source_lang: Optional[str] = None) -> None:
        clean_text = text.strip()
        if not clean_text:
            logger.warning("Empty text input received, ignoring")
            return
        if len(clean_text) > 5000:
            logger.warning(f"Text input exceeds 5000 chars limit ({len(clean_text)} chars)")
            raise ValueError("Message exceeds maximum length of 5000 characters")
        start_ts = time.time()
        logger.info(f"[TEXT MODE] Typed text received ({len(clean_text)} chars): '{clean_text[:60]}'")
        segment = TranscriptionSegment(
            text=clean_text, is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language=source_lang or getattr(self, "_source_lang", "AUTO"),
            confidence=1.0, input_source="TEXT",
        )
        if self.on_transcription:
            try:
                self.on_transcription(segment)
            except Exception as e:
                logger.debug(f"on_transcription callback error: {e}")
        try:
            await self.translation_queue.put(segment)
            logger.info(f"[TEXT MODE] Text segment enqueued to translation pipeline (preparation latency: {(time.time() - start_ts) * 1000:.1f}ms)")
        except asyncio.QueueFull:
            logger.warning("Translation queue full, dropping text segment")

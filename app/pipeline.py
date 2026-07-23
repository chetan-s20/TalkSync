from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Optional

import numpy as np

from app.interfaces import (
    AudioChunk,
    AudioProcessor,
    BaseAudioInput,
    BaseAudioOutput,
    BaseSTT,
    BaseTTS,
    BaseTranslator,
    BaseVAD,
    TranscriptionSegment,
    TranslationResult,
)
from app.pipeline_state import PipelineState, SttJob
from services.history.database import HistoryDatabase
from services.translation.context_engine import ContextEngine
from services.translation.language_validator import LanguageValidator
from utils.logger import get_logger

logger = get_logger("pipeline")

FEED_INTERVAL_S = 0.5


class Pipeline:
    def __init__(
        self,
        audio_input: BaseAudioInput,
        vad: BaseVAD,
        stt: BaseSTT,
        translator: BaseTranslator,
        tts: BaseTTS,
        audio_output: BaseAudioOutput,
        audio_processors: Optional[list[AudioProcessor]] = None,
        context_engine: Optional[ContextEngine] = None,
        settings: Any = None,
        db: Optional[HistoryDatabase] = None,
    ):
        self._audio_input = audio_input
        self._vad = vad
        self._stt = stt
        self._translator = translator
        self._tts = tts
        self._audio_output = audio_output
        self._audio_processors = audio_processors or []
        self._context_engine = context_engine or ContextEngine()
        self._settings = settings
        self._lang_validator = LanguageValidator()
        self._state = PipelineState()
        self._db = db
        self._db_session_id: Optional[int] = None
        self._db_blocks: list[dict] = []

        self.running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: list[asyncio.Task] = []

        self.audio_queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=1000)
        self.stt_queue: asyncio.Queue[SttJob] = asyncio.Queue(maxsize=256)
        self.translation_queue: asyncio.Queue[TranscriptionSegment] = asyncio.Queue(maxsize=256)
        self.tts_queue: asyncio.Queue[TranslationResult] = asyncio.Queue(maxsize=256)

        self._ignore_mic_until: float = 0.0
        self._source_lang: str = "EN"
        self._target_lang: str = "HI"
        self._translation_mode: str = "two_way"
        self._loopback_enabled: bool = False
        self._mic_muted: bool = False
        self._text_mode: bool = False

        self.on_transcription: Optional[Callable] = None
        self.on_translation: Optional[Callable] = None
        self.on_status: Optional[Callable] = None
        self.on_latency: Optional[Callable] = None
        self.on_audio_level: Optional[Callable] = None

        # Per-panel TTS enable flags (set by UI speaker buttons)
        self.tts_enabled_a: bool = True  # Panel A: English→Hindi TTS
        self.tts_enabled_b: bool = True  # Panel B: Hindi→English TTS

    async def start(
        self,
        source_lang: str,
        target_lang: str,
        loopback: bool = False,
        text_mode: bool = False,
    ) -> None:
        if self.running:
            return
        self.running = True
        self._loop = asyncio.get_running_loop()
        self._source_lang = source_lang.upper()
        self._target_lang = target_lang.upper()
        self._loopback_enabled = loopback
        self._text_mode = text_mode

        self.audio_queue = asyncio.Queue(maxsize=1000)
        self.stt_queue = asyncio.Queue(maxsize=256)
        self.translation_queue = asyncio.Queue(maxsize=256)
        self.tts_queue = asyncio.Queue(maxsize=256)

        logger.info(f"Pipeline start: {self._source_lang} -> {self._target_lang}")

        # Start history session
        self._db_blocks = []
        if self._db is not None:
            try:
                self._db.connect()
                from datetime import datetime as _dt
                session_title = f"Session {_dt.now().strftime('%Y-%m-%d %H:%M')}"
                self._db_session_id = self._db.save_session(session_title, [])
            except Exception as e:
                logger.warning(f"DB session create failed: {e}")
                self._db_session_id = None

        if self._settings:
            seed = getattr(self._settings, "context_seed", "") or ""
            if seed:
                self._context_engine.set_seed_context(seed)

        try:
            if self.on_status:
                self.on_status("Starting audio...", "processing")
            should_capture = loopback or not text_mode
            if should_capture:
                await self._audio_input.start(loopback=loopback, capture_mic=not text_mode)
            if not self.running:
                return

            for svc_name, svc in [("VAD", self._vad), ("STT", self._stt), ("Translator", self._translator), ("TTS", self._tts)]:
                if self.on_status:
                    self.on_status(f"Loading {svc_name}...", "processing")
                await svc.start()
                if not self.running:
                    return

            if self.on_status:
                self.on_status("Warming translator...", "processing")
            try:
                await asyncio.wait_for(
                    self._translator.translate("warm up", self._source_lang, self._target_lang),
                    timeout=15.0,
                )
            except Exception:
                logger.debug("Translator warm-up skipped")

            if self.on_status:
                self.on_status("Opening audio output...", "processing")
            await self._audio_output.start()

            if self.on_status:
                self.on_status("Listening...", "listening")

            tasks = [
                asyncio.create_task(self._vad_worker()),
                asyncio.create_task(self._stt_worker()),
                asyncio.create_task(self._translation_worker()),
                asyncio.create_task(self._tts_worker()),
                asyncio.create_task(self._stats_worker()),
            ]
            if should_capture:
                if not text_mode:
                    tasks.append(asyncio.create_task(self._capture_worker("mic")))
                if loopback:
                    tasks.append(asyncio.create_task(self._capture_worker("loopback")))
            self._tasks = tasks
            logger.info(f"Pipeline workers launched")
        except Exception as e:
            logger.error(f"Pipeline start failed: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        self.running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for svc in [self._audio_output, self._tts, self._translator, self._stt, self._vad, self._audio_input]:
            try:
                await svc.stop()
            except Exception:
                pass

        self._state.reset()
        self._lang_validator.reset()

        # Persist history session
        if self._db is not None and self._db_session_id is not None and self._db_blocks:
            try:
                import sqlite3
                conn = self._db._conn
                if conn:
                    conn.execute(
                        "UPDATE sessions SET blocks=?, duration_seconds=? WHERE id=?",
                        (
                            __import__('json').dumps(self._db_blocks),
                            len(self._db_blocks) * 5.0,  # rough estimate
                            self._db_session_id,
                        )
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"DB session save failed: {e}")
            try:
                self._db.close()
            except Exception:
                pass
        self._db_session_id = None
        self._db_blocks = []

        logger.info("Pipeline stopped")

    def _should_ignore_mic(self) -> bool:
        if self._mic_muted:
            return True
        return time.time() < self._ignore_mic_until

    async def _process_audio(self, chunk: AudioChunk) -> AudioChunk:
        audio_array = np.frombuffer(chunk.data, dtype=np.float32)
        for processor in self._audio_processors:
            audio_array = await processor.process(audio_array, chunk.sample_rate)
        chunk.data = audio_array.tobytes()
        return chunk

    # Stereo Mix delivers very quiet signal (RMS ~0.005 vs speech ~0.1); amplify to match normal level
    _LOOPBACK_GAIN = 30.0

    async def _capture_worker(self, source: str) -> None:
        try:
            stream = self._audio_input.stream() if source == "mic" else self._audio_input.stream_loopback()
            chunk_count = 0
            async for chunk in stream:
                if source == "mic" and self._should_ignore_mic():
                    continue
                chunk.source = source
                if source == "loopback":
                    arr = np.frombuffer(chunk.data, dtype=np.float32)
                    arr = np.clip(arr * self._LOOPBACK_GAIN, -1.0, 1.0)
                    chunk.data = arr.tobytes()
                    if chunk_count % 200 == 0:
                        gained_rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                        logger.info(f"[DIAG] LOOPBACK_GAINED: rms={gained_rms:.6f} (after {self._LOOPBACK_GAIN}×)")
                chunk = await self._process_audio(chunk)

                # Compute and emit RMS audio level
                if self.on_audio_level and source == "mic":
                    try:
                        audio_array = np.frombuffer(chunk.data, dtype=np.float32)
                        rms = float(np.sqrt(np.mean(audio_array ** 2)))
                        self.on_audio_level(rms)
                    except Exception:
                        pass

                chunk_count += 1
                if chunk_count % 200 == 0:
                    logger.info(f"[DIAG] CAPTURE [{source}]: enqueued {chunk_count} chunks to audio_queue")

                try:
                    await self.audio_queue.put(chunk)
                except asyncio.QueueFull:
                    logger.warning(f"[DIAG] CAPTURE [{source}]: audio_queue FULL — dropping chunk #{chunk_count}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Capture worker [{source}] error: {e}")

    async def _vad_worker(self) -> None:
        try:
            while self.running:
                try:
                    chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue

                audio_array = np.frombuffer(chunk.data, dtype=np.float32)

                # DIAG: confirm VAD is receiving chunks (every 500th)
                self._vad_chk = getattr(self, "_vad_chk", 0) + 1
                if self._vad_chk % 500 == 0:
                    rms = float(np.sqrt(np.mean((audio_array.astype(np.float64) ** 2))))
                    logger.info(f"[DIAG] VAD_WORKER [{chunk.source}]: chunk #{self._vad_chk}, rms={rms:.6f}")

                buf = self._state.get_buffer(chunk.source)
                tracker = self._state.get_speech_tracker(chunk.source)

                async for vad_result in self._vad.process(chunk):
                    is_active = tracker.update(vad_result.is_speech)

                    # DIAG: log VAD probability for periodic health check
                    if self._vad_chk % 500 == 0:
                        logger.info(f"[DIAG] VAD_MODEL [{chunk.source}]: prob={vad_result.confidence:.4f}, threshold=0.6, is_speech={vad_result.is_speech}, active={is_active}")

                    if is_active or tracker.just_activated:
                        buf.append(audio_array)

                    if tracker.just_deactivated and buf.has_minimum:
                        if self.on_status:
                            self.on_status("Processing speech...", "processing")
                        stt_job = buf.finalize()
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: speech finalized ({len(stt_job.audio)} bytes) → stt_queue")
                            await self.stt_queue.put(stt_job)
                    elif buf.is_full and buf.has_minimum:
                        stt_job = buf.finalize()
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: buffer full ({len(stt_job.audio)} bytes) → stt_queue")
                            await self.stt_queue.put(stt_job)
                    elif buf.total_samples >= 16000 and time.time() - buf.last_feed_time >= FEED_INTERVAL_S:
                        buf.last_feed_time = time.time()
                        stt_job = buf.finalize(partial=True)
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: partial ({buf.total_samples}samples) → stt_queue")
                            await self.stt_queue.put(stt_job)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"VAD worker error: {e}")

    async def _stt_worker(self) -> None:
        try:
            while self.running:
                try:
                    job = await asyncio.wait_for(self.stt_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                if self.on_status:
                    self.on_status("Transcribing..." if job.is_final else "Processing...", "processing")

                try:
                    result = await self._stt.transcribe(job.audio, is_final=job.is_final)
                except Exception as e:
                    logger.error(f"STT error [{job.source}]: {e}")
                    continue

                if result is None:
                    continue
                text = (result.text or "").strip()
                logger.info(f"[DIAG] STT [{job.source}]: text='{text[:80]}', lang={result.language}, final={job.is_final}, confidence={result.confidence:.3f}")
                if not text:
                    continue

                input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"
                result.input_source = input_src

                if self.on_transcription:
                    try:
                        self.on_transcription(result)
                    except Exception:
                        pass

                if job.is_final:
                    if text.lower() == job.last_final_text.lower():
                        continue
                    segment = TranscriptionSegment(
                        text=text, is_final=True,
                        start_time=datetime.now(), end_time=datetime.now(),
                        language=result.language or "", confidence=result.confidence,
                        language_probability=getattr(result, "language_probability", 0.0),
                        input_source=input_src,
                    )
                    try:
                        await self.translation_queue.put(segment)
                    except asyncio.QueueFull:
                        pass
                else:
                    accumulated = (job.accumulated_text + " " + text).strip()
                    if accumulated.lower() == job.last_partial_text.lower():
                        continue
                    if self.on_translation:
                        try:
                            self.on_translation(TranslationResult(
                                original_text=accumulated, translated_text="...",
                                source_lang=self._source_lang, target_lang=self._target_lang,
                                is_final=False, input_source=input_src,
                            ))
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT worker error: {e}")

    async def _translation_worker(self) -> None:
        try:
            while self.running:
                try:
                    segment = await asyncio.wait_for(self.translation_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                logger.info(f"[DIAG] TRANSLATION: got segment text='{segment.text[:60]}', src={segment.input_source}, is_final={segment.is_final}")
                await self._translate_and_route(
                    segment,
                    is_final=segment.is_final,
                    enqueue_tts=segment.is_final,
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Translation worker error: {e}")

    async def _translate_and_route(self, segment: TranscriptionSegment, is_final: bool, enqueue_tts: bool = True) -> None:
        detected = (segment.language or "").strip()
        confidence = segment.confidence

        if detected.upper() in ("HI", "HINDI"):
            src = "HI"
            tgt = "EN"
        elif detected and detected.upper() in ("EN", "ENGLISH"):
            src = "EN"
            tgt = "HI"
        else:
            # No language detected: fall back to input-source heuristic
            if segment.input_source and segment.input_source.upper() in ("COMPUTER_AUDIO", "LOOPBACK"):
                src = self._target_lang
                tgt = self._source_lang
            else:
                src = self._source_lang
                tgt = self._target_lang

        if src.upper() == "AUTO":
            if detected:
                from utils.languages import get_language_code
                det_code = (get_language_code(detected) or detected).upper()
                src = det_code
            else:
                src = "EN"

        if tgt.upper() == "AUTO":
            if detected:
                from utils.languages import get_language_code
                det_code = (get_language_code(detected) or detected).upper()
                if det_code != src.upper():
                    tgt = det_code
                else:
                    tgt = "HI" if src.upper() == "EN" else "EN"
            else:
                tgt = "HI" if src.upper() == "EN" else "EN"

        if self._translation_mode == "two_way" and detected:
            from utils.languages import get_language_code
            det_code = (get_language_code(detected) or detected).upper()
            src_code = src.upper()
            tgt_code = tgt.upper()
            if det_code in (src_code, tgt_code):
                validated = self._lang_validator.validate(
                    detected_lang=det_code, confidence=confidence,
                    source_lang=src_code, target_lang=tgt_code,
                    context_engine=self._context_engine if is_final else None,
                )
                if validated == tgt_code:
                    src, tgt = tgt_code, src_code

        if self.on_status and is_final:
            self.on_status("Translating...", "translating")

        context = self._context_engine.build_context_prompt(src, tgt) if is_final else None
        try:
            translation = await asyncio.wait_for(
                self._translator.translate(segment.text, src, tgt, context=context),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Translation timed out")
            return
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return

        translated = (translation.translated_text or "").strip()
        if not translated:
            return

        if self._settings and getattr(self._settings, "ai_assistant_enabled", True):
            keywords_str = getattr(self._settings, "keywords", "")
            if keywords_str:
                from utils.keywords import parse_keywords, apply_keywords
                kw_map = parse_keywords(keywords_str)
                translated = apply_keywords(translated, kw_map)

        if is_final:
            self._context_engine.add_segment(segment.text, translated, src, tgt)

        result = TranslationResult(
            original_text=segment.text, translated_text=translated,
            source_lang=src, target_lang=tgt,
            is_final=is_final, input_source=segment.input_source,
        )
        if self.on_translation:
            try:
                self.on_translation(result)
            except Exception:
                pass

        # Save to history DB
        if is_final and self._db is not None:
            try:
                self._db_blocks.append({
                    "original": segment.text,
                    "translated": translated,
                    "src": src,
                    "tgt": tgt,
                    "source": getattr(segment, "input_source", "VOICE"),
                    "ts": datetime.now().isoformat(),
                })
            except Exception:
                pass

        if enqueue_tts and result.is_final:
            src_upper = (result.source_lang or "").upper()
            if src_upper == "EN" and not self.tts_enabled_a:
                logger.debug(f"TTS skipped: Panel A speaker off (src={src_upper})")
            elif src_upper == "HI" and not self.tts_enabled_b:
                logger.debug(f"TTS skipped: Panel B speaker off (src={src_upper})")
            else:
                logger.info(f"[DIAG] TTS_ENQUEUE: text='{result.translated_text[:60]}', lang={result.target_lang} → tts_queue")
                try:
                    await self.tts_queue.put(result)
                except asyncio.QueueFull:
                    logger.warning("[DIAG] TTS_ENQUEUE: tts_queue FULL — dropping")

    async def _tts_worker(self) -> None:
        try:
            while self.running:
                try:
                    result = await asyncio.wait_for(self.tts_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                if self.on_status:
                    self.on_status("Speaking...", "speaking")
                logger.info(f"[DIAG] TTS_SYNTH: synthesizing text='{result.translated_text[:60]}', lang={result.target_lang}")
                try:
                    async for synth in self._tts.synthesize_stream(
                        self._split_sentences(result.translated_text),
                        result.target_lang,
                    ):
                        arr = np.frombuffer(synth.audio_data, dtype=np.float32) if getattr(synth, "audio_data", None) else np.array([])
                        if synth is None or len(arr) == 0 or np.all(arr == 0):
                            if result.original_text:
                                logger.info(f"[DIAG] TTS_SYNTH: primary failed, trying English fallback: '{result.original_text[:60]}'")
                                synth = await self._tts.synthesize(result.original_text, "en")
                                arr = np.frombuffer(synth.audio_data, dtype=np.float32) if getattr(synth, "audio_data", None) else np.array([])
                        if synth is None or len(arr) == 0 or np.all(arr == 0):
                            logger.warning("[DIAG] TTS_SYNTH: all synthesis attempts returned empty audio — skipping")
                            continue
                        logger.info(f"[DIAG] TTS_SYNTH: synthesized {synth.duration_ms:.0f}ms of audio, playing...")
                        if not self._loopback_enabled:
                            mute_s = (synth.duration_ms / 1000.0) + 0.3
                            self._ignore_mic_until = time.time() + mute_s
                        await self._audio_output.play(AudioChunk(
                            data=synth.audio_data,
                            sample_rate=synth.sample_rate,
                            channels=1,
                            timestamp=datetime.now(),
                            duration_ms=synth.duration_ms,
                            source="tts",
                        ))
                except Exception as e:
                    logger.error(f"TTS/playback error: {e}")
                finally:
                    if self.running and self.on_status:
                        self.on_status("Listening...", "listening")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"TTS worker error: {e}")

    @staticmethod
    async def _split_sentences(text: str) -> AsyncIterator[str]:
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
                pass

    async def process_text_input(self, text: str, source_lang: Optional[str] = None) -> None:
        clean = text.strip()
        if not clean:
            return
        if len(clean) > 5000:
            raise ValueError("Message exceeds 5000 character limit")

        segment = TranscriptionSegment(
            text=clean, is_final=True,
            start_time=datetime.now(), end_time=datetime.now(),
            language=source_lang or self._source_lang, confidence=1.0,
            input_source="TEXT",
        )
        if self.on_transcription:
            try:
                self.on_transcription(segment)
            except Exception:
                pass
        try:
            await self.translation_queue.put(segment)
        except asyncio.QueueFull:
            logger.warning("Translation queue full, dropping text segment")

    def mute_mic(self, muted: bool) -> None:
        self._mic_muted = muted

    def set_volume(self, volume: float) -> None:
        if hasattr(self._audio_output, "set_volume"):
            self._audio_output.set_volume(volume)

    def set_delay(self, delay_s: float) -> None:
        if hasattr(self._audio_output, "set_delay"):
            self._audio_output.set_delay(delay_s)

    def set_translation_mode(self, mode: str) -> None:
        self._translation_mode = mode

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    @property
    def text_input_mode(self) -> bool:
        return self._text_mode

    @text_input_mode.setter
    def text_input_mode(self, value: bool) -> None:
        self._text_mode = bool(value)

    def submit_text_input(self, text: str, source_lang: Optional[str] = None) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.process_text_input(text=text, source_lang=source_lang),
                self._loop,
            )
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.process_text_input(text=text, source_lang=source_lang))
            except RuntimeError:
                asyncio.run(self.process_text_input(text=text, source_lang=source_lang))

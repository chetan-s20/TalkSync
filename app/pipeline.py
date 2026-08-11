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

FEED_INTERVAL_S = 0.2  # Ultra-low latency streaming updates


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
        self._ignore_loopback_until: float = 0.0
        self._source_lang: str = "EN"
        self._target_lang: str = "HI"
        self._translation_mode: str = "two_way"
        self._loopback_enabled: bool = False
        self._mic_muted: bool = False
        self._text_mode: bool = False
        self._vad_chk: int = 0

        self.on_transcription: Optional[Callable] = None
        self.on_translation: Optional[Callable] = None
        self.on_status: Optional[Callable] = None
        self.on_latency: Optional[Callable] = None
        self.on_audio_level: Optional[Callable] = None

        # Per-panel TTS enable flags (set by UI speaker buttons)
        self.tts_enabled_a: bool = True  # Panel A: English→Hindi TTS
        self.tts_enabled_b: bool = True  # Panel B: Hindi→English TTS
        self._last_audio_level_time: float = 0.0
        self._last_stt_api_time: dict[str, float] = {"mic": 0.0, "loopback": 0.0}

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
        self._last_audio_level_time = 0.0

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
                self.on_status("Starting services...", "processing")

            for svc_name, svc in [("VAD", self._vad), ("STT", self._stt), ("Translator", self._translator), ("TTS", self._tts)]:
                if self.on_status:
                    self.on_status(f"Loading {svc_name}...", "processing")
                await svc.start()
                if not self.running:
                    return

            if self.on_status:
                self.on_status("Warming translator...", "processing")
            try:
                # Warm both translation directions to pre-load models
                await asyncio.wait_for(
                    self._translator.translate("warm up", self._source_lang, self._target_lang),
                    timeout=15.0,
                )
                # Reverse direction warmup
                await asyncio.wait_for(
                    self._translator.translate("नमस्ते रूप", self._target_lang, self._source_lang),
                    timeout=15.0,
                )
            except Exception:
                logger.debug("Translator bidirectional warm-up completed")

            if self.on_status:
                self.on_status("Opening audio output...", "processing")
            await self._audio_output.start()

            # Start audio capture input AFTER models are fully loaded and warmed up!
            # This ensures latency benchmarks don't include model loading and warm up times!
            should_capture = loopback or not text_mode
            if should_capture:
                if self.on_status:
                    self.on_status("Starting audio input...", "processing")
                await self._audio_input.start(loopback=loopback, capture_mic=not text_mode)
                if not self.running:
                    return

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

    def _should_ignore_loopback(self) -> bool:
        return time.time() < self._ignore_loopback_until

    def _activate_tts_mute_gate(self, duration_s: float) -> None:
        now = time.time()
        mute_until = (self._ignore_loopback_until if self._ignore_loopback_until > now else now) + duration_s + 0.5
        self._ignore_loopback_until = max(self._ignore_loopback_until, mute_until)
        # Mute loopback during TTS playback to prevent echo loops, but keep user mic active
        self._purge_loopback_queues()

    def _purge_loopback_queues(self) -> None:
        if hasattr(self, "_state") and self._state is not None:
            try:
                buf = self._state.get_buffer("loopback")
                if buf:
                    buf.clear()
            except Exception:
                pass
            try:
                tracker = self._state.get_speech_tracker("loopback")
                if tracker:
                    tracker.reset()
            except Exception:
                pass

        if hasattr(self, "audio_queue") and self.audio_queue is not None:
            temp_audio = []
            while not self.audio_queue.empty():
                try:
                    item = self.audio_queue.get_nowait()
                    if getattr(item, "source", "") != "loopback":
                        temp_audio.append(item)
                except asyncio.QueueEmpty:
                    break
            for item in temp_audio:
                try:
                    self.audio_queue.put_nowait(item)
                except asyncio.QueueFull:
                    logger.warning("audio_queue full while re-inserting non-loopback items during purge; dropping item")

        if hasattr(self, "stt_queue") and self.stt_queue is not None:
            temp_stt = []
            while not self.stt_queue.empty():
                try:
                    job = self.stt_queue.get_nowait()
                    if getattr(job, "source", "") != "loopback":
                        temp_stt.append(job)
                except asyncio.QueueEmpty:
                    break
            for job in temp_stt:
                try:
                    self.stt_queue.put_nowait(job)
                except asyncio.QueueFull:
                    logger.warning("stt_queue full while re-inserting non-loopback items during purge; dropping job")

    async def _process_audio(self, chunk: AudioChunk) -> AudioChunk:
        audio_array = np.frombuffer(chunk.data, dtype=np.float32)
        for processor in self._audio_processors:
            audio_array = await processor.process(audio_array, chunk.sample_rate)
        chunk.data = audio_array.tobytes()
        return chunk

    # Loopback and mic gains: keep at 1.0 (no gain) to prevent waveform clipping/distortion
    # and silent background noise amplification. Whisper STT does internal normalization.
    _LOOPBACK_GAIN = 1.0
    _MIC_GAIN = 1.0

    async def _capture_worker(self, source: str) -> None:
        try:
            stream = self._audio_input.stream() if source == "mic" else self._audio_input.stream_loopback()
            chunk_count = 0
            async for chunk in stream:
                if source == "mic" and self._should_ignore_mic():
                    continue
                if source == "loopback" and self._should_ignore_loopback():
                    continue
                chunk.source = source
                arr = np.frombuffer(chunk.data, dtype=np.float32)
                raw_rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))

                if source == "loopback":
                    # Digital loopback: zero out ambient digital hiss (RMS < 0.003) so VAD sees silence
                    if raw_rms < 0.003:
                        chunk.data = np.zeros_like(arr).tobytes()
                    else:
                        arr = np.clip(arr * self._LOOPBACK_GAIN, -1.0, 1.0)
                        chunk.data = arr.tobytes()
                    if chunk_count % 200 == 0:
                        gained_rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                        logger.info(f"[DIAG] LOOPBACK_GAINED: rms={gained_rms:.6f} (after {self._LOOPBACK_GAIN}x)")
                elif source == "mic":
                    threshold = getattr(self._settings.stt, "rms_gate_threshold", 0.0003) if self._settings else 0.0003
                    if raw_rms < threshold:
                        chunk.data = np.zeros_like(arr).tobytes()
                    else:
                        arr = np.clip(arr * self._MIC_GAIN, -1.0, 1.0)
                        chunk.data = arr.tobytes()
                chunk = await self._process_audio(chunk)

                # Compute and emit RMS audio level (throttled to 25 Hz / 40ms interval for smooth visualization)
                now = time.time()
                if self.on_audio_level and source in ("mic", "loopback") and (now - self._last_audio_level_time >= 0.04):
                    self._last_audio_level_time = now
                    try:
                        self.on_audio_level({"level": raw_rms, "rms": raw_rms, "source": source})
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
                self._vad_chk += 1
                if self._vad_chk % 500 == 0:
                    rms = float(np.sqrt(np.mean((audio_array.astype(np.float64) ** 2))))
                    logger.info(f"[DIAG] VAD_WORKER [{chunk.source}]: chunk #{self._vad_chk}, rms={rms:.6f}")

                buf = self._state.get_buffer(chunk.source)
                tracker = self._state.get_speech_tracker(chunk.source)

                async for vad_result in self._vad.process(chunk):
                    # Use tuned sensitivity threshold: 0.20 for loopback, 0.28 for mic to capture soft sentence beginnings
                    effective_threshold = 0.20 if chunk.source == "loopback" else min(0.28, getattr(self._vad.settings, "threshold", 0.35))
                    effective_is_speech = vad_result.confidence >= effective_threshold
                    is_active = tracker.update(effective_is_speech, audio_array)

                    # DIAG: log VAD probability for periodic health check
                    if self._vad_chk % 500 == 0:
                        logger.info(f"[DIAG] VAD_MODEL [{chunk.source}]: prob={vad_result.confidence:.4f}, threshold={effective_threshold}, is_speech={effective_is_speech}, active={is_active}")

                    if tracker.just_activated:
                        pending_frames = tracker.get_and_clear_pending_frames()
                        if pending_frames:
                            for p_frame in pending_frames:
                                buf.append(p_frame)
                        else:
                            buf.append(audio_array)
                    elif is_active:
                        buf.append(audio_array)

                    if tracker.just_deactivated and buf.has_minimum:
                        if self.on_status:
                            self.on_status("Processing speech...", "processing")
                        stt_job = buf.finalize()
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: speech finalized ({len(stt_job.audio)} bytes) → stt_queue")
                            try:
                                self.stt_queue.put_nowait(stt_job)
                            except asyncio.QueueFull:
                                logger.warning(f"[DIAG] VAD [{chunk.source}]: stt_queue FULL — dropping finalized job")
                    elif buf.is_full and buf.has_minimum:
                        stt_job = buf.finalize()
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: buffer full ({len(stt_job.audio)} bytes) → stt_queue")
                            try:
                                self.stt_queue.put_nowait(stt_job)
                            except asyncio.QueueFull:
                                logger.warning(f"[DIAG] VAD [{chunk.source}]: stt_queue FULL — dropping full-buffer job")
                    elif buf.total_samples >= 4800 and time.time() - buf.last_feed_time >= FEED_INTERVAL_S:
                        buf.last_feed_time = time.time()
                        stt_job = buf.finalize(partial=True)
                        if stt_job:
                            logger.info(f"[DIAG] VAD [{chunk.source}]: partial ({buf.total_samples}samples) → stt_queue")
                            try:
                                self.stt_queue.put_nowait(stt_job)
                            except asyncio.QueueFull:
                                logger.warning(f"[DIAG] VAD [{chunk.source}]: stt_queue FULL — dropping partial job")
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
                    if job.source == "loopback":
                        lang_code = self._target_lang.lower().split("-")[0] if self._target_lang else None
                    else:
                        lang_code = self._source_lang.lower().split("-")[0] if self._source_lang else "en"
                    if lang_code in ("auto", "automatic"):
                        lang_code = None

                    # Dynamically construct initial prompt using settings context and keywords to guide Whisper's vocabulary
                    prompt_parts = []
                    if self._settings:
                        context_str = getattr(self._settings, "context", "")
                        keywords_str = getattr(self._settings, "keywords", "")
                        if context_str:
                            prompt_parts.append(context_str)
                        if keywords_str:
                            from utils.keywords import parse_keywords
                            kw_map = parse_keywords(keywords_str)
                            if kw_map:
                                prompt_parts.append(", ".join(kw_map.keys()))
                    custom_prompt = " ".join(prompt_parts) if prompt_parts else None
                    # Throttle unfinalized partial API calls for cloud STT providers to respect RPM rate limits
                    if not job.is_final and self._stt.__class__.__name__ in ("GroqSTT", "OpenAISTT"):
                        now = time.time()
                        last_t = self._last_stt_api_time.get(job.source, 0.0)
                        if now - last_t < 2.0:
                            continue
                        self._last_stt_api_time[job.source] = now

                    t_stt_start = time.perf_counter()
                    result = await self._stt.transcribe(
                        job.audio,
                        is_final=job.is_final,
                        language=lang_code,
                        initial_prompt=custom_prompt,
                        source=job.source,
                    )
                    from utils.latency import get_tracker
                    get_tracker().record("stt", t_stt_start, time.perf_counter())
                except Exception as e:
                    logger.error(f"STT error [{job.source}]: {e}")
                    continue

                if result is None:
                    continue
                text = (result.text or "").strip()
                logger.info(f"[DIAG] STT [{job.source}]: text='{text[:80]}', lang={result.language}, final={job.is_final}, confidence={result.confidence:.3f}")

                if not text:
                    continue

                # Filter common Whisper hallucinations on low-volume/silent audio
                clean_norm = text.lower().strip(" .!?,")
                hallucination_phrases = {
                    "its done", "it's done", "its done.", "it's done.",
                    "thank you", "thank you.", "thank you for watching",
                    "subtitles by", "amara.org", "you", "thanks for watching",
                    "subscribe", "bye", "okay", "like and subscribe",
                    "warm up", "hello, form", "hello, form."
                }
                if clean_norm in hallucination_phrases or any(clean_norm.startswith(h) for h in ("subtitles by", "amara.org", "its done", "it's done")):
                    logger.info(f"[DIAG] STT: dropping Whisper hallucination phrase '{text}'")
                    continue

                # Translation gate: confidence filter
                if result.confidence < 0.4:
                    logger.debug(f"[DIAG] STT: low confidence ({result.confidence:.3f}) — dropping '{text[:60]}'")
                    continue

                # Translation gate: minimum word count
                min_words = getattr(self._settings.stt, "min_word_count", 1) if self._settings else 1
                words = text.split()
                if len(words) < min_words:
                    logger.debug(f"[DIAG] STT: too few words ({len(words)} < {min_words}) — dropping '{text[:60]}'")
                    continue

                input_src = "COMPUTER_AUDIO" if job.source == "loopback" else "VOICE"
                result.input_source = input_src

                if self.on_transcription:
                    try:
                        self.on_transcription(result)
                    except Exception:
                        pass

                if job.is_final:
                    if job.last_final_text and text.lower() == job.last_final_text.lower():
                        logger.info(f"[DIAG] STT: skipping duplicate final text: '{text[:60]}'")
                        continue
                    buf = self._state.get_buffer(job.source)
                    buf._last_final_text = text
                    segment = TranscriptionSegment(
                        text=text, is_final=True,
                        start_time=datetime.now(), end_time=datetime.now(),
                        language=result.language or "", confidence=result.confidence,
                        language_probability=getattr(result, "language_probability", 0.0),
                        input_source=input_src,
                    )
                    logger.info(f"[DIAG] STT: enqueuing final segment to translation_queue: text='{text[:60]}', lang={result.language}, conf={result.confidence:.3f}")
                    await self._enqueue_translation_segment(segment)
                else:
                    accumulated = (job.accumulated_text + " " + text).strip()
                    buf = self._state.get_buffer(job.source)
                    if accumulated and accumulated.lower() == getattr(buf, "_last_partial_text", "").lower():
                        continue
                    buf._last_partial_text = accumulated
                    if not accumulated:
                        continue

                    segment = TranscriptionSegment(
                        text=accumulated, is_final=False,
                        start_time=datetime.now(), end_time=datetime.now(),
                        language=result.language or "", confidence=result.confidence,
                        language_probability=getattr(result, "language_probability", 0.0),
                        input_source=input_src,
                    )
                    logger.info(f"[DIAG] STT: enqueuing partial segment to translation_queue: text='{accumulated[:60]}', lang={result.language}")
                    await self._enqueue_translation_segment(segment)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT worker error: {e}")

    async def _enqueue_translation_segment(self, segment: TranscriptionSegment) -> None:
        """
        Enqueues a segment into translation_queue with queue pruning for partial segments.
        If a new segment arrives for an input_source, older pending partial segments
        (is_final=False) for that exact source are pruned from translation_queue.
        """
        temp_items = []
        while not self.translation_queue.empty():
            try:
                item = self.translation_queue.get_nowait()
                if item.input_source != segment.input_source or item.is_final:
                    temp_items.append(item)
                else:
                    logger.info(
                        f"[DIAG] TRANSLATION_QUEUE: Pruned obsolete partial segment "
                        f"'{item.text[:30]}' for source {item.input_source}"
                    )
            except asyncio.QueueEmpty:
                break

        for item in temp_items:
            try:
                self.translation_queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning("[DIAG] TRANSLATION_QUEUE: Queue full while restoring item during prune")

        try:
            self.translation_queue.put_nowait(segment)
            logger.info(
                f"[DIAG] TRANSLATION_QUEUE: Enqueued segment (is_final={segment.is_final}, "
                f"src={segment.input_source}, qsize={self.translation_queue.qsize()})"
            )
        except asyncio.QueueFull:
            if segment.is_final:
                await self.translation_queue.put(segment)
            else:
                logger.warning(
                    f"[DIAG] TRANSLATION_QUEUE: Queue full, dropping partial segment '{segment.text[:30]}'"
                )

    async def _translation_worker(self) -> None:
        try:
            logger.info("[DIAG] TRANSLATION_WORKER: started")
            while self.running:
                try:
                    segment = await asyncio.wait_for(self.translation_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                if not segment.is_final:
                    has_newer = any(
                        item.input_source == segment.input_source
                        for item in list(self.translation_queue._queue)
                    )
                    if has_newer:
                        logger.info(
                            f"[DIAG] TRANSLATION_WORKER: Skipping obsolete partial segment "
                            f"'{segment.text[:30]}' for source {segment.input_source}"
                        )
                        continue

                logger.info(f"[DIAG] TRANSLATION: got segment text='{segment.text[:60]}', src={segment.input_source}, is_final={segment.is_final}, lang={segment.language}, conf={segment.confidence:.3f}")
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
        logger.info(f"[DIAG] TRANSLATE_AND_ROUTE: detected='{detected}', conf={confidence:.3f}, text='{segment.text[:60]}'")

        if confidence < 0.4:
            logger.info(f"[DIAG] TRANSLATE_AND_ROUTE: dropped low-confidence segment (conf={confidence:.2f})")
            return

        is_loopback = segment.input_source and segment.input_source.upper() in ("COMPUTER_AUDIO", "LOOPBACK")

        if is_loopback:
            if detected and (detected.upper() in ("EN", "ENGLISH") or detected.lower().startswith("en")):
                src = "EN"
                tgt = "HI"
            elif detected and (detected.upper() in ("HI", "HINDI") or detected.lower().startswith("hi")):
                src = "HI"
                tgt = "EN"
            else:
                src = self._target_lang or "HI"
                tgt = self._source_lang or "EN"
        elif detected and detected.upper() in ("HI", "HINDI"):
            src = "HI"
            tgt = "EN"
        elif detected and detected.upper() in ("EN", "ENGLISH"):
            src = "EN"
            tgt = "HI"
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

        if self._translation_mode == "two_way" and detected and not is_loopback:
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
        
        # Apply keywords/spelling correction mapping to original transcribed text BEFORE translating
        orig_text = segment.text
        if self._settings:
            keywords_str = getattr(self._settings, "keywords", "")
            if keywords_str:
                from utils.keywords import parse_keywords, apply_keywords
                kw_map = parse_keywords(keywords_str)
                orig_text = apply_keywords(orig_text, kw_map)
                segment.text = orig_text  # update segment with corrected spelling
        
        try:
            timeout_s = 5.0 if is_final else 2.0
            t_tr_start = time.perf_counter()
            translation = await asyncio.wait_for(
                self._translator.translate(orig_text, src, tgt, context=context),
                timeout=timeout_s,
            )
            from utils.latency import get_tracker
            get_tracker().record("translation", t_tr_start, time.perf_counter())
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
        logger.info(f"[DIAG] TRANSLATE_AND_ROUTE: calling on_translation callback with result: orig='{result.original_text[:40]}', trans='{result.translated_text[:40]}', is_final={is_final}")
        if self.on_translation:
            try:
                self.on_translation(result)
                logger.info(f"[DIAG] TRANSLATE_AND_ROUTE: on_translation callback completed successfully")
            except Exception as e:
                logger.error(f"[DIAG] TRANSLATE_AND_ROUTE: on_translation callback raised exception: {e}")
                pass
        else:
            logger.warning("[DIAG] TRANSLATE_AND_ROUTE: on_translation callback is None!")

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
            input_src = (getattr(result, "input_source", "VOICE") or "VOICE").upper()
            if input_src in ("COMPUTER_AUDIO", "LOOPBACK"):
                if not self.tts_enabled_b:
                    logger.debug(f"TTS skipped: Panel B speaker off (input_source={input_src})")
                else:
                    logger.info(f"[DIAG] TTS_ENQUEUE: text='{result.translated_text[:60]}', lang={result.target_lang} → tts_queue")
                    try:
                        self.tts_queue.put_nowait(result)
                    except asyncio.QueueFull:
                        logger.warning("[DIAG] TTS_ENQUEUE: tts_queue FULL — dropping")
            else:
                if not self.tts_enabled_a:
                    logger.debug(f"TTS skipped: Panel A speaker off (input_source={input_src})")
                else:
                    logger.info(f"[DIAG] TTS_ENQUEUE: text='{result.translated_text[:60]}', lang={result.target_lang} → tts_queue")
                    try:
                        self.tts_queue.put_nowait(result)
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
                    t_tts_start = time.perf_counter()
                    async for synth in self._tts.synthesize_stream(
                        self._split_sentences(result.translated_text),
                        result.target_lang,
                    ):
                        from utils.latency import get_tracker
                        get_tracker().record("tts", t_tts_start, time.perf_counter())
                        arr = np.frombuffer(synth.audio_data, dtype=np.float32) if getattr(synth, "audio_data", None) else np.array([])
                        if synth is None or len(arr) == 0 or np.all(arr == 0):
                            if result.original_text:
                                logger.info(f"[DIAG] TTS_SYNTH: primary failed, trying English fallback: '{result.original_text[:60]}'")
                                synth = await self._tts.synthesize(result.original_text, "en")
                                arr = np.frombuffer(synth.audio_data, dtype=np.float32) if getattr(synth, "audio_data", None) else np.array([])
                        if synth is None or len(arr) == 0 or np.all(arr == 0):
                            logger.warning("[DIAG] TTS_SYNTH: all synthesis attempts returned empty audio — falling back to Windows SAPI5 speak")
                            est_text = result.original_text or result.translated_text or ""
                            if est_text and hasattr(self._tts, "_sapi_speak"):
                                self._tts._sapi_speak(est_text)
                            est_duration_s = len(est_text) * 0.06 + 0.5
                            self._activate_tts_mute_gate(est_duration_s)
                            continue
                        logger.info(f"[DIAG] TTS_SYNTH: synthesized {synth.duration_ms:.0f}ms of audio, activating mute gate and playing...")
                        duration_s = synth.duration_ms / 1000.0
                        self._activate_tts_mute_gate(duration_s + 1.5)
                        input_src = (getattr(result, "input_source", "VOICE") or "VOICE").upper()
                        chunk_source = "panel_b" if input_src in ("COMPUTER_AUDIO", "LOOPBACK") else "panel_a"
                        await self._audio_output.play(AudioChunk(
                            data=synth.audio_data,
                            sample_rate=synth.sample_rate,
                            channels=1,
                            timestamp=datetime.now(),
                            duration_ms=synth.duration_ms,
                            source=chunk_source,
                        ))
                        # Keep mute gate active for 1.0s after playback finishes to absorb room echo & WASAPI buffer flush
                        self._activate_tts_mute_gate(1.0)
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
                    stt_ms = 0.0
                    trans_ms = 0.0
                    tts_ms = 0.0
                    for s in summaries:
                        name = (s.get("name") or "").lower()
                        if "stt" in name:
                            stt_ms = s.get("avg_ms", 0.0)
                        elif "trans" in name:
                            trans_ms = s.get("avg_ms", 0.0)
                        elif "tts" in name:
                            tts_ms = s.get("avg_ms", 0.0)
                    total_ms = stt_ms + trans_ms + tts_ms
                    self.on_latency({
                        "stt_ms": stt_ms,
                        "translation_ms": trans_ms,
                        "tts_ms": tts_ms,
                        "total_ms": total_ms,
                        "stages": summaries
                    })
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Stats worker error: {e}")

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

"""GPT-4o-mini Translator Service for TalkSync AI."""
from __future__ import annotations

import asyncio
import time
import httpx
from typing import Optional, Any

from app.interfaces import BaseTranslator, TranslationResult
from utils.logger import get_logger

logger = get_logger("gpt_translator")


class GPTTranslator(BaseTranslator):
    """High-accuracy, context-aware translation engine powered by OpenAI gpt-4o-mini."""

    OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: Any = None, api_key: Optional[str] = None, model: str = "gpt-4o-mini") -> None:
        self.settings = getattr(settings, "translation", settings) if settings else None
        
        # Extract OpenAI API key from settings if not passed explicitly
        if not api_key:
            if hasattr(settings, "openai") and getattr(settings.openai, "api_key", ""):
                api_key = settings.openai.api_key
            elif hasattr(self.settings, "deepl_api_key"):
                api_key = getattr(self.settings, "deepl_api_key", "")

        self.api_key = api_key or ""
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(f"GPTTranslator initialized with model='{self.model}'")

    async def start(self) -> None:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

    async def stop(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> TranslationResult:
        clean_text = text.strip()
        if not clean_text:
            return TranslationResult(
                original_text="",
                translated_text="",
                source_lang=source_lang,
                target_lang=target_lang,
                is_final=True,
            )

        if not self.api_key:
            raise ValueError("OpenAI API key missing for GPTTranslator")

        if self._client is None or self._client.is_closed:
            await self.start()

        # Language code normalization (e.g. EN -> English, HI -> Hindi)
        lang_names = {
            "EN": "English", "HI": "Hindi", "ES": "Spanish",
            "FR": "French", "DE": "German", "ZH": "Chinese",
            "JA": "Japanese", "KO": "Korean", "RU": "Russian",
            "AR": "Arabic", "IT": "Italian", "PT": "Portuguese"
        }
        src_name = lang_names.get(source_lang.upper(), source_lang)
        tgt_name = lang_names.get(target_lang.upper(), target_lang)

        system_prompt = (
            f"You are a professional real-time speech translator. "
            f"Translate spoken text from {src_name} to {tgt_name}. "
            f"Provide only the direct translation. Do not add explanations, notes, or quotes."
        )
        if context:
            system_prompt += f" Context: {context}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_text},
            ],
            "temperature": 0.0,
            "max_tokens": 80,
        }

        t_start = time.perf_counter()
        try:
            resp = await self._client.post(self.OPENAI_CHAT_URL, json=payload)
            duration_ms = (time.perf_counter() - t_start) * 1000.0

            if resp.status_code != 200:
                logger.error(f"GPT Translator error HTTP {resp.status_code}: {resp.text}")
                return TranslationResult(
                    original_text=clean_text,
                    translated_text=clean_text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    is_final=True,
                )

            data = resp.json()
            translated = (data["choices"][0]["message"]["content"] or "").strip()
            # Strip outer quotes if model adds them
            if translated.startswith('"') and translated.endswith('"'):
                translated = translated[1:-1].strip()

            safe_text = clean_text.encode("ascii", "replace").decode("ascii")
            safe_trans = translated.encode("ascii", "replace").decode("ascii")
            logger.info(f"GPT Translator ({duration_ms:.1f}ms): '{safe_text}' -> '{safe_trans}'")
            return TranslationResult(
                original_text=clean_text,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=target_lang,
                is_final=True,
            )
        except Exception as e:
            logger.error(f"GPT Translation failed: {e}")
            return TranslationResult(
                original_text=clean_text,
                translated_text=clean_text,
                source_lang=source_lang,
                target_lang=target_lang,
                is_final=True,
            )

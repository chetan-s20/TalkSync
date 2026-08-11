from __future__ import annotations

from typing import Optional

from app.interfaces import TranslationResult, BaseTranslator
from utils.logger import get_logger
from utils.proxy import get_proxy_dict

logger = get_logger("translation_deepl")


class DeepLTranslator(BaseTranslator):
    def __init__(self, settings):
        self.settings = settings
        self._client = None

    async def start(self) -> None:
        api_key = getattr(self.settings, "deepl_api_key", "") or ""
        if not api_key:
            logger.warning("DeepL API key not configured")
            raise ValueError("DeepL API key not configured")

        try:
            import deepl
            import asyncio

            # Try proxy first only if it is reachable via fast single socket check (1.0s timeout)
            proxy_dict = get_proxy_dict()
            proxy_url = getattr(self.settings, "proxy_url", None) or proxy_dict.get("https://")
            use_proxy = False
            if proxy_url:
                try:
                    import socket
                    from urllib.parse import urlparse
                    url_to_parse = proxy_url if "://" in proxy_url else f"http://{proxy_url}"
                    parsed = urlparse(url_to_parse)
                    host = parsed.hostname
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    if host:
                        # Fast socket connectivity check (1s timeout)
                        with socket.create_connection((host, port), timeout=1.0):
                            use_proxy = True
                except Exception as check_err:
                    logger.debug(f"DeepL proxy check failed ({check_err}) — falling back to direct connection")

            if use_proxy:
                try:
                    self._client = deepl.Translator(api_key, proxy=proxy_url)
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._client.get_usage)
                    logger.info("DeepL API initialized (via proxy)")
                    return
                except Exception as proxy_e:
                    logger.warning(f"DeepL proxy connection failed: {proxy_e}. Falling back to direct connection.")

            # Try direct
            self._client = deepl.Translator(api_key)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._client.get_usage)
            logger.info("DeepL API initialized (direct connection)")
        except Exception as e:
            logger.warning(f"DeepL init failed: {e}")
            self._client = None
            raise RuntimeError(f"DeepL init failed: {e}") from e

    async def stop(self) -> None:
        self._client = None

    async def translate(self, text: str, source_lang: str, target_lang: str, context: Optional[str] = None) -> TranslationResult:
        if self._client is None:
            return TranslationResult(
                original_text=text, translated_text=text,
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )

        import asyncio
        src = source_lang.upper()
        tgt = target_lang.upper()
        if tgt == "EN":
            tgt = "EN-US"
        elif tgt == "PT":
            tgt = "PT-PT"

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._client.translate_text(
                    text, source_lang=src, target_lang=tgt
                )
            )
            return TranslationResult(
                original_text=text, translated_text=getattr(result, "text", str(result)),
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )
        except Exception as e:
            logger.error(f"DeepL error: {e}")
            return TranslationResult(
                original_text=text, translated_text=text,
                source_lang=source_lang, target_lang=target_lang,
                is_final=True,
            )

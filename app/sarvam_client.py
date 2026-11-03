import os
import time
import base64
import logging
from typing import Optional
from dotenv import load_dotenv
import sarvamai
from sarvamai.core.api_error import ApiError
from app.chunker import chunk_text_for_translation

load_dotenv()
logger = logging.getLogger("sarvam_narrator")

MAYURA_LANGUAGES = {
    "bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN",
    "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"
}

class SarvamAPIException(Exception):
    """Clean readable exception for Sarvam API failures."""
    pass

class SarvamClientWrapper:
    def __init__(self, api_key: Optional[str] = None):
        # SARVAM_API_NEW is supported as an explicit override so a new account
        # key can be introduced without removing the existing variable.
        key = (api_key or os.getenv("SARVAM_API_NEW") or os.getenv("SARVAM_API_KEY") or "").strip()
        if not key:
            raise SarvamAPIException(
                "SARVAM_API_KEY is not configured. Please set SARVAM_API_KEY (or SARVAM_API_NEW) in your environment."
            )
        self.client = sarvamai.SarvamAI(api_subscription_key=key)

    def _should_retry(self, err: Exception) -> bool:
        status = getattr(err, "status_code", None)
        if status in [429, 500, 502, 503, 504]:
            return True
        if hasattr(err, "response") and getattr(err.response, "status_code", None) in [429, 500, 502, 503, 504]:
            return True
        return False

    def _human_error_message(self, err: Exception, action: str) -> str:
        status = getattr(err, "status_code", None)
        body = getattr(err, "body", None)
        if hasattr(err, "response"):
            status = status or getattr(err.response, "status_code", None)
            body = body or getattr(err.response, "text", None)

        # Sarvam reports exhausted account credits as a generic API error; turn
        # it into an actionable message instead of exposing the raw payload.
        raw_error = f"{body or ''} {err}"
        if "insufficient_quota" in raw_error or "No credits available" in raw_error:
            return (
                "Sarvam AI account has no credits available. Add credits to the "
                "organisation that owns this API key at https://indus.sarvam.ai/billing, "
                "then try again."
            )

        if status == 401 or status == 403:
            return "Sarvam API authentication failed. Please verify your SARVAM_API_KEY."
        elif status == 429:
            return "Sarvam API rate limit exceeded. Please try again in a few moments."
        elif status == 400:
            return f"Sarvam API bad request during {action}: {body or str(err)}"
        elif status and status >= 500:
            return f"Sarvam AI service is temporarily unavailable (HTTP {status})."
        return f"Error during {action}: {body or str(err)}"

    def translate_text(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "hi-IN",
        mode: str = "formal",
        max_retries: int = 3,
    ) -> str:
        """
        Translate text into target language, chunking into <=900 character slices.
        """
        if not text or not text.strip():
            return ""

        chunks = chunk_text_for_translation(text, max_chars=900)
        translated_pieces = []

        # Choose model: Mayura supports auto-detect and 11 languages with multiple modes
        is_extended_target = target_lang not in MAYURA_LANGUAGES
        is_extended_source = source_lang not in MAYURA_LANGUAGES and source_lang != "auto"

        if is_extended_target or is_extended_source:
            model = "sarvam-translate:v1"
            translation_mode = "formal"
        else:
            model = "mayura:v1"
            translation_mode = mode if mode in ["formal", "modern-colloquial", "classic-colloquial", "code-mixed"] else "formal"

        for idx, chunk in enumerate(chunks):
            chunk_str = chunk.strip()
            if not chunk_str:
                continue

            last_err = None
            translated_part = None

            for attempt in range(max_retries):
                try:
                    resp = self.client.text.translate(
                        input=chunk_str,
                        source_language_code=source_lang,
                        target_language_code=target_lang,
                        model=model,
                        mode=translation_mode,
                    )
                    translated_part = resp.translated_text
                    break
                except Exception as e:
                    last_err = e
                    if self._should_retry(e) and attempt < max_retries - 1:
                        backoff = (2 ** attempt) + 0.5
                        logger.warning(f"Translate retry {attempt + 1}/{max_retries} after {backoff:.1f}s: {e}")
                        time.sleep(backoff)
                    else:
                        break

            if translated_part is None:
                msg = self._human_error_message(last_err, f"translating chunk {idx + 1}")
                raise SarvamAPIException(msg)

            translated_pieces.append(translated_part)

        return " ".join(translated_pieces)

    def synthesize(
        self,
        chunk: str,
        language_code: str = "hi-IN",
        model: str = "bulbul:v3",
        speaker: str = "shubh",
        pace: float = 1.0,
        max_retries: int = 3,
    ) -> bytes:
        """
        Synthesize a chunk of text into WAV audio bytes using Bulbul TTS.
        """
        cleaned_chunk = chunk.strip()
        if not cleaned_chunk:
            raise SarvamAPIException("Cannot synthesize empty text.")

        # Clamp pace to valid range 0.5 - 2.0
        safe_pace = max(0.5, min(2.0, float(pace)))

        last_err = None
        for attempt in range(max_retries):
            try:
                resp = self.client.text_to_speech.convert(
                    text=cleaned_chunk,
                    language_code=language_code,
                    model=model,
                    speaker=speaker,
                    pace=safe_pace,
                    output_audio_codec="wav",
                )
                if not resp.audios:
                    raise SarvamAPIException("TTS response did not contain audio data.")

                audio_bytes = base64.b64decode(resp.audios[0])
                return audio_bytes
            except Exception as e:
                last_err = e
                if self._should_retry(e) and attempt < max_retries - 1:
                    backoff = (2 ** attempt) + 0.5
                    logger.warning(f"TTS retry {attempt + 1}/{max_retries} after {backoff:.1f}s: {e}")
                    time.sleep(backoff)
                else:
                    break

        msg = self._human_error_message(last_err, "text-to-speech synthesis")
        raise SarvamAPIException(msg)

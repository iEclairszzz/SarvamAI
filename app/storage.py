"""Audio persistence for serverless deployments.

Local development writes WAV files to ``outputs/`` and serves them from the
FastAPI process. On Vercel the filesystem is ephemeral, so the generated audio
is uploaded to Vercel Blob (when ``BLOB_READ_WRITE_TOKEN`` is configured) and the
public URL is returned instead.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sarvam_narrator")

BLOB_API_URL = "https://blob.vercel-storage.com"
# Keep inline fallbacks comfortably below Vercel's 4.5 MB response limit.
MAX_INLINE_AUDIO_BYTES = 2_500_000


def upload_audio_to_blob(path: Path, job_id: str) -> Optional[str]:
    """Upload a generated WAV file to Vercel Blob and return its public URL.

    Returns ``None`` when no token is configured or the upload fails, allowing
    the caller to fall back to an inline data URI.
    """
    token = (os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip()
    if not token:
        return None

    if not path.is_file():
        logger.warning("Blob upload skipped: %s does not exist", path)
        return None

    pathname = f"narration/{job_id}.wav"
    request = urllib.request.Request(
        f"{BLOB_API_URL}/{pathname}",
        data=path.read_bytes(),
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
            "x-content-type": "audio/wav",
            "x-add-random-suffix": "0",
            "x-cache-control-max-age": "86400",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        url = payload.get("url")
        if not url:
            logger.warning("Blob upload returned no URL: %s", payload)
            return None
        logger.info("Uploaded narration audio to Vercel Blob: %s", url)
        return url
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.warning("Vercel Blob upload failed (HTTP %s): %s", exc.code, detail)
        return None
    except Exception as exc:  # pragma: no cover - defensive network handling
        logger.warning("Vercel Blob upload failed: %s", exc)
        return None


def audio_data_uri(path: Path) -> Optional[str]:
    """Return a base64 data URI for small audio files, or ``None`` if too large."""
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_INLINE_AUDIO_BYTES:
        logger.warning(
            "Audio file %s is too large for inline delivery (%s bytes)",
            path,
            path.stat().st_size,
        )
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"

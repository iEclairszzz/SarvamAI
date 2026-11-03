import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.chunker import chunk_text_for_tts
from app.extract import extract_from_text, extract_from_file, extract_from_url, InputTooLargeError, ExtractionError
from app.sarvam_client import SarvamClientWrapper, SarvamAPIException
from app.audio import concatenate_wav_chunks, AudioProcessingError, OUTPUTS_DIR
from app.storage import upload_audio_to_blob, audio_data_uri
from app.presets import (
    SUPPORTED_LANGUAGES,
    SPEAKERS,
    STYLE_PRESETS,
    TRANSLATION_MODES,
    get_style_defaults,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sarvam_narrator")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Vercel sets VERCEL=1 in every function invocation. Serverless functions have
# no shared memory between requests, so narration is executed synchronously and
# audio is persisted to Vercel Blob instead of the local filesystem.
IS_SERVERLESS = bool(os.getenv("VERCEL"))

app = FastAPI(title="Sarvam Narrator", description="Multilingual TTS Content Reader powered by Sarvam AI")

# In-memory jobs store (per-process; used for local polling)
jobs: Dict[str, Dict[str, Any]] = {}

def process_narration_job(
    job_id: str,
    raw_text: Optional[str],
    file_bytes: Optional[bytes],
    filename: Optional[str],
    url: Optional[str],
    language: str,
    translate_to: Optional[str],
    translate_mode: str,
    style: str,
    speaker: Optional[str],
    pace: Optional[float],
    model: str,
):
    job = jobs[job_id]
    try:
        # Step A: Extract
        job["status"] = "extracting"
        if file_bytes and filename:
            extracted = extract_from_file(filename, file_bytes)
        elif url and url.strip():
            extracted = extract_from_url(url.strip())
        elif raw_text and raw_text.strip():
            extracted = extract_from_text(raw_text.strip())
        else:
            raise ExtractionError("No input content was provided.")

        job["title"] = extracted["title"]
        extracted_text = extracted["text"]

        # Step B: Determine Voice & Pace defaults if not explicitly given
        preset = get_style_defaults(style)
        actual_speaker = (speaker or preset["speaker"]).strip()
        actual_pace = float(pace if pace is not None else preset["pace"])
        actual_model = model or preset["model"]

        sarvam = SarvamClientWrapper()

        # Step C: Optional Translation
        narration_lang = language
        text_to_narrate = extracted_text

        if translate_to and translate_to.strip() and translate_to.strip() != language:
            job["status"] = "translating"
            logger.info(f"Job {job_id}: Translating from {language} to {translate_to} (mode={translate_mode})")
            text_to_narrate = sarvam.translate_text(
                text=extracted_text,
                source_lang=language,
                target_lang=translate_to.strip(),
                mode=translate_mode or "formal",
            )
            narration_lang = translate_to.strip()

        job["final_text"] = text_to_narrate

        # Step D: Chunking for TTS
        chunks = chunk_text_for_tts(text_to_narrate, max_chars=2000)
        if not chunks:
            raise ExtractionError("No readable sentences found to narrate.")

        job["status"] = "synthesizing"
        job["progress_total"] = len(chunks)
        job["progress_done"] = 0
        logger.info(f"Job {job_id}: Synthesizing {len(chunks)} chunks with voice={actual_speaker}, lang={narration_lang}")

        # Step E: Synthesize chunks
        audio_chunks = []
        for i, chunk in enumerate(chunks):
            wav_bytes = sarvam.synthesize(
                chunk=chunk.text,
                language_code=narration_lang,
                model=actual_model,
                speaker=actual_speaker,
                pace=actual_pace,
            )
            audio_chunks.append((wav_bytes, chunk.is_paragraph_end))
            job["progress_done"] = i + 1

        # Step F: Audio Concatenation
        job["status"] = "concatenating"
        out_filename = f"{job_id}.wav"
        out_path, duration = concatenate_wav_chunks(audio_chunks, out_filename, silence_ms=250)
        job["duration"] = round(duration, 2)

        if IS_SERVERLESS:
            # The function filesystem is ephemeral, so persist the WAV somewhere
            # the browser can fetch it from (Vercel Blob).
            audio_url = upload_audio_to_blob(out_path, job_id)
            if audio_url is None:
                audio_url = audio_data_uri(out_path)
            if audio_url is None:
                raise AudioProcessingError(
                    "Generated audio is too large for this deployment. "
                    "Configure BLOB_READ_WRITE_TOKEN (Vercel Blob) to store narration audio."
                )
            job["audio_url"] = audio_url
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            job["audio_url"] = f"/api/audio/{out_filename}"

        job["status"] = "completed"
        logger.info(f"Job {job_id} completed successfully ({duration:.1f}s). File saved to {out_path}")

    except (InputTooLargeError, ExtractionError, SarvamAPIException, AudioProcessingError) as e:
        logger.warning(f"Job {job_id} business error: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
    except Exception as e:
        logger.exception(f"Job {job_id} unexpected error: {e}")
        job["status"] = "failed"
        job["error"] = f"An unexpected error occurred: {str(e)}"

    return job


@app.get("/api/voices")
def get_voices():
    """Return available languages, speakers, content styles, and translation modes."""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "speakers": SPEAKERS,
        "styles": STYLE_PRESETS,
        "translation_modes": TRANSLATION_MODES,
    }


@app.post("/api/narrate")
async def narrate(
    background_tasks: BackgroundTasks,
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    language: str = Form("hi-IN"),
    translate_to: Optional[str] = Form(None),
    translate_mode: Optional[str] = Form("formal"),
    style: Optional[str] = Form("news"),
    speaker: Optional[str] = Form(None),
    pace: Optional[float] = Form(None),
    model: Optional[str] = Form("bulbul:v3"),
):
    """
    Initiate narration job in background.
    Returns job_id for progress polling.
    """
    file_bytes = None
    filename = None
    if file and file.filename:
        file_bytes = await file.read()
        filename = file.filename

    # Basic quick validation
    has_text = bool(text and text.strip())
    has_file = bool(file_bytes and len(file_bytes) > 0)
    has_url = bool(url and url.strip())

    if not (has_text or has_file or has_url):
        raise HTTPException(
            status_code=400,
            detail="Please provide input via pasted text, a file upload (.txt, .md, .pdf), or a web article URL."
        )

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress_done": 0,
        "progress_total": 1,
        "title": "Processing...",
        "audio_url": None,
        "duration": None,
        "final_text": None,
        "error": None,
    }

    job_kwargs = dict(
        raw_text=text,
        file_bytes=file_bytes,
        filename=filename,
        url=url,
        language=language,
        translate_to=translate_to,
        translate_mode=translate_mode,
        style=style or "news",
        speaker=speaker,
        pace=pace,
        model=model or "bulbul:v3",
    )

    if IS_SERVERLESS:
        # Serverless instances do not share memory between requests, so run the
        # job before responding and return the finished result directly.
        return process_narration_job(job_id=job_id, **job_kwargs)

    background_tasks.add_task(process_narration_job, job_id=job_id, **job_kwargs)

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    """Get status and progress of an active or completed narration job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    return jobs[job_id]


@app.get("/api/audio/{filename}")
def get_audio(filename: str):
    """Serve synthesized WAV audio file for playback and download."""
    safe_filename = Path(filename).name
    file_path = OUTPUTS_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return FileResponse(
        path=str(file_path),
        media_type="audio/wav",
        filename=safe_filename,
    )

@app.get("/api/health")
def health():
    """Lightweight readiness probe for the deployed environment."""
    return {
        "status": "ok",
        "serverless": IS_SERVERLESS,
        "blob_storage": bool(os.getenv("BLOB_READ_WRITE_TOKEN")),
    }

# Static files for Single Page App
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

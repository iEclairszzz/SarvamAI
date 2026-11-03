import os
import io
import uuid
import wave
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.chunker import chunk_text_for_tts, split_into_sentences
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
from app.db import (
    init_db,
    save_job,
    get_job,
    update_job_position,
    get_listening_history,
    delete_history_job,
    clear_all_history,
    add_bookmark,
    delete_bookmark,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sarvam_narrator")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
PREVIEWS_DIR = OUTPUTS_DIR / "previews"
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

# Initialize database
init_db()

# Vercel sets VERCEL=1 in every function invocation. Serverless functions have
# no shared memory between requests, so narration is executed synchronously and
# audio is persisted to Vercel Blob instead of the local filesystem.
IS_SERVERLESS = bool(os.getenv("VERCEL"))

app = FastAPI(title="Sarvam Narrator", description="Multilingual TTS Content Reader powered by Sarvam AI")

# In-memory jobs store (per-process; used for local polling)
jobs: Dict[str, Dict[str, Any]] = {}


class PositionUpdateRequest(BaseModel):
    position: float


class BookmarkCreateRequest(BaseModel):
    time: float
    label: Optional[str] = None


def compute_sentence_timestamps(
    chunks: list,
    audio_chunks: list,
) -> List[Dict[str, Any]]:
    """Compute exact sentence start and end timestamps across concatenated chunks."""
    all_sentences: List[Dict[str, Any]] = []
    current_time_offset = 0.0
    sentence_counter = 0

    for i, (chunk_obj, (wav_bytes, is_para_end)) in enumerate(zip(chunks, audio_chunks)):
        # Determine exact chunk duration from WAV headers
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
                chunk_duration = float(reader.getnframes()) / float(reader.getframerate())
        except Exception:
            chunk_duration = 0.0

        # Split chunk text into constituent sentences
        chunk_sentences = split_into_sentences(chunk_obj.text)
        if not chunk_sentences:
            chunk_sentences = [chunk_obj.text]

        total_chunk_chars = sum(len(s.strip()) for s in chunk_sentences) or 1
        chunk_accum_time = 0.0

        for s_idx, s_text in enumerate(chunk_sentences):
            s_clean = s_text.strip()
            if not s_clean:
                continue
            prop_ratio = len(s_clean) / float(total_chunk_chars)
            s_duration = prop_ratio * chunk_duration

            start_sec = current_time_offset + chunk_accum_time
            end_sec = start_sec + s_duration
            chunk_accum_time += s_duration

            all_sentences.append({
                "id": sentence_counter,
                "chunk_id": i,
                "text": s_clean,
                "start": round(start_sec, 2),
                "end": round(end_sec, 2),
                "is_paragraph_end": (s_idx == len(chunk_sentences) - 1 and is_para_end),
            })
            sentence_counter += 1

        current_time_offset += chunk_duration
        if is_para_end:
            current_time_offset += 0.250  # 250ms silence between paragraphs

    return all_sentences


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
    if job_id not in jobs:
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
            "last_position": 0.0,
            "sentences": [],
            "bookmarks": [],
        }
    job = jobs[job_id]
    try:
        # Step A: Extract
        job["status"] = "extracting"
        save_job(job)
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
            save_job(job)
            logger.info(f"Job {job_id}: Translating from {language} to {translate_to} (mode={translate_mode})")
            text_to_narrate = sarvam.translate_text(
                text=extracted_text,
                source_lang=language,
                target_lang=translate_to.strip(),
                mode=translate_mode or "formal",
            )
            narration_lang = translate_to.strip()

        job["final_text"] = text_to_narrate
        job["language"] = narration_lang
        job["speaker"] = actual_speaker
        job["style"] = style

        # Step D: Chunking for TTS
        chunks = chunk_text_for_tts(text_to_narrate, max_chars=2000)
        if not chunks:
            raise ExtractionError("No readable sentences found to narrate.")

        job["status"] = "synthesizing"
        job["progress_total"] = len(chunks)
        job["progress_done"] = 0
        save_job(job)
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

        # Step G: Calculate sentence-level timestamps for synchronized karaoke reading
        job["sentences"] = compute_sentence_timestamps(chunks, audio_chunks)

        if IS_SERVERLESS:
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
        save_job(job)
        logger.info(f"Job {job_id} completed successfully ({duration:.1f}s, {len(job['sentences'])} sentences). File saved to {out_path}")

    except (InputTooLargeError, ExtractionError, SarvamAPIException, AudioProcessingError) as e:
        logger.warning(f"Job {job_id} business error: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
        save_job(job)
    except Exception as e:
        logger.exception(f"Job {job_id} unexpected error: {e}")
        job["status"] = "failed"
        job["error"] = f"An unexpected error occurred: {str(e)}"
        save_job(job)

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


@app.get("/api/voice-preview")
def get_voice_preview(
    speaker: str = Query("shubh", description="Voice persona"),
    language: str = Query("hi-IN", description="Language code"),
    model: str = Query("bulbul:v3", description="Model name"),
):
    """
    Generate or return cached voice audition preview audio.
    Enables comparing voices easily before generating narration.
    """
    speaker_clean = speaker.lower().strip()
    safe_lang = language.strip()
    preview_filename = f"preview_{speaker_clean}_{safe_lang.replace('-', '_')}.wav"
    preview_path = PREVIEWS_DIR / preview_filename

    # If already cached on disk, return immediately
    if preview_path.exists() and preview_path.stat().st_size > 1000:
        return FileResponse(
            path=str(preview_path),
            media_type="audio/wav",
            filename=preview_filename,
        )

    # Find speaker display name
    sp_info = next((s for s in SPEAKERS if s["id"] == speaker_clean), None)
    speaker_name = sp_info["name"] if sp_info else speaker_clean.capitalize()

    # Formulate sample text
    if safe_lang.startswith("hi"):
        sample_text = f"नमस्ते! मैं सर्वम एआई का {speaker_name} स्वर हूँ। यह मेरी आवाज़ का नमूना है।"
    elif safe_lang.startswith("en"):
        sample_text = f"Hello! I am {speaker_name} from Sarvam AI. This is a sample of my voice."
    elif safe_lang.startswith("ta"):
        sample_text = f"வணக்கம்! இது சர்வம் ஏஐ {speaker_name} குரல் மாதிரி."
    elif safe_lang.startswith("te"):
        sample_text = f"నమస్కారం! ఇది సర్వం ఏఐ {speaker_name} వాయిస్ ప్రివ్యూ."
    elif safe_lang.startswith("bn"):
        sample_text = f"নমস্কার! এটি সর্বম এআই {speaker_name} ভয়েস প্রিভিউ।"
    else:
        sample_text = f"Hello, I am {speaker_name}. Welcome to Sarvam AI voice narrator."

    try:
        sarvam = SarvamClientWrapper()
        wav_bytes = sarvam.synthesize(
            chunk=sample_text,
            language_code=safe_lang,
            model=model,
            speaker=speaker_clean,
            pace=1.0,
        )
        preview_path.write_bytes(wav_bytes)
        return FileResponse(
            path=str(preview_path),
            media_type="audio/wav",
            filename=preview_filename,
        )
    except Exception as e:
        logger.warning(f"Voice preview failed for {speaker_clean}/{safe_lang}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate voice preview: {e}")


@app.get("/api/history")
def get_history(limit: int = Query(25, ge=1, le=100)):
    """
    Get server-stored listening history with progress percentage and bookmark count.
    Stored in database; does not rely on browser localStorage.
    """
    return get_listening_history(limit=limit)


@app.delete("/api/history/{job_id}")
def delete_history_item(job_id: str):
    """Delete a single narration from history on the server."""
    success = delete_history_job(job_id)
    if job_id in jobs:
        del jobs[job_id]
    return {"status": "ok", "deleted": success}


@app.delete("/api/history")
def clear_all_narrations_history():
    """Clear all listening history from the server."""
    clear_all_history()
    jobs.clear()
    return {"status": "ok", "cleared": True}


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

    has_text = bool(text and text.strip())
    has_file = bool(file_bytes and len(file_bytes) > 0)
    has_url = bool(url and url.strip())

    if not (has_text or has_file or has_url):
        raise HTTPException(
            status_code=400,
            detail="Please provide input via pasted text, a file upload (.txt, .md, .pdf), or a web article URL."
        )

    job_id = uuid.uuid4().hex[:10]
    initial_job = {
        "job_id": job_id,
        "status": "queued",
        "progress_done": 0,
        "progress_total": 1,
        "title": "Processing...",
        "audio_url": None,
        "duration": None,
        "final_text": None,
        "error": None,
        "last_position": 0.0,
        "sentences": [],
        "bookmarks": [],
    }
    jobs[job_id] = initial_job
    save_job(initial_job)

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
        return process_narration_job(job_id=job_id, **job_kwargs)

    background_tasks.add_task(process_narration_job, job_id=job_id, **job_kwargs)

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    """Get status and progress of an active or completed narration job."""
    # First check database for persistent record
    db_job = get_job(job_id)
    if db_job:
        # Merge in live progress if job is currently running in-memory
        if job_id in jobs and jobs[job_id]["status"] in ["queued", "extracting", "translating", "synthesizing", "concatenating"]:
            db_job["progress_done"] = jobs[job_id].get("progress_done", 0)
            db_job["progress_total"] = jobs[job_id].get("progress_total", 1)
            db_job["status"] = jobs[job_id]["status"]
        return db_job

    if job_id in jobs:
        return jobs[job_id]

    raise HTTPException(status_code=404, detail="Job not found.")


@app.post("/api/jobs/{job_id}/position")
def save_playback_position(job_id: str, payload: PositionUpdateRequest):
    """
    Save user playback position on server to enable resuming where they stopped.
    Stored on server; does not rely on browser localStorage.
    """
    success = update_job_position(job_id, payload.position)
    if job_id in jobs:
        jobs[job_id]["last_position"] = round(payload.position, 2)
    return {"status": "ok", "job_id": job_id, "position": payload.position, "saved": success}


@app.post("/api/jobs/{job_id}/bookmarks")
def create_bookmark(job_id: str, payload: BookmarkCreateRequest):
    """
    Create a timestamp bookmark on server for listening continuity.
    Stored on server; does not rely on browser localStorage.
    """
    db_job = get_job(job_id)
    if not db_job and job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    bookmark = add_bookmark(job_id=job_id, time_sec=payload.time, label=payload.label)
    return bookmark


@app.delete("/api/jobs/{job_id}/bookmarks/{bookmark_id}")
def remove_bookmark(job_id: str, bookmark_id: str):
    """Delete a bookmark from the server."""
    success = delete_bookmark(bookmark_id)
    return {"status": "ok", "deleted": success}


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
    api_key_var = None
    if os.getenv("SARVAM_API_NEW"):
        api_key_var = "SARVAM_API_NEW"
    elif os.getenv("SARVAM_API_KEY"):
        api_key_var = "SARVAM_API_KEY"
    return {
        "status": "ok",
        "serverless": IS_SERVERLESS,
        "blob_storage": bool(os.getenv("BLOB_READ_WRITE_TOKEN")),
        "api_key_var": api_key_var,
    }


# Static files for Single Page App
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

"""Database layer for Sarvam Narrator.

Stores jobs, playback positions, listening history, and bookmarks on the server
without relying on browser localStorage.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# In serverless environments like Vercel, /tmp is writable; otherwise write to app root.
if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    DB_PATH = Path("/tmp/narrator.db")
else:
    DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "narrator.db")))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                language TEXT,
                speaker TEXT,
                style TEXT,
                duration REAL,
                audio_url TEXT,
                final_text TEXT,
                sentences_json TEXT,
                status TEXT,
                error TEXT,
                last_position REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                time_sec REAL NOT NULL,
                label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs (updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_job ON bookmarks (job_id)")
        conn.commit()


def save_job(job_data: Dict[str, Any]) -> None:
    """Insert or update a job record."""
    job_id = job_data["job_id"]
    sentences_str = None
    if "sentences" in job_data and job_data["sentences"] is not None:
        sentences_str = json.dumps(job_data["sentences"], ensure_ascii=False)

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs (
                id, title, language, speaker, style, duration, audio_url,
                final_text, sentences_json, status, error, last_position, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                language=excluded.language,
                speaker=excluded.speaker,
                style=excluded.style,
                duration=excluded.duration,
                audio_url=excluded.audio_url,
                final_text=excluded.final_text,
                sentences_json=COALESCE(excluded.sentences_json, jobs.sentences_json),
                status=excluded.status,
                error=excluded.error,
                last_position=COALESCE(jobs.last_position, excluded.last_position),
                updated_at=excluded.updated_at
        """, (
            job_id,
            job_data.get("title"),
            job_data.get("language"),
            job_data.get("speaker"),
            job_data.get("style"),
            job_data.get("duration"),
            job_data.get("audio_url"),
            job_data.get("final_text"),
            sentences_str,
            job_data.get("status"),
            job_data.get("error"),
            job_data.get("last_position", 0.0),
            now,
        ))
        conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full job details including sentences and bookmarks."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None

        job = dict(row)
        # Parse sentences JSON
        sentences = []
        if job.get("sentences_json"):
            try:
                sentences = json.loads(job["sentences_json"])
            except Exception:
                sentences = []
        job["sentences"] = sentences

        # Fetch bookmarks
        bm_rows = conn.execute(
            "SELECT id, job_id, time_sec, label, created_at FROM bookmarks WHERE job_id = ? ORDER BY time_sec ASC",
            (job_id,)
        ).fetchall()
        job["bookmarks"] = [dict(b) for b in bm_rows]

        return job


def update_job_position(job_id: str, position: float) -> bool:
    """Save user playback position on server."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET last_position = ?, updated_at = ? WHERE id = ?",
            (round(position, 2), now, job_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_listening_history(limit: int = 25) -> List[Dict[str, Any]]:
    """Get recent jobs that completed or have saved progress."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT 
                j.id AS job_id,
                j.title,
                j.language,
                j.speaker,
                j.style,
                j.duration,
                j.audio_url,
                j.status,
                j.last_position,
                j.created_at,
                j.updated_at,
                (SELECT COUNT(*) FROM bookmarks b WHERE b.job_id = j.id) AS bookmark_count
            FROM jobs j
            WHERE j.status = 'completed'
            ORDER BY j.updated_at DESC, j.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def add_bookmark(job_id: str, time_sec: float, label: Optional[str] = None) -> Dict[str, Any]:
    """Add a timestamp bookmark on the server."""
    bm_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO bookmarks (id, job_id, time_sec, label, created_at) VALUES (?, ?, ?, ?, ?)",
            (bm_id, job_id, round(time_sec, 2), label or "Bookmark", now)
        )
        conn.commit()
    return {"id": bm_id, "job_id": job_id, "time_sec": round(time_sec, 2), "label": label, "created_at": now}


def delete_bookmark(bookmark_id: str) -> bool:
    """Delete a bookmark from the server."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        conn.commit()
        return cursor.rowcount > 0

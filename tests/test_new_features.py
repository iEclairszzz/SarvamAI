import pytest
from fastapi.testclient import TestClient
from app.main import app, compute_sentence_timestamps
from app.chunker import TextChunk
from app.audio import concatenate_wav_chunks
import io
import wave

client = TestClient(app)

def create_mock_wav(duration_sec: float = 1.0, framerate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = b"\x10\x00" * int(duration_sec * framerate)
        w.writeframes(frames)
    return buf.getvalue()

def test_compute_sentence_timestamps():
    chunk1 = TextChunk(text="नमस्ते सर्वम। यह पहला वाक्य है।", is_paragraph_end=True)
    wav1 = create_mock_wav(duration_sec=2.0)

    chunk2 = TextChunk(text="यह दूसरा पैराग्राफ है।", is_paragraph_end=False)
    wav2 = create_mock_wav(duration_sec=1.0)

    sentences = compute_sentence_timestamps(
        chunks=[chunk1, chunk2],
        audio_chunks=[(wav1, True), (wav2, False)],
    )

    assert len(sentences) >= 3
    assert sentences[0]["start"] == 0.0
    assert sentences[0]["end"] > 0.0
    # Between chunk 1 and chunk 2, 0.25s silence is added
    assert sentences[2]["start"] >= 2.25

def test_history_and_continuity_api():
    # Fetch history
    res = client.get("/api/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

def test_voice_preview_api_cached_or_generated(monkeypatch):
    # Mock synthesize to avoid consuming API credits during unit test
    def mock_synthesize(*args, **kwargs):
        return create_mock_wav(0.5)

    monkeypatch.setattr("app.sarvam_client.SarvamClientWrapper.synthesize", mock_synthesize)

    res = client.get("/api/voice-preview?speaker=shubh&language=hi-IN")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert len(res.content) > 1000

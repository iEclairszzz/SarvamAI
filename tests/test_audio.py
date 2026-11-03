import io
import wave
import pytest
from pathlib import Path
from app.audio import generate_silence_frames, concatenate_wav_chunks

def create_dummy_wav(duration_sec: float = 0.5, framerate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = b"\x10\x00" * int(duration_sec * framerate)
        w.writeframes(frames)
    return buf.getvalue()

def test_silence_generator():
    silence = generate_silence_frames(250, 22050, 1, 2)
    # 22050 * 0.250 = 5512.5 -> 5512 frames * 2 bytes = 11024 bytes
    assert len(silence) == 5512 * 2

def test_concatenate_wav_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.audio.OUTPUTS_DIR", tmp_path)
    wav1 = create_dummy_wav(0.5)
    wav2 = create_dummy_wav(0.5)

    chunks = [(wav1, True), (wav2, False)]
    out_file, duration = concatenate_wav_chunks(chunks, "test_out.wav", silence_ms=250)

    assert out_file.exists()
    assert duration > 1.2  # 0.5 + 0.25 + 0.5 = 1.25s

    with wave.open(str(out_file), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == 22050

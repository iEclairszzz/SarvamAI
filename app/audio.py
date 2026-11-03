import io
import os
import wave
from pathlib import Path
from typing import List, Tuple, Optional

BASE_DIR = Path(__file__).resolve().parent.parent


def _default_outputs_dir() -> Path:
    """Return a writable directory for generated audio.

    Serverless platforms (including Vercel) expose a read-only project
    filesystem; only ``/tmp`` is writable for the lifetime of an instance.
    """
    if os.getenv("OUTPUTS_DIR"):
        return Path(os.getenv("OUTPUTS_DIR"))
    if os.getenv("VERCEL"):
        return Path("/tmp/sarvam-narrator-outputs")
    return BASE_DIR / "outputs"


OUTPUTS_DIR = _default_outputs_dir()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

class AudioProcessingError(Exception):
    pass

def generate_silence_frames(duration_ms: int, framerate: int, nchannels: int, sampwidth: int) -> bytes:
    """Generate PCM silence bytes for specified duration in milliseconds."""
    num_frames = int(framerate * (duration_ms / 1000.0))
    bytes_per_frame = nchannels * sampwidth
    return b"\x00" * (num_frames * bytes_per_frame)

def concatenate_wav_chunks(
    chunks: List[Tuple[bytes, bool]],
    output_filename: str,
    silence_ms: int = 250,
) -> Tuple[Path, float]:
    """
    Concatenate list of (wav_bytes, is_paragraph_end) using stdlib wave module.
    Inserts `silence_ms` milliseconds of silence after paragraph ends.
    Returns (Path to generated file, total duration in seconds).
    """
    if not chunks:
        raise AudioProcessingError("No audio chunks to concatenate.")

    out_path = OUTPUTS_DIR / output_filename
    base_params = None
    all_frames = bytearray()

    for i, (wav_bytes, is_paragraph_end) in enumerate(chunks):
        if not wav_bytes:
            continue

        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
                nchannels = reader.getnchannels()
                sampwidth = reader.getsampwidth()
                framerate = reader.getframerate()
                nframes = reader.getnframes()
                frames = reader.readframes(nframes)

                if base_params is None:
                    base_params = (nchannels, sampwidth, framerate)
                elif base_params != (nchannels, sampwidth, framerate):
                    # In case of mismatched params (unlikely from same TTS model)
                    pass

                all_frames.extend(frames)

                # Insert silence between paragraphs (not after the very last chunk)
                if is_paragraph_end and i < len(chunks) - 1 and silence_ms > 0:
                    silence = generate_silence_frames(silence_ms, framerate, nchannels, sampwidth)
                    all_frames.extend(silence)

        except Exception as e:
            raise AudioProcessingError(f"Failed to process WAV chunk {i + 1}: {e}")

    if base_params is None or len(all_frames) == 0:
        raise AudioProcessingError("Could not extract audio frames from chunks.")

    nchannels, sampwidth, framerate = base_params
    total_frames = len(all_frames) // (nchannels * sampwidth)
    total_duration = total_frames / float(framerate)

    with wave.open(str(out_path), "wb") as writer:
        writer.setnchannels(nchannels)
        writer.setsampwidth(sampwidth)
        writer.setframerate(framerate)
        writer.writeframes(bytes(all_frames))

    return out_path, total_duration

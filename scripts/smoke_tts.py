import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

def smoke_test():
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError("SARVAM_API_KEY environment variable is not set")

    client = SarvamAI(api_subscription_key=api_key.strip())
    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Synthesizing Hindi sentence...")
    hi_text = "सर्वम एआई में आपका स्वागत है।"
    hi_resp = client.text_to_speech.convert(
        text=hi_text,
        language_code="hi-IN",
        model="bulbul:v3",
        speaker="shubh",
        pace=1.0,
        output_audio_codec="wav",
    )
    hi_audio_b64 = hi_resp.audios[0]
    hi_wav = base64.b64decode(hi_audio_b64)
    hi_path = out_dir / "smoke_hi.wav"
    hi_path.write_bytes(hi_wav)
    print(f"Saved Hindi audio ({len(hi_wav)} bytes) to {hi_path}")

    print("Synthesizing English sentence...")
    en_text = "Welcome to Sarvam AI multilingual narrator."
    en_resp = client.text_to_speech.convert(
        text=en_text,
        language_code="en-IN",
        model="bulbul:v3",
        speaker="priya",
        pace=1.0,
        output_audio_codec="wav",
    )
    en_audio_b64 = en_resp.audios[0]
    en_wav = base64.b64decode(en_audio_b64)
    en_path = out_dir / "smoke_en.wav"
    en_path.write_bytes(en_wav)
    print(f"Saved English audio ({len(en_wav)} bytes) to {en_path}")

    print("Smoke test completed successfully!")

if __name__ == "__main__":
    smoke_test()

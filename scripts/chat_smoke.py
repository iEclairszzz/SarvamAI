import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sarvamai import SarvamAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

client = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))

response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[
        {"role": "user", "content": "Hello! Please introduce yourself briefly in one sentence."}
    ],
)

print(response.choices[0].message.content)

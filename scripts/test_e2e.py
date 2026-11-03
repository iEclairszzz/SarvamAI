import time
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from app.main import jobs, process_narration_job

load_dotenv()

def run_job_sync(job_id: str, **kwargs):
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
    process_narration_job(job_id=job_id, **kwargs)
    job = jobs[job_id]
    if job["status"] != "completed":
        raise RuntimeError(f"Job {job_id} failed: {job.get('error')}")
    return job

def main():
    print("=== Step 10: Running End-to-End Tests ===")

    # Test 1: Hindi paste -> Hindi audio
    print("\n--- Test 1: Hindi paste -> Hindi audio ---")
    hi_text = "सर्वम एआई भारत के लिए स्वदेशी भाषा मॉडल विकसित कर रहा है। यह बुलबुल मॉडल का उपयोग करता है।"
    job1 = run_job_sync(
        job_id="e2e_hindi",
        raw_text=hi_text,
        file_bytes=None,
        filename=None,
        url=None,
        language="hi-IN",
        translate_to=None,
        translate_mode="formal",
        style="news",
        speaker="shubh",
        pace=1.0,
        model="bulbul:v3",
    )
    print(f"Test 1 PASSED: Title='{job1['title']}', Duration={job1['duration']}s, Audio={job1['audio_url']}")
    assert Path(f"outputs/{job1['job_id']}.wav").exists()

    # Test 2: Tamil paste -> Tamil audio
    print("\n--- Test 2: Tamil paste -> Tamil audio ---")
    ta_text = "வணக்கம்! சர்வமை நேரேட்டர் உங்களை அன்புடன் வரவேற்கிறது. இது கதை வாசிப்புக்கான குரல்."
    job2 = run_job_sync(
        job_id="e2e_tamil",
        raw_text=ta_text,
        file_bytes=None,
        filename=None,
        url=None,
        language="ta-IN",
        translate_to=None,
        translate_mode="formal",
        style="story",
        speaker="priya",
        pace=0.9,
        model="bulbul:v3",
    )
    print(f"Test 2 PASSED: Title='{job2['title']}', Duration={job2['duration']}s, Audio={job2['audio_url']}")
    assert Path(f"outputs/{job2['job_id']}.wav").exists()

    # Test 3: English article URL -> Hindi translation -> Hindi narration
    print("\n--- Test 3: English URL -> Translate to Hindi -> Hindi audio ---")
    test_url = "https://en.wikipedia.org/wiki/National_emblem_of_India"
    job3 = run_job_sync(
        job_id="e2e_url_translate",
        raw_text=None,
        file_bytes=None,
        filename=None,
        url=test_url,
        language="en-IN",
        translate_to="hi-IN",
        translate_mode="formal",
        style="education",
        speaker="ritu",
        pace=0.85,
        model="bulbul:v3",
    )
    print(f"Test 3 PASSED: Title='{job3['title']}', Duration={job3['duration']}s, Audio={job3['audio_url']}")
    print(f"Translated preview: {job3['final_text'][:120]}...")
    assert Path(f"outputs/{job3['job_id']}.wav").exists()

    print("\nAll 3 End-to-End Tests Completed Successfully!")

if __name__ == "__main__":
    main()

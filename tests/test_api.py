import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_voices():
    response = client.get("/api/voices")
    assert response.status_code == 200
    data = response.json()
    assert "languages" in data
    assert "speakers" in data
    assert "styles" in data
    assert any(l["code"] == "hi-IN" for l in data["languages"])
    assert any(s["id"] == "shubh" for s in data["speakers"])

def test_narrate_empty_input_rejected():
    response = client.post("/api/narrate", data={"language": "hi-IN"})
    assert response.status_code == 400
    assert "provide input" in response.json()["detail"].lower()

def test_narrate_creates_job():
    response = client.post(
        "/api/narrate",
        data={
            "text": "नमस्ते, यह एक परीक्षण है।",
            "language": "hi-IN",
            "style": "news",
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    job_id = data["job_id"]

    # Check job status endpoint
    job_resp = client.get(f"/api/jobs/{job_id}")
    assert job_resp.status_code == 200


def test_playback_position_and_bookmarks():
    # Create test job in db
    from app.db import save_job
    test_id = "test_continuity_job"
    save_job({
        "job_id": test_id,
        "title": "Continuity Test",
        "language": "hi-IN",
        "speaker": "shubh",
        "duration": 50.0,
        "status": "completed",
    })

    # Save position on server
    pos_res = client.post(f"/api/jobs/{test_id}/position", json={"position": 25.5})
    assert pos_res.status_code == 200

    # Add bookmark on server
    bm_res = client.post(f"/api/jobs/{test_id}/bookmarks", json={"time": 12.0, "label": "Key Insight"})
    assert bm_res.status_code == 200
    bm_data = bm_res.json()
    assert bm_data["time_sec"] == 12.0
    bm_id = bm_data["id"]

    # Verify job contains updated position and bookmark
    job_res = client.get(f"/api/jobs/{test_id}")
    assert job_res.status_code == 200
    job_data = job_res.json()
    assert job_data["last_position"] == 25.5
    assert len(job_data["bookmarks"]) == 1
    assert job_data["bookmarks"][0]["id"] == bm_id

    # Verify history endpoint returns the job
    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert any(h["job_id"] == test_id for h in hist_data)

    # Delete bookmark
    del_res = client.delete(f"/api/jobs/{test_id}/bookmarks/{bm_id}")
    assert del_res.status_code == 200

    # Verify bookmark deleted
    job_res2 = client.get(f"/api/jobs/{test_id}")
    assert len(job_res2.json()["bookmarks"]) == 0

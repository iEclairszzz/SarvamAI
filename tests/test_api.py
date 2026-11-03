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

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_and_ready():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"

def test_requires_idempotency_key():
    response = client.post("/api/v1/music/jobs", json={"prompt":"calm piano", "duration_s":5})
    assert response.status_code == 422

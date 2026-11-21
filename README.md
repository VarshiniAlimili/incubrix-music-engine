# IncuBrix AI Background Music Engine

A CPU-compatible FastAPI prototype for generating original instrumental background music with independently rendered instrument stems.

## Current implementation status

This repository is the first engineering milestone, not a claim that every assessment requirement is complete.

Implemented:
- FastAPI job API (`POST /api/v1/music/jobs`, `GET /api/v1/jobs/{job_id}`)
- In-memory background job queue and idempotency keys (single-process prototype)
- Deterministic procedural composition using a shared tempo/key grid
- Four independently synthesized stems: drums, bass, harmony and melody
- Mix generated as the sum of stems
- 48 kHz WAV output, exact sample count, fade ending and loudness/peak gain staging
- JSON manifest and health/readiness endpoints

Not yet implemented:
- Durable queue/database, MinIO/S3, callback signing, narration URL ingestion/ducking, MP3 export
- Production-grade true-peak metering and independent listening/quality evaluation
- Neural text-to-music model; the current engine is procedural/algorithmic
- Commercial licensing review for any future external model/provider

## Requirements

- Python 3.11 recommended
- Windows 10/11
- Docker Desktop optional (for container run)

## Local setup (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open:
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- Readiness: http://127.0.0.1:8000/ready

## Create a job

```powershell
$body = @{
  prompt = "warm optimistic acoustic pop for a product launch"
  duration_s = 30
  sections = @(
    @{ start_s = 0; mood = "calm intro" },
    @{ start_s = 10; mood = "build-up" },
    @{ start_s = 22; mood = "uplifting peak" }
  )
  tempo_bpm = 100
  seed = 42
  output = @{ sample_rate = 48000; target_lufs = -16; formats = @("wav") }
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/music/jobs" `
  -Headers @{"Idempotency-Key"="demo-001"} `
  -ContentType "application/json" -Body $body

$response
```

Poll the returned `job_id`:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/jobs/$($response.job_id)"
```

When succeeded, the response contains local download URLs under `result`.

## Tests

```powershell
pytest -q
```

## Project layout

```text
app/
  main.py                 FastAPI routes and job orchestration
  models.py               Request/response schemas
  engine/
    composer.py           Deterministic arrangement and stem synthesis
    audio.py              Audio export, gain staging and measurements
tests/
  test_engine.py
  test_api.py
```

## Important engineering notes

- The stems are synthesized as independent musical parts, not frequency bands.
- The mix is constructed by summing the exported stem arrays after shared gain staging.
- Current jobs and idempotency records are held in process memory. Restarting the server loses them; this must be replaced before production.
- Narration URLs are accepted in the request schema but ducking is not yet implemented. The API currently reports this limitation as a warning in the manifest.
- Do not report a requirement as passed until it has been measured and evidenced.

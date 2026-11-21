import os, json, uuid, time, logging, hashlib
from pathlib import Path
from datetime import datetime, timezone
from threading import Lock
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from app.models import MusicJobRequest
from app.engine.composer import generate_stems
from app.engine.audio import write_wav, apply_shared_gain, audio_metrics

load_dotenv()
APP_NAME = os.getenv("APP_NAME", "IncuBrix Background Music Engine")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./outputs")).resolve()
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "48000"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version="0.1.0")
jobs = {}
idempotency = {}
lock = Lock()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("incubrix")

def log_event(level, event, **fields):
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level,
              "event": event, **fields}
    logger.log(logging.INFO if level == "INFO" else logging.ERROR, json.dumps(record))

def run_job(job_id: str, payload: dict):
    started = time.perf_counter()
    with lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 5
    try:
        sections = payload.get("sections") or []
        warnings = []
        valid_sections = []
        for s in sections:
            if s["start_s"] >= payload["duration_s"]:
                warnings.append(f"Section at {s['start_s']}s is outside the track and was ignored.")
            else:
                valid_sections.append(s)
        # Closely spaced sections are retained; the renderer changes the active mood at the next beat.
        if payload.get("narration_url"):
            warnings.append("Narration URL received, but voiceover download and ducking are not implemented yet.")
        if payload.get("loopable"):
            warnings.append("Loopable flag received; seamless loop-point validation is not implemented yet.")

        stems, bpm, detected_key = generate_stems(
            payload["prompt"], payload["duration_s"], payload.get("tempo_bpm"),
            payload.get("key"), valid_sections, payload.get("seed") or 42, SAMPLE_RATE
        )
        with lock: jobs[job_id]["progress"] = 65
        stems, mix, gain_db = apply_shared_gain(stems, payload["output"]["target_lufs"])
        job_dir = OUTPUT_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        stem_paths = {}
        for name, audio in stems.items():
            p = job_dir / "stems" / f"{name}.wav"
            write_wav(p, audio, SAMPLE_RATE)
            stem_paths[name] = str(p)
        mix_path = job_dir / "mix.wav"
        write_wav(mix_path, mix, SAMPLE_RATE)
        metrics = audio_metrics(mix, SAMPLE_RATE)
        elapsed = time.perf_counter() - started
        manifest = {
            "job_id": job_id, "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt": payload["prompt"], "duration_requested_s": payload["duration_s"],
            "duration_delivered_s": len(mix)/SAMPLE_RATE,
            "sample_rate": SAMPLE_RATE, "tempo_bpm": bpm, "key": detected_key,
            "sections": valid_sections, "seed": payload.get("seed"),
            "stems": {name: {"file": f"stems/{name}.wav", "gain_applied_db": gain_db} for name in stems},
            "mix": {"file": "mix.wav", **metrics},
            "generation_time_s": elapsed,
            "provider": "local_procedural_synthesizer", "model_version": "0.1.0",
            "ai_generated": True, "warnings": warnings,
            "licence_rights": {"source_audio": "No external samples or recordings used; synthesized procedurally.",
                               "third_party_model": None},
            "limitations": ["Procedural engine; not a pretrained neural text-to-music model.",
                            "True-peak compliance has not yet been independently verified.",
                            "Narration ducking and seamless looping are not implemented."]
        }
        manifest_path = job_dir / "music_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with lock:
            jobs[job_id].update(status="succeeded", progress=100, result={
                "mix": f"/api/v1/files/{job_id}/mix.wav",
                "stems": {n: f"/api/v1/files/{job_id}/stems/{n}.wav" for n in stems},
                "manifest": f"/api/v1/files/{job_id}/music_manifest.json"
            }, warnings=warnings)
        log_event("INFO", "job_succeeded", job_id=job_id, elapsed_s=round(elapsed,3))
    except Exception as exc:
        with lock:
            jobs[job_id].update(status="failed", progress=100,
                                error={"code":"GENERATION_FAILED","message":str(exc),
                                       "retryable":True,"details":{}})
        log_event("ERROR", "job_failed", job_id=job_id, error=str(exc))

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    return response

@app.post("/api/v1/music/jobs", status_code=202)
def create_music_job(body: MusicJobRequest, background_tasks: BackgroundTasks,
                     idempotency_key: str = Header(..., alias="Idempotency-Key")):
    if not idempotency_key.strip():
        raise HTTPException(400, detail={"error":{"code":"INVALID_IDEMPOTENCY_KEY","message":"Idempotency-Key cannot be empty","retryable":False,"details":{}}})
    payload = body.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with lock:
        if idempotency_key in idempotency:
            old_hash, old_job = idempotency[idempotency_key]
            if old_hash != fingerprint:
                raise HTTPException(409, detail={"error":{"code":"IDEMPOTENCY_CONFLICT","message":"This key was already used with a different request","retryable":False,"details":{}}})
            return {"job_id":old_job, "status_url":f"/api/v1/jobs/{old_job}", "idempotent_replay":True}
        job_id = str(uuid.uuid4())
        jobs[job_id] = {"job_id":job_id,"status":"queued","progress":0,"created_at":datetime.now(timezone.utc).isoformat()}
        idempotency[idempotency_key] = (fingerprint, job_id)
    background_tasks.add_task(run_job, job_id, payload)
    return {"job_id":job_id, "status_url":f"/api/v1/jobs/{job_id}", "idempotent_replay":False}

@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job: raise HTTPException(404, detail={"error":{"code":"JOB_NOT_FOUND","message":"Job not found","retryable":False,"details":{}}})
        return job

@app.get("/api/v1/files/{job_id}/{filename:path}")
def get_file(job_id: str, filename: str):
    base = (OUTPUT_DIR / job_id).resolve()
    path = (base / filename).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, detail={"error":{"code":"FILE_NOT_FOUND","message":"File not found","retryable":False,"details":{}}})
    return FileResponse(path)

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/ready")
def ready():
    return {"status":"ready","output_dir_writable":os.access(OUTPUT_DIR, os.W_OK)}

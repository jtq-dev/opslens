from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

from .db import connect, init_db
from .parser import parse_run
from .analytics import rolling_metric, compare_runs
from .settings import settings

app = FastAPI(title="OpsLens", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
STATIC_DIR = os.path.abspath(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/health")
def health():
    return {"ok": True}

class RunOut(BaseModel):
    id: str
    created_at: str
    host: str
    archive_name: str
    uname: str | None = None
    os_release: str | None = None

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Upload must be a .tar.gz produced by cluster_diag.sh")

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large. Max {settings.max_upload_mb}MB")

    run_info, metrics, artifacts = parse_run(data, file.filename)

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO runs(id, created_at, host, archive_name, uname, os_release) VALUES(?,?,?,?,?,?)",
        (run_info["id"], run_info["created_at"], run_info["host"], run_info["archive_name"], run_info["uname"], run_info["os_release"]),
    )

    for k, v in metrics.items():
        unit = "pct" if k.endswith("_pct") else None
        cur.execute(
            "INSERT OR REPLACE INTO metrics(run_id, key, value, unit) VALUES(?,?,?,?)",
            (run_info["id"], k, float(v), unit),
        )

    for name, content in artifacts.items():
        # store only the last N chars to avoid huge DB
        content2 = content[-20000:] if content else ""
        cur.execute(
            "INSERT OR REPLACE INTO artifacts(run_id, name, content) VALUES(?,?,?)",
            (run_info["id"], name, content2),
        )

    conn.commit()
    conn.close()

    return {"run_id": run_info["id"], "host": run_info["host"], "health_score": metrics.get("health_score", None)}

@app.get("/api/runs")
def list_runs(limit: int = Query(50, ge=1, le=200)):
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at, host, archive_name, uname, os_release
        FROM runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise HTTPException(status_code=404, detail="Run not found")

    cur.execute("SELECT key, value, unit FROM metrics WHERE run_id = ? ORDER BY key", (run_id,))
    metrics = [dict(m) for m in cur.fetchall()]
    conn.close()
    return {"run": dict(r), "metrics": metrics}

@app.get("/api/runs/{run_id}/artifact")
def run_artifact(run_id: str, name: str):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT content FROM artifacts WHERE run_id = ? AND name = ?", (run_id, name))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"name": name, "content": row["content"]}

@app.get("/api/analytics/rolling")
def analytics_rolling(host: str, key: str, days: int = Query(30, ge=1, le=365)):
    conn = connect()
    out = rolling_metric(conn, host=host, key=key, days=days)
    conn.close()
    return out

@app.get("/api/compare")
def compare(run_a: str, run_b: str):
    conn = connect()
    out = compare_runs(conn, run_a=run_a, run_b=run_b)
    conn.close()
    return out

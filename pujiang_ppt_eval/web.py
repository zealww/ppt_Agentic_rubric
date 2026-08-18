from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
RUNTIME_ROOT = PROJECT_ROOT / ".web_runtime"
RUNTIME_ROOT.mkdir(exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Job:
    id: str
    status: Literal["queued", "running", "succeeded", "partial", "failed", "cancelled"] = "queued"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    command: list[str] = field(default_factory=list)
    source: str = ""
    output: str = ""
    result_file: str = "results.json"
    logs: list[str] = field(default_factory=list)
    return_code: int | None = None
    process: subprocess.Popen | None = field(default=None, repr=False)

    def public(self, include_logs: bool = True) -> dict:
        result_path = Path(self.output) / self.result_file
        data = {
            "id": self.id, "status": self.status, "created_at": self.created_at,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "source": self.source, "output": self.output, "result_file": self.result_file,
            "return_code": self.return_code, "has_result": result_path.is_file(),
        }
        if include_logs:
            data["logs"] = self.logs[-2000:]
        return data


JOBS: dict[str, Job] = {}
LOCK = threading.RLock()
app = FastAPI(title="PPT Eval 1", version="0.2.0")


def _append_log(job: Job, line: str) -> None:
    with LOCK:
        job.logs.append(line.rstrip("\n"))


def _run_job(job: Job, environment: dict[str, str]) -> None:
    with LOCK:
        job.status = "running"
        job.started_at = datetime.now().isoformat()
    try:
        process = subprocess.Popen(
            job.command, cwd=PROJECT_ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        with LOCK:
            job.process = process
        assert process.stdout is not None
        for line in process.stdout:
            _append_log(job, line)
        return_code = process.wait()
        with LOCK:
            job.return_code = return_code
            if job.status != "cancelled":
                job.status = "succeeded" if return_code == 0 else "failed"
                result_path = Path(job.output) / job.result_file
                if return_code == 0 and result_path.is_file():
                    try:
                        payload = json.loads(result_path.read_text(encoding="utf-8"))
                        if payload.get("summary", {}).get("failed", 0):
                            job.status = "partial"
                    except (OSError, json.JSONDecodeError):
                        pass
    except Exception as exc:
        _append_log(job, f"Web runner error: {exc}")
        with LOCK:
            job.status = "failed"
            job.return_code = -1
    finally:
        with LOCK:
            job.process = None
            job.completed_at = datetime.now().isoformat()


def _bool(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _validated_source(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(400, f"PPT directory does not exist: {path}")
    if not any(p.is_file() and p.suffix.lower() in {".ppt", ".pptx"} for p in path.iterdir()):
        raise HTTPException(400, f"No .ppt/.pptx files directly under: {path}")
    return path


def _build_command(*, source: Path, output: Path, model: str, rubric: Path,
                   result_file: str, topic_map: str, workers: int, dpi: int,
                   max_grids: int, max_tokens: int, api_retries: int,
                   format_retries: int, resume: bool, force_render: bool,
                   force_extract: bool, base_url: str) -> list[str]:
    command = [
        sys.executable, "-u", "-m", "pujiang_ppt_eval",
        "--source", str(source), "--output", str(output), "--model", model,
        "--rubric", str(rubric), "--result-file", result_file,
        "--workers", str(workers), "--dpi", str(dpi), "--max-grids", str(max_grids),
        "--max-tokens", str(max_tokens), "--api-retries", str(api_retries),
        "--format-retries", str(format_retries),
    ]
    if topic_map.strip():
        topic_path = Path(topic_map).expanduser().resolve()
        if not topic_path.is_file():
            raise HTTPException(400, f"Topic map does not exist: {topic_path}")
        command.extend(["--topic-map", str(topic_path)])
    if base_url.strip():
        command.extend(["--base-url", base_url.strip()])
    if resume:
        command.append("--resume")
    if force_render:
        command.append("--force-render")
    if force_extract:
        command.append("--force-extract")
    return command


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((WEB_ROOT / "index.html").read_text(encoding="utf-8"))


@app.get("/api/config")
def config() -> dict:
    rubrics = [{"name": p.stem, "path": str(p.resolve())}
               for p in sorted((Path(__file__).resolve().parent / "rubrics").glob("*.json"))]
    return {"rubrics": rubrics, "default_output_root": str((PROJECT_ROOT / "output").resolve()),
            "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
            "base_url": os.getenv("OPENAI_BASE_URL", "")}


@app.post("/api/jobs")
async def create_job(
    files: list[UploadFile] = File(default=[]), source_path: str = Form(default=""),
    output_path: str = Form(default=""), model: str = Form(...), rubric: str = Form(...),
    result_file: str = Form(default="results.json"), topic_map: str = Form(default=""),
    api_key: str = Form(default=""), base_url: str = Form(default=""),
    workers: int = Form(default=2), dpi: int = Form(default=150),
    max_grids: int = Form(default=8), max_tokens: int = Form(default=4096),
    api_retries: int = Form(default=3), format_retries: int = Form(default=2),
    resume: str = Form(default="false"), force_render: str = Form(default="false"),
    force_extract: str = Form(default="false"),
) -> JSONResponse:
    if not model.strip():
        raise HTTPException(400, "Model is required")
    rubric_path = Path(rubric).expanduser().resolve()
    if not rubric_path.is_file():
        raise HTTPException(400, f"Rubric does not exist: {rubric_path}")
    if not result_file.endswith(".json") or Path(result_file).name != result_file:
        raise HTTPException(400, "Result filename must be a simple .json filename")
    if workers < 1 or dpi < 72 or max_grids < 1 or max_tokens < 1:
        raise HTTPException(400, "Invalid numeric settings")

    job_id = uuid.uuid4().hex[:12]
    valid_uploads = [item for item in files if item.filename]
    if valid_uploads:
        upload_dir = RUNTIME_ROOT / "uploads" / job_id
        upload_dir.mkdir(parents=True, exist_ok=False)
        for upload in valid_uploads:
            safe_name = Path(upload.filename or "").name
            if Path(safe_name).suffix.lower() not in {".ppt", ".pptx"}:
                raise HTTPException(400, f"Unsupported upload: {safe_name}")
            with (upload_dir / safe_name).open("wb") as target:
                shutil.copyfileobj(upload.file, target)
        source = upload_dir
    elif source_path.strip():
        source = _validated_source(source_path)
    else:
        raise HTTPException(400, "Upload PPT files or provide a PPT directory path")

    output = (Path(output_path).expanduser().resolve() if output_path.strip()
              else (PROJECT_ROOT / "output" / f"web_{job_id}").resolve())
    output.mkdir(parents=True, exist_ok=True)
    command = _build_command(
        source=source, output=output, model=model.strip(), rubric=rubric_path,
        result_file=result_file, topic_map=topic_map, workers=workers, dpi=dpi,
        max_grids=max_grids, max_tokens=max_tokens, api_retries=api_retries,
        format_retries=format_retries, resume=_bool(resume),
        force_render=_bool(force_render), force_extract=_bool(force_extract),
        base_url=base_url)
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    if api_key.strip():
        environment["OPENAI_API_KEY"] = api_key.strip()
    job = Job(job_id, command=command, source=str(source), output=str(output), result_file=result_file)
    with LOCK:
        JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job, environment), daemon=True).start()
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    with LOCK:
        return [job.public(include_logs=False) for job in reversed(list(JOBS.values()))]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.process and job.status == "running":
            job.status = "cancelled"
            job.process.terminate()
        return job.public()


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        path = Path(job.output) / job.result_file
    if not path.is_file():
        raise HTTPException(404, "Result is not available yet")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/download")
def download_result(job_id: str) -> FileResponse:
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        path = Path(job.output) / job.result_file
    if not path.is_file():
        raise HTTPException(404, "Result is not available yet")
    return FileResponse(path, filename=job.result_file, media_type="application/json")


def main() -> None:
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="PPT Eval 1 web interface")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    uvicorn.run("pujiang_ppt_eval.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LUMINORBIT v25 — PRODUCTION BACKEND (Railway)                             ║
║  luminorbit_backend.py                                                     ║
║                                                                            ║
║  Deploy alongside luminorbit_pipelines.py on Railway.                     ║
║  Requires env vars defined in §0.                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════════════════════
# §0  SETTINGS  (all from env; safe defaults for dev)
# ══════════════════════════════════════════════════════════════════════════════

class Settings:
    # ── Auth ───────────────────────────────────────────────────────────────────
    API_KEY: str                     = os.getenv("LUMINORBIT_API_KEY",       "luminorbit_secure_123")

    # ── Provider keys ──────────────────────────────────────────────────────────
    POLLINATIONS_API_KEY: str        = os.getenv("POLLINATIONS_API_KEY",     "")
    TOGETHER_API_KEY: str            = os.getenv("TOGETHER_API_KEY",         "")
    HF_API_KEY: str                  = os.getenv("HF_API_KEY",               "")
    GEMINI_API_KEY: str              = os.getenv("GEMINI_API_KEY",           "")
    GROQ_API_KEY: str                = os.getenv("GROQ_API_KEY",             "")
    SEGMIND_API_KEY: str             = os.getenv("SEGMIND_API_KEY",          "")
    OPENROUTER_API_KEY: str          = os.getenv("OPENROUTER_API_KEY",       "")
    CLOUDFLARE_ACCOUNT_ID: str       = os.getenv("CF_ACCOUNT_ID",            "")
    CLOUDFLARE_API_TOKEN: str        = os.getenv("CF_API_TOKEN",             "")
    MISTRAL_API_KEY: str             = os.getenv("MISTRAL_API_KEY",          "")
    DEEPAI_API_KEY: str              = os.getenv("DEEPAI_API_KEY",           "")
    KREA_API_KEY: str                = os.getenv("KREA_API_KEY",             "")
    PEXELS_API_KEY: str              = os.getenv("PEXELS_API_KEY",           "")
    UNSPLASH_ACCESS_KEY: str         = os.getenv("UNSPLASH_ACCESS_KEY",      "")
    CLOUDINARY_CLOUD_NAME: str       = os.getenv("CLOUDINARY_CLOUD_NAME",    "")
    CLOUDINARY_API_KEY: str          = os.getenv("CLOUDINARY_API_KEY",       "")
    CLOUDINARY_API_SECRET: str       = os.getenv("CLOUDINARY_API_SECRET",    "")

    # ── Server ─────────────────────────────────────────────────────────────────
    PORT: int                        = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str                   = os.getenv("LOG_LEVEL", "INFO")

_settings = Settings()


# ══════════════════════════════════════════════════════════════════════════════
# §1  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=getattr(logging, _settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("luminorbit")


# ══════════════════════════════════════════════════════════════════════════════
# §2  PIPELINE ENGINE (from luminorbit_pipelines.py)
# ══════════════════════════════════════════════════════════════════════════════

try:
    from luminorbit_pipelines import (
        CORS_ALLOWED_ORIGINS,
        build_pipeline_engine,
    )
    _pipeline, _router = build_pipeline_engine(_settings, logger)
    logger.info("[backend] Pipeline engine loaded from luminorbit_pipelines")
except ImportError:
    logger.warning("[backend] luminorbit_pipelines not found — running in stub mode")
    CORS_ALLOWED_ORIGINS = [
        "https://luminorbit1.dpdns.org",
        "https://luminorbit-1.pages.dev",
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    _pipeline = None
    _router   = None


# ══════════════════════════════════════════════════════════════════════════════
# §3  FASTAPI APP + CORS
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Luminorbit Backend",
    version="25.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# ── CORS — ACTIVELY REGISTERED ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,          # no cookies; bearer-token auth only
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Pipeline",
        "X-Request-Id",
        "Accept",
        "Origin",
    ],
    expose_headers=["X-Request-Id", "X-Execution-Ms"],
    max_age=86400,
)


# ══════════════════════════════════════════════════════════════════════════════
# §4  IN-MEMORY JOB STORE
# ══════════════════════════════════════════════════════════════════════════════

_JOB_TTL_S  = 3600   # jobs expire after 1 h
_jobs: Dict[str, Dict] = {}

def _job_create(tool: str, request_id: str) -> str:
    job_id = f"job_{request_id}"
    _jobs[job_id] = {
        "id":         job_id,
        "tool":       tool,
        "status":     "queued",
        "progress":   0,
        "output_url": None,
        "error":      None,
        "created_at": time.time(),
    }
    return job_id

def _job_update(job_id: str, **kwargs):
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)

def _job_get(job_id: str) -> Optional[Dict]:
    job = _jobs.get(job_id)
    if job and time.time() - job["created_at"] > _JOB_TTL_S:
        del _jobs[job_id]
        return None
    return job

async def _job_cleanup_loop():
    """Prune expired jobs every 10 minutes."""
    while True:
        await asyncio.sleep(600)
        now = time.time()
        expired = [jid for jid, j in list(_jobs.items()) if now - j["created_at"] > _JOB_TTL_S]
        for jid in expired:
            _jobs.pop(jid, None)
        if expired:
            logger.info("[jobs] Pruned %d expired jobs", len(expired))


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_job_cleanup_loop())
    logger.info("[backend] Luminorbit v25 started | port=%s", _settings.PORT)


# ══════════════════════════════════════════════════════════════════════════════
# §5  AUTH HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _check_auth(authorization: Optional[str]) -> bool:
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return parts[1] == _settings.API_KEY


# ══════════════════════════════════════════════════════════════════════════════
# §6  RESPONSE HELPERS — ONE STANDARDIZED FORMAT
# ══════════════════════════════════════════════════════════════════════════════

def _ok(tool: str = "", pipeline: str = "", provider: str = "",
        output_url: str = "", preview_url: str = "",
        execution_ms: int = 0, metadata: dict = None,
        warnings: list = None, fallback_used: bool = False,
        job_id: str = "", extra: dict = None) -> dict:
    resp = {
        "success":      True,
        "tool":         tool,
        "pipeline":     pipeline,
        "provider":     provider,
        "execution_ms": execution_ms,
        "output":       output_url,
        "output_url":   output_url,
        "preview_url":  preview_url or output_url,
        "metadata":     metadata or {},
        "warnings":     warnings or [],
        "fallback_used": fallback_used,
    }
    if job_id:
        resp["job_id"] = job_id
    if extra:
        resp.update(extra)
    return resp


def _err(error_code: str, message: str, provider: str = "",
         fallback_attempted: bool = False, status: int = 200) -> JSONResponse:
    body = {
        "success":            False,
        "error_code":         error_code,
        "message":            message,
        "provider":           provider,
        "fallback_attempted": fallback_attempted,
    }
    return JSONResponse(content=body, status_code=status)


# ══════════════════════════════════════════════════════════════════════════════
# §7  MIME VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

_ALLOWED_IMAGE_MIME = {"image/jpeg","image/png","image/webp","image/gif","image/bmp","image/tiff"}
_ALLOWED_VIDEO_MIME = {"video/mp4","video/webm","video/quicktime","video/x-msvideo","video/mpeg"}
_ALLOWED_AUDIO_MIME = {"audio/mpeg","audio/wav","audio/ogg","audio/aac","audio/flac","audio/mp4"}
_ALLOWED_DOC_MIME   = {"application/pdf","text/plain","text/csv"}
_ALL_ALLOWED_MIME   = _ALLOWED_IMAGE_MIME | _ALLOWED_VIDEO_MIME | _ALLOWED_AUDIO_MIME | _ALLOWED_DOC_MIME

MAX_UPLOAD_BYTES   = 50 * 1024 * 1024   # 50 MB

def _validate_mime(mime: str, content_length: int = 0) -> Optional[str]:
    if mime and mime not in _ALL_ALLOWED_MIME:
        return f"Unsupported file type: {mime}"
    if content_length > MAX_UPLOAD_BYTES:
        return f"File too large: {content_length} bytes (max {MAX_UPLOAD_BYTES})"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# §8  REQUEST SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ProcessRequest(BaseModel):
    tool:                str
    pipeline:            str                   = "basic"
    preset:              str                   = ""
    capability:          str                   = "basic-processing"
    params:              Dict[str, Any]         = Field(default_factory=dict)
    file_data:           Optional[str]          = None   # base64
    file_mime:           Optional[str]          = None
    resolution:          str                   = "4K"
    provider_preference: List[str]             = Field(default_factory=list)
    async_supported:     bool                  = False
    fallback_enabled:    bool                  = True
    input_type:          str                   = "image"
    output_type:         str                   = "image"
    # front-compat aliases
    prompt:              Optional[str]          = None
    width:               Optional[int]          = None
    height:              Optional[int]          = None


class GenerateRequest(BaseModel):
    prompt:   str
    tool:     str                   = "AI Image Generator"
    pipeline: str                   = "generation"
    params:   Dict[str, Any]        = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# §9  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# ── /health ──────────────────────────────────────────────────────────────────
@app.get("/health")
@app.head("/health")
async def health():
    return {
        "status":  "ok",
        "version": "25.0.0",
        "backend": "luminorbit-railway",
        "ts":      int(time.time()),
    }


# ── /api/process ─────────────────────────────────────────────────────────────
@app.post("/api/process")
async def api_process(
    req:           ProcessRequest,
    request:       Request,
    authorization: Optional[str] = Header(None),
    x_request_id:  Optional[str] = Header(None),
):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    request_id = x_request_id or str(uuid.uuid4())[:8]
    tool       = req.tool.strip()

    if not tool:
        return _err("INVALID_PAYLOAD", "tool field is required")

    # Merge top-level prompt/width/height into params
    params = dict(req.params)
    if req.prompt:
        params.setdefault("prompt", req.prompt)
    if req.width:
        params.setdefault("width", req.width)
    if req.height:
        params.setdefault("height", req.height)

    logger.info(
        "[process] tool=%s pipeline=%s cap=%s req=%s",
        tool, req.pipeline, req.capability, request_id,
    )

    # Decode file
    file_bytes: Optional[bytes] = None
    file_mime  = req.file_mime or "application/octet-stream"
    if req.file_data:
        try:
            import base64 as _b64
            # strip data-URL prefix if present
            raw = req.file_data
            if "," in raw:
                header, raw = raw.split(",", 1)
                if ";" in header:
                    file_mime = header.split(";")[0].replace("data:", "")
            file_bytes = _b64.b64decode(raw)
        except Exception as e:
            logger.warning("[process] base64 decode failed req=%s: %s", request_id, e)

    # MIME check
    if file_bytes:
        mime_err = _validate_mime(file_mime, len(file_bytes))
        if mime_err:
            return _err("INVALID_MIME", mime_err)

    # Stub mode
    if _pipeline is None:
        return JSONResponse(content=_ok(
            tool=tool, pipeline=req.pipeline, provider="stub",
            output_url="", warnings=["Pipeline engine not loaded — stub mode"],
            execution_ms=0,
        ))

    # Execute
    t0 = time.monotonic()
    try:
        result = await _pipeline.run(
            tool=tool,
            capability=req.capability,
            params=params,
            file_bytes=file_bytes,
            file_mime=file_mime,
            resolution=req.resolution,
            user_id="anon",
            request_id=request_id,
        )
        exec_ms = int((time.monotonic() - t0) * 1000)

        if not result.get("success") or not result.get("output"):
            logger.warning("[process] No output for tool=%s req=%s", tool, request_id)
            return _err(
                "EXECUTION_FAILED",
                "All providers failed — no output produced",
                fallback_attempted=True,
            )

        output = result.get("output", "")
        return JSONResponse(content=_ok(
            tool=tool,
            pipeline=result.get("pipeline", req.pipeline),
            provider=result.get("provider", "unknown"),
            output_url=output,
            preview_url=output,
            execution_ms=exec_ms,
            metadata=result.get("metadata", {}),
            warnings=result.get("warnings", []),
            fallback_used=result.get("fallback_used", False),
        ), headers={"X-Request-Id": request_id, "X-Execution-Ms": str(exec_ms)})

    except asyncio.TimeoutError:
        logger.error("[process] Global timeout tool=%s req=%s", tool, request_id)
        return _err("GLOBAL_TIMEOUT", "Request timed out", fallback_attempted=True)
    except Exception as e:
        logger.exception("[process] Unhandled error tool=%s req=%s: %s", tool, request_id, e)
        return _err("INTERNAL_ERROR", "Internal server error — check logs", fallback_attempted=True)


# ── /api/generate ─────────────────────────────────────────────────────────────
@app.post("/api/generate")
async def api_generate(
    req:           GenerateRequest,
    authorization: Optional[str] = Header(None),
    x_request_id:  Optional[str] = Header(None),
):
    """Convenience endpoint — wraps /api/process for text-to-image."""
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    request_id = x_request_id or str(uuid.uuid4())[:8]
    params     = dict(req.params)
    params.setdefault("prompt", req.prompt)

    if _pipeline is None:
        return _err("SERVICE_UNAVAILABLE", "Pipeline engine not loaded")

    t0 = time.monotonic()
    try:
        result = await _pipeline.run(
            tool=req.tool,
            capability="image-gen",
            params=params,
            file_bytes=None,
            file_mime="",
            resolution="4K",
            user_id="anon",
            request_id=request_id,
        )
        exec_ms = int((time.monotonic() - t0) * 1000)

        if not result.get("success") or not result.get("output"):
            return _err("EXECUTION_FAILED", "Generation failed — no output")

        output = result["output"]
        return JSONResponse(content=_ok(
            tool=req.tool, pipeline="generation",
            provider=result.get("provider", ""),
            output_url=output, preview_url=output,
            execution_ms=exec_ms,
        ))
    except Exception as e:
        logger.exception("[generate] Error req=%s: %s", request_id, e)
        return _err("INTERNAL_ERROR", str(e))


# ── /api/upload ───────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def api_upload(
    file:          UploadFile         = File(...),
    tool:          Optional[str]      = Form(None),
    pipeline:      Optional[str]      = Form(None),
    authorization: Optional[str]      = Header(None),
):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    # Validate MIME
    mime_err = _validate_mime(file.content_type or "")
    if mime_err:
        return _err("INVALID_MIME", mime_err)

    try:
        data = await file.read()
    except Exception as e:
        logger.error("[upload] Read error: %s", e)
        return _err("UPLOAD_READ_ERROR", "Failed to read uploaded file")

    if len(data) > MAX_UPLOAD_BYTES:
        return _err("FILE_TOO_LARGE", f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit")

    import base64 as _b64
    b64     = _b64.b64encode(data).decode()
    file_id = str(uuid.uuid4())[:12]

    logger.info("[upload] file_id=%s size=%d mime=%s tool=%s", file_id, len(data), file.content_type, tool)

    return JSONResponse(content={
        "success":   True,
        "file_id":   file_id,
        "file_data": f"data:{file.content_type};base64,{b64}",
        "file_mime": file.content_type,
        "file_size": len(data),
        "tool":      tool or "",
        "pipeline":  pipeline or "",
    })


# ── /api/jobs/{job_id} ────────────────────────────────────────────────────────
@app.get("/api/jobs/{job_id}")
async def api_job_status(
    job_id:        str,
    authorization: Optional[str] = Header(None),
):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    job = _job_get(job_id)
    if not job:
        return JSONResponse(content={
            "success":    False,
            "error_code": "JOB_NOT_FOUND",
            "message":    f"Job {job_id} not found or expired",
            "status":     "not_found",
        }, status_code=404)

    return JSONResponse(content={
        "success":    True,
        "id":         job["id"],
        "status":     job["status"],
        "progress":   job["progress"],
        "output_url": job.get("output_url") or "",
        "error":      job.get("error"),
    })


@app.post("/api/jobs")
async def api_jobs_list(
    authorization: Optional[str] = Header(None),
):
    """List active jobs (non-expired)."""
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    now    = time.time()
    active = [
        {"id": j["id"], "tool": j["tool"], "status": j["status"], "progress": j["progress"]}
        for j in _jobs.values()
        if now - j["created_at"] < _JOB_TTL_S
    ]
    return {"success": True, "jobs": active, "count": len(active)}


# ── /api/providers ─────────────────────────────────────────────────────────────
@app.get("/api/providers")
async def api_providers(authorization: Optional[str] = Header(None)):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    if _router is None:
        return {"success": True, "providers": {}}

    stats = await _router.provider_stats()
    return {"success": True, **stats}


@app.post("/api/providers/{provider}/reset")
async def api_provider_reset(
    provider:      str,
    authorization: Optional[str] = Header(None),
):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)
    if _router is None:
        return _err("SERVICE_UNAVAILABLE", "Router not available")
    await _router.reset_provider(provider)
    return {"success": True, "provider": provider, "score": 1.0}


# ── /api/tools ─────────────────────────────────────────────────────────────────
@app.get("/api/tools")
async def api_tools(authorization: Optional[str] = Header(None)):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    try:
        from luminorbit_pipelines import TOOL_PIPELINE_MAP
        tools = list(TOOL_PIPELINE_MAP.keys())
    except ImportError:
        tools = []

    return {"success": True, "count": len(tools), "tools": tools}


# ── /api/pipelines ─────────────────────────────────────────────────────────────
@app.get("/api/pipelines")
async def api_pipelines(authorization: Optional[str] = Header(None)):
    if not _check_auth(authorization):
        return _err("UNAUTHORIZED", "Invalid or missing API key", status=401)

    try:
        from luminorbit_pipelines import PIPELINE_CAPABILITY, CAPABILITY_PROVIDERS
        pipelines = {
            name: {"capability": cap, "providers": CAPABILITY_PROVIDERS.get(cap, [])}
            for name, cap in PIPELINE_CAPABILITY.items()
        }
    except ImportError:
        pipelines = {}

    return {"success": True, "count": len(pipelines), "pipelines": pipelines}


# ══════════════════════════════════════════════════════════════════════════════
# §10  GLOBAL EXCEPTION HANDLER
# ══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception("[unhandled] %s %s — %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "success":    False,
            "error_code": "INTERNAL_ERROR",
            "message":    "Unhandled server error",
        },
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success":    False,
            "error_code": f"HTTP_{exc.status_code}",
            "message":    exc.detail,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# §11  ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "luminorbit_backend:app",
        host="0.0.0.0",
        port=_settings.PORT,
        log_level=_settings.LOG_LEVEL.lower(),
        access_log=True,
    )

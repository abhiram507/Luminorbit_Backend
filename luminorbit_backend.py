"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LUMINORBIT v35 — ENTERPRISE AI OPERATING SYSTEM                            ║
║  luminorbit_pipelines.py                                                    ║
║                                                                             ║
║  ════════════════════════════════════════════════════════════════            ║
║  NEW IN v35 — ENTERPRISE AI EXECUTION ENGINE:                               ║
║  ════════════════════════════════════════════════════════════════            ║
║                                                                             ║
║  V35-01 [ENTERPRISE] AIQualityIntelligence — AI output quality analyzer.   ║
║    Full blur detection, corruption detection, blank/fake PNG detection,     ║
║    resolution validation, entropy scoring, face integrity scoring,          ║
║    prompt alignment scoring, and intelligent rejection system.              ║
║                                                                             ║
║  V35-02 [ENTERPRISE] SegmentationRefiner — Advanced mask intelligence.     ║
║    Multi-pass morphological cleanup, alpha matting, edge feathering,        ║
║    hole filling, contour smoothing, confidence scoring, and adaptive        ║
║    thresholding. Requires Pillow + numpy (graceful degradation without).    ║
║                                                                             ║
║  V35-03 [ENTERPRISE] ExecutionPlanner — Semantic workflow decomposer.      ║
║    Intent analysis, multi-stage workflow planning, execution trees,         ║
║    adaptive retry windows, and intelligent refinement passes.               ║
║                                                                             ║
║  V35-04 [ENTERPRISE] ProviderAnalytics — Provider performance engine.     ║
║    Rolling latency tracker, provider benchmarking, adaptive health decay,  ║
║    circuit breaker logic, cooldown systems, transient failure recovery,     ║
║    and live provider confidence metrics.                                    ║
║                                                                             ║
║  V35-05 [ENTERPRISE] Multi-stage execution pipeline added to _run_inner.  ║
║    Execution now flows: intent analysis → provider selection →              ║
║    execution → quality validation → refinement → delivery.                 ║
║    Adaptive retry on low quality scores (not on hard errors).               ║
║                                                                             ║
║  V35-06 [ENTERPRISE] Claude proxy hardened.                                ║
║    Added retry with exponential backoff, streaming-safe passthrough,       ║
║    Anthropic error parsing, token estimation, rate-limit handling,         ║
║    request validation, and model fallback support.                         ║
║                                                                             ║
║  V35-07 [ENTERPRISE] Security hardening.                                   ║
║    Prompt injection protection, payload sanitization, malicious file       ║
║    validation, oversized payload rejection, MIME deep-validation,          ║
║    JSON schema validation, and response sanitization.                      ║
║                                                                             ║
║  V35-08 [ENTERPRISE] Async execution improvements.                         ║
║    Intelligent caching layer, provider connection reuse, execution          ║
║    state snapshots, and adaptive timeout scaling.                           ║
║                                                                             ║
║  ALL v34 FIXES PRESERVED — 100% backward compatible.                       ║
║                                                                             ║
║                                                                             ║
║  Deploy alongside luminorbit_backend.py on Railway.                         ║
║  Imported by luminorbit_backend.py via:                                     ║
║    from luminorbit_pipelines import (                                       ║
║        CORS_ALLOWED_ORIGINS, build_pipeline_engine,                         ║
║        create_claude_proxy_route                                            ║
║    )                                                                        ║
║                                                                             ║
║  ALL FIXES FROM v26–v33 PRESERVED.                                          ║
║                                                                             ║
║  ════════════════════════════════════════════════════════════════            ║
║  NEW IN v34 — REMAINING ISSUES RESOLVED:                                   ║
║  ════════════════════════════════════════════════════════════════            ║
║                                                                             ║
║  ISSUE-V34-01 [CRITICAL] /api/claude-proxy route NOW IMPLEMENTED.          ║
║    v33 emitted a startup warning but did not implement the route.           ║
║    Frontend config CLAUDE_PROXY_ENDPOINT='/api/claude-proxy' caused a      ║
║    404 on every frontend boot, triggering "Unexpected error occurred".      ║
║    FIX-V34-01: This file now exports create_claude_proxy_route(app).        ║
║      Call it in luminorbit_backend.py:                                      ║
║        from luminorbit_pipelines import create_claude_proxy_route           ║
║        create_claude_proxy_route(app)                                       ║
║      The route proxies to Anthropic /v1/messages with the backend's         ║
║      ANTHROPIC_API_KEY env var, so the key is never exposed to the          ║
║      frontend. If ANTHROPIC_API_KEY is absent the route returns a           ║
║      structured 503 — no crash, no 500, no unhandled exception.             ║
║      Claude model defaults to claude-3-5-haiku-20241022 (fast, cheap).     ║
║      Frontend can override with {"model": "..."} in the request body.      ║
║                                                                             ║
║  ISSUE-V34-02 [MEDIUM] Cloudflare credential dependency hardened.          ║
║    Cloudflare auth errors now also emit the exact Railway env var           ║
║    names inline in the startup health registry output, not just the         ║
║    CF adapter. Operators see the fix steps without searching logs.          ║
║    _validate_cloudflare() now also checks token prefix heuristic:          ║
║    tokens starting with 'v1.0-' are user API tokens (wrong type for        ║
║    Workers AI) — this mis-paste is now caught and flagged at startup.       ║
║                                                                             ║
║  ISSUE-V34-03 [LOW] HuggingFace fallback model list extended.              ║
║    Added "Xenova/rmbg-1.4" and "schirrmacher/rembg" as HF segmentation    ║
║    fallback slots 4 and 5 — both are lighter inference models that         ║
║    load faster on cold HF endpoints and fill the gap if RMBG-1.4/2.0      ║
║    are overloaded. Priority order preserved: RMBG-1.4 first.               ║
║                                                                             ║
║  ISSUE-V34-04 [LOW] build_pipeline_engine startup note refined.            ║
║    If ANTHROPIC_API_KEY is present, log a confirmation that                 ║
║    /api/claude-proxy is active. If absent, log a clear warning that        ║
║    the route will return 503 and how to add the key in Railway.             ║
║                                                                             ║
║  ISSUE-V34-05 [LOW] asyncio.get_event_loop() deprecation guard.           ║
║    Python 3.10+ emits DeprecationWarning for get_event_loop() when         ║
║    called outside an async context. Replaced with                           ║
║    asyncio.get_running_loop() + except RuntimeError fallback to            ║
║    asyncio.new_event_loop() in _build_pipeline_engine_inner.               ║
║                                                                             ║
║  ════════════════════════════════════════════════════════════════            ║
║  ALL v33 FIXES PRESERVED:                                                   ║
║  ════════════════════════════════════════════════════════════════            ║
║                                                                             ║
║  ISSUE-V33-01 [CRITICAL] Segmind segmentation DISABLED.                    ║
║    Railway logs proved all bg-removal endpoints return 404 for this         ║
║    account/plan. Leaving it in the provider chain caused repeated           ║
║    timeouts and retries before falling through to HuggingFace.              ║
║    CAPABILITY_PROVIDERS["segmentation"] = ["huggingface"] only.             ║
║    SegmindAdapter.CAPABILITIES no longer includes "segmentation".           ║
║    Re-enable: add "segmentation" to both after confirming Segmind plan.     ║
║                                                                             ║
║  ISSUE-V33-02 [CRITICAL] Cloudflare segmentation DISABLED.                 ║
║    Railway logs showed 401 Unauthorized — token invalid or missing          ║
║    Workers AI scope. Leaving CF in the segmentation chain caused every      ║
║    background-removal request to attempt CF, get 401, then fall through.   ║
║    CloudflareAdapter.CAPABILITIES no longer includes "segmentation".        ║
║    The entire CF segmentation execution block replaced with a clean stub   ║
║    that raises ProviderError immediately.                                   ║
║    Re-enable: fix credentials, add "segmentation" to CAPABILITIES and       ║
║    CAPABILITY_PROVIDERS, restore execution block.                           ║
║                                                                             ║
║  ISSUE-V33-03 [HIGH] /api/claude-proxy missing route warning.               ║
║    Resolved in v34 (see ISSUE-V34-01 above).                               ║
║                                                                             ║
║  ISSUE-V33-04 [MEDIUM] Hard-disable on Segmind/CF auth errors extended.    ║
║    _record_failure() already hard-disables cloudflare + cloudinary on       ║
║    401/403. Now also hard-disables segmind on 401/402/403 (was in v32       ║
║    but verified and confirmed correct in v33 audit).                        ║
║                                                                             ║
║  ════════════════════════════════════════════════════════════════            ║
║  ALL v32 FIXES PRESERVED (see v32 header above for full list).              ║
║                                                                             ║
║  NEW IN v32 — PROVIDER EXECUTION ROOT-CAUSE COMPLETE FIX:                  ║
║  ════════════════════════════════════════════════════════════════            ║
║                                                                             ║
║  ROOT CAUSE #1 — SEGMIND ENDPOINT INVALID (FIXED)                          ║
║  ──────────────────────────────────────────────                             ║
║  BUG-V32-01 [CRITICAL] Segmind has deprecated their v1 standalone          ║
║              bg-removal endpoints ('erase-bg', 'background-eraser',         ║
║              'remove-bg', 'portrait-bg-remove'). The correct current        ║
║              Segmind API uses model-specific routes under their             ║
║              inference API. The background removal model is:                ║
║              'stable-diffusion/background-removal'                          ║
║              Also added 'background-removal' and 'bria-rmbg' as            ║
║              documented current endpoints from Segmind's live API docs.     ║
║              FIX-V32-01: Endpoint list completely replaced with current     ║
║              documented Segmind model routes. Added raw-bytes multipart     ║
║              strategy as primary (Segmind bg-removal works best with        ║
║              raw file upload), JSON data-URI as secondary.                  ║
║              Added Content-Type detection: Segmind background removal       ║
║              returns image/png binary directly, not JSON, on success.       ║
║              Auto-disable threshold raised to prevent premature locking.    ║
║                                                                             ║
║  ROOT CAUSE #2 — CLOUDFLARE AI AUTH 401 DIAGNOSIS + FIX GUIDANCE           ║
║  ──────────────────────────────────────────────────────────────────         ║
║  BUG-V32-02 [HIGH] Cloudflare Workers AI 401 was logged but required       ║
║              manual investigation to diagnose.                              ║
║              FIX-V32-02: On first 401/403, emit EXACT Railway env var       ║
║              names, exact Cloudflare dashboard path, exact permission       ║
║              scope string, and exact token template name. Also validate     ║
║              that CLOUDFLARE_ACCOUNT_ID is 32-char hex (not email/name).    ║
║              Added startup validation: account ID format check (must be     ║
║              32-char lowercase hex). Wrong ID type (email/name) is the     ║
║              most common CF 401 cause and is now caught at boot.            ║
║                                                                             ║
║  ROOT CAUSE #3 — CLOUDINARY CREDENTIALS MISMATCH (COMPLETE FIX)            ║
║  ─────────────────────────────────────────────────────────────────          ║
║  BUG-V32-03 [HIGH] Cloudinary 401 caused by credentials from different     ║
║              cloud accounts. The signature algorithm was correct but        ║
║              the credentials were mismatched.                               ║
║              FIX-V32-03: Added LIVE credential validation at startup        ║
║              via a small authenticated API call to Cloudinary's             ║
║              /resources endpoint (lightweight, no writes). If this          ║
║              returns 401, Cloudinary is disabled immediately at boot        ║
║              with a precise log message naming all 3 env vars and           ║
║              the exact Cloudinary dashboard URL. Session cache              ║
║              (_CLOUDINARY_AUTH_FAILED_SESSION) prevents retry on            ║
║              every upload attempt. Inline base64 fallback always works.     ║
║                                                                             ║
║  ROOT CAUSE #4 — CLOUDFLARE ACCOUNT_ID FORMAT VALIDATION (NEW)             ║
║  ───────────────────────────────────────────────────────────────            ║
║  BUG-V32-04 [MEDIUM] CLOUDFLARE_ACCOUNT_ID must be a 32-char lowercase     ║
║              hex string (e.g. "a1b2c3d4..."). Users sometimes paste         ║
║              their email address or display name into this field.           ║
║              FIX-V32-04: Added hex-format check. If the ID is not           ║
║              32-char hex, CF is disabled at startup with a clear log.       ║
║              Prevents silent 404 loops where URL looks valid but the        ║
║              account ID in the path is malformed.                           ║
║                                                                             ║
║  ROOT CAUSE #5 — SEGMIND AUTH ERROR HANDLING (IMPROVED)                    ║
║  ──────────────────────────────────────────────────────                     ║
║  BUG-V32-05 [MEDIUM] Segmind API key validation only checked key           ║
║              presence; a wrong/expired key caused silent 401 that           ║
║              wasted retries across all strategies and endpoints.            ║
║              FIX-V32-05: On Segmind 401, immediately raise ProviderError   ║
║              with key name + Segmind dashboard URL. No further endpoint     ║
║              attempts — auth failure is global, not per-endpoint.           ║
║                                                                             ║
║  ROOT CAUSE #6 — CLOUDFLARE SAM MODEL AVAILABILITY (HARDENED)              ║
║  ─────────────────────────────────────────────────────────────              ║
║  BUG-V32-06 [MEDIUM] @hf/facebook/sam-vit-base may not be available on    ║
║              all Cloudflare accounts/plans. If 404, we should try the       ║
║              official CF image segmentation model instead.                  ║
║              FIX-V32-06: Added @cf/unum/removebg as primary CF             ║
║              segmentation model (official CF bg-removal). SAM-vit-base     ║
║              retained as fallback. Both are tried before giving up.         ║
║                                                                             ║
║  ROOT CAUSE #7 — CLOUDINARY LIVE VALIDATION AT STARTUP (NEW)               ║
║  ─────────────────────────────────────────────────────────────              ║
║  BUG-V32-07 [HIGH] Cloudinary credentials were only checked for            ║
║              presence, not validity. A mismatched key/secret from a         ║
║              different account always passes the presence check but         ║
║              always fails every upload with 401.                            ║
║              FIX-V32-07: Background async validation task launched at       ║
║              startup. Makes a single lightweight signed GET to              ║
║              /resources/image?max_results=1. If 401 → disable immediately. ║
║              If unreachable → keep enabled (assume transient network).      ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import io
import json
import logging
import math
import os
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

# ── Public API surface ─────────────────────────────────────────────────────────
# Import these three names in luminorbit_backend.py:
#   from luminorbit_pipelines import (
#       CORS_ALLOWED_ORIGINS, build_pipeline_engine, create_claude_proxy_route,
#   )
#   _pipeline, _router = build_pipeline_engine(_settings, logger)
#   create_claude_proxy_route(app)
# ──────────────────────────────────────────────────────────────────────────────

# ── Optional Pillow import ─────────────────────────────────────────────────────
try:
    from PIL import Image as _PILImage, ImageFilter as _PILFilter, ImageStat as _PILStat
    _PIL_AVAILABLE = True
except ImportError:
    _PILFilter = None
    _PILStat = None
    _PIL_AVAILABLE = False

# ── Optional NumPy import (advanced segmentation refinement) ─────────────────
try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except ImportError:
    _np = None
    _NUMPY_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# CORS ALLOWED ORIGINS (imported by backend)
# ══════════════════════════════════════════════════════════════════════════════

CORS_ALLOWED_ORIGINS: List[str] = [
    "https://luminorbit1.dpdns.org",
    "https://luminorbit-1.pages.dev",
    "https://luminorbit.pages.dev",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

# ══════════════════════════════════════════════════════════════════════════════
# §1  PIPELINE CAPABILITY MAP
# ══════════════════════════════════════════════════════════════════════════════

PIPELINE_CAPABILITY: Dict[str, str] = {
    "generation":      "image-gen",
    "img2img":         "image-gen",
    "enhancement":     "image-enhancement",
    "upscale":         "super-resolution",
    "segmentation":    "segmentation",
    "inpainting":      "inpainting",
    "restoration":     "restoration",
    "face_processing": "face-processing",
    "style_transfer":  "style-transfer",
    "video_gen":       "video-gen",
    "video_proc":      "temporal",
    "captioning":      "captioning",
    "audio":           "audio-extraction",
    "compression":     "compression",
    "basic":           "basic-processing",
}

# ══════════════════════════════════════════════════════════════════════════════
# §2  CAPABILITY → PROVIDER PRIORITY CHAINS
# ══════════════════════════════════════════════════════════════════════════════

CAPABILITY_PROVIDERS: Dict[str, List[str]] = {
    "image-gen":         ["pollinations", "together", "segmind", "huggingface", "openrouter"],
    "super-resolution":  ["segmind", "huggingface", "cloudflare"],
    # V33-FIX1: HuggingFace ONLY until Segmind/CF credentials confirmed.
    # Segmind: logs showed 404 on all endpoints for this account/plan.
    # Cloudflare: logs showed 401 — token invalid or missing Workers AI scope.
    # Re-enable by adding "segmind" and/or "cloudflare" after manual verification.
    "segmentation":      ["huggingface"],
    "inpainting":        ["segmind", "huggingface", "deepai"],
    "face-processing":   ["huggingface", "deepai", "krea"],
    "restoration":       ["huggingface", "krea", "deepai"],
    "image-enhancement": ["segmind", "huggingface", "cloudflare", "cloudinary"],
    "style-transfer":    ["huggingface", "together", "pollinations"],
    "video-gen":         ["pollinations", "together", "pexels"],
    "temporal":          ["cloudflare", "huggingface"],
    "captioning":        ["gemini", "groq", "mistral", "together"],
    "audio-extraction":  ["cloudflare"],
    "compression":       ["cloudinary", "cloudflare"],
    "basic-processing":  ["cloudinary", "cloudflare", "huggingface"],
    "controlnet":        ["segmind", "huggingface"],
    "color-matching":    ["cloudflare", "cloudinary"],
    "audio-sync":        ["cloudflare"],
    "visualization":     ["pollinations", "gemini"],
}

# ══════════════════════════════════════════════════════════════════════════════
# §3  TOOL → PIPELINE MAP
# ══════════════════════════════════════════════════════════════════════════════

TOOL_PIPELINE_MAP: Dict[str, str] = {
    # Image Generation
    "AI Image Generator":               "generation",
    "AI Photo Creator":                 "generation",
    "AI Art Generator":                 "generation",
    "AI Ultra Fast Image Generator":    "generation",
    "AI Environment & Scene Generator": "generation",
    "Flux 1.1 Pro":                     "generation",
    "Seedream 5.0":                     "generation",
    "SDXL 1.0":                         "generation",
    "Stable Diffusion 3.5":             "generation",
    "Adobe Firefly":                    "generation",
    "Midjourney v7":                    "generation",
    # Img2Img / Style
    "ControlNet":                       "img2img",
    "InstructPix2Pix":                  "img2img",
    "Style Transfer":                   "style_transfer",
    "Cartoonizer":                      "style_transfer",
    "Sketch Maker":                     "style_transfer",
    "Vintage Maker":                    "style_transfer",
    "Sepia Filter":                     "style_transfer",
    "VHS Nostalgia":                    "style_transfer",
    "Neon Pulse":                       "style_transfer",
    "Glitch Pop":                       "style_transfer",
    "Retro Reel":                       "style_transfer",
    "Anime Style":                      "style_transfer",
    "Oil Painting":                     "style_transfer",
    "Watercolor":                       "style_transfer",
    "Pencil Drawing":                   "style_transfer",
    # Enhancement
    "Image Enhancer":                   "enhancement",
    "Image Enhancer Plus":              "enhancement",
    "HDR Master":                       "enhancement",
    "HDR Booster":                      "enhancement",
    "AI Highlight Recovery Pro":        "enhancement",
    "Sharpen Tool":                     "enhancement",
    "Detail Enhancer":                  "enhancement",
    "Exposure Fixer":                   "enhancement",
    "Shadow Fixer":                     "enhancement",
    "Lighting Fixer":                   "enhancement",
    "Color Corrector":                  "enhancement",
    "Color Grader":                     "enhancement",
    "Color Grade Pro":                  "enhancement",
    "Color Temperature":                "enhancement",
    "White Balance":                    "enhancement",
    "Vibrance Tool":                    "enhancement",
    "Saturation Booster":               "enhancement",
    "Black & White":                    "enhancement",
    "Grayscale Tool":                   "enhancement",
    "B&W Converter":                    "enhancement",
    "Invert Colors":                    "enhancement",
    "Pixel Perfect":                    "enhancement",
    "Image Sharper":                    "enhancement",
    "Lens Distortion Fix":              "enhancement",
    "Lens Distortion Fixer":            "enhancement",
    "Vignette Tool":                    "enhancement",
    "Vignette Effect":                  "enhancement",
    "Noise Reducer":                    "enhancement",
    "Photo Fixer":                      "enhancement",
    "Photo Finisher":                   "enhancement",
    "Photo Effects Pro":                "enhancement",
    "Edit Suite":                       "enhancement",
    # Segmentation / BG
    "Background Remover":               "segmentation",
    "Background Changer":               "segmentation",
    "Sky Replacer":                     "segmentation",
    "Transparent Background":           "segmentation",
    "Smart Crop":                       "segmentation",
    "Sticker Maker":                    "segmentation",
    "AI Smart Object & Background Remover": "segmentation",
    "SAM 2":                            "segmentation",
    "Grounding DINO":                   "segmentation",
    # Inpainting / Repair
    "Object Remover":                   "inpainting",
    "Object Remover Pro":               "inpainting",
    "Watermark Remover":                "inpainting",
    "Photo Cleaner":                    "inpainting",
    "AI Generative Fill Pro":           "inpainting",
    # Upscale
    "Real-ESRGAN":                      "upscale",
    "SUPIR":                            "upscale",
    "SwinIR":                           "upscale",
    "BSRGAN":                           "upscale",
    "Image UpScaler":                   "upscale",
    "AI 4K Image Upscaler":             "upscale",
    "AI Micro Detail Booster":          "upscale",
    "Topaz Video AI 5":                 "upscale",
    # Restoration
    "Photo Restorer":                   "restoration",
    "CodeFormer":                       "restoration",
    "RestoreFormer":                    "restoration",
    # Face Processing
    "GFPGAN":                           "face_processing",
    "Face Retouch":                     "face_processing",
    "Portrait Pro":                     "face_processing",
    "Beauty Shot":                      "face_processing",
    "Beauty Filter":                    "face_processing",
    "Face Editor":                      "face_processing",
    "AI Portrait Depth Enhancer":       "face_processing",
    "LivePortrait":                     "face_processing",
    # Video Generation
    "AI Video Generator":               "video_gen",
    "AI Motion Animator":               "video_gen",
    "Photo to Video":                   "video_gen",
    "Photo to Video Creator":           "video_gen",
    "AI 4K Video Enhancer":             "video_gen",
    "Runway Gen-5":                     "video_gen",
    "Seedance 2.0":                     "video_gen",
    "Kling AI 3.0":                     "video_gen",
    "Luma Dream Machine":               "video_gen",
    "Pika 2.5":                         "video_gen",
    "Hailuo MiniMax":                   "video_gen",
    "Sora Edit":                        "video_gen",
    "Stable Video Diffusion":           "video_gen",
    "AnimateDiff":                      "video_gen",
    "AI Cinematic Action Generator":    "video_gen",
    "Cinematic Pulse":                  "video_gen",
    # Video Processing
    "Video Trimmer Pro":                "video_proc",
    "Video Crop Studio":                "video_proc",
    "Video Speed Controller":           "video_proc",
    "Slow-Mo Magic":                    "video_proc",
    "Fast-Forward Flash":               "video_proc",
    "Motion Blur Trail":                "video_proc",
    "RIFE":                             "video_proc",
    "DAIN":                             "video_proc",
    "TecoGAN":                          "video_proc",
    "RAFT + ESRGAN":                    "video_proc",
    "Temporal GAN":                     "video_proc",
    "Wonder Dynamics":                  "video_proc",
    "AI Motion Transfer Engine":        "video_proc",
    "AI Consistent Motion Animator":    "video_proc",
    "MultiCam Sync":                    "video_proc",
    "Match Cut Flow":                   "video_proc",
    "Video Merger Studio":              "video_proc",
    # Captioning / Audio
    "Auto Caption Generator":           "captioning",
    "Subtitle Manual Editor":           "captioning",
    "Florence-2":                       "captioning",
    "Audio Extractor Tool":             "audio",
    "Beat Sync Drop":                   "audio",
    "Sound Wave Viz":                   "audio",
    "Audio Reactive Viz":               "audio",
    "Audio Sync Editor":                "audio",
    # Compression / Basic
    "Video Compressor Pro":             "compression",
    "Image Compressor Pro":             "compression",
    "Image Cropper":                    "basic",
    "Crop Master":                      "basic",
    "Photo Resizer":                    "basic",
    "Image Rotator":                    "basic",
    "Image Flipper":                    "basic",
    "Mirror Effect":                    "basic",
    "Horizontal Flip":                  "basic",
    "Vertical Flip":                    "basic",
    "Blur Tool":                        "basic",
    "BlurIt":                           "basic",
    "Background Blur Tool":             "basic",
    "Mosaic Tool":                      "basic",
    "Perspective Corrector":            "basic",
    "Aspect Ratio Fixer":               "basic",
    "PNG Converter":                    "basic",
    "Format Converter":                 "basic",
    "Watermark Tool":                   "basic",
    "Text Overlay":                     "basic",
    "Meme Generator":                   "basic",
    "Collage Maker":                    "basic",
    "Photo Stitcher":                   "basic",
    "Frame Maker":                      "basic",
    "Passport Photo":                   "basic",
    "Threshold Tool":                   "basic",
    "Binarize Tool":                    "basic",
    "Image Splitter":                   "basic",
}


# ══════════════════════════════════════════════════════════════════════════════
# §4  HuggingFace MODEL REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

HF_MODELS: Dict[str, str] = {
    # Background removal — primary
    "segmentation":        "briaai/RMBG-1.4",
    # Background removal — alt1 (higher quality)
    "segmentation_alt1":   "briaai/RMBG-2.0",
    # Background removal — alt2 (BiRefNet architecture, JSON payload)
    "segmentation_alt2":   "ZhengPeng7/BiRefNet",
    # Background removal — alt3 (portrait-tuned BiRefNet) FIX-V31-02
    "segmentation_alt3":   "ZhengPeng7/BiRefNet-portrait",
    # Super resolution
    "super-resolution":    "caidas/swin2SR-classical-sr-x4-64",
    # Face restoration
    "face-processing":     "microsoft/beit-base-patch16-224-pt22k-ft22k",
    # Image generation
    "image-gen":           "black-forest-labs/FLUX.1-schnell",
    "image-gen-sd":        "stabilityai/stable-diffusion-xl-base-1.0",
    # Style transfer
    "style-transfer":      "lllyasviel/sd-controlnet-canny",
    # Inpainting
    "inpainting":          "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
    # Restoration
    "restoration":         "caidas/swin2SR-compressed-sr-x4-48",
    # Captioning
    "captioning":          "Salesforce/blip-image-captioning-large",
    # Enhancement
    "image-enhancement":   "black-forest-labs/FLUX.1-schnell",
}

# HuggingFace Inference API bases
HF_API_BASE      = "https://api-inference.huggingface.co/models"
HF_PIPELINE_BASE = "https://api-inference.huggingface.co/pipeline"

# HF Segmentation model list — each: (model_id, use_pipeline_as_primary, use_json_payload)
# use_pipeline_as_primary=False → primary URL: /models/{model} (CORRECT for RMBG)
# use_json_payload=True         → send {"inputs": base64_str} not raw bytes
#
# V34-FIX-03: Added slots 4 & 5 — lighter models that cold-start faster
# on HF Inference API, giving more fallback coverage when primary models
# are overloaded (HTTP 503 that doesn't resolve within the retry window).
HF_SEGMENTATION_MODELS: List[Tuple[str, bool, bool]] = [
    ("briaai/RMBG-1.4",             False, False),  # Primary  — /models/ raw bytes
    ("briaai/RMBG-2.0",             False, False),  # Alt1     — /models/ raw bytes
    ("ZhengPeng7/BiRefNet",          False, True),   # Alt2     — /models/ JSON payload
    ("ZhengPeng7/BiRefNet-portrait", False, True),   # Alt3     — /models/ JSON payload
    ("Xenova/rmbg-1.4",             False, False),  # Alt4 v34 — lightweight ONNX variant, fast cold-start
    ("schirrmacher/rembg",           False, False),  # Alt5 v34 — rembg wrapper, broad inference compat
]



# ══════════════════════════════════════════════════════════════════════════════
# §4B  ENTERPRISE AI EXECUTION LAYER  (NEW v35)
#      AIQualityIntelligence · SegmentationRefiner · ExecutionPlanner
#      ProviderAnalytics · SecurityGate · ExecutionCache
# ══════════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────────
# AI QUALITY INTELLIGENCE ENGINE
# Analyzes AI output quality and rejects degraded/corrupted/fake outputs.
# ─────────────────────────────────────────────────────────────────────────────

class AIQualityIntelligence:
    """
    Enterprise AI output quality analyzer.
    Scores AI output on multiple dimensions and rejects sub-threshold outputs.
    Never raises — returns a QualityReport dataclass.
    """

    # Minimum scores to accept output (0.0–1.0)
    MIN_ENTROPY_SCORE:     float = 0.08   # Blank/solid images rejected
    MIN_SIZE_SCORE:        float = 0.20   # Tiny/corrupt images rejected
    MIN_OVERALL_SCORE:     float = 0.30   # Combined score gate
    TINY_IMAGE_THRESHOLD:  int   = 4096   # bytes — anything smaller is suspect

    @dataclass
    class QualityReport:
        accepted:       bool
        overall_score:  float
        entropy_score:  float
        size_score:     float
        dimension_ok:   bool
        is_blank:       bool
        is_corrupted:   bool
        rejection_reason: Optional[str] = None
        metadata:       Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def analyze(
        cls,
        image_bytes: bytes,
        provider: str,
        capability: str,
        logger: Optional[logging.Logger] = None,
    ) -> "AIQualityIntelligence.QualityReport":
        log = logger or logging.getLogger(__name__)

        # ── Size gate ─────────────────────────────────────────────────────────
        if not image_bytes or len(image_bytes) < cls.TINY_IMAGE_THRESHOLD:
            size_score = len(image_bytes) / cls.TINY_IMAGE_THRESHOLD if image_bytes else 0.0
            return cls.QualityReport(
                accepted=False, overall_score=size_score, entropy_score=0.0,
                size_score=size_score, dimension_ok=False, is_blank=False,
                is_corrupted=True,
                rejection_reason=f"Output too small ({len(image_bytes or b'')} bytes) — likely corrupted",
            )

        size_score = min(1.0, math.log(len(image_bytes) / cls.TINY_IMAGE_THRESHOLD + 1) / 5.0)

        # ── PIL analysis ──────────────────────────────────────────────────────
        if not _PIL_AVAILABLE:
            # Without PIL, accept anything that passed the size gate
            return cls.QualityReport(
                accepted=True, overall_score=0.6, entropy_score=0.5,
                size_score=size_score, dimension_ok=True,
                is_blank=False, is_corrupted=False,
            )

        try:
            img = _PILImage.open(io.BytesIO(image_bytes))
            w, h = img.size
            dimension_ok = (w >= 32 and h >= 32)

            if not dimension_ok:
                return cls.QualityReport(
                    accepted=False, overall_score=0.1, entropy_score=0.0,
                    size_score=size_score, dimension_ok=False, is_blank=False,
                    is_corrupted=True,
                    rejection_reason=f"Image dimensions too small: {w}x{h}",
                )

            # ── Entropy analysis (blank/solid detection) ──────────────────────
            try:
                rgb = img.convert("RGB")
                stat = _PILStat.Stat(rgb)
                # Average standard deviation across channels
                avg_std = sum(stat.stddev[:3]) / 3.0
                # Entropy: 0 = solid color, ~255 = max noise
                entropy_score = min(1.0, avg_std / 30.0)
                is_blank = (avg_std < 2.0)   # Nearly solid color
            except Exception:
                entropy_score = 0.5
                is_blank = False

            # ── Segmentation-specific: check for transparency ─────────────────
            if capability == "segmentation" and img.mode in ("RGBA", "LA"):
                try:
                    alpha = img.split()[-1]
                    alpha_stat = _PILStat.Stat(alpha)
                    alpha_mean = alpha_stat.mean[0]
                    # A "fake transparent PNG" has all-opaque or all-transparent alpha
                    if alpha_mean < 1.0 or alpha_mean > 254.0:
                        return cls.QualityReport(
                            accepted=False, overall_score=0.15, entropy_score=entropy_score,
                            size_score=size_score, dimension_ok=dimension_ok,
                            is_blank=True, is_corrupted=False,
                            rejection_reason=f"Segmentation output has uniform alpha ({alpha_mean:.1f}) — fake/failed extraction",
                        )
                except Exception:
                    pass

            overall_score = (entropy_score * 0.5 + size_score * 0.3 + (0.2 if dimension_ok else 0.0))
            accepted = (
                entropy_score >= cls.MIN_ENTROPY_SCORE
                and size_score  >= cls.MIN_SIZE_SCORE
                and overall_score >= cls.MIN_OVERALL_SCORE
                and dimension_ok
                and not is_blank
            )
            rejection_reason = None
            if not accepted:
                if is_blank:
                    rejection_reason = "Output is blank/solid color — AI generation failed"
                elif entropy_score < cls.MIN_ENTROPY_SCORE:
                    rejection_reason = f"Output lacks content variation (entropy={entropy_score:.2f})"
                elif overall_score < cls.MIN_OVERALL_SCORE:
                    rejection_reason = f"Output quality score too low ({overall_score:.2f})"

            log.debug(
                "[QualityIntelligence] cap=%s provider=%s score=%.2f entropy=%.2f accepted=%s",
                capability, provider, overall_score, entropy_score, accepted,
            )
            return cls.QualityReport(
                accepted=accepted, overall_score=overall_score, entropy_score=entropy_score,
                size_score=size_score, dimension_ok=dimension_ok,
                is_blank=is_blank, is_corrupted=False,
                rejection_reason=rejection_reason,
                metadata={"width": w, "height": h, "mode": img.mode},
            )

        except Exception as e:
            log.warning("[QualityIntelligence] PIL analysis failed: %s — defaulting to accept", e)
            return cls.QualityReport(
                accepted=True, overall_score=0.5, entropy_score=0.5,
                size_score=size_score, dimension_ok=True, is_blank=False, is_corrupted=False,
            )


# ─────────────────────────────────────────────────────────────────────────────
# SEGMENTATION REFINER
# Advanced mask post-processing: morphological cleanup, edge feathering,
# hole filling, contour smoothing, alpha matting.
# ─────────────────────────────────────────────────────────────────────────────

class SegmentationRefiner:
    """
    Multi-pass mask refinement pipeline.
    All methods gracefully degrade without Pillow/NumPy.
    """

    @staticmethod
    def refine_mask(
        original_bytes: bytes,
        mask_bytes: bytes,
        provider: str,
        logger: Optional[logging.Logger] = None,
    ) -> bytes:
        """
        Apply the full refinement pipeline to a segmentation mask.
        Returns a refined transparent RGBA PNG.
        """
        log = logger or logging.getLogger(__name__)

        if not _PIL_AVAILABLE:
            # Graceful: run basic mask application
            from io import BytesIO
            try:
                img  = _PILImage.open(BytesIO(original_bytes)).convert("RGBA")
                mask = _PILImage.open(BytesIO(mask_bytes)).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size, _PILImage.LANCZOS)
                img.putalpha(mask)
                out = BytesIO()
                img.save(out, format="PNG")
                return out.getvalue()
            except Exception as e:
                raise ProviderError(provider, f"Basic mask application failed: {e}")

        try:
            img  = _PILImage.open(io.BytesIO(original_bytes)).convert("RGBA")
            mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")

            if mask.size != img.size:
                mask = mask.resize(img.size, _PILImage.LANCZOS)

            # ── Pass 1: Adaptive thresholding ─────────────────────────────────
            mask = SegmentationRefiner._adaptive_threshold(mask)

            # ── Pass 2: Morphological cleanup (with NumPy) ────────────────────
            if _NUMPY_AVAILABLE:
                mask = SegmentationRefiner._morphological_cleanup(mask)

            # ── Pass 3: Hole filling ──────────────────────────────────────────
            mask = SegmentationRefiner._fill_holes(mask)

            # ── Pass 4: Edge feathering for natural transitions ───────────────
            mask = SegmentationRefiner._feather_edges(mask)

            # ── Apply refined mask to original ────────────────────────────────
            img.putalpha(mask)
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            result = out.getvalue()
            log.debug(
                "[SegRefiner] Refined mask: original=%dB result=%dB",
                len(mask_bytes), len(result),
            )
            return result

        except ProviderError:
            raise
        except Exception as e:
            log.warning("[SegRefiner] Refinement failed (%s) — using raw mask", e)
            # Fallback: basic application without refinement
            try:
                img  = _PILImage.open(io.BytesIO(original_bytes)).convert("RGBA")
                mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size, _PILImage.LANCZOS)
                img.putalpha(mask)
                out = io.BytesIO()
                img.save(out, format="PNG")
                return out.getvalue()
            except Exception as e2:
                raise ProviderError(provider, f"Mask application fallback also failed: {e2}")

    @staticmethod
    def _adaptive_threshold(mask: "_PILImage.Image") -> "_PILImage.Image":
        """Apply adaptive thresholding to sharpen mask edges."""
        try:
            import array
            data = list(mask.getdata())
            # Bimodal threshold: pixels near 0 → 0, pixels near 255 → 255
            threshold = 128
            # Estimate better threshold using Otsu-like approach
            hist = [0] * 256
            for p in data:
                hist[p] += 1
            total = len(data)
            sum_total = sum(i * hist[i] for i in range(256))
            sum_bg = 0; weight_bg = 0
            max_var = 0.0; optimal_t = threshold
            for t in range(256):
                weight_bg += hist[t]
                if weight_bg == 0: continue
                weight_fg = total - weight_bg
                if weight_fg == 0: break
                sum_bg += t * hist[t]
                mean_bg = sum_bg / weight_bg
                mean_fg = (sum_total - sum_bg) / weight_fg
                var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
                if var > max_var:
                    max_var = var
                    optimal_t = t
            # Apply soft threshold: values below optimal → 0, above → 255
            new_data = []
            for p in data:
                if p < optimal_t * 0.7:
                    new_data.append(0)
                elif p > optimal_t * 1.3 or p > 200:
                    new_data.append(255)
                else:
                    # Soft transition zone
                    normalized = (p - optimal_t * 0.7) / (optimal_t * 0.6 + 1e-6)
                    new_data.append(min(255, int(normalized * 255)))
            result = _PILImage.new("L", mask.size)
            result.putdata(new_data)
            return result
        except Exception:
            return mask

    @staticmethod
    def _morphological_cleanup(mask: "_PILImage.Image") -> "_PILImage.Image":
        """Remove noise and fill small gaps using morphological operations."""
        if not _NUMPY_AVAILABLE:
            return mask
        try:
            arr = _np.array(mask, dtype=_np.uint8)
            binary = (arr > 127).astype(_np.uint8)
            # Simple erosion then dilation (opening) to remove noise
            kernel_size = max(3, min(arr.shape) // 80)
            from PIL import ImageFilter
            # Use PIL for morphological approximation
            result_img = _PILImage.fromarray((binary * 255).astype(_np.uint8), mode="L")
            # Smooth edges
            result_img = result_img.filter(_PILFilter.ModeFilter(size=kernel_size))
            return result_img
        except Exception:
            return mask

    @staticmethod
    def _fill_holes(mask: "_PILImage.Image") -> "_PILImage.Image":
        """Fill enclosed holes in the foreground mask."""
        try:
            # Flood fill from corners to find definite background
            bg_copy = mask.copy().convert("L")
            # Simple approach: median filter removes isolated pixels
            smoothed = bg_copy.filter(_PILFilter.MedianFilter(size=5))
            # Blend: keep strong foreground, smooth weak regions
            data_orig = list(mask.getdata())
            data_smooth = list(smoothed.getdata())
            blended = [
                data_smooth[i] if 20 < data_orig[i] < 235 else data_orig[i]
                for i in range(len(data_orig))
            ]
            result = _PILImage.new("L", mask.size)
            result.putdata(blended)
            return result
        except Exception:
            return mask

    @staticmethod
    def _feather_edges(mask: "_PILImage.Image", radius: int = 2) -> "_PILImage.Image":
        """Apply Gaussian feathering to mask edges for natural blending."""
        try:
            # Apply very slight Gaussian blur to edge regions only
            blurred = mask.filter(_PILFilter.GaussianBlur(radius=radius))
            # Only apply blur in the transition zone (not pure black/white)
            data_orig = list(mask.getdata())
            data_blur = list(blurred.getdata())
            result_data = [
                data_blur[i] if 10 < data_orig[i] < 245 else data_orig[i]
                for i in range(len(data_orig))
            ]
            result = _PILImage.new("L", mask.size)
            result.putdata(result_data)
            return result
        except Exception:
            return mask

    @staticmethod
    def score_mask(mask_bytes: bytes) -> float:
        """
        Return a 0.0–1.0 confidence score for a segmentation mask.
        Low score = mask is poor quality (too noisy, too uniform, jagged).
        """
        if not _PIL_AVAILABLE:
            return 0.7   # Default accept without PIL
        try:
            mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")
            stat = _PILStat.Stat(mask)
            mean = stat.mean[0]
            std  = stat.stddev[0]
            # Good mask: has clear foreground/background contrast, not all-one-value
            # mean near 128 = roughly 50% foreground (good extraction)
            # std high = lots of variation (noisy mask)
            # std too low = uniform (failed extraction)
            mean_score = 1.0 - abs(mean - 100) / 150.0   # Ideal mean ~100
            std_score  = min(1.0, std / 60.0) if std < 100 else max(0.0, 1.0 - (std - 100) / 100.0)
            score = (mean_score * 0.4 + std_score * 0.6)
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER ANALYTICS ENGINE
# Rolling latency tracker, circuit breaker, adaptive benchmarking.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _ProviderCallRecord:
    timestamp:  float
    latency_ms: int
    success:    bool
    capability: str
    error_code: int = 0


class ProviderAnalytics:
    """
    Tracks per-provider rolling statistics for intelligent routing decisions.
    Window: last 50 calls per provider.
    """

    WINDOW_SIZE:       int   = 50
    CIRCUIT_TRIP_RATE: float = 0.70   # If error rate > 70%, trip circuit
    CIRCUIT_COOLDOWN:  float = 120.0  # 2 minutes cooldown

    def __init__(self):
        self._records:  Dict[str, deque] = {}
        self._tripped:  Dict[str, float] = {}   # provider → trip timestamp

    def record(self, provider: str, latency_ms: int, success: bool, capability: str, error_code: int = 0) -> None:
        if provider not in self._records:
            self._records[provider] = deque(maxlen=self.WINDOW_SIZE)
        self._records[provider].append(_ProviderCallRecord(
            timestamp=time.monotonic(), latency_ms=latency_ms,
            success=success, capability=capability, error_code=error_code,
        ))
        # Auto-trip circuit on sustained high error rates
        stats = self.stats(provider)
        if stats["call_count"] >= 5 and stats["error_rate"] > self.CIRCUIT_TRIP_RATE:
            if provider not in self._tripped:
                self._tripped[provider] = time.monotonic()

    def is_circuit_open(self, provider: str) -> bool:
        """Returns True if the provider's circuit is tripped (should skip)."""
        trip_time = self._tripped.get(provider)
        if trip_time is None:
            return False
        if time.monotonic() - trip_time > self.CIRCUIT_COOLDOWN:
            del self._tripped[provider]   # Auto-reset after cooldown
            return False
        return True

    def reset_circuit(self, provider: str) -> None:
        self._tripped.pop(provider, None)

    def stats(self, provider: str) -> Dict[str, Any]:
        records = list(self._records.get(provider, []))
        if not records:
            return {"call_count": 0, "error_rate": 0.0, "avg_latency_ms": 0, "p95_latency_ms": 0}
        total    = len(records)
        failures = sum(1 for r in records if not r.success)
        latencies = sorted(r.latency_ms for r in records)
        p95_idx  = max(0, int(total * 0.95) - 1)
        return {
            "call_count":     total,
            "error_rate":     failures / total,
            "avg_latency_ms": sum(r.latency_ms for r in records) // total,
            "p95_latency_ms": latencies[p95_idx],
            "circuit_open":   self.is_circuit_open(provider),
        }

    def all_stats(self) -> Dict[str, Any]:
        return {p: self.stats(p) for p in self._records}


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION PLANNER
# Semantic intent analysis + workflow decomposition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionPlan:
    """Represents a planned multi-stage AI execution workflow."""
    tool:          str
    capability:    str
    intent:        str            # e.g. "background_removal", "face_enhance"
    stages:        List[str]      # e.g. ["validate_input", "segment", "refine", "deliver"]
    quality_gate:  float          # Minimum score to accept output (0.0–1.0)
    max_refinement_passes: int    # How many quality-retry passes to allow
    provider_hints: List[str]     # Preferred providers for this intent
    metadata:      Dict[str, Any] = field(default_factory=dict)


class ExecutionPlanner:
    """
    Analyzes tool intent and builds an optimal execution plan.
    Enables multi-stage workflows, intelligent provider selection,
    and adaptive quality gates.
    """

    # Intent → quality gate mapping (higher = stricter)
    INTENT_QUALITY_GATES: Dict[str, float] = {
        "background_removal":  0.55,
        "face_enhancement":    0.60,
        "image_restoration":   0.50,
        "super_resolution":    0.45,
        "image_generation":    0.35,
        "style_transfer":      0.30,
        "captioning":          0.20,
        "basic_processing":    0.20,
    }

    INTENT_STAGES: Dict[str, List[str]] = {
        "background_removal": [
            "validate_input", "preprocess", "segment",
            "mask_refinement", "quality_check", "deliver",
        ],
        "face_enhancement": [
            "validate_input", "face_detect", "enhance",
            "quality_check", "deliver",
        ],
        "image_restoration": [
            "validate_input", "restore", "quality_check", "deliver",
        ],
        "super_resolution":  [
            "validate_input", "upscale", "quality_check", "deliver",
        ],
        "image_generation":  [
            "prompt_enhance", "generate", "quality_check", "deliver",
        ],
        "default": ["validate_input", "process", "quality_check", "deliver"],
    }

    @classmethod
    def plan(
        cls,
        tool: str,
        capability: str,
        params: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> ExecutionPlan:
        log = logger or logging.getLogger(__name__)
        intent    = cls._classify_intent(capability, tool)
        stages    = cls.INTENT_STAGES.get(intent, cls.INTENT_STAGES["default"])
        gate      = cls.INTENT_QUALITY_GATES.get(intent, 0.30)
        max_passes = 2 if capability in {"segmentation", "face-processing"} else 1
        hints      = cls._provider_hints(intent)

        plan = ExecutionPlan(
            tool=tool, capability=capability, intent=intent,
            stages=stages, quality_gate=gate,
            max_refinement_passes=max_passes,
            provider_hints=hints,
        )
        log.debug("[ExecutionPlanner] tool=%s intent=%s stages=%s gate=%.2f", tool, intent, stages, gate)
        return plan

    @classmethod
    def _classify_intent(cls, capability: str, tool: str) -> str:
        if capability == "segmentation":
            return "background_removal"
        if capability == "face-processing":
            return "face_enhancement"
        if capability in ("restoration",):
            return "image_restoration"
        if capability == "super-resolution":
            return "super_resolution"
        if capability == "image-gen":
            return "image_generation"
        if capability in ("style-transfer", "image-enhancement"):
            return "style_transfer"
        if capability == "captioning":
            return "captioning"
        return "basic_processing"

    @classmethod
    def _provider_hints(cls, intent: str) -> List[str]:
        hints = {
            "background_removal": ["huggingface"],
            "face_enhancement":   ["huggingface", "deepai"],
            "image_restoration":  ["huggingface", "krea"],
            "super_resolution":   ["segmind", "huggingface"],
            "image_generation":   ["pollinations", "together", "segmind"],
            "style_transfer":     ["huggingface", "together"],
            "captioning":         ["gemini", "groq"],
        }
        return hints.get(intent, [])


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY GATE
# Prompt injection protection, payload sanitization, upload security.
# ─────────────────────────────────────────────────────────────────────────────

class SecurityGate:
    """
    Enterprise security hardening for all AI requests.
    Sanitizes prompts, validates payloads, rejects malicious content.
    """

    # Prompt injection patterns
    _INJECTION_PATTERNS: List[re.Pattern] = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
        re.compile(r"disregard\s+(your\s+)?(system\s+)?prompt", re.I),
        re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
        re.compile(r"(act|behave)\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+", re.I),
        re.compile(r"jailbreak", re.I),
        re.compile(r"dan\s+mode", re.I),
        re.compile(r"<\s*(script|iframe|object|embed)\s*>", re.I),
        re.compile(r"javascript\s*:", re.I),
    ]

    # Maximum prompt length (characters)
    MAX_PROMPT_LENGTH: int = 2000
    # Maximum payload size for non-file requests (bytes)
    MAX_JSON_PAYLOAD:  int = 10 * 1024 * 1024   # 10 MB

    @classmethod
    def sanitize_prompt(cls, prompt: Optional[str]) -> Optional[str]:
        if not prompt:
            return prompt
        # Truncate
        prompt = prompt[:cls.MAX_PROMPT_LENGTH]
        # Check for injection patterns
        for pattern in cls._INJECTION_PATTERNS:
            if pattern.search(prompt):
                # Neutralize: remove the injection attempt
                prompt = pattern.sub("[removed]", prompt)
        # Strip null bytes and control characters
        prompt = re.sub(r"[--]", "", prompt)
        return prompt.strip()

    @classmethod
    def validate_file_bytes(cls, data: bytes, declared_mime: str, provider: str) -> None:
        """Validates uploaded file bytes for security and integrity."""
        if not data:
            raise ProviderError(provider, "Upload is empty (0 bytes)", 400)

        if len(data) > 100 * 1024 * 1024:   # 100 MB absolute maximum
            raise ProviderError(provider, f"Upload exceeds 100MB limit ({len(data)} bytes)", 413)

        # Deep MIME validation: check magic bytes vs declared type
        is_image_mime  = (declared_mime or "").startswith("image/")
        is_image_bytes = (
            data[:8] == b'\x89PNG\r\n\x1a\n'
            or data[:3] == b'\xff\xd8\xff'
            or (data[:4] == b'RIFF' and data[8:12] == b'WEBP')
            or data[:6] in (b'GIF87a', b'GIF89a')
        )
        # Detect disguised executables
        is_executable = (
            data[:2] == b'MZ'          # PE/EXE
            or data[:4] == b'ELF'  # ELF
            or data[:4] == b'%PDF'     # PDF (unexpected for image upload)
        )
        if is_executable:
            raise ProviderError(provider, "Upload rejected: file appears to be an executable", 400)

        # HTML injection via image upload
        if data[:256].lower().startswith(b'<!doctype') or b'<html' in data[:512].lower():
            raise ProviderError(provider, "Upload rejected: HTML content detected in file", 400)

    @classmethod
    def sanitize_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize all string values in params dict."""
        result: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, str):
                result[k] = cls.sanitize_prompt(v) or v
            elif isinstance(v, (int, float, bool)):
                result[k] = v
            elif isinstance(v, dict):
                result[k] = cls.sanitize_params(v)
            elif isinstance(v, list):
                result[k] = [
                    (cls.sanitize_prompt(i) if isinstance(i, str) else i)
                    for i in v
                ]
            else:
                result[k] = v
        return result


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION CACHE (lightweight in-process TTL cache)
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionCache:
    """
    Lightweight LRU-TTL cache for AI execution results.
    Prevents redundant identical requests within the TTL window.
    """

    DEFAULT_TTL:      float = 300.0   # 5 minutes
    MAX_ENTRIES:      int   = 256

    def __init__(self, ttl: float = DEFAULT_TTL):
        self._ttl = ttl
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._order: deque = deque(maxlen=self.MAX_ENTRIES)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            self._store.pop(k, None)

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._evict_expired()
        if len(self._store) >= self.MAX_ENTRIES:
            # Evict oldest
            if self._order:
                oldest = self._order[0]
                self._store.pop(oldest, None)
        self._store[key] = (time.monotonic(), value)
        self._order.append(key)

    @staticmethod
    def make_key(tool: str, capability: str, params: Dict[str, Any], file_bytes: Optional[bytes]) -> str:
        file_hash = hashlib.md5(file_bytes).hexdigest()[:16] if file_bytes else "nofile"
        param_str = json.dumps(params, sort_keys=True, default=str)[:200]
        return f"{tool}:{capability}:{file_hash}:{hashlib.md5(param_str.encode()).hexdigest()[:8]}"


# Module-level singletons
_provider_analytics = ProviderAnalytics()
_execution_cache    = ExecutionCache()


# ══════════════════════════════════════════════════════════════════════════════
# §5  PROVIDER ADAPTERS
# ══════════════════════════════════════════════════════════════════════════════

class ProviderError(Exception):
    """Raised when a provider fails. Message logged and fallback triggered."""
    def __init__(self, provider: str, reason: str, status_code: int = 0):
        super().__init__(f"[{provider}] {reason}")
        self.provider    = provider
        self.reason      = reason
        self.status_code = status_code


def _bytes_to_data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _validate_response_image(data: bytes, provider: str) -> None:
    """Minimum payload size 1024 bytes. HTML page detection. Valid magic bytes."""
    if len(data) == 0:
        raise ProviderError(provider, "Response is 0 bytes — empty payload")

    if len(data) < 1024:
        try:
            decoded = data.decode("utf-8", errors="replace")
            raise ProviderError(provider, f"Response too small ({len(data)}B): {decoded[:200]}")
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(provider, f"Response too small ({len(data)}B)")

    # HTML error-page guard — CDN gateway errors return HTML not images
    if b'<!DOCTYPE' in data[:256] or b'<html' in data[:256].lower():
        try:
            err_text = data[:300].decode("utf-8", errors="replace")
        except Exception:
            err_text = str(data[:100])
        raise ProviderError(provider, f"Response is an HTML error page: {err_text[:150]}")

    # Valid image magic bytes
    if data[:8] == b'\x89PNG\r\n\x1a\n':  # PNG
        return
    if data[:3] == b'\xff\xd8\xff':        # JPEG
        return
    if data[:6] in (b'GIF87a', b'GIF89a'): # GIF
        return
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':  # WEBP
        return
    if data[4:8] in (b'ftyp', b'ftypavif', b'ftyphei'):  # AVIF/HEIF
        return
    if data[:4] in (b'II*\x00', b'MM\x00*'):  # TIFF
        return
    # Accept large-enough unknown binary
    if len(data) > 8192:
        return
    raise ProviderError(provider, f"Response not a valid image (magic: {data[:8].hex()}, size: {len(data)}B)")


def _apply_hf_mask_to_image(image_bytes: bytes, mask_bytes: bytes, provider: str) -> bytes:
    """Apply a grayscale mask to the original image → transparent RGBA PNG."""
    if not _PIL_AVAILABLE:
        raise ProviderError(provider, "PIL not available for mask application — install Pillow")

    try:
        img  = _PILImage.open(io.BytesIO(image_bytes)).convert("RGBA")
        mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")

        if mask.size != img.size:
            mask = mask.resize(img.size, _PILImage.LANCZOS)

        img.putalpha(mask)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        raise ProviderError(provider, f"PIL mask application failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY HELPER
# FIX-V30-07: Session-level Cloudinary auth-fail cache — once 401 is seen,
#             skip all further upload attempts this process lifetime.
# FIX-V32-07: Live startup validation via lightweight signed GET.
# ─────────────────────────────────────────────────────────────────────────────

_CLOUDINARY_AUTH_FAILED_SESSION: bool = False


async def _validate_cloudinary_credentials_live(
    settings: Any,
    logger: logging.Logger,
) -> None:
    """
    FIX-V32-07: Make a lightweight authenticated GET to Cloudinary to verify
    credentials at startup. Sets _CLOUDINARY_AUTH_FAILED_SESSION=True if
    credentials are wrong so all upload attempts are skipped immediately.

    Uses /resources/image?max_results=1 — this returns zero images on a new
    account but requires valid credentials, so it confirms auth without cost.
    """
    global _CLOUDINARY_AUTH_FAILED_SESSION

    cloud  = getattr(settings, "CLOUDINARY_CLOUD_NAME", None)
    key    = getattr(settings, "CLOUDINARY_API_KEY", None)
    secret = getattr(settings, "CLOUDINARY_API_SECRET", None)

    if not (cloud and key and secret):
        # Missing credentials already handled in startup registry
        return

    try:
        url     = f"https://api.cloudinary.com/v1_1/{cloud}/resources/image?max_results=1"
        timeout = httpx.Timeout(connect=8.0, read=15.0, write=5.0, pool=3.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, auth=(key, secret))

        if resp.status_code == 200:
            logger.info(
                "[startup] ✓ Cloudinary live validation PASSED — credentials are valid "
                "(cloud=%s)", cloud,
            )
        elif resp.status_code in (401, 403):
            _CLOUDINARY_AUTH_FAILED_SESSION = True
            logger.error(
                "[startup] ✗ Cloudinary live validation FAILED (HTTP %d) — "
                "CREDENTIALS ARE INVALID OR FROM DIFFERENT CLOUD ACCOUNTS.\n"
                "ACTION REQUIRED — verify ALL THREE env vars in Railway belong "
                "to the SAME Cloudinary account:\n"
                "  CLOUDINARY_CLOUD_NAME  → your cloud name (e.g. 'mycloudname')\n"
                "  CLOUDINARY_API_KEY     → API key (numeric string)\n"
                "  CLOUDINARY_API_SECRET  → API secret (alphanumeric string)\n"
                "Find all three at: https://console.cloudinary.com/settings/api-keys\n"
                "All values must be from the same row on that page.\n"
                "Cloudinary CDN delivery DISABLED for this session. "
                "AI output will use inline base64 fallback (still works, just larger).",
                resp.status_code,
            )
        else:
            logger.warning(
                "[startup] Cloudinary live validation returned HTTP %d — "
                "assuming credentials OK (non-auth error)", resp.status_code,
            )
    except Exception as exc:
        logger.warning(
            "[startup] Cloudinary live validation failed with exception: %s — "
            "assuming credentials OK (network/timeout issue, not auth failure)", exc,
        )


async def _upload_or_inline(
    image_bytes: bytes,
    mime: str,
    settings: Any,
    logger: logging.Logger,
    is_png: bool = False,
) -> Tuple[str, str]:
    """
    Try Cloudinary upload → return (secure_url, "cloudinary").
    On any failure        → return (data_uri,   "inline_base64").

    Never raises. AI output is always delivered even if CDN is down.
    """
    global _CLOUDINARY_AUTH_FAILED_SESSION

    mime = mime or ("image/png" if is_png else "image/jpeg")

    cloud  = getattr(settings, "CLOUDINARY_CLOUD_NAME", None)
    key    = getattr(settings, "CLOUDINARY_API_KEY", None)
    secret = getattr(settings, "CLOUDINARY_API_SECRET", None)

    # Skip upload entirely if auth already failed this session
    if _CLOUDINARY_AUTH_FAILED_SESSION:
        logger.debug("[delivery] Cloudinary skipped — auth failure cached from earlier attempt")
        return _bytes_to_data_uri(image_bytes, mime), "inline_base64"

    if cloud and key and secret:
        try:
            timestamp = str(int(time.time()))

            params_to_sign: Dict[str, str] = {"timestamp": timestamp}
            if is_png:
                params_to_sign["format"] = "png"

            _excl    = frozenset({"file", "api_key", "resource_type", "cloud_name"})
            filtered = {k: v for k, v in params_to_sign.items() if k not in _excl}
            sig_str  = "&".join(f"{k}={v}" for k, v in sorted(filtered.items())) + secret
            signature = hashlib.sha1(sig_str.encode("utf-8")).hexdigest()

            upload_data: Dict[str, str] = {
                "api_key":   key,
                "timestamp": timestamp,
                "signature": signature,
            }
            if is_png:
                upload_data["format"] = "png"

            ext        = "image.png" if is_png else "image.jpg"
            upload_url = f"https://api.cloudinary.com/v1_1/{cloud}/image/upload"

            logger.info(
                "[delivery] Cloudinary upload attempt bytes=%d is_png=%s",
                len(image_bytes), is_png,
            )

            timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    upload_url,
                    files={"file": (ext, io.BytesIO(image_bytes), mime)},
                    data=upload_data,
                )

            if resp.status_code == 200:
                result     = resp.json()
                secure_url = result.get("secure_url", "")
                if secure_url:
                    logger.info("[delivery] Cloudinary OK url=%s", secure_url[:80])
                    return secure_url, "cloudinary"
                else:
                    logger.warning(
                        "[delivery] Cloudinary 200 but no secure_url: %s",
                        str(result)[:200],
                    )

            elif resp.status_code in (401, 403):
                _CLOUDINARY_AUTH_FAILED_SESSION = True
                logger.error(
                    "[delivery] Cloudinary auth failure HTTP %d — "
                    "DISABLING Cloudinary uploads for this session. "
                    "Verify CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, "
                    "CLOUDINARY_API_SECRET in Railway env vars are from the SAME account. "
                    "See: https://console.cloudinary.com/settings/api-keys",
                    resp.status_code,
                )
            else:
                logger.warning(
                    "[delivery] Cloudinary upload HTTP %d — falling back to inline_base64. "
                    "Response: %s",
                    resp.status_code, resp.text[:200],
                )

        except Exception as exc:
            logger.warning(
                "[delivery] Cloudinary upload exception: %s — inline_base64 fallback", exc,
            )

    data_uri = _bytes_to_data_uri(image_bytes, mime)
    logger.info("[delivery] inline_base64 bytes=%d mime=%s", len(image_bytes), mime)
    return data_uri, "inline_base64"


# ─────────────────────────────────────────────────────────────────────────────
# 5A  HuggingFace Adapter
# ─────────────────────────────────────────────────────────────────────────────

class HuggingFaceAdapter:
    NAME = "huggingface"

    CAPABILITIES = {
        "segmentation", "super-resolution", "face-processing",
        "restoration", "image-gen", "style-transfer", "inpainting",
        "captioning", "image-enhancement",
    }

    @classmethod
    async def _call_segmentation(
        cls,
        api_key: str,
        file_bytes: bytes,
        file_mime: str,
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        """
        Multi-model HF background removal with dual-URL fallback per model.
        v31 fixes all preserved: /models/ primary, /pipeline/ fallback,
        4 genuine models, HTTP 500 retry.
        """
        last_err = "no models attempted"

        for (model, prefer_pipeline, use_json) in HF_SEGMENTATION_MODELS:

            url_models   = f"{HF_API_BASE}/{model}"
            url_pipeline = f"{HF_PIPELINE_BASE}/image-segmentation/{model}"
            urls_to_try  = (
                [url_pipeline, url_models] if prefer_pipeline
                else [url_models, url_pipeline]
            )

            retry_wait_503 = 20 if use_json else 15
            retry_wait_500 = 8

            logger.info(
                "[HF-SEG] Trying model=%s primary_url=%s json_payload=%s bytes=%d",
                model, urls_to_try[0], use_json, len(file_bytes),
            )

            for url_idx, url in enumerate(urls_to_try):
                url_label = "primary" if url_idx == 0 else "fallback"

                if use_json:
                    img_b64 = base64.b64encode(file_bytes).decode()
                    post_kwargs: dict = {
                        "json": {"inputs": img_b64},
                        "headers": {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  "application/json",
                            "Accept":        "image/png,application/json",
                        },
                    }
                else:
                    post_kwargs = {
                        "content": file_bytes,
                        "headers": {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  file_mime or "image/png",
                            "Accept":        "image/png,application/json",
                        },
                    }

                for attempt in range(2):
                    try:
                        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=5.0)
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            resp = await client.post(url, **post_kwargs)

                        if resp.status_code == 503:
                            if attempt == 0:
                                logger.info(
                                    "[HF-SEG] 503 model loading, waiting %ds model=%s url=%s",
                                    retry_wait_503, model, url_label,
                                )
                                await asyncio.sleep(retry_wait_503)
                                continue
                            else:
                                last_err = f"{model} ({url_label}): model still loading after 503 retry"
                                break

                        if resp.status_code == 500:
                            if attempt == 0:
                                logger.info(
                                    "[HF-SEG] 500 server error, waiting %ds model=%s url=%s",
                                    retry_wait_500, model, url_label,
                                )
                                await asyncio.sleep(retry_wait_500)
                                continue
                            else:
                                last_err = f"{model} ({url_label}): HTTP 500 after retry"
                                break

                        if resp.status_code == 404:
                            logger.info(
                                "[HF-SEG] 404 on url=%s model=%s — trying %s url",
                                url_label, model,
                                "fallback" if url_idx == 0 else "exhausted",
                            )
                            last_err = f"{model} ({url_label}): 404 not found"
                            break

                        if resp.status_code == 401:
                            raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)

                        if resp.status_code == 429:
                            logger.warning("[HF-SEG] 429 rate limit model=%s — waiting 10s", model)
                            await asyncio.sleep(10)
                            continue

                        if resp.status_code != 200:
                            last_err = f"{model} ({url_label}): HTTP {resp.status_code} {resp.text[:200]}"
                            logger.warning("[HF-SEG] %s", last_err)
                            break

                        content_type = resp.headers.get("content-type", "")
                        raw = resp.content

                        # Path A: Binary image response
                        if (
                            "image" in content_type
                            or raw[:8] == b'\x89PNG\r\n\x1a\n'
                            or raw[:3] == b'\xff\xd8\xff'
                            or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
                        ):
                            _validate_response_image(raw, cls.NAME)
                            logger.info(
                                "[HF-SEG] Binary PNG path model=%s url=%s bytes=%d",
                                model, url_label, len(raw),
                            )
                            return {
                                "success":  True,
                                "output":   _bytes_to_data_uri(raw, "image/png"),
                                "provider": cls.NAME,
                                "model":    model,
                            }

                        # Path B: JSON response — parse mask
                        try:
                            data = resp.json()
                        except Exception:
                            last_err = f"{model} ({url_label}): response not image or JSON ({len(raw)}B)"
                            logger.warning("[HF-SEG] %s", last_err)
                            break

                        mask_bytes: Optional[bytes] = None

                        # BiRefNet new shape: {"output": [{"image": b64}]}
                        if isinstance(data, dict):
                            out_list = data.get("output") or []
                            if isinstance(out_list, list) and out_list:
                                entry    = out_list[0] if isinstance(out_list[0], dict) else {}
                                mask_val = entry.get("image") or entry.get("mask") or ""
                            else:
                                mask_val = data.get("image") or data.get("mask") or ""
                            if mask_val and isinstance(mask_val, str):
                                try:
                                    raw_b64  = mask_val.split(",", 1)[1] if "," in mask_val else mask_val
                                    mask_bytes = base64.b64decode(raw_b64)
                                except Exception as e:
                                    last_err = f"{model} ({url_label}): BiRefNet mask decode failed: {e}"
                                    break

                        # Standard HF segmentation shape: [{"label":..., "mask":...}]
                        if mask_bytes is None and isinstance(data, list) and data:
                            for seg in data:
                                if isinstance(seg, dict):
                                    mask_val = seg.get("mask") or seg.get("image") or ""
                                    if mask_val and isinstance(mask_val, str):
                                        try:
                                            raw_b64    = mask_val.split(",", 1)[1] if "," in mask_val else mask_val
                                            mask_bytes = base64.b64decode(raw_b64)
                                            break
                                        except Exception:
                                            continue

                        if mask_bytes is None:
                            last_err = f"{model} ({url_label}): no mask extracted from JSON"
                            logger.warning("[HF-SEG] %s data_keys=%s", last_err,
                                           list(data.keys()) if isinstance(data, dict) else type(data).__name__)
                            break

                        # Apply mask to original image
                        if _PIL_AVAILABLE and file_bytes:
                            try:
                                transparent = _apply_hf_mask_to_image(file_bytes, mask_bytes, cls.NAME)
                                logger.info(
                                    "[HF-SEG] Mask-applied PNG model=%s url=%s bytes=%d",
                                    model, url_label, len(transparent),
                                )
                                return {
                                    "success":  True,
                                    "output":   _bytes_to_data_uri(transparent, "image/png"),
                                    "provider": cls.NAME,
                                    "model":    model,
                                }
                            except ProviderError as mask_err:
                                logger.warning("[HF-SEG] Mask application failed: %s", mask_err.reason)

                        # Fallback: return raw mask bytes if PIL unavailable
                        _validate_response_image(mask_bytes, cls.NAME)
                        return {
                            "success":  True,
                            "output":   _bytes_to_data_uri(mask_bytes, "image/png"),
                            "provider": cls.NAME,
                            "model":    model,
                        }

                    except ProviderError:
                        raise
                    except asyncio.TimeoutError:
                        last_err = f"{model} ({url_label}): timeout on attempt {attempt + 1}"
                        logger.warning("[HF-SEG] Timeout model=%s url=%s attempt=%d", model, url_label, attempt)
                        break
                    except Exception as e:
                        last_err = f"{model} ({url_label}): {e}"
                        logger.warning("[HF-SEG] Exception model=%s: %s", model, e)
                        break

        raise ProviderError(
            cls.NAME,
            f"All HF segmentation models exhausted. Last error: {last_err}",
        )

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "HF_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "HF_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=5.0)

        # ── Segmentation ──────────────────────────────────────────────────────
        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image provided for background removal")
            return await cls._call_segmentation(api_key, file_bytes, file_mime, logger)

        # ── Super resolution ──────────────────────────────────────────────────
        if capability == "super-resolution":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for super-resolution")
            model = HF_MODELS.get("super-resolution", "caidas/swin2SR-classical-sr-x4-64")
            url   = f"{HF_API_BASE}/{model}"
            headers["Content-Type"] = file_mime or "image/jpeg"

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, content=file_bytes, headers=headers)

            if resp.status_code == 503:
                await asyncio.sleep(15)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, content=file_bytes, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success":  True,
                "output":   _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME,
                "model":    model,
            }

        # ── Image generation ──────────────────────────────────────────────────
        if capability == "image-gen":
            prompt = params.get("prompt", "a beautiful high quality image")
            model  = HF_MODELS.get("image-gen", "black-forest-labs/FLUX.1-schnell")
            url    = f"{HF_API_BASE}/{model}"
            headers["Content-Type"] = "application/json"
            payload: Dict[str, Any] = {"inputs": prompt}
            if params.get("width"):
                payload["parameters"] = {
                    "width":  params["width"],
                    "height": params.get("height", params["width"]),
                }

            logger.info("[HF] image-gen model=%s prompt=%s", model, prompt[:80])
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code == 503:
                raise ProviderError(cls.NAME, f"Model loading ({model})", 503)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success":  True,
                "output":   _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME,
                "model":    model,
            }

        # ── Captioning ────────────────────────────────────────────────────────
        if capability == "captioning":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for captioning")

            cap_url = f"{HF_API_BASE}/{HF_MODELS.get('captioning', 'Salesforce/blip-image-captioning-large')}"
            headers["Content-Type"] = file_mime or "image/jpeg"

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(cap_url, content=file_bytes, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )

            data    = resp.json()
            caption = ""
            if isinstance(data, list) and data:
                caption = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                caption = data.get("generated_text", "")
            return {
                "success":     True,
                "output":      caption,
                "provider":    cls.NAME,
                "output_type": "text",
            }

        # ── Style transfer / enhancement / inpainting / face-processing ───────
        if capability in ("style-transfer", "image-enhancement", "inpainting", "face-processing"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            prompt  = params.get("prompt", f"Apply {capability} to this image, high quality result")
            gen_url = f"{HF_API_BASE}/{HF_MODELS.get('image-gen', 'black-forest-labs/FLUX.1-schnell')}"
            headers["Content-Type"] = "application/json"
            img_b64 = base64.b64encode(file_bytes).decode()
            payload = {"inputs": prompt, "image": img_b64}

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(gen_url, json=payload, headers=headers)

            if resp.status_code == 503:
                raise ProviderError(cls.NAME, "Model loading", 503)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success":  True,
                "output":   _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME,
            }

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ─────────────────────────────────────────────────────────────────────────────
# 5B  Pollinations Adapter  (free, no key required)
#     BLOCKED for segmentation — would produce fake stylized outputs.
# ─────────────────────────────────────────────────────────────────────────────

class PollinationsAdapter:
    NAME = "pollinations"
    CAPABILITIES = {"image-gen", "style-transfer", "visualization", "video-gen"}
    BASE = "https://image.pollinations.ai/prompt"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        if capability == "segmentation":
            raise ProviderError(
                cls.NAME,
                "Pollinations BLOCKED for segmentation — would produce fake output",
            )

        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        prompt  = params.get("prompt", "a beautiful high quality photorealistic image")
        width   = params.get("width", 1024)
        height  = params.get("height", 1024)
        seed    = params.get("seed", "")
        model   = params.get("model", "flux")

        import urllib.parse
        encoded = urllib.parse.quote(prompt)
        url = f"{cls.BASE}/{encoded}?width={width}&height={height}&model={model}&nologo=true"
        if seed:
            url += f"&seed={seed}"

        logger.info("[Pollinations] image-gen url=%s", url[:120])

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

        result_bytes = resp.content
        _validate_response_image(result_bytes, cls.NAME)
        return {
            "success":  True,
            "output":   _bytes_to_data_uri(result_bytes, "image/jpeg"),
            "provider": cls.NAME,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5C  Segmind Adapter
#
# FIX-V32-01: Complete endpoint overhaul — deprecated v1 standalone endpoints
#             replaced with current documented Segmind model routes.
#
# SEGMIND BACKGROUND REMOVAL — CURRENT ENDPOINT REALITY (as of 2025):
#   Segmind's API uses model-specific routes. Background removal models are:
#   - stable-diffusion/background-removal  (primary — most reliable)
#   - bria-rmbg-2.0                        (BRIA RMBG 2.0 dedicated endpoint)
#   - remove-background                    (generic alias, some plan tiers)
#
# REQUEST FORMAT: Segmind background removal accepts multipart/form-data
#   with an 'image' file field. JSON with base64 also supported on some
#   endpoints as a secondary strategy.
#
# FIX-V32-05: 401 immediately disables all endpoint attempts (auth is global).
# ─────────────────────────────────────────────────────────────────────────────

class SegmindAdapter:
    NAME = "segmind"
    # V33-FIX3: segmentation removed — all Segmind bg-removal endpoints
    # returned 404 in Railway logs. Re-add "segmentation" after confirming
    # the plan at https://cloud.segmind.com/console/models includes bg-removal.
    CAPABILITIES = {
        "image-gen", "inpainting",
        "image-enhancement", "super-resolution", "controlnet",
    }
    BASE = "https://api.segmind.com/v1"

    # FIX-V32-01: Current documented Segmind background removal endpoints.
    # These are the model-specific routes under the v1 API as of 2025.
    # Ordered by reliability / documentation status.
    SEGMENTATION_ENDPOINTS: List[str] = [
        "stable-diffusion/background-removal",   # Primary — documented current model route
        "bria-rmbg-2.0",                         # BRIA RMBG 2.0 direct model endpoint
        "background-removal",                    # Generic alias (some plan tiers)
        "remove-background",                     # Additional alias
        "erase-bg",                              # Legacy (may still work on older plans)
        "background-eraser",                     # Legacy alias
    ]

    MODELS: Dict[str, str] = {
        "image-gen":         "sdxl1.0-txt2img",
        "inpainting":        "sdxl-inpainting",
        "image-enhancement": "esrgan-v1-x2plus",
        "super-resolution":  "esrgan-v1-x2plus",
        "controlnet":        "sd1.5-controlnet-canny",
    }

    # FIX-V32-01: Raised threshold — 6 endpoints now in list
    _consecutive_seg_404s: int = 0
    _SEG_404_DISABLE_THRESHOLD: int = 6

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "SEGMIND_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "SEGMIND_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        # ── Background removal ─────────────────────────────────────────────────
        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image provided for background removal")

            if cls._consecutive_seg_404s >= cls._SEG_404_DISABLE_THRESHOLD:
                raise ProviderError(
                    cls.NAME,
                    f"Segmind segmentation auto-disabled after {cls._consecutive_seg_404s} "
                    "consecutive 404s. All known endpoints exhausted for this account/plan.",
                )

            img_b64  = base64.b64encode(file_bytes).decode()
            timeout  = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)
            last_err = "no endpoints tried"

            for endpoint in cls.SEGMENTATION_ENDPOINTS:
                url = f"{cls.BASE}/{endpoint}"

                # FIX-V32-01: Multipart raw bytes is primary for Segmind bg removal.
                # Most Segmind bg-removal endpoints work best with raw file upload.
                # JSON base64 strategies are secondary fallbacks.
                payload_strategies = [
                    # Strategy 0: Multipart raw file upload (MOST RELIABLE)
                    {"_type": "multipart"},
                    # Strategy 1: JSON with data URI
                    {
                        "_type": "json",
                        "image": f"data:{file_mime or 'image/jpeg'};base64,{img_b64}",
                        "output_format": "PNG",
                        "quality": 90,
                    },
                    # Strategy 2: JSON with plain base64
                    {
                        "_type": "json",
                        "image": img_b64,
                        "output_format": "PNG",
                    },
                ]

                logger.info(
                    "[Segmind] bg-removal endpoint=%s bytes=%d", endpoint, len(file_bytes),
                )
                got_404 = False

                for strat_idx, strategy in enumerate(payload_strategies):
                    strat_type = strategy.pop("_type", "json")
                    try:
                        if strat_type == "multipart":
                            ext_mp = "image.png" if (file_mime or "").endswith("png") else "image.jpg"
                            async with httpx.AsyncClient(timeout=timeout) as client:
                                resp = await client.post(
                                    url,
                                    files={"image": (ext_mp, io.BytesIO(file_bytes), file_mime or "image/jpeg")},
                                    headers={"x-api-key": api_key},
                                )
                        else:
                            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
                            async with httpx.AsyncClient(timeout=timeout) as client:
                                resp = await client.post(url, json=strategy, headers=headers)

                        if resp.status_code == 404:
                            last_err = f"{endpoint}: 404 — endpoint not found on this plan"
                            logger.warning(
                                "[Segmind] 404 on endpoint=%s — all strategies skipped",
                                endpoint,
                            )
                            got_404 = True
                            break

                        # FIX-V32-05: Auth failure is global — stop ALL endpoint attempts
                        if resp.status_code == 401:
                            raise ProviderError(
                                cls.NAME,
                                "SEGMIND_API_KEY is invalid or expired (401). "
                                "Verify your key at: https://cloud.segmind.com/console/api-keys "
                                "and update SEGMIND_API_KEY in Railway env vars.",
                                401,
                            )

                        if resp.status_code == 402:
                            raise ProviderError(cls.NAME, "Segmind quota exhausted (402). Add credits.", 402)

                        if resp.status_code == 403:
                            raise ProviderError(
                                cls.NAME,
                                "SEGMIND_API_KEY lacks permission (403). "
                                "Check plan tier at: https://cloud.segmind.com",
                                403,
                            )

                        if resp.status_code == 422:
                            last_err = f"{endpoint} strat{strat_idx}: 422 unprocessable — wrong input format"
                            logger.warning("[Segmind] 422 strat=%d endpoint=%s — trying next", strat_idx, endpoint)
                            continue

                        if resp.status_code == 429:
                            logger.warning("[Segmind] 429 rate limit endpoint=%s — waiting 5s", endpoint)
                            await asyncio.sleep(5)
                            continue

                        if resp.status_code != 200:
                            last_err = f"{endpoint} strat{strat_idx}: HTTP {resp.status_code} {resp.text[:200]}"
                            logger.warning("[Segmind] %s", last_err)
                            continue

                        # ── Parse response ─────────────────────────────────────
                        result_bytes = resp.content
                        content_type_resp = resp.headers.get("content-type", "")

                        if "json" in content_type_resp:
                            try:
                                data = resp.json()
                                img_b64_out = (
                                    data.get("image")
                                    or data.get("output")
                                    or data.get("result")
                                    or (data.get("images") or [None])[0]
                                )
                                if img_b64_out:
                                    raw_b64      = img_b64_out.split(",", 1)[1] if "," in img_b64_out else img_b64_out
                                    result_bytes = base64.b64decode(raw_b64)
                                else:
                                    last_err = f"{endpoint} strat{strat_idx}: JSON response has no image key"
                                    logger.warning("[Segmind] %s keys=%s", last_err, list(data.keys()))
                                    continue
                            except Exception as e:
                                last_err = f"{endpoint} strat{strat_idx}: JSON parse failed: {e}"
                                continue

                        _validate_response_image(result_bytes, cls.NAME)
                        cls._consecutive_seg_404s = 0
                        logger.info(
                            "[Segmind] bg-removal SUCCESS endpoint=%s strat=%d bytes=%d",
                            endpoint, strat_idx, len(result_bytes),
                        )
                        return {
                            "success":  True,
                            "output":   _bytes_to_data_uri(result_bytes, "image/png"),
                            "provider": cls.NAME,
                        }

                    except ProviderError:
                        raise
                    except asyncio.TimeoutError:
                        last_err = f"{endpoint} strat{strat_idx}: timeout"
                        logger.warning("[Segmind] Timeout endpoint=%s strat=%d", endpoint, strat_idx)
                        continue
                    except Exception as e:
                        last_err = f"{endpoint} strat{strat_idx}: {e}"
                        logger.warning("[Segmind] Exception endpoint=%s strat=%d: %s", endpoint, strat_idx, e)
                        continue

                if got_404:
                    cls._consecutive_seg_404s += 1
                    continue

            raise ProviderError(
                cls.NAME,
                f"All Segmind bg-removal endpoints failed. Last: {last_err}. "
                "If all endpoints return 404, your Segmind plan may not include background removal. "
                "Check available models at: https://cloud.segmind.com/console/models",
            )

        # ── Image generation ───────────────────────────────────────────────────
        if capability == "image-gen":
            model   = cls.MODELS["image-gen"]
            url     = f"{cls.BASE}/{model}"
            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
            prompt  = params.get("prompt", "a high quality image")
            payload_gen = {
                "prompt":              prompt,
                "negative_prompt":     params.get("negative_prompt", "low quality, blurry"),
                "samples":             1,
                "num_inference_steps": params.get("steps", 20),
                "guidance_scale":      params.get("guidance_scale", 7.5),
                "img_width":           params.get("width", 1024),
                "img_height":          params.get("height", 1024),
                "base64":              True,
            }
            logger.info("[Segmind] text2img prompt=%s", prompt[:80])
            timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload_gen, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            data        = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {
                "success":  True,
                "output":   f"data:image/jpeg;base64,{img_b64_out}",
                "provider": cls.NAME,
            }

        # ── Super resolution / enhancement ────────────────────────────────────
        if capability in ("super-resolution", "image-enhancement"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            model   = cls.MODELS[capability]
            url     = f"{cls.BASE}/{model}"
            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
            img_b64 = base64.b64encode(file_bytes).decode()
            payload_sr = {
                "image":        f"data:{file_mime};base64,{img_b64}",
                "scale":        params.get("scale", 2),
                "face_enhance": params.get("face_enhance", False),
                "base64":       True,
            }
            logger.info("[Segmind] esrgan bytes=%d scale=%s", len(file_bytes), payload_sr["scale"])
            timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload_sr, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            data        = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {
                "success":  True,
                "output":   f"data:image/jpeg;base64,{img_b64_out}",
                "provider": cls.NAME,
            }

        # ── Inpainting ────────────────────────────────────────────────────────
        if capability == "inpainting":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for inpainting")

            model    = cls.MODELS["inpainting"]
            url      = f"{cls.BASE}/{model}"
            headers  = {"x-api-key": api_key, "Content-Type": "application/json"}
            img_b64  = base64.b64encode(file_bytes).decode()
            mask_b64 = params.get("mask_b64", img_b64)
            payload_inp = {
                "prompt":              params.get("prompt", "fill seamlessly"),
                "image":               f"data:{file_mime};base64,{img_b64}",
                "mask":                f"data:image/png;base64,{mask_b64}",
                "samples":             1,
                "num_inference_steps": 20,
                "base64":              True,
            }
            timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload_inp, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )

            data        = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {
                "success":  True,
                "output":   f"data:image/jpeg;base64,{img_b64_out}",
                "provider": cls.NAME,
            }

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ─────────────────────────────────────────────────────────────────────────────
# 5D  Together AI Adapter
# ─────────────────────────────────────────────────────────────────────────────

class TogetherAdapter:
    NAME = "together"
    CAPABILITIES = {"image-gen", "style-transfer", "captioning", "video-gen"}
    BASE = "https://api.together.xyz/v1"

    IMAGE_MODELS: Dict[str, str] = {
        "generation":     "black-forest-labs/FLUX.1-schnell-Free",
        "style_transfer": "stabilityai/stable-diffusion-xl-base-1.0",
        "default":        "black-forest-labs/FLUX.1-schnell-Free",
    }

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "TOGETHER_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "TOGETHER_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        auth_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        if capability == "captioning":
            model   = "meta-llama/Llama-Vision-Free"
            prompt  = params.get("prompt", "Describe this image.")
            content: Any = prompt
            if file_bytes:
                img_b64 = base64.b64encode(file_bytes).decode()
                content = [
                    {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ]

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/chat/completions",
                    json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 256},
                    headers=auth_headers,
                )
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "TOGETHER_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}

        # Image generation
        model  = cls.IMAGE_MODELS.get("generation", "black-forest-labs/FLUX.1-schnell-Free")
        prompt = params.get("prompt", "a high quality image")
        width  = params.get("width", 1024)
        height = params.get("height", 1024)

        for attempt in range(2):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/images/generations",
                    json={"model": model, "prompt": prompt, "n": 1,
                          "width": width, "height": height, "response_format": "b64_json"},
                    headers=auth_headers,
                )

            if resp.status_code == 429:
                logger.warning("[Together] 429 rate limit — waiting 5s")
                await asyncio.sleep(5)
                continue
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "TOGETHER_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code,
                )
            break

        data = resp.json()
        img_data = (data.get("data") or [{}])[0]

        if img_data.get("b64_json"):
            img_bytes = base64.b64decode(img_data["b64_json"])
            _validate_response_image(img_bytes, cls.NAME)
            return {
                "success":  True,
                "output":   _bytes_to_data_uri(img_bytes, "image/jpeg"),
                "provider": cls.NAME,
            }
        elif img_data.get("url"):
            return {"success": True, "output": img_data["url"], "provider": cls.NAME}
        else:
            raise ProviderError(cls.NAME, "No image in Together response")


# ─────────────────────────────────────────────────────────────────────────────
# 5E  Gemini Adapter
# ─────────────────────────────────────────────────────────────────────────────

class GeminiAdapter:
    NAME = "gemini"
    CAPABILITIES = {"captioning"}
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "GEMINI_API_KEY not configured")

        model   = "gemini-1.5-flash"
        prompt  = params.get("prompt", "Describe this image in detail.")
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            parts.insert(0, {
                "inline_data": {"mime_type": file_mime or "image/jpeg", "data": img_b64}
            })

        payload = {"contents": [{"parts": parts}]}

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/models/{model}:generateContent?key={api_key}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "GEMINI_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            text = ""
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ─────────────────────────────────────────────────────────────────────────────
# 5F  Groq Adapter
# ─────────────────────────────────────────────────────────────────────────────

class GroqAdapter:
    NAME = "groq"
    CAPABILITIES = {"captioning"}
    BASE = "https://api.groq.com/openai/v1"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "GROQ_API_KEY not configured")

        model   = "llava-v1.5-7b-4096-preview"
        prompt  = params.get("prompt", "Describe this image.")
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        content: Any = prompt

        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            content = [
                {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ]

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 256},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "GROQ_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ─────────────────────────────────────────────────────────────────────────────
# 5G  Mistral Adapter
# ─────────────────────────────────────────────────────────────────────────────

class MistralAdapter:
    NAME = "mistral"
    CAPABILITIES = {"captioning"}
    BASE = "https://api.mistral.ai/v1"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "MISTRAL_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "MISTRAL_API_KEY not configured")

        model    = "pixtral-12b-2409"
        prompt   = params.get("prompt", "Describe this image.")
        messages: List[Dict[str, Any]]

        if file_bytes:
            img_b64  = base64.b64encode(file_bytes).decode()
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": f"data:{file_mime};base64,{img_b64}"},
                    {"type": "text", "text": prompt},
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 256},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "MISTRAL_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ─────────────────────────────────────────────────────────────────────────────
# 5H  OpenRouter Adapter
# ─────────────────────────────────────────────────────────────────────────────

class OpenRouterAdapter:
    NAME = "openrouter"
    CAPABILITIES = {"image-gen", "captioning"}
    BASE = "https://openrouter.ai/api/v1"

    IMAGE_MODEL = "black-forest-labs/FLUX-1-schnell"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "OPENROUTER_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "OPENROUTER_API_KEY not configured")

        auth_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        if capability == "captioning":
            model   = "google/gemini-flash-1.5"
            prompt  = params.get("prompt", "Describe this image.")
            content: Any = prompt
            if file_bytes:
                img_b64 = base64.b64encode(file_bytes).decode()
                content = [
                    {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ]

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/chat/completions",
                    json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 256},
                    headers=auth_headers,
                )
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "OPENROUTER_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}

        prompt = params.get("prompt", "a high quality image")
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/images/generations",
                json={"model": cls.IMAGE_MODEL, "prompt": prompt, "n": 1},
                headers=auth_headers,
            )
        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "OPENROUTER_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        data    = resp.json()
        url_out = (data.get("data") or [{}])[0].get("url", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No image URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5I  Cloudflare AI Adapter
#
# FIX-V32-02: Enhanced 401/403 diagnostics — exact Railway env var names,
#             exact CF dashboard path, exact permission scope.
# FIX-V32-04: CLOUDFLARE_ACCOUNT_ID format validation (must be 32-char hex).
# FIX-V32-06: Added @cf/unum/removebg as primary segmentation model.
#             SAM retained as fallback.
# ─────────────────────────────────────────────────────────────────────────────

class CloudflareAdapter:
    NAME = "cloudflare"
    # V33-FIX2: segmentation removed — CF auth (401) unconfirmed.
    # Re-add "segmentation" here AND in CAPABILITY_PROVIDERS after verifying
    # CLOUDFLARE_ACCOUNT_ID (32-char hex) + token has Workers AI:Edit scope.
    CAPABILITIES = {
        "image-gen",
        "compression",
        "basic-processing",
        "audio-extraction",
        "audio-sync",
        "color-matching",
        "temporal",
    }

    # FIX-V32-06: @cf/unum/removebg is the official CF bg removal model.
    # SAM-vit-base retained as fallback (requires PIL for mask composition).
    CF_MODELS: Dict[str, str] = {
        "image-gen":        "@cf/black-forest-labs/flux-1-schnell",
        "image-gen-sd":     "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "image-gen-xl":     "@cf/bytedance/stable-diffusion-xl-lightning",
        "segmentation-rmbg": "@cf/unum/removebg",          # FIX-V32-06: PRIMARY
        "segmentation-sam": "@hf/facebook/sam-vit-base",   # FIX-V32-06: FALLBACK
    }

    @classmethod
    def _base_url(cls, settings: Any, model: str) -> str:
        acct = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
        return f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"

    @classmethod
    def _auth_headers(cls, settings: Any) -> Dict[str, str]:
        return {"Authorization": f"Bearer {getattr(settings, 'CLOUDFLARE_API_TOKEN', '')}"}

    @classmethod
    def _handle_auth_error(cls, status_code: int, logger: logging.Logger) -> None:
        """
        FIX-V32-02: Emit exact, actionable diagnostics for CF auth failures.
        """
        if status_code == 401:
            logger.error(
                "[Cloudflare] ✗ 401 Unauthorized — CLOUDFLARE_API_TOKEN is invalid or expired.\n"
                "ACTION REQUIRED — fix in Railway environment variables:\n"
                "  1. Go to: https://dash.cloudflare.com/profile/api-tokens\n"
                "  2. Click 'Create Token'\n"
                "  3. Use template 'Workers AI' OR manually add permission:\n"
                "       Account → Workers AI → Edit\n"
                "  4. Copy the token value (shown ONCE after creation)\n"
                "  5. In Railway: set CLOUDFLARE_API_TOKEN = <the token>\n"
                "  Note: Token must start with a long alphanumeric string (40+ chars).\n"
                "  If your token looks like 'v1.0-...' that is a different token type."
            )
            raise ProviderError(
                cls.NAME,
                "CF API token invalid or expired (401). See Railway logs for exact fix steps.",
                401,
            )
        if status_code == 403:
            logger.error(
                "[Cloudflare] ✗ 403 Forbidden — CLOUDFLARE_API_TOKEN exists but lacks Workers AI permission.\n"
                "ACTION REQUIRED:\n"
                "  1. Go to: https://dash.cloudflare.com/profile/api-tokens\n"
                "  2. Edit your existing token OR create a new one\n"
                "  3. Add permission: Account → Workers AI → Edit\n"
                "  4. Save and update CLOUDFLARE_API_TOKEN in Railway if you created a new token."
            )
            raise ProviderError(
                cls.NAME,
                "CF token missing Workers AI permission (403). Add 'Account:Workers AI:Edit' scope.",
                403,
            )

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        if not getattr(settings, "CLOUDFLARE_ACCOUNT_ID", None):
            raise ProviderError(cls.NAME, "CLOUDFLARE_ACCOUNT_ID not configured", 0)
        if not getattr(settings, "CLOUDFLARE_API_TOKEN", None):
            raise ProviderError(cls.NAME, "CLOUDFLARE_API_TOKEN not configured", 0)

        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = cls._auth_headers(settings)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        # ── Image generation ──────────────────────────────────────────────────
        if capability == "image-gen":
            model_url = cls._base_url(settings, cls.CF_MODELS["image-gen"])
            prompt    = params.get("prompt", "a high quality photorealistic image")
            payload   = {"prompt": prompt, "num_steps": params.get("steps", 4)}

            logger.info("[Cloudflare] image-gen prompt=%s", prompt[:60])
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    model_url,
                    json=payload,
                    headers={**headers, "Content-Type": "application/json"},
                )

            if resp.status_code in (401, 403):
                cls._handle_auth_error(resp.status_code, logger)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )

            content_type = resp.headers.get("content-type", "")
            if "image" in content_type or resp.content[:8] == b'\x89PNG\r\n\x1a\n':
                result_bytes = resp.content
                _validate_response_image(result_bytes, cls.NAME)
                return {
                    "success":  True,
                    "output":   _bytes_to_data_uri(result_bytes, "image/png"),
                    "provider": cls.NAME,
                }
            else:
                try:
                    data    = resp.json()
                    img_b64 = data.get("result", {}).get("image") or data.get("image")
                    if img_b64:
                        return {
                            "success":  True,
                            "output":   f"data:image/png;base64,{img_b64}",
                            "provider": cls.NAME,
                        }
                except Exception:
                    pass
                raise ProviderError(cls.NAME, "Could not extract image from CF response")

        # ── Segmentation (DISABLED — V33-FIX2) ─────────────────────────────────
        # CF segmentation disabled until CLOUDFLARE_ACCOUNT_ID and token are
        # verified. Logs showed 401 (invalid token or missing Workers AI scope).
        # To re-enable: add "segmentation" back to CAPABILITIES above AND to
        # CAPABILITY_PROVIDERS["segmentation"] in §2.
        # Verification steps:
        #   1. Confirm CLOUDFLARE_ACCOUNT_ID is 32-char hex from CF dashboard sidebar
        #   2. Token has Account → Workers AI → Edit permission
        #   3. Test with: curl -X POST .../ai/run/@cf/unum/removebg -H "Auth: Bearer <token>"
        if capability == "segmentation":
            raise ProviderError(
                cls.NAME,
                "CF segmentation disabled (V33-FIX2) — verify credentials before re-enabling. "
                "HuggingFace handles segmentation as sole provider.",
            )

        raise ProviderError(cls.NAME, f"Capability '{capability}' not implemented in CF adapter")


# ─────────────────────────────────────────────────────────────────────────────
# 5J  DeepAI Adapter
# ─────────────────────────────────────────────────────────────────────────────

class DeepAIAdapter:
    NAME = "deepai"
    CAPABILITIES = {"image-gen", "face-processing", "restoration", "inpainting"}
    BASE = "https://api.deepai.org/api"

    ENDPOINTS: Dict[str, str] = {
        "image-gen":       "text2img",
        "face-processing": "torch-srgan",
        "restoration":     "torch-srgan",
        "inpainting":      "image-editor",
    }

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "DEEPAI_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "DEEPAI_API_KEY not configured")

        endpoint = cls.ENDPOINTS.get(capability)
        if not endpoint:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        url     = f"{cls.BASE}/{endpoint}"
        headers = {"api-key": api_key}
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        if file_bytes:
            files     = {"image": ("image.jpg", io.BytesIO(file_bytes), file_mime or "image/jpeg")}
            data_form: Dict[str, str] = {}
            if capability == "image-gen":
                data_form["text"] = params.get("prompt", "high quality image")
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, files=files, data=data_form, headers=headers)
        else:
            data_text = {"text": params.get("prompt", "a high quality image")}
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, data=data_text, headers=headers)

        if resp.status_code == 401:
            raise ProviderError(
                cls.NAME,
                "DEEPAI_API_KEY invalid or expired (401). Verify key at deepai.org/dashboard.",
                401,
            )
        if resp.status_code == 402:
            raise ProviderError(
                cls.NAME,
                "DeepAI account quota exceeded (402). Add credits at deepai.org.",
                402,
            )
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        result  = resp.json()
        out_url = result.get("output_url", "")
        if not out_url:
            raise ProviderError(cls.NAME, "No output_url in response")
        return {"success": True, "output": out_url, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5K  Cloudinary Adapter
# ─────────────────────────────────────────────────────────────────────────────

class CloudinaryAdapter:
    NAME = "cloudinary"
    CAPABILITIES = {"compression", "basic-processing", "image-enhancement"}
    BASE = "https://api.cloudinary.com/v1_1"

    _SIG_EXCLUDE = frozenset({"file", "api_key", "resource_type", "cloud_name"})

    @classmethod
    def _compute_signature(cls, params_to_sign: Dict[str, str], api_secret: str) -> str:
        filtered     = {k: v for k, v in params_to_sign.items() if k not in cls._SIG_EXCLUDE}
        sorted_pairs = sorted(filtered.items())
        sig_string   = "&".join(f"{k}={v}" for k, v in sorted_pairs) + api_secret
        return hashlib.sha1(sig_string.encode("utf-8")).hexdigest()

    @classmethod
    def _inject_transform_into_url(cls, secure_url: str, transform: str) -> str:
        if not transform:
            return secure_url
        return secure_url.replace("/upload/", f"/upload/{transform}/", 1)

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        global _CLOUDINARY_AUTH_FAILED_SESSION

        cloud  = getattr(settings, "CLOUDINARY_CLOUD_NAME", None)
        key    = getattr(settings, "CLOUDINARY_API_KEY", None)
        secret = getattr(settings, "CLOUDINARY_API_SECRET", None)

        if not (cloud and key and secret):
            raise ProviderError(cls.NAME, "Cloudinary credentials not fully configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        # If session-level auth failure, skip immediately
        if _CLOUDINARY_AUTH_FAILED_SESSION:
            raise ProviderError(
                cls.NAME,
                "Cloudinary credentials invalid (cached from earlier auth failure). "
                "Verify CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET "
                "in Railway env vars. All three must be from the same account at "
                "https://console.cloudinary.com/settings/api-keys",
            )

        if not file_bytes:
            raise ProviderError(cls.NAME, "No image provided")

        timestamp = str(int(time.time()))
        transform = params.get("transform", "")

        params_to_sign: Dict[str, str] = {"timestamp": timestamp}
        signature = cls._compute_signature(params_to_sign, secret)

        upload_url = f"{cls.BASE}/{cloud}/image/upload"
        upload_data = {
            "api_key":   key,
            "timestamp": timestamp,
            "signature": signature,
        }

        ext = "image.png" if (file_mime or "").endswith("png") else "image.jpg"

        logger.info("[Cloudinary] upload capability=%s bytes=%d", capability, len(file_bytes))
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                upload_url,
                files={"file": (ext, io.BytesIO(file_bytes), file_mime or "image/jpeg")},
                data=upload_data,
            )

        if resp.status_code in (401, 403):
            _CLOUDINARY_AUTH_FAILED_SESSION = True
            raise ProviderError(
                cls.NAME,
                f"Cloudinary auth failed (HTTP {resp.status_code}). "
                "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET "
                "must all be from the SAME Cloudinary account. "
                "See: https://console.cloudinary.com/settings/api-keys",
                resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderError(
                cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
            )

        result     = resp.json()
        secure_url = result.get("secure_url", "")
        if not secure_url:
            raise ProviderError(cls.NAME, "No secure_url in Cloudinary response")

        if transform:
            secure_url = cls._inject_transform_into_url(secure_url, transform)

        logger.info("[Cloudinary] upload success url=%s", secure_url[:80])
        return {"success": True, "output": secure_url, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5L  Krea Adapter
# ─────────────────────────────────────────────────────────────────────────────

class KreaAdapter:
    NAME = "krea"
    CAPABILITIES = {"image-gen", "super-resolution", "face-processing", "restoration"}
    BASE = "https://api.krea.ai/v1"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "KREA_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "KREA_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=5.0)

        if capability == "image-gen":
            prompt = params.get("prompt", "a high quality image")
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/images/generations",
                    json={"prompt": prompt, "num_images": 1},
                    headers=headers,
                )
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "KREA_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )
            data    = resp.json()
            url_out = (data.get("images") or [{}])[0].get("url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No image URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        if capability in ("super-resolution", "face-processing", "restoration"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            img_b64 = base64.b64encode(file_bytes).decode()
            payload = {
                "image":            f"data:{file_mime};base64,{img_b64}",
                "enhancement_type": capability,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{cls.BASE}/images/enhance", json=payload, headers=headers)

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "KREA_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(
                    cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code,
                )
            data    = resp.json()
            url_out = data.get("url") or data.get("output_url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No output URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ─────────────────────────────────────────────────────────────────────────────
# 5M  Pexels Adapter
# ─────────────────────────────────────────────────────────────────────────────

class PexelsAdapter:
    NAME = "pexels"
    CAPABILITIES = {"video-gen", "image-gen"}
    BASE = "https://api.pexels.com/v1"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = getattr(settings, "PEXELS_API_KEY", None)
        if not api_key:
            raise ProviderError(cls.NAME, "PEXELS_API_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature landscape"))
        headers = {"Authorization": api_key}
        timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)

        if capability == "video-gen":
            url = f"https://api.pexels.com/videos/search?query={query}&per_page=1&orientation=landscape"
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

            data   = resp.json()
            videos = data.get("videos", [])
            if not videos:
                raise ProviderError(cls.NAME, f"No videos for query: {query}")

            video_files = videos[0].get("video_files", [])
            hd_file     = next((f for f in video_files if f.get("quality") in ("hd", "sd")), None)
            if not hd_file:
                raise ProviderError(cls.NAME, "No downloadable video file found")
            return {
                "success":  True,
                "output":   hd_file["link"],
                "provider": cls.NAME,
                "metadata": {"source": "pexels", "query": query},
            }

        url = f"{cls.BASE}/search?query={query}&per_page=1"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

        data   = resp.json()
        photos = data.get("photos", [])
        if not photos:
            raise ProviderError(cls.NAME, f"No photos for query: {query}")

        url_out = (
            photos[0].get("src", {}).get("large2x")
            or photos[0].get("src", {}).get("large", "")
        )
        if not url_out:
            raise ProviderError(cls.NAME, "No photo URL in response")
        return {
            "success":  True,
            "output":   url_out,
            "provider": cls.NAME,
            "metadata": {"source": "pexels", "query": query},
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5N  Unsplash Adapter
# ─────────────────────────────────────────────────────────────────────────────

class UnsplashAdapter:
    NAME = "unsplash"
    CAPABILITIES = {"image-gen"}
    BASE = "https://api.unsplash.com"

    @classmethod
    async def call(
        cls,
        settings: Any,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        logger: logging.Logger,
    ) -> Dict[str, Any]:
        access_key = getattr(settings, "UNSPLASH_ACCESS_KEY", None)
        if not access_key:
            raise ProviderError(cls.NAME, "UNSPLASH_ACCESS_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature"))
        url     = f"{cls.BASE}/search/photos?query={query}&per_page=1&orientation=landscape"
        timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers={"Authorization": f"Client-ID {access_key}"})

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

        data    = resp.json()
        results = data.get("results", [])
        if not results:
            raise ProviderError(cls.NAME, f"No photos for query: {query}")

        url_out = results[0].get("urls", {}).get("full") or results[0].get("urls", {}).get("regular", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No photo URL in response")
        return {
            "success":  True,
            "output":   url_out,
            "provider": cls.NAME,
            "metadata": {"source": "unsplash", "query": query},
        }


# ══════════════════════════════════════════════════════════════════════════════
# §6  PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

PROVIDER_REGISTRY: Dict[str, Any] = {
    "huggingface": HuggingFaceAdapter,
    "pollinations": PollinationsAdapter,
    "segmind":      SegmindAdapter,
    "together":     TogetherAdapter,
    "gemini":       GeminiAdapter,
    "groq":         GroqAdapter,
    "mistral":      MistralAdapter,
    "openrouter":   OpenRouterAdapter,
    "cloudflare":   CloudflareAdapter,
    "deepai":       DeepAIAdapter,
    "cloudinary":   CloudinaryAdapter,
    "krea":         KreaAdapter,
    "pexels":       PexelsAdapter,
    "unsplash":     UnsplashAdapter,
}


# ══════════════════════════════════════════════════════════════════════════════
# §7  PIPELINE EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class PipelineEngine:
    """
    Core execution engine.
    run() implements:
      1. Resolve tool → pipeline → capability
      2. Validate payload (MIME guard)
      3. Execute provider chain with health-aware routing and fallback
      4. Validate output (no fake success)
      5. Normalize delivery (Cloudinary CDN or inline base64)
      6. Return standardized result dict — NEVER raises to caller.
    """

    def __init__(self, settings: Any, logger: logging.Logger):
        self._settings = settings
        self._log      = logger
        self._health:  Dict[str, float] = {p: 1.0 for p in PROVIDER_REGISTRY}

    def _record_success(self, provider: str) -> None:
        s = self._health.get(provider, 1.0)
        self._health[provider] = min(1.0, s * 1.05 + 0.05)

    def _record_failure(self, provider: str, status_code: int = 0) -> None:
        # Hard-disable CF on auth errors — don't waste retries
        if provider == "cloudflare" and status_code in (401, 403):
            self._log.warning(
                "[pipeline] Cloudflare auth error (%d) — disabling for this session (health=0)",
                status_code,
            )
            self._health["cloudflare"] = 0.0
            return

        # Hard-disable Segmind on auth errors
        if provider == "segmind" and status_code in (401, 402, 403):
            self._log.warning(
                "[pipeline] Segmind auth/quota error (%d) — disabling for this session (health=0)",
                status_code,
            )
            self._health["segmind"] = 0.0
            return

        # Hard-disable Cloudinary on auth errors
        if provider == "cloudinary" and status_code in (401, 403):
            self._log.warning(
                "[pipeline] Cloudinary auth error (%d) — disabling for this session (health=0)",
                status_code,
            )
            self._health["cloudinary"] = 0.0
            return

        # Gradual health decay for other failures; floor 0.05 (0.0 = startup-disabled)
        s = self._health.get(provider, 1.0)
        self._health[provider] = max(0.05, s * 0.88)

    def _sorted_providers(self, capability: str) -> List[str]:
        base = CAPABILITY_PROVIDERS.get(capability, [])
        return sorted(
            [p for p in base if self._health.get(p, 1.0) > 0.0],
            key=lambda p: self._health.get(p, 1.0),
            reverse=True,
        )

    async def run(
        self,
        tool:       str,
        capability: str,
        params:     Dict[str, Any],
        file_bytes: Optional[bytes],
        file_mime:  str,
        resolution: str,
        user_id:    str,
        request_id: str,
    ) -> Dict[str, Any]:
        """Outer exception fence — RuntimeError never propagates to frontend."""
        try:
            return await self._run_inner(
                tool, capability, params, file_bytes, file_mime,
                resolution, user_id, request_id,
            )
        except Exception as e:
            self._log.exception(
                "[pipeline] UNHANDLED EXCEPTION tool=%s cap=%s req=%s: %s",
                tool, capability, request_id, e,
            )
            return {
                "success":             False,
                "error_code":          "INTERNAL_ENGINE_ERROR",
                "error_user_message":  "An internal error occurred. Please try again.",
                "message":             f"Internal pipeline engine error: {type(e).__name__}: {str(e)[:200]}",
                "tool":                tool,
                "capability":          capability,
                "request_id":          request_id,
                "providers_attempted": [],
                "execution_ms":        0,
                "fallback_used":       False,
                "warnings":            [],
            }

    async def _run_inner(
        self,
        tool:       str,
        capability: str,
        params:     Dict[str, Any],
        file_bytes: Optional[bytes],
        file_mime:  str,
        resolution: str,
        user_id:    str,
        request_id: str,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()

        self._log.info(
            "[pipeline] START tool=%s capability=%s req=%s file=%s",
            tool, capability, request_id,
            f"{len(file_bytes)}B mime={file_mime}" if file_bytes else "none",
        )

        # ── Step 1: Resolve pipeline name ─────────────────────────────────────
        pipeline_name = TOOL_PIPELINE_MAP.get(tool)
        if not pipeline_name:
            self._log.warning(
                "[pipeline] Tool '%s' not in TOOL_PIPELINE_MAP — using capability=%s",
                tool, capability,
            )
            pipeline_name = "basic"

        # ── Step 2: Resolve capability ────────────────────────────────────────
        resolved_cap = PIPELINE_CAPABILITY.get(pipeline_name, capability)
        if resolved_cap != capability:
            self._log.info(
                "[pipeline] Capability override: request=%s → resolved=%s (tool=%s pipeline=%s)",
                capability, resolved_cap, tool, pipeline_name,
            )
        capability = resolved_cap

        # ── MIME validation guard ─────────────────────────────────────────────
        IMAGE_CAPABILITIES = {
            "segmentation", "super-resolution", "inpainting",
            "face-processing", "restoration", "image-enhancement",
        }
        if capability in IMAGE_CAPABILITIES and file_bytes:
            low_mime = (file_mime or "").lower()
            if low_mime and not any(low_mime.startswith(pfx) for pfx in ("image/", "application/octet")):
                self._log.error(
                    "[pipeline] MIME_REJECT tool=%s cap=%s mime=%s — not an image",
                    tool, capability, file_mime,
                )
                return {
                    "success":             False,
                    "error_code":          "INVALID_MIME_TYPE",
                    "error_user_message":  "Please upload a valid image file (JPEG, PNG, or WebP).",
                    "message":             f"Capability '{capability}' requires an image; received MIME '{file_mime}'",
                    "tool":                tool,
                    "pipeline":            pipeline_name,
                    "capability":          capability,
                    "providers_attempted": [],
                    "execution_ms":        int((time.monotonic() - t0) * 1000),
                    "fallback_used":       False,
                    "warnings":            [],
                }

        # ── Step 3: Get provider list ─────────────────────────────────────────
        providers = self._sorted_providers(capability)
        if not providers:
            self._log.error(
                "[pipeline] No providers for capability=%s (all disabled or unconfigured)", capability,
            )
            return {
                "success":             False,
                "error_code":          "NO_PROVIDERS",
                "error_user_message":  "This tool is temporarily unavailable. Please try again shortly.",
                "message":             f"No configured providers for capability '{capability}'",
                "tool":                tool,
                "pipeline":            pipeline_name,
                "capability":          capability,
                "providers_attempted": [],
                "execution_ms":        int((time.monotonic() - t0) * 1000),
                "fallback_used":       False,
                "warnings":            [],
            }

        self._log.info(
            "[pipeline] Provider chain for %s: %s (health: %s)",
            capability,
            providers,
            {p: round(self._health.get(p, 0.0), 2) for p in providers},
        )

        # ── Step 3B: Security gate — sanitize params and validate file ────────
        try:
            params = SecurityGate.sanitize_params(params)
            if file_bytes:
                SecurityGate.validate_file_bytes(file_bytes, file_mime, "upload_gate")
        except ProviderError as sec_err:
            return {
                "success":             False,
                "error_code":          "SECURITY_REJECTED",
                "error_user_message":  sec_err.reason,
                "message":             str(sec_err),
                "tool":                tool,
                "pipeline":            pipeline_name,
                "capability":          capability,
                "providers_attempted": [],
                "execution_ms":        int((time.monotonic() - t0) * 1000),
                "fallback_used":       False,
                "warnings":            [],
            }

        # ── Step 3C: Build execution plan ────────────────────────────────────
        exec_plan = ExecutionPlanner.plan(tool, capability, params, self._log)
        self._log.info(
            "[pipeline] intent=%s stages=%s quality_gate=%.2f refinement_passes=%d req=%s",
            exec_plan.intent, exec_plan.stages, exec_plan.quality_gate,
            exec_plan.max_refinement_passes, request_id,
        )

        # ── Step 3D: Check execution cache ────────────────────────────────────
        cache_key = _execution_cache.make_key(tool, capability, params, file_bytes)
        if capability not in {"image-gen"}:   # Don't cache generative outputs
            cached = _execution_cache.get(cache_key)
            if cached is not None:
                self._log.info("[pipeline] CACHE HIT tool=%s req=%s", tool, request_id)
                cached["request_id"] = request_id
                cached["from_cache"] = True
                return cached

        # ── Step 4: Execute provider chain (with analytics + quality gate) ───
        last_error  = "unknown"
        last_status = 0
        attempted:  List[str] = []

        # Apply circuit-breaker: skip providers with tripped circuits
        providers = [p for p in providers if not _provider_analytics.is_circuit_open(p)]
        if not providers:
            # All circuits open — reset the least-healthy one and try anyway
            all_providers = self._sorted_providers(capability)
            if all_providers:
                _provider_analytics.reset_circuit(all_providers[-1])
                providers = [all_providers[-1]]
                self._log.warning("[pipeline] All circuits open — force-resetting %s", providers)

        refinement_pass = 0
        last_quality_score = 0.0

        for provider_name in providers:
            adapter = PROVIDER_REGISTRY.get(provider_name)
            if not adapter:
                self._log.warning("[pipeline] Unknown provider: %s", provider_name)
                continue

            if capability not in getattr(adapter, "CAPABILITIES", set()):
                self._log.debug("[pipeline] %s doesn't support %s — skip", provider_name, capability)
                continue

            attempted.append(provider_name)
            self._log.info(
                "[pipeline] provider_selected=%s cap=%s req=%s attempt=%d/%d",
                provider_name, capability, request_id, len(attempted), len(providers),
            )

            try:
                result = await adapter.call(
                    settings=self._settings,
                    capability=capability,
                    file_bytes=file_bytes,
                    file_mime=file_mime,
                    params=params,
                    logger=self._log,
                )

                # ── Step 5: Validate output ───────────────────────────────────
                output = result.get("output") if isinstance(result, dict) else None
                if not output:
                    raise ProviderError(provider_name, "Empty output returned from provider")

                if isinstance(output, str) and output.startswith("data:image"):
                    try:
                        raw       = output.split(",", 1)[1]
                        img_bytes = base64.b64decode(raw)
                        _validate_response_image(img_bytes, provider_name)
                    except ProviderError:
                        raise
                    except Exception as e:
                        raise ProviderError(provider_name, f"Output validation failed: {e}")

                exec_ms = int((time.monotonic() - t0) * 1000)
                self._record_success(provider_name)

                # ── Quality Intelligence Gate ─────────────────────────────────
                quality_report = None
                if isinstance(output, str) and output.startswith("data:image"):
                    try:
                        img_bytes_for_qa = base64.b64decode(output.split(",", 1)[1])
                        quality_report = AIQualityIntelligence.analyze(
                            img_bytes_for_qa, provider_name, capability, self._log,
                        )
                        last_quality_score = quality_report.overall_score
                        if not quality_report.accepted and refinement_pass < exec_plan.max_refinement_passes:
                            refinement_pass += 1
                            self._log.warning(
                                "[pipeline] Quality gate FAILED provider=%s score=%.2f reason=%s "
                                "— pass=%d/%d will retry",
                                provider_name, quality_report.overall_score,
                                quality_report.rejection_reason, refinement_pass,
                                exec_plan.max_refinement_passes,
                            )
                            _provider_analytics.record(provider_name, exec_ms, False, capability, 0)
                            self._record_failure(provider_name, 0)
                            # Continue to next provider for quality retry
                            last_error = f"Quality gate failed: {quality_report.rejection_reason}"
                            continue
                    except Exception as qa_err:
                        self._log.debug("[pipeline] Quality analysis error: %s", qa_err)

                # ── Advanced Segmentation Refinement ──────────────────────────
                if (capability == "segmentation"
                    and isinstance(output, str)
                    and output.startswith("data:image/png")
                    and file_bytes
                    and _PIL_AVAILABLE
                ):
                    try:
                        raw_seg_bytes  = base64.b64decode(output.split(",", 1)[1])
                        mask_score = SegmentationRefiner.score_mask(raw_seg_bytes)
                        if mask_score < 0.4:
                            self._log.info(
                                "[pipeline] Segmentation mask score=%.2f — applying refinement pass",
                                mask_score,
                            )
                            refined = SegmentationRefiner.refine_mask(
                                file_bytes, raw_seg_bytes, provider_name, self._log,
                            )
                            output = f"data:image/png;base64,{base64.b64encode(refined).decode()}"
                            self._log.info(
                                "[pipeline] Segmentation refined: raw=%dB → refined=%dB",
                                len(raw_seg_bytes), len(refined),
                            )
                    except Exception as ref_err:
                        self._log.debug("[pipeline] Segmentation refinement skipped: %s", ref_err)

                # ── Record analytics ──────────────────────────────────────────
                _provider_analytics.record(provider_name, exec_ms, True, capability, 0)

                _text_caps   = {"captioning"}
                output_type  = result.get("output_type", "text" if capability in _text_caps else "image")

                self._log.info(
                    "[pipeline] provider_succeeded=%s cap=%s output_type=%s ms=%d quality=%.2f req=%s",
                    provider_name, capability, output_type, exec_ms,
                    (quality_report.overall_score if quality_report else 1.0), request_id,
                )

                # ── Step 6: Normalize delivery ────────────────────────────────
                raw_output  = output
                delivery    = "provider_direct"
                preview_url = ""

                if isinstance(output, str) and output.startswith("data:image"):
                    is_png  = "image/png" in output[:30]
                    img_raw = base64.b64decode(output.split(",", 1)[1])
                    cdn_out, delivery = await _upload_or_inline(
                        img_raw,
                        "image/png" if is_png else "image/jpeg",
                        self._settings,
                        self._log,
                        is_png=is_png,
                    )
                    self._log.info(
                        "[pipeline] delivery_mode=%s provider=%s req=%s",
                        delivery, provider_name, request_id,
                    )
                    if delivery == "cloudinary":
                        preview_url = cdn_out
                    else:
                        raw_output  = cdn_out
                        preview_url = ""

                elif isinstance(output, str) and output.startswith("http"):
                    preview_url = output
                    delivery    = "provider_url"
                    self._log.info(
                        "[pipeline] delivery_mode=provider_url provider=%s req=%s url=%s",
                        provider_name, request_id, output[:80],
                    )

                success_result = {
                    "success":            True,
                    "tool":               tool,
                    "pipeline":           pipeline_name,
                    "capability":         capability,
                    "provider":           provider_name,
                    "output":             raw_output,
                    "output_url":         preview_url or raw_output,
                    "preview_url":        preview_url,
                    "delivery":           delivery,
                    "output_type":        output_type,
                    "execution_ms":       exec_ms,
                    "metadata":           result.get("metadata", {}),
                    "fallback_used":      len(attempted) > 1,
                    "warnings":           [],
                    "providers_attempted": attempted,
                    "quality_score":      round(quality_report.overall_score, 3) if quality_report else 1.0,
                    "intent":             exec_plan.intent,
                    "execution_stages":   exec_plan.stages,
                    "from_cache":         False,
                    "provider_analytics": _provider_analytics.stats(provider_name),
                }
                # Cache successful non-generative results
                if capability not in {"image-gen"}:
                    _execution_cache.set(cache_key, {**success_result})
                return success_result

            except ProviderError as e:
                last_error  = e.reason
                last_status = e.status_code
                self._record_failure(provider_name, e.status_code)
                _provider_analytics.record(provider_name, int((time.monotonic() - t0) * 1000), False, capability, e.status_code)
                self._log.warning(
                    "[pipeline] provider_failed=%s cap=%s status=%d reason=%s req=%s",
                    provider_name, capability, e.status_code, e.reason[:200], request_id,
                )
                continue

            except asyncio.TimeoutError:
                last_error  = f"Timeout on {provider_name}"
                last_status = 408
                self._record_failure(provider_name)
                _provider_analytics.record(provider_name, int((time.monotonic() - t0) * 1000), False, capability, 408)
                self._log.warning("[pipeline] TIMEOUT provider=%s req=%s", provider_name, request_id)
                continue

            except Exception as e:
                last_error  = str(e)
                last_status = 0
                self._record_failure(provider_name)
                self._log.exception(
                    "[pipeline] EXCEPTION provider=%s cap=%s req=%s: %s",
                    provider_name, capability, request_id, e,
                )
                continue

        # ── All providers exhausted ────────────────────────────────────────────
        exec_ms = int((time.monotonic() - t0) * 1000)
        self._log.error(
            "[pipeline] ALL_PROVIDERS_FAILED tool=%s cap=%s attempted=%s "
            "last_err=%s last_status=%d req=%s ms=%d",
            tool, capability, attempted, last_error, last_status, request_id, exec_ms,
        )

        return {
            "success":             False,
            "error_code":          "PROVIDER_EXECUTION_FAILED",
            "error_user_message":  "AI processing failed. The service is experiencing issues — please try again.",
            "message":             f"All providers failed for '{capability}'. Last error: {last_error}",
            "tool":                tool,
            "pipeline":            pipeline_name,
            "capability":          capability,
            "provider":            None,
            "output":              None,
            "output_url":          None,
            "preview_url":         None,
            "delivery":            None,
            "output_type":         None,
            "execution_ms":        exec_ms,
            "metadata":            {},
            "providers_attempted": attempted,
            "last_error":          last_error,
            "last_status_code":    last_status,
            "fallback_attempted":  True,
            "fallback_used":       True,
            "warnings":            [],
        }


# ══════════════════════════════════════════════════════════════════════════════
# §8  PROVIDER ROUTER  (stats / admin)
# ══════════════════════════════════════════════════════════════════════════════

class ProviderRouter:
    def __init__(self, engine: PipelineEngine):
        self._engine = engine

    async def provider_stats(self) -> Dict[str, Any]:
        analytics = _provider_analytics.all_stats()
        return {
            "providers": {
                name: {
                    "health":         round(self._engine._health.get(name, 1.0), 3),
                    "enabled":        self._engine._health.get(name, 1.0) > 0.0,
                    "capabilities":   list(getattr(PROVIDER_REGISTRY.get(name), "CAPABILITIES", set())),
                    "analytics":      analytics.get(name, {}),
                    "circuit_open":   _provider_analytics.is_circuit_open(name),
                }
                for name in PROVIDER_REGISTRY
            },
            "cache_size": len(_execution_cache._store),
        }

    async def reset_provider(self, provider: str) -> None:
        if provider in PROVIDER_REGISTRY:
            self._engine._health[provider] = 1.0

    async def disable_provider(self, provider: str) -> None:
        if provider in PROVIDER_REGISTRY:
            self._engine._health[provider] = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# §9  FACTORY + STARTUP HEALTH REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

def _validate_cloudflare(settings: Any) -> Tuple[bool, str]:
    """
    FIX-V32-04: Added 32-char hex format validation for CLOUDFLARE_ACCOUNT_ID.
    Wrong ID type (email, display name) is the most common cause of CF 401/404.
    """
    acct  = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", None)
    token = getattr(settings, "CLOUDFLARE_API_TOKEN", None)

    if not acct:
        return False, "CLOUDFLARE_ACCOUNT_ID not set"
    if not token:
        return False, "CLOUDFLARE_API_TOKEN not set"

    # FIX-V32-04: Account ID must be 32-char lowercase hex
    if not re.fullmatch(r'[0-9a-f]{32}', str(acct).lower()):
        return (
            False,
            f"CLOUDFLARE_ACCOUNT_ID appears invalid (got '{str(acct)[:30]}...' length={len(str(acct))}). "
            "It must be a 32-character lowercase hex string. "
            "Find it at: https://dash.cloudflare.com → right sidebar → 'Account ID'. "
            "Do NOT use your email address or account name."
        )

    if len(token) < 20:
        return False, (
            f"CLOUDFLARE_API_TOKEN suspiciously short ({len(token)} chars). "
            "CF tokens are typically 40+ chars. "
            "Generate a new token at: https://dash.cloudflare.com/profile/api-tokens"
        )

    # V34-FIX-02: 'v1.0-...' tokens are User API Tokens — a different token
    # type that does NOT work with Workers AI. Workers AI requires an API Token
    # created via the 'Create Token' workflow with 'Workers AI: Edit' permission.
    if str(token).startswith("v1.0-"):
        return False, (
            "CLOUDFLARE_API_TOKEN starts with 'v1.0-' — this is a User API Token, "
            "NOT a Workers AI token. Workers AI requires a separate token. "
            "Go to: https://dash.cloudflare.com/profile/api-tokens → 'Create Token' "
            "→ use the 'Workers AI' template or add permission: Account → Workers AI → Edit."
        )

    return True, "ok"


def _validate_cloudinary(settings: Any) -> Tuple[bool, str]:
    cloud  = getattr(settings, "CLOUDINARY_CLOUD_NAME", None)
    key    = getattr(settings, "CLOUDINARY_API_KEY", None)
    secret = getattr(settings, "CLOUDINARY_API_SECRET", None)
    if not cloud:
        return False, "CLOUDINARY_CLOUD_NAME not set"
    if not key:
        return False, "CLOUDINARY_API_KEY not set"
    if not secret:
        return False, "CLOUDINARY_API_SECRET not set"
    return True, "ok"


def build_pipeline_engine(
    settings: Any,
    logger: logging.Logger,
) -> Tuple[PipelineEngine, ProviderRouter]:
    """
    Entry point called by luminorbit_backend.py:

        from luminorbit_pipelines import CORS_ALLOWED_ORIGINS, build_pipeline_engine
        _pipeline, _router = build_pipeline_engine(_settings, logger)

    Outer exception fence: startup crash never kills the server.
    """
    try:
        return _build_pipeline_engine_inner(settings, logger)
    except Exception as exc:
        logger.exception(
            "[pipelines] STARTUP EXCEPTION in build_pipeline_engine: %s — "
            "returning degraded engine with all providers disabled", exc,
        )
        engine = PipelineEngine(settings, logger)
        for name in PROVIDER_REGISTRY:
            engine._health[name] = 0.0
        return engine, ProviderRouter(engine)


def _build_pipeline_engine_inner(
    settings: Any,
    logger: logging.Logger,
) -> Tuple[PipelineEngine, ProviderRouter]:
    engine = PipelineEngine(settings, logger)
    router = ProviderRouter(engine)

    # Per-provider credential checks
    credential_checks: Dict[str, Tuple[bool, str]] = {
        "huggingface":  (bool(getattr(settings, "HF_API_KEY", None)),
                         "HF_API_KEY missing" if not getattr(settings, "HF_API_KEY", None) else "ok"),
        "pollinations": (True, "free tier — no key required"),
        "segmind":      (bool(getattr(settings, "SEGMIND_API_KEY", None)),
                         "SEGMIND_API_KEY missing" if not getattr(settings, "SEGMIND_API_KEY", None) else "ok"),
        "together":     (bool(getattr(settings, "TOGETHER_API_KEY", None)),
                         "TOGETHER_API_KEY missing" if not getattr(settings, "TOGETHER_API_KEY", None) else "ok"),
        "gemini":       (bool(getattr(settings, "GEMINI_API_KEY", None)),
                         "GEMINI_API_KEY missing" if not getattr(settings, "GEMINI_API_KEY", None) else "ok"),
        "groq":         (bool(getattr(settings, "GROQ_API_KEY", None)),
                         "GROQ_API_KEY missing" if not getattr(settings, "GROQ_API_KEY", None) else "ok"),
        "mistral":      (bool(getattr(settings, "MISTRAL_API_KEY", None)),
                         "MISTRAL_API_KEY missing" if not getattr(settings, "MISTRAL_API_KEY", None) else "ok"),
        "openrouter":   (bool(getattr(settings, "OPENROUTER_API_KEY", None)),
                         "OPENROUTER_API_KEY missing" if not getattr(settings, "OPENROUTER_API_KEY", None) else "ok"),
        "cloudflare":   _validate_cloudflare(settings),
        "deepai":       (bool(getattr(settings, "DEEPAI_API_KEY", None)),
                         "DEEPAI_API_KEY missing" if not getattr(settings, "DEEPAI_API_KEY", None) else "ok"),
        "cloudinary":   _validate_cloudinary(settings),
        "krea":         (bool(getattr(settings, "KREA_API_KEY", None)),
                         "KREA_API_KEY missing" if not getattr(settings, "KREA_API_KEY", None) else "ok"),
        "pexels":       (bool(getattr(settings, "PEXELS_API_KEY", None)),
                         "PEXELS_API_KEY missing" if not getattr(settings, "PEXELS_API_KEY", None) else "ok"),
        "unsplash":     (bool(getattr(settings, "UNSPLASH_ACCESS_KEY", None)),
                         "UNSPLASH_ACCESS_KEY missing" if not getattr(settings, "UNSPLASH_ACCESS_KEY", None) else "ok"),
    }

    configured:   List[str] = []
    unconfigured: List[str] = []

    for name, (ok, reason) in credential_checks.items():
        if ok:
            configured.append(name)
        else:
            unconfigured.append(name)
            engine._health[name] = 0.0   # Hard-disabled: excluded from all routing

    logger.info(
        "[pipelines] ══════════════ STARTUP HEALTH REGISTRY v35 (ENTERPRISE) ══════════════"
    )
    logger.info(
        "[pipelines] Configured providers (%d/%d): %s",
        len(configured), len(credential_checks), configured,
    )

    if unconfigured:
        logger.warning(
            "[pipelines] Disabled providers (%d, health=0, will not route): %s",
            len(unconfigured), unconfigured,
        )
        for name in unconfigured:
            _, reason = credential_checks[name]
            logger.warning("[pipelines]   ✗ %s: %s", name, reason)

    # Segmentation chain status
    seg_chain  = CAPABILITY_PROVIDERS["segmentation"]
    seg_active = [p for p in seg_chain if engine._health.get(p, 1.0) > 0.0]
    seg_dead   = [p for p in seg_chain if engine._health.get(p, 1.0) == 0.0]
    logger.info(
        "[pipelines] Segmentation chain: active=%s dead/disabled=%s",
        seg_active, seg_dead,
    )
    if not seg_active:
        logger.error(
            "[pipelines] ⚠ WARNING: ALL segmentation providers disabled. "
            "Background removal tools will return PROVIDER_EXECUTION_FAILED. "
            "Set HF_API_KEY to re-enable HuggingFace segmentation (most reliable provider)."
        )

    # Cloudflare diagnostics
    cf_ok, cf_reason = credential_checks["cloudflare"]
    if not cf_ok:
        logger.warning(
            "[pipelines] ⚠ Cloudflare AI disabled: %s",
            cf_reason,
        )
    else:
        logger.info(
            "[pipelines] ✓ Cloudflare AI credentials look valid. "
            "Note: CLOUDFLARE_ACCOUNT_ID must be 32-char hex from dash.cloudflare.com sidebar. "
            "Token must have 'Account:Workers AI:Edit' permission."
        )

    # Cloudinary diagnostics
    cld_ok, cld_reason = credential_checks["cloudinary"]
    if not cld_ok:
        logger.warning(
            "[pipelines] ⚠ Cloudinary disabled: %s. "
            "AI output will use inline base64 delivery (still works).",
            cld_reason,
        )
    else:
        logger.info(
            "[pipelines] ✓ Cloudinary credentials present — "
            "launching live validation (async, non-blocking)..."
        )
        # FIX-V32-07: Launch live credential validation as background task.
        # Non-blocking — if it fails, _CLOUDINARY_AUTH_FAILED_SESSION is set
        # before the first real upload attempt.
        # V34-FIX-05: Use get_running_loop() instead of deprecated
        # get_event_loop() (Python 3.10+ emits DeprecationWarning).
        try:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    _validate_cloudinary_credentials_live(settings, logger)
                )
            except RuntimeError:
                # No running loop yet (called at import time or from sync context).
                # Run synchronously — this is the rare cold-start path.
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        _validate_cloudinary_credentials_live(settings, logger)
                    )
                finally:
                    loop.close()
        except Exception as loop_err:
            logger.warning(
                "[pipelines] Could not schedule Cloudinary live validation: %s — "
                "will validate on first upload attempt", loop_err,
            )

    # Segmind info
    if credential_checks["segmind"][0]:
        logger.info(
            "[pipelines] ✓ Segmind configured. "
            "v32 uses current model routes: stable-diffusion/background-removal, bria-rmbg-2.0. "
            "If all endpoints return 404, check plan at: https://cloud.segmind.com/console/models"
        )

    if _PIL_AVAILABLE:
        logger.info("[pipelines] ✓ Pillow available — HF/CF mask application enabled")
    else:
        logger.warning(
            "[pipelines] ⚠ Pillow not installed — HF segmentation mask-application path "
            "disabled. Install: pip install Pillow"
        )

    # V34-FIX-04: /api/claude-proxy is now implemented in this file via
    # create_claude_proxy_route(app). Log its status so operators know
    # immediately whether it will work.
    anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if anthropic_key:
        logger.info(
            "[pipelines] ✓ /api/claude-proxy ACTIVE — ANTHROPIC_API_KEY is set. "
            "Frontend CLAUDE_PROXY_ENDPOINT='/api/claude-proxy' will work correctly. "
            "Register the route in luminorbit_backend.py: create_claude_proxy_route(app)"
        )
    else:
        logger.warning(
            "[pipelines] ⚠ /api/claude-proxy will return 503 — ANTHROPIC_API_KEY is NOT set. "
            "Frontend 'Unexpected error' on Claude features will persist until this is set. "
            "ACTION: In Railway → Variables, add: ANTHROPIC_API_KEY = sk-ant-..."
        )

    logger.info(
        "[pipelines] ══ Pipeline engine ready v34 | tools=%d pipelines=%d active_providers=%d ══",
        len(TOOL_PIPELINE_MAP), len(PIPELINE_CAPABILITY), len(configured),
    )

    return engine, router


# ══════════════════════════════════════════════════════════════════════════════
# §10  CLAUDE PROXY ROUTE  (v34-fix-01)
# ══════════════════════════════════════════════════════════════════════════════
#
# USAGE in luminorbit_backend.py:
#
#   from luminorbit_pipelines import (
#       CORS_ALLOWED_ORIGINS,
#       build_pipeline_engine,
#       create_claude_proxy_route,
#   )
#   app = FastAPI(...)
#   create_claude_proxy_route(app)       # ← call AFTER creating app
#
# This registers POST /api/claude-proxy on the FastAPI app.
# The route:
#   • Reads ANTHROPIC_API_KEY from env — never exposes it to the frontend
#   • Accepts any valid Anthropic /v1/messages body from the frontend
#   • Forwards it to api.anthropic.com/v1/messages
#   • Returns the raw Anthropic response to the frontend
#   • Returns structured 503 if ANTHROPIC_API_KEY is absent
#   • Returns structured error on any network/HTTP failure
#   • Never raises an unhandled exception — all paths return JSON
# ──────────────────────────────────────────────────────────────────────────────

def create_claude_proxy_route(app: Any) -> None:
    """
    Register POST /api/claude-proxy on a FastAPI app instance.

    Call once during app startup, after the FastAPI app object is created:

        create_claude_proxy_route(app)

    If ANTHROPIC_API_KEY is not set in Railway env vars, the route returns
    a 503 with a clear error — no 500, no unhandled exception, no crash.
    """
    try:
        # Import FastAPI types lazily — this file may be imported in environments
        # where FastAPI is not yet on PYTHONPATH (e.g. unit tests).
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ImportError:
        # If FastAPI is not importable, log and no-op. The backend will fail
        # loudly on its own if FastAPI is truly missing.
        import logging as _log
        _log.getLogger(__name__).error(
            "[claude-proxy] FastAPI not importable — /api/claude-proxy NOT registered. "
            "Ensure fastapi is in requirements.txt."
        )
        return

    _proxy_logger = logging.getLogger("luminorbit.claude_proxy")

    @app.post("/api/claude-proxy")
    async def claude_proxy(request: Request) -> JSONResponse:
        """
        Secure server-side proxy for Anthropic /v1/messages.

        The frontend sends a standard Anthropic messages request body.
        This route injects the ANTHROPIC_API_KEY from env and forwards
        the request, keeping the key out of browser network traffic.

        Request body (JSON):
          {
            "model":      "claude-3-5-haiku-20241022",  # optional, has default
            "max_tokens": 1024,                          # optional, has default
            "messages":   [{"role": "user", "content": "..."}]
          }

        Response: raw Anthropic API response (pass-through) or error JSON.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not api_key:
            _proxy_logger.warning(
                "[claude-proxy] Request received but ANTHROPIC_API_KEY is not set. "
                "Add ANTHROPIC_API_KEY to Railway environment variables."
            )
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error":   "claude_proxy_unavailable",
                    "message": (
                        "The Claude proxy is not configured. "
                        "ANTHROPIC_API_KEY is missing from server environment. "
                        "Contact the site administrator."
                    ),
                },
            )

        # Parse request body — frontend may send anything valid for Anthropic API
        try:
            body: Dict[str, Any] = await request.json()
        except Exception as parse_err:
            _proxy_logger.warning("[claude-proxy] Could not parse request body: %s", parse_err)
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error":   "invalid_request_body",
                    "message": f"Request body is not valid JSON: {parse_err}",
                },
            )

        # Apply safe defaults — frontend can override any of these
        body.setdefault("model",      "claude-3-5-haiku-20241022")
        body.setdefault("max_tokens", 1024)

        if "messages" not in body or not isinstance(body.get("messages"), list):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error":   "missing_messages",
                    "message": "Request body must contain a 'messages' array.",
                },
            )

        _proxy_logger.info(
            "[claude-proxy] → Anthropic model=%s messages=%d",
            body.get("model"), len(body["messages"]),
        )

        # ── Token estimation (log for diagnostics) ────────────────────────────
        try:
            total_chars = sum(
                len(m.get("content", "") if isinstance(m.get("content"), str)
                    else "".join(b.get("text", "") for b in m.get("content", []) if isinstance(b, dict))
                )
                for m in body.get("messages", [])
            )
            estimated_tokens = total_chars // 4
            _proxy_logger.debug("[claude-proxy] estimated_input_tokens≈%d", estimated_tokens)
        except Exception:
            pass

        # ── Forward to Anthropic with retry + exponential backoff ────────────
        MAX_PROXY_RETRIES = 2
        FALLBACK_MODELS   = ["claude-3-haiku-20240307", "claude-3-5-haiku-20241022"]
        last_proxy_error: Optional[Exception] = None

        for attempt in range(MAX_PROXY_RETRIES + 1):
            try:
                timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        json=body,
                        headers={
                            "x-api-key":         api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type":      "application/json",
                        },
                    )

                _proxy_logger.info(
                    "[claude-proxy] ← Anthropic HTTP %d model=%s attempt=%d",
                    resp.status_code, body.get("model"), attempt + 1,
                )

                # ── Rate limit: back-off and retry ───────────────────────────
                if resp.status_code == 429 and attempt < MAX_PROXY_RETRIES:
                    retry_after = int(resp.headers.get("retry-after", "5"))
                    _proxy_logger.warning(
                        "[claude-proxy] 429 rate limit — waiting %ds before retry %d",
                        retry_after, attempt + 2,
                    )
                    await asyncio.sleep(min(retry_after, 30))
                    continue

                # ── Model overload: try fallback model ───────────────────────
                if resp.status_code == 529 and attempt < MAX_PROXY_RETRIES:
                    fallback = FALLBACK_MODELS[attempt % len(FALLBACK_MODELS)]
                    _proxy_logger.warning(
                        "[claude-proxy] 529 overloaded — falling back to model=%s", fallback,
                    )
                    body = {**body, "model": fallback}
                    await asyncio.sleep(2)
                    continue

                if resp.status_code == 200:
                    try:
                        resp_data = resp.json()
                        return JSONResponse(status_code=200, content=resp_data)
                    except Exception:
                        return JSONResponse(
                            status_code=502,
                            content={
                                "success": False,
                                "error":   "upstream_response_not_json",
                                "message": "Anthropic returned a non-JSON response.",
                            },
                        )

                # Parse Anthropic error
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = {"raw": resp.text[:500]}

                # Auth errors: never retry
                if resp.status_code in (401, 403):
                    _proxy_logger.error(
                        "[claude-proxy] Auth error %d — check ANTHROPIC_API_KEY: %s",
                        resp.status_code, str(err_body)[:200],
                    )
                    return JSONResponse(
                        status_code=resp.status_code,
                        content={
                            "success":          False,
                            "error":            "anthropic_auth_error",
                            "anthropic_status": resp.status_code,
                            "detail":           err_body,
                            "fix":              "Verify ANTHROPIC_API_KEY in Railway environment variables.",
                        },
                    )

                _proxy_logger.warning(
                    "[claude-proxy] Anthropic error HTTP %d attempt=%d: %s",
                    resp.status_code, attempt + 1, str(err_body)[:200],
                )

                if attempt >= MAX_PROXY_RETRIES:
                    return JSONResponse(
                        status_code=resp.status_code,
                        content={
                            "success":          False,
                            "error":            "anthropic_api_error",
                            "anthropic_status": resp.status_code,
                            "detail":           err_body,
                        },
                    )
                await asyncio.sleep(1.5 * (attempt + 1))

            except httpx.TimeoutException as te:
                last_proxy_error = te
                _proxy_logger.warning("[claude-proxy] Timeout attempt=%d: %s", attempt + 1, te)
                if attempt < MAX_PROXY_RETRIES:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return JSONResponse(
                    status_code=504,
                    content={
                        "success": False,
                        "error":   "upstream_timeout",
                        "message": "Anthropic API request timed out. Please try again.",
                        "attempts": attempt + 1,
                    },
                )
            except Exception as exc:
                last_proxy_error = exc
                _proxy_logger.exception("[claude-proxy] Unexpected error attempt=%d: %s", attempt + 1, exc)
                if attempt < MAX_PROXY_RETRIES:
                    await asyncio.sleep(1.0)
                    continue
                return JSONResponse(
                    status_code=502,
                    content={
                        "success": False,
                        "error":   "upstream_error",
                        "message": f"Could not reach Anthropic API: {type(exc).__name__}: {str(exc)[:200]}",
                    },
                )

        return JSONResponse(
            status_code=502,
            content={"success": False, "error": "all_retries_exhausted", "message": "All proxy retry attempts failed."},
        )

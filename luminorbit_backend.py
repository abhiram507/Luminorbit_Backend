"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       LUMINORBIT V22 — PRODUCTION HARDENED BACKEND (SECURITY REWRITE)      ║
║       Single-file deployment — all config embedded, no extra files needed   ║
╚══════════════════════════════════════════════════════════════════════════════╝

DEPLOY GUIDE
════════════
# Luminorbit v22 — Deployment Guide
# Free Stack: GitHub Pages + Render.com + dpdns.org + Cloudflare
#
# STEP 1 — Run setup to generate deployment files:
#   python luminorbit_backend_FIXED.py --setup
#   (Writes requirements.txt and render.yaml in the current directory)
#
# STEP 2 — Create GitHub repo and push:
#   gh repo create luminorbit --public
#   git init && git add . && git commit -m "init"
#   git push origin main
#   gh api repos/:owner/luminorbit/pages -X POST -f source.branch=main -f source.path=/
#   (Frontend will be at https://YOUR_USERNAME.github.io/luminorbit/)
#
# STEP 3 — Deploy backend to Render.com (free):
#   - New Web Service → connect your GitHub repo
#   - Build: pip install -r requirements.txt
#   - Start: uvicorn luminorbit_backend_FIXED:app --host 0.0.0.0 --port $PORT
#   - Add env vars:
#       APP_ENV=production
#       API_SECRET=<random 32-char string>
#       ALLOWED_ORIGINS=https://YOUR_USERNAME.github.io,https://yourdomain.dpdns.org
#   - Health check: https://luminorbit-api.onrender.com/health
#
# STEP 4 — Custom domain (dpdns.org):
#   - Register subdomain at https://dpdns.org
#   - CNAME luminorbit → YOUR_USERNAME.github.io
#   - CNAME api → luminorbit-api.onrender.com
#
# STEP 5 — Cloudflare (free HTTPS + CDN):
#   - Add domain to Cloudflare, proxy both CNAMEs (orange cloud)
#   - SSL/TLS → Full (strict)
#
# STEP 6 — Update frontend HTML config:
#   In Luminorbit-v22-FINAL.html find the config block and set:
#     window.LUMINORBIT_API_URL = 'https://api.yourdomain.dpdns.org';
#     window.LUMINORBIT_API_KEY = 'YOUR_API_SECRET';
#   Then: git add . && git commit -m "set backend url" && git push
#
# ENV VARS REFERENCE:
#   APP_ENV               = production
#   API_SECRET            = any random string (required)
#   ALLOWED_ORIGINS       = comma-separated frontend URLs
#   CLOUDINARY_CLOUD_ID   = your cloud name (optional, leave blank for data-URL fallback)
#   REDIS_URL             = redis://... (optional, falls back to in-memory)
#   RATE_LIMIT_IP         = 20/minute (default)
#   DAILY_REQUEST_LIMIT   = 200 (default)
#   MAX_FILE_MB           = 50 (default)

CHANGES FROM ORIGINAL V22:
  SEC-1  API_SECRET enforced — startup fails if blank in production
  SEC-2  CORS wildcard replaced with strict domain allowlist from env
  SEC-3  HSTS + CSP + X-Frame-Options + Referrer-Policy security headers
  SEC-4  Secrets never logged (key hashes only)
  SEC-5  Global exception handler strips internal stack traces from responses
  SEC-6  Cloudinary CLOUD_ID validated as name (not numeric ID) at startup
  ARCH-1 Redis REQUIRED in production — startup fails if unreachable
  ARCH-2 Rate limiting via slowapi (default_limits, no private API abuse)
  ARCH-3 Per-IP + per-user + burst limits
  ARCH-4 Structured JSON logging via python-json-logger
  ARCH-5 Multipart upload replaces base64 for large files
  ARCH-6 Provider timeout enforced globally
  ARCH-7 Retry + backoff on transient provider 5xx errors
  VAL-1  Tool name and params strictly validated
  VAL-2  File MIME validated against magic bytes
  VAL-3  File size, image dimension, video duration hard limits enforced
  CDN-1  Cloudinary upload uses secure_url only, never http
  CDN-2  Upload failures are hard errors when cloud_id is configured
  MON-1  /health includes provider liveness, Redis status, uptime
  MON-2  Request logging: IP (hashed), latency, tool, provider, status
  MON-3  Startup validation log (missing keys, config errors)
  FIX-1  uvicorn module name corrected (was luminorbit_backend_prod)
  FIX-2  CORS allow_origins now uses env allowlist (was hardcoded wildcard)
  FIX-3  slowapi private _check_request_limit removed (crashed every request)
  FIX-4  CLOUDINARY_CLOUD_ID default cleared (was invalid placeholder)
  FIX-5  HTTPSRedirectMiddleware removed (caused loops behind Cloudflare)
  FIX-6  CSP connect-src expanded to include all 12 provider domains
  EMBED  requirements.txt + render.yaml embedded — run --setup to extract
"""

# ═══════════════════════════════════════════════════════════════════════════════
# §1  IMPORTS & LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

import abc
import asyncio
import base64
import collections
import datetime
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import pathlib
import struct
import sys
import tempfile
import time
import urllib.parse
import uuid

# ═══════════════════════════════════════════════════════════════════════════════
# §0  SELF-CONTAINED SETUP — python luminorbit_backend_FIXED.py --setup
#     Writes requirements.txt and render.yaml into the current directory.
#     All deployment files are embedded here — no separate files needed.
# ═══════════════════════════════════════════════════════════════════════════════

_REQUIREMENTS_TXT = """\
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.28.1
pydantic==2.10.3
pydantic-settings==2.6.1
Pillow==11.0.0
python-multipart==0.0.17
slowapi==0.1.9
redis==5.2.1
python-json-logger==2.0.7
starlette==0.41.3
"""

_WORKER_JS_EMBED = r"""
/**
 * ╔══════════════════════════════════════════════════════════════════════════════╗
 * ║      LUMINORBIT V22 — CLOUDFLARE WORKER BACKEND                            ║
 * ║      Full JS replacement for the Python backend on Cloudflare's edge       ║
 * ║      Deploy: wrangler deploy (see wrangler.toml in same directory)         ║
 * ╚══════════════════════════════════════════════════════════════════════════════╝
 *
 * WHAT THIS DOES:
 *   Implements the same API surface as luminorbit_backend_FIXED.py but runs
 *   entirely on Cloudflare Workers (V8 isolates, no Python, no Docker).
 *
 * ENDPOINTS:
 *   GET  /health                         → liveness check
 *   GET  /api/tools                      → valid tool + capability list
 *   POST /api/process                    → sync AI processing (JSON body)
 *   GET  /api/jobs/:id                   → poll async job (uses KV store)
 *   GET  /api/providers                  → provider routing stats (from KV)
 *
 * LIMITATIONS vs PYTHON BACKEND:
 *   ✗  No PIL/image post-processing (no Pillow on CF Workers)
 *   ✗  No video duration parsing (no struct module)
 *   ✗  No multipart /api/process/upload endpoint (use JSON base64)
 *   ✗  No Redis — KV Namespace used for job state instead
 *   ✗  CPU limit 10ms (wall time unlimited — HTTP waits don't count)
 *   ✓  Global edge network — lower latency than Render free tier
 *   ✓  100K free requests/day on free plan
 *   ✓  Zero cold starts after first request
 *
 * DEPLOY STEPS:
 *   1. npm install -g wrangler
 *   2. wrangler login
 *   3. wrangler kv:namespace create LUMINORBIT_JOBS
 *      → copy the id into wrangler.toml [[kv_namespaces]] binding
 *   4. wrangler secret put API_SECRET          (your auth token)
 *   5. wrangler secret put ALLOWED_ORIGINS     (comma-separated frontend URLs)
 *   6. wrangler deploy
 *   7. Update LUMINORBIT_API_URL in Luminorbit-v22-FINAL.html to:
 *      'https://luminorbit.YOUR_SUBDOMAIN.workers.dev'
 *
 * OPTIONAL SECRETS (provider API keys — set via `wrangler secret put <NAME>`):
 *   POLLINATIONS_API_KEY, TOGETHER_API_KEY, HF_API_KEY, DEEPAI_API_KEY,
 *   SEGMIND_API_KEY, CF_AI_TOKEN, CF_ACCOUNT_ID, GEMINI_API_KEY,
 *   GROQ_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY, KREA_API_KEY,
 *   PEXELS_API_KEY, UNSPLASH_API_KEY, CLOUDINARY_CLOUD_ID,
 *   CLOUDINARY_UPLOAD_PRESET
 *
 * WRANGLER.TOML (wrangler.toml in same directory):
 *   name = "luminorbit"
 *   main = "worker.js"
 *   compatibility_date = "2024-01-01"
 *   [[kv_namespaces]]
 *   binding = "LUMINORBIT_JOBS"
 *   id = "<your-kv-namespace-id>"
 */

// ═══════════════════════════════════════════════════════════════════════════════
// §1  CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════════

const APP_VERSION = "22.1.0-cf";

const VALID_CAPABILITIES = new Set([
  "image-gen","super-resolution","segmentation","inpainting",
  "face-processing","restoration","style-transfer","captioning",
  "audio-extraction","compression","temporal","color-matching",
  "audio-sync","visualization","video-gen","basic-processing",
  "denoising","image-enhancement","controlnet",
]);

const VALID_TOOLS = {
  "Flux 1.1 Pro":"image-gen","Seedream 5.0":"image-gen",
  "SDXL 1.0":"image-gen","Stable Diffusion 3.5":"image-gen",
  "Adobe Firefly":"image-gen","Midjourney v7":"image-gen",
  "ControlNet":"controlnet","InstructPix2Pix":"inpainting",
  "SUPIR":"super-resolution","Real-ESRGAN":"super-resolution",
  "GFPGAN":"face-processing","CodeFormer":"restoration",
  "RestoreFormer":"restoration","SwinIR":"super-resolution",
  "BSRGAN":"super-resolution","SAM 2":"segmentation",
  "Grounding DINO":"segmentation","Florence-2":"captioning",
  "Runway Gen-5":"video-gen","Seedance 2.0":"video-gen",
  "Kling AI 3.0":"video-gen","Luma Dream Machine":"video-gen",
  "Pika 2.5":"video-gen","Hailuo MiniMax":"video-gen",
  "Sora Edit":"video-gen","Stable Video Diffusion":"video-gen",
  "LivePortrait":"face-processing","Topaz Video AI 5":"super-resolution",
  "TecoGAN":"temporal","RIFE":"temporal","DAIN":"temporal",
  "RAFT + ESRGAN":"temporal","Temporal GAN":"temporal",
  "AnimateDiff":"video-gen","Wonder Dynamics":"temporal",
  "Auto Caption Generator":"captioning",
  "Audio Extractor Tool":"audio-extraction",
  "Video Compressor Pro":"compression",
  "Video Speed Controller":"temporal",
  "MultiCam Sync":"color-matching","Match Cut Flow":"color-matching",
  "Beat Sync Drop":"audio-sync","Sound Wave Viz":"visualization",
  "Audio Reactive Viz":"visualization",
};

// Tool → provider fallback chains
const TOOL_PROVIDERS = {
  "Flux 1.1 Pro":         ["pollinations","together","krea"],
  "Seedream 5.0":         ["pollinations","krea"],
  "SDXL 1.0":             ["huggingface","deepai"],
  "Stable Diffusion 3.5": ["segmind","huggingface"],
  "SUPIR":                ["cloudflare","krea"],
  "Real-ESRGAN":          ["huggingface","cloudflare"],
  "GFPGAN":               ["huggingface","deepai"],
  "CodeFormer":           ["huggingface"],
  "RestoreFormer":        ["krea","cloudflare"],
  "SwinIR":               ["huggingface","cloudflare"],
  "BSRGAN":               ["huggingface"],
  "Adobe Firefly":        ["pollinations"],
  "ControlNet":           ["segmind","huggingface"],
  "InstructPix2Pix":      ["huggingface"],
  "SAM 2":                ["huggingface"],
  "Grounding DINO":       ["huggingface"],
  "Florence-2":           ["gemini","groq"],
  "Midjourney v7":        ["pollinations","krea"],
  "Runway Gen-5":         ["pollinations","together"],
  "Seedance 2.0":         ["pollinations"],
  "Kling AI 3.0":         ["together"],
  "Luma Dream Machine":   ["pollinations"],
  "Pika 2.5":             ["pollinations"],
  "Hailuo MiniMax":       ["together"],
  "Sora Edit":            ["pollinations"],
  "Stable Video Diffusion":["huggingface"],
  "LivePortrait":         ["huggingface"],
  "Topaz Video AI 5":     ["krea"],
  "TecoGAN":              ["huggingface"],
  "RIFE":                 ["huggingface"],
  "DAIN":                 ["huggingface"],
  "RAFT + ESRGAN":        ["cloudflare"],
  "Temporal GAN":         ["huggingface"],
  "AnimateDiff":          ["huggingface","pollinations"],
  "Wonder Dynamics":      ["cloudflare"],
};

const CAPABILITY_PROVIDERS = {
  "segmentation":      ["huggingface","cloudflare","segmind"],
  "inpainting":        ["huggingface","segmind","deepai"],
  "face-processing":   ["huggingface","deepai","krea"],
  "super-resolution":  ["huggingface","cloudflare","krea"],
  "image-enhancement": ["huggingface","segmind"],
  "denoising":         ["huggingface","cloudflare"],
  "restoration":       ["huggingface","deepai","krea"],
  "style-transfer":    ["huggingface","pollinations","together"],
  "captioning":        ["gemini","groq","mistral"],
  "audio-extraction":  ["cloudflare"],
  "compression":       ["cloudflare"],
  "temporal":          ["cloudflare","huggingface"],
  "color-matching":    ["cloudflare"],
  "audio-sync":        ["cloudflare"],
  "visualization":     ["pollinations","gemini"],
  "image-gen":         ["pollinations","together","krea","segmind"],
  "video-gen":         ["pollinations","together"],
  "basic-processing":  ["huggingface","pollinations","cloudflare"],
  "controlnet":        ["segmind","huggingface"],
};

// Provider timeout ms (CF Workers HTTP has no timeout — this is enforced via Promise.race)
const PROVIDER_TIMEOUT_MS = 13000;
const TARGET_W = 3840;
const TARGET_H = 2160;

// ═══════════════════════════════════════════════════════════════════════════════
// §2  MAIN ENTRY POINT
// ═══════════════════════════════════════════════════════════════════════════════

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const method = request.method;

    // CORS preflight
    if (method === "OPTIONS") {
      return corsPreflightResponse(request, env);
    }

    // Route dispatch
    try {
      if (url.pathname === "/health" && method === "GET") {
        return withCors(await handleHealth(env), request, env);
      }
      if (url.pathname === "/api/tools" && method === "GET") {
        return withCors(jsonResp({ tools: VALID_TOOLS, capabilities: [...VALID_CAPABILITIES] }), request, env);
      }
      if (url.pathname === "/api/process" && method === "POST") {
        const authErr = verifyAuth(request, env);
        if (authErr) return withCors(authErr, request, env);
        return withCors(await handleProcess(request, env, ctx), request, env);
      }
      if (url.pathname.startsWith("/api/jobs/") && method === "GET") {
        const authErr = verifyAuth(request, env);
        if (authErr) return withCors(authErr, request, env);
        const jobId = url.pathname.slice("/api/jobs/".length);
        return withCors(await handleJobStatus(jobId, env), request, env);
      }
      // Alias: /process → /api/process
      if (url.pathname === "/process" && method === "POST") {
        const authErr = verifyAuth(request, env);
        if (authErr) return withCors(authErr, request, env);
        return withCors(await handleProcess(request, env, ctx), request, env);
      }
      if (url.pathname === "/api/providers" && method === "GET") {
        const authErr = verifyAuth(request, env);
        if (authErr) return withCors(authErr, request, env);
        return withCors(jsonResp({ message: "Provider stats not persisted in CF Workers (stateless)" }), request, env);
      }
      return withCors(jsonResp({ success: false, error: "not_found" }, 404), request, env);
    } catch (err) {
      console.error("[worker] unhandled:", err);
      return withCors(jsonResp({ success: false, error: "internal_server_error" }, 500), request, env);
    }
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// §3  AUTH
// ═══════════════════════════════════════════════════════════════════════════════

function verifyAuth(request, env) {
  const secret = env.API_SECRET || "";
  if (!secret) return null; // Dev mode: no auth required
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ")) {
    return jsonResp({ success: false, error: "Missing Authorization header" }, 401);
  }
  const token = auth.slice("Bearer ".length);
  // Constant-time comparison
  if (!timingSafeEqual(token, secret)) {
    return jsonResp({ success: false, error: "Invalid token" }, 401);
  }
  return null;
}

function timingSafeEqual(a, b) {
  // Polyfill for CF Workers — no crypto.timingSafeEqual available in all runtimes
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

// ═══════════════════════════════════════════════════════════════════════════════
// §4  CORS
// ═══════════════════════════════════════════════════════════════════════════════

function getAllowedOrigins(env) {
  const raw = env.ALLOWED_ORIGINS || "";
  if (!raw || raw.trim() === "*") return ["*"];
  return raw.split(",").map(o => o.trim()).filter(Boolean);
}

function corsHeaders(request, env) {
  const origins = getAllowedOrigins(env);
  const reqOrigin = request.headers.get("Origin") || "";
  let origin = "null";
  if (origins.includes("*")) {
    origin = "*";
  } else if (origins.includes(reqOrigin)) {
    origin = reqOrigin;
  }
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function corsPreflightResponse(request, env) {
  return new Response(null, { status: 204, headers: corsHeaders(request, env) });
}

function withCors(response, request, env) {
  const hdrs = corsHeaders(request, env);
  const newHdrs = new Headers(response.headers);
  for (const [k, v] of Object.entries(hdrs)) newHdrs.set(k, v);
  // Security headers
  newHdrs.set("X-Content-Type-Options", "nosniff");
  newHdrs.set("X-Frame-Options", "DENY");
  newHdrs.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return new Response(response.body, { status: response.status, headers: newHdrs });
}

// ═══════════════════════════════════════════════════════════════════════════════
// §5  HEALTH ENDPOINT
// ═══════════════════════════════════════════════════════════════════════════════

async function handleHealth(env) {
  const kvOk = env.LUMINORBIT_JOBS ? "connected" : "not_configured";
  return jsonResp({
    status: "ok",
    version: APP_VERSION,
    runtime: "cloudflare-workers",
    kv_store: kvOk,
    timestamp: Math.floor(Date.now() / 1000),
    note: "No PIL post-processing. No video validation. Job state via KV.",
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// §6  PROCESS ENDPOINT
// ═══════════════════════════════════════════════════════════════════════════════

async function handleProcess(request, env, ctx) {
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResp({ success: false, error: "Invalid JSON body" }, 400);
  }

  const { tool, capability = "basic-processing", params = {}, file_data, file_mime, resolution = "4K" } = body;

  // Validate tool
  if (!tool || !tool.trim()) {
    return jsonResp({ success: false, error: "tool:required" }, 422);
  }
  // Validate capability
  const cap = capability || "basic-processing";
  if (cap !== "basic-processing" && !VALID_CAPABILITIES.has(cap)) {
    return jsonResp({ success: false, error: `capability:unknown:${cap}` }, 422);
  }

  // Decode file bytes if provided
  let fileBytes = null;
  let fileMime = file_mime || "application/octet-stream";
  if (file_data) {
    try {
      const b64 = file_data.includes(",") ? file_data.split(",")[1] : file_data;
      fileBytes = base64Decode(b64);
    } catch {
      return jsonResp({ success: false, error: "Invalid file_data encoding" }, 400);
    }
  }

  // Build provider chain
  const seen = new Set();
  const chain = [];
  for (const n of [...(TOOL_PROVIDERS[tool] || []), ...(CAPABILITY_PROVIDERS[cap] || [])]) {
    if (!seen.has(n)) { seen.add(n); chain.push(n); }
  }

  const requestId = randomId();
  console.log(`[worker:${requestId}] tool=${tool} cap=${cap} chain=${chain.join(",")}`);

  // Try providers in order
  let lastError = "no_providers";
  let fallbackUsed = false;

  for (const providerName of chain) {
    try {
      const result = await withTimeout(
        callProvider(providerName, cap, fileBytes, fileMime, params, env),
        PROVIDER_TIMEOUT_MS,
        `${providerName}:timeout`
      );
      if (result.success) {
        console.log(`[worker:${requestId}] ✓ ${providerName}`);
        return jsonResp({
          success: true,
          output: result.output,
          output_url: result.output,
          provider: providerName,
          resolution: result.resolution || `${TARGET_W}x${TARGET_H}`,
          metadata: result.metadata || {},
          status: fallbackUsed ? "fallback_used" : "ok",
          fallback_reason: fallbackUsed ? lastError : undefined,
          request_id: requestId,
        });
      }
      lastError = result.error || "unknown";
    } catch (err) {
      lastError = String(err.message || err);
    }
    console.warn(`[worker:${requestId}] ✗ ${providerName}: ${lastError}`);
    fallbackUsed = true;
  }

  // Emergency Pollinations fallback
  try {
    const emergency = await emergencyFallback(tool, cap, params, env);
    if (emergency.success) {
      return jsonResp({
        success: true,
        output: emergency.output,
        output_url: emergency.output,
        provider: "pollinations-emergency",
        resolution: `${TARGET_W}x${TARGET_H}`,
        metadata: {},
        status: "fallback_used",
        fallback_reason: lastError,
        request_id: requestId,
      });
    }
  } catch (err) {
    console.error("[worker] emergency fallback failed:", err);
  }

  return jsonResp({ success: false, error: `All providers failed: ${lastError}`, request_id: requestId }, 500);
}

// ═══════════════════════════════════════════════════════════════════════════════
// §7  JOB STATUS (KV-backed)
// ═══════════════════════════════════════════════════════════════════════════════

async function handleJobStatus(jobId, env) {
  if (!jobId || jobId.length > 64) {
    return jsonResp({ success: false, error: "invalid_job_id" }, 400);
  }
  if (!env.LUMINORBIT_JOBS) {
    return jsonResp({ success: false, error: "KV not configured" }, 503);
  }
  const raw = await env.LUMINORBIT_JOBS.get(`job:${jobId}`);
  if (!raw) {
    return jsonResp({ success: false, error: "Job not found" }, 404);
  }
  const job = JSON.parse(raw);
  return jsonResp({
    job_id: job.job_id,
    status: job.status,
    progress: job.progress || 0,
    output: job.output || null,
    output_url: job.output || null,
    error: job.error || null,
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// §8  PROVIDER IMPLEMENTATIONS
// ═══════════════════════════════════════════════════════════════════════════════

async function callProvider(name, capability, fileBytes, fileMime, params, env) {
  switch (name) {
    case "pollinations":  return callPollinations(capability, fileBytes, fileMime, params, env);
    case "together":      return callTogether(capability, fileBytes, fileMime, params, env);
    case "huggingface":   return callHuggingFace(capability, fileBytes, fileMime, params, env);
    case "gemini":        return callGemini(capability, fileBytes, fileMime, params, env);
    case "groq":          return callGroq(capability, fileBytes, fileMime, params, env);
    case "mistral":       return callMistral(capability, fileBytes, fileMime, params, env);
    case "openrouter":    return callOpenRouter(capability, fileBytes, fileMime, params, env);
    case "segmind":       return callSegmind(capability, fileBytes, fileMime, params, env);
    case "krea":          return callKrea(capability, fileBytes, fileMime, params, env);
    case "deepai":        return callDeepAI(capability, fileBytes, fileMime, params, env);
    case "cloudflare":    return callCFAI(capability, fileBytes, fileMime, params, env);
    case "pexels":        return callPexels(capability, fileBytes, fileMime, params, env);
    case "unsplash":      return callUnsplash(capability, fileBytes, fileMime, params, env);
    default: return { success: false, error: `unknown_provider:${name}` };
  }
}

// ── Pollinations ─────────────────────────────────────────────────────────────
async function callPollinations(capability, fileBytes, fileMime, params, env) {
  const key    = env.POLLINATIONS_API_KEY || "";
  const prompt = params.prompt || "professional studio quality photograph ultra high detail";
  const model  = (capability === "style-transfer" || capability === "restoration") ? "flux-pro" : "flux";
  const seed   = params.seed || 42;
  const url    = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=${TARGET_W}&height=${TARGET_H}&model=${model}&seed=${seed}&nologo=true&enhance=true`;
  const headers = key ? { "Authorization": `Bearer ${key}` } : {};
  const r = await fetch(url, { headers });
  if (!r.ok) return { success: false, error: `pollinations:${r.status}` };
  const raw = await r.arrayBuffer();
  if (raw.byteLength < 1000) return { success: false, error: "pollinations:tiny_payload" };
  const ct  = r.headers.get("content-type") || "image/jpeg";
  const b64 = arrayBufferToBase64(raw);
  return { success: true, output: `data:${ct};base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { model } };
}

// ── Together AI ──────────────────────────────────────────────────────────────
const TA_MODELS = {
  "image-gen":"black-forest-labs/FLUX.1-pro","style-transfer":"black-forest-labs/FLUX.1-pro",
  "inpainting":"black-forest-labs/FLUX.1-pro","face-processing":"black-forest-labs/FLUX.1-pro",
  "super-resolution":"black-forest-labs/FLUX.1-pro","restoration":"black-forest-labs/FLUX.1-pro",
  "image-enhancement":"black-forest-labs/FLUX.1-pro","denoising":"black-forest-labs/FLUX.1-schnell",
  "segmentation":"black-forest-labs/FLUX.1-schnell","basic-processing":"black-forest-labs/FLUX.1-schnell",
  "video-gen":"stabilityai/stable-video-diffusion-img2vid-xt",
  "captioning":"meta-llama/Llama-3.3-70B-Instruct-Turbo",
};
async function callTogether(capability, fileBytes, fileMime, params, env) {
  const key   = env.TOGETHER_API_KEY || "";
  if (!key) return { success: false, error: "together:no_key" };
  const model  = TA_MODELS[capability] || "black-forest-labs/FLUX.1-schnell";
  const prompt = params.prompt || "ultra detailed professional studio quality 4K photograph";
  const body   = { model, prompt, width: TARGET_W, height: TARGET_H, steps: params.steps || 28, n: 1, response_format: "b64_json" };
  if (fileBytes && capability !== "image-gen") {
    body.image_base64 = arrayBufferToBase64(fileBytes);
    body.strength     = params.strength || 0.75;
  }
  const r = await fetch("https://api.together.xyz/v1/images/generations", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) return { success: false, error: `together:${r.status}` };
  const data = await r.json();
  const b64  = data.data?.[0]?.b64_json;
  if (!b64) return { success: false, error: "together:no_image" };
  return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { model } };
}

// ── HuggingFace ──────────────────────────────────────────────────────────────
const HF_MODELS = {
  "super-resolution":"ai-forever/Real-ESRGAN","face-processing":"tencentarc/gfpgan",
  "restoration":"sczhou/codeformer","segmentation":"facebook/sam-vit-huge",
  "inpainting":"runwayml/stable-diffusion-inpainting",
  "image-gen":"stabilityai/stable-diffusion-xl-base-1.0",
  "style-transfer":"lambdalabs/sd-image-variations-diffusers",
  "denoising":"ai-forever/Real-ESRGAN","video-gen":"stabilityai/stable-video-diffusion-img2vid-xt",
  "captioning":"Salesforce/blip-image-captioning-large",
  "temporal":"microsoft/phi-3-vision-128k-instruct",
  "image-enhancement":"stabilityai/stable-diffusion-xl-refiner-1.0",
  "basic-processing":"stabilityai/stable-diffusion-xl-base-1.0",
  "color-matching":"stabilityai/stable-diffusion-xl-base-1.0",
};
const HF_IMAGE_INPUT = new Set([
  "super-resolution","face-processing","restoration","segmentation",
  "inpainting","denoising","style-transfer","captioning","video-gen","temporal",
]);
async function callHuggingFace(capability, fileBytes, fileMime, params, env) {
  const key   = env.HF_API_KEY || "";
  if (!key) return { success: false, error: "huggingface:no_key" };
  const model   = HF_MODELS[capability] || HF_MODELS["basic-processing"];
  const baseUrl = `https://api-inference.huggingface.co/models/${model}`;
  let payload, contentType;
  if (HF_IMAGE_INPUT.has(capability) && fileBytes) {
    payload     = fileBytes;
    contentType = "application/octet-stream";
  } else {
    const prompt = params.prompt || "ultra detailed professional 4K studio photograph";
    payload     = JSON.stringify({ inputs: prompt, parameters: { width: TARGET_W, height: TARGET_H, num_inference_steps: 30, guidance_scale: 7.5 } });
    contentType = "application/json";
  }
  let r = await fetch(baseUrl, {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": contentType },
    body: payload,
  });
  // HF returns 503 when model is loading — retry once
  if (r.status === 503) {
    await sleep(8000);
    r = await fetch(baseUrl, {
      method: "POST",
      headers: { "Authorization": `Bearer ${key}`, "Content-Type": contentType },
      body: payload,
    });
  }
  if (!r.ok) return { success: false, error: `huggingface:${r.status}` };
  const ct  = r.headers.get("content-type") || "image/png";
  let raw;
  if (ct.includes("application/json")) {
    const data = await r.json();
    if (Array.isArray(data) && data[0]?.blob) {
      raw = base64Decode(data[0].blob);
    } else {
      return { success: false, error: "huggingface:unexpected_json" };
    }
  } else {
    raw = await r.arrayBuffer();
  }
  if (!raw || (raw.byteLength || raw.length) < 100) return { success: false, error: "huggingface:empty_response" };
  const b64 = arrayBufferToBase64(raw instanceof ArrayBuffer ? raw : raw.buffer || raw);
  return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { model } };
}

// ── Gemini ───────────────────────────────────────────────────────────────────
async function callGemini(capability, fileBytes, fileMime, params, env) {
  const key  = env.GEMINI_API_KEY || "";
  if (!key) return { success: false, error: "gemini:no_key" };
  const base = "https://generativelanguage.googleapis.com/v1beta/models";
  if (capability === "image-gen" || capability === "basic-processing" || capability === "style-transfer" || capability === "restoration") {
    // Imagen 3
    const prompt = params.prompt || "professional studio photograph ultra detailed 4K";
    const r = await fetch(`${base}/imagen-3.0-generate-001:predict?key=${key}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instances: [{ prompt }], parameters: { sampleCount: 1, aspectRatio: "16:9", outputOptions: { mimeType: "image/png" } } }),
    });
    if (!r.ok) return { success: false, error: `gemini:${r.status}` };
    const data = await r.json();
    const b64  = data.predictions?.[0]?.bytesBase64Encoded;
    if (!b64) return { success: false, error: "gemini:no_image" };
    return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { model: "imagen-3.0-generate-001" } };
  }
  // Vision / captioning
  const prompt = params.prompt || `Analyze this image for ${capability}. Be detailed.`;
  const parts  = [{ text: prompt }];
  if (fileBytes) parts.push({ inlineData: { mimeType: fileMime || "image/jpeg", data: arrayBufferToBase64(fileBytes) } });
  const r = await fetch(`${base}/gemini-2.0-flash-exp:generateContent?key=${key}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contents: [{ parts }] }),
  });
  if (!r.ok) return { success: false, error: `gemini:${r.status}` };
  const data = await r.json();
  const text  = data.candidates?.[0]?.content?.parts?.[0]?.text || "";
  return { success: true, output: `data:text/plain;charset=utf-8,${encodeURIComponent(text.slice(0, 500))}`, resolution: "N/A", metadata: { caption: text } };
}

// ── Groq ─────────────────────────────────────────────────────────────────────
async function callGroq(capability, fileBytes, fileMime, params, env) {
  const key  = env.GROQ_API_KEY || "";
  if (!key) return { success: false, error: "groq:no_key" };
  const model   = fileBytes ? "llama-3.2-90b-vision-preview" : "llama-3.3-70b-versatile";
  const prompt  = params.prompt || `Process this for ${capability}. Output professional studio quality.`;
  const content = [];
  if (fileBytes) content.push({ type: "image_url", image_url: { url: `data:${fileMime};base64,${arrayBufferToBase64(fileBytes)}` } });
  content.push({ type: "text", text: prompt });
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages: [{ role: "user", content }], max_tokens: 1024 }),
  });
  if (!r.ok) return { success: false, error: `groq:${r.status}` };
  const data = await r.json();
  const text  = data.choices?.[0]?.message?.content || "";
  return { success: true, output: `data:text/plain;charset=utf-8,${encodeURIComponent(text.slice(0, 500))}`, resolution: "N/A", metadata: { model } };
}

// ── Mistral ───────────────────────────────────────────────────────────────────
async function callMistral(capability, fileBytes, fileMime, params, env) {
  const key   = env.MISTRAL_API_KEY || "";
  if (!key) return { success: false, error: "mistral:no_key" };
  const model   = fileBytes ? "pixtral-large-latest" : "mistral-large-latest";
  const prompt  = params.prompt || `Professional image processing AI: analyze for '${capability}'.`;
  const content = fileBytes
    ? [{ type: "image_url", image_url: `data:${fileMime};base64,${arrayBufferToBase64(fileBytes)}` }, { type: "text", text: prompt }]
    : [{ type: "text", text: prompt }];
  const r = await fetch("https://api.mistral.ai/v1/chat/completions", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages: [{ role: "user", content }], max_tokens: 1024 }),
  });
  if (!r.ok) return { success: false, error: `mistral:${r.status}` };
  const data = await r.json();
  const text  = data.choices?.[0]?.message?.content || "";
  return { success: true, output: `data:text/plain;charset=utf-8,${encodeURIComponent(text.slice(0, 500))}`, resolution: "N/A", metadata: { model } };
}

// ── OpenRouter ────────────────────────────────────────────────────────────────
const OR_MODELS = {
  "image-gen":"google/gemini-flash-1.5","captioning":"google/gemini-flash-1.5",
  "style-transfer":"anthropic/claude-3.5-sonnet","visualization":"google/gemini-flash-1.5",
  "basic-processing":"google/gemini-flash-1.5",
};
async function callOpenRouter(capability, fileBytes, fileMime, params, env) {
  const key  = env.OPENROUTER_API_KEY || "";
  if (!key) return { success: false, error: "openrouter:no_key" };
  const model   = OR_MODELS[capability] || "google/gemini-flash-1.5";
  const prompt  = params.prompt || `Professional AI studio processing: ${capability}. 4K quality.`;
  const content = [];
  if (fileBytes) content.push({ type: "image_url", image_url: { url: `data:${fileMime};base64,${arrayBufferToBase64(fileBytes)}` } });
  content.push({ type: "text", text: prompt });
  const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "HTTP-Referer": "https://luminorbit.app", "X-Title": "Luminorbit", "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages: [{ role: "user", content }] }),
  });
  if (!r.ok) return { success: false, error: `openrouter:${r.status}` };
  const data = await r.json();
  const text  = data.choices?.[0]?.message?.content || "";
  return { success: true, output: `data:text/plain;charset=utf-8,${encodeURIComponent(text.slice(0, 500))}`, resolution: "N/A", metadata: { model } };
}

// ── Segmind ───────────────────────────────────────────────────────────────────
const SM_ENDPOINTS = {
  "image-gen":"sdxl1.0-txt2img","segmentation":"segment-anything",
  "inpainting":"stable-diffusion-inpainting","style-transfer":"sdxl1.0-txt2img",
  "restoration":"sdxl1.0-txt2img","face-processing":"sdxl1.0-txt2img",
  "super-resolution":"sdxl1.0-txt2img","denoising":"sdxl1.0-txt2img",
  "basic-processing":"sdxl1.0-txt2img","controlnet":"controlnet-canny",
};
async function callSegmind(capability, fileBytes, fileMime, params, env) {
  const key  = env.SEGMIND_API_KEY || "";
  if (!key) return { success: false, error: "segmind:no_key" };
  const ep     = SM_ENDPOINTS[capability] || "sdxl1.0-txt2img";
  const prompt = params.prompt || "ultra detailed professional studio photo 4K";
  let body;
  if (ep === "segment-anything" && fileBytes) {
    body = { image: arrayBufferToBase64(fileBytes), output_type: "mask" };
  } else if (ep === "stable-diffusion-inpainting" && fileBytes) {
    body = { prompt, image: arrayBufferToBase64(fileBytes), strength: params.strength || 0.8, width: TARGET_W, height: TARGET_H, samples: 1, num_inference_steps: 30, guidance_scale: 7.5 };
  } else {
    body = { prompt, negative_prompt: "blurry, low quality, watermark", width: TARGET_W, height: TARGET_H, samples: 1, num_inference_steps: 30, guidance_scale: 7.5, seed: params.seed || -1 };
  }
  const r = await fetch(`https://api.segmind.com/v1/${ep}`, {
    method: "POST",
    headers: { "x-api-key": key, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) return { success: false, error: `segmind:${r.status}` };
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("image")) {
    const raw = await r.arrayBuffer();
    const b64 = arrayBufferToBase64(raw);
    return { success: true, output: `data:${ct};base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { ep } };
  }
  const data = await r.json();
  const b64  = data.image || data.data || "";
  if (!b64) return { success: false, error: "segmind:no_image" };
  return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { ep } };
}

// ── Krea ──────────────────────────────────────────────────────────────────────
async function callKrea(capability, fileBytes, fileMime, params, env) {
  const key  = env.KREA_API_KEY || "";
  if (!key) return { success: false, error: "krea:no_key" };
  const base    = "https://api.krea.ai/v1";
  const prompt  = params.prompt || "ultra detailed professional studio quality 4K photograph";
  const headers = { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" };
  let ep, body;
  if ((capability === "super-resolution" || capability === "restoration" || capability === "denoising") && fileBytes) {
    ep   = `${base}/images/upscale`;
    body = { image: arrayBufferToBase64(fileBytes), scale: 4, output_size: { width: TARGET_W, height: TARGET_H } };
  } else if (capability === "face-processing" && fileBytes) {
    ep   = `${base}/images/enhance`;
    body = { image: arrayBufferToBase64(fileBytes), enhance_face: true, output_size: { width: TARGET_W, height: TARGET_H } };
  } else {
    ep   = `${base}/images/generate`;
    body = { prompt, model: "flux-pro", width: TARGET_W, height: TARGET_H, num_images: 1, output_format: "png" };
  }
  const r = await fetch(ep, { method: "POST", headers, body: JSON.stringify(body) });
  if (!r.ok) return { success: false, error: `krea:${r.status}` };
  const data    = await r.json();
  const imgData = data.images?.[0]?.url || data.images?.[0]?.base64 || data.image || data.url || "";
  if (!imgData) return { success: false, error: "krea:no_image" };
  if (imgData.startsWith("http")) {
  const ir  = await fetch(imgData);
    const raw = await ir.arrayBuffer();
    const b64 = arrayBufferToBase64(raw);
    return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}` };
  }
  return { success: true, output: `data:image/png;base64,${imgData}`, resolution: `${TARGET_W}x${TARGET_H}` };
}

// ── DeepAI ────────────────────────────────────────────────────────────────────
const DA_ENDPOINTS = {
  "super-resolution":"torch-srgan","face-processing":"face-recognition",
  "restoration":"image-editor","inpainting":"image-editor","image-gen":"text2img",
  "denoising":"torch-srgan","image-enhancement":"waifu2x","style-transfer":"fast-style-transfer",
  "basic-processing":"image-editor",
};
async function callDeepAI(capability, fileBytes, fileMime, params, env) {
  const key  = env.DEEPAI_API_KEY || "";
  if (!key) return { success: false, error: "deepai:no_key" };
  const ep     = DA_ENDPOINTS[capability] || "image-editor";
  const base   = "https://api.deepai.org/api";
  let r;
  if (fileBytes && capability !== "image-gen") {
    // DeepAI expects multipart
    const fd = new FormData();
    fd.append("image", new Blob([fileBytes], { type: fileMime || "image/jpeg" }), "input.jpg");
    if (ep === "fast-style-transfer") fd.append("style", params.style || "mosaic");
    r = await fetch(`${base}/${ep}`, { method: "POST", headers: { "api-key": key }, body: fd });
  } else {
    const prompt = params.prompt || "ultra detailed professional studio photograph 4K";
    const fd     = new FormData();
    fd.append("text", prompt);
    fd.append("grid_size", "1");
    r = await fetch(`${base}/${ep}`, { method: "POST", headers: { "api-key": key }, body: fd });
  }
  if (!r.ok) return { success: false, error: `deepai:${r.status}` };
  const data    = await r.json();
  const outUrl  = data.output_url || "";
  if (!outUrl) return { success: false, error: "deepai:no_output_url" };
  const ir  = await fetch(outUrl);
  const raw = await ir.arrayBuffer();
  const ct  = ir.headers.get("content-type") || "image/jpeg";
  const b64 = arrayBufferToBase64(raw);
  return { success: true, output: `data:${ct};base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { ep } };
}

// ── Cloudflare AI ─────────────────────────────────────────────────────────────
const CF_MODELS = {
  "super-resolution":"@cf/microsoft/realsr-esrgan-x4",
  "segmentation":    "@cf/facebook/detr-resnet-50-panoptic",
  "inpainting":      "@cf/stabilityai/stable-diffusion-xl-base-1.0",
  "image-gen":       "@cf/stabilityai/stable-diffusion-xl-base-1.0",
  "denoising":       "@cf/microsoft/realsr-esrgan-x4",
  "temporal":        "@cf/stabilityai/stable-video-diffusion-img2vid-xt",
  "audio-extraction":"@cf/openai/whisper",
  "basic-processing":"@cf/stabilityai/stable-diffusion-xl-base-1.0",
  "color-matching":  "@cf/stabilityai/stable-diffusion-xl-base-1.0",
};
async function callCFAI(capability, fileBytes, fileMime, params, env) {
  const token = env.CF_AI_TOKEN || "";
  const acct  = env.CF_ACCOUNT_ID || "";
  if (!token || !acct) return { success: false, error: "cloudflare_ai:no_credentials" };
  const model = CF_MODELS[capability] || CF_MODELS["basic-processing"];
  const url   = `https://api.cloudflare.com/client/v4/accounts/${acct}/ai/run/${model}`;
  let body;
  if (capability === "audio-extraction" && fileBytes) {
    body = { audio: Array.from(new Uint8Array(fileBytes)) };
  } else if ((capability === "super-resolution" || capability === "segmentation" || capability === "denoising") && fileBytes) {
    body = { image: Array.from(new Uint8Array(fileBytes)) };
  } else {
    const prompt = params.prompt || "ultra-detailed professional photo 4K";
    body = { prompt, width: TARGET_W, height: TARGET_H, num_steps: 30 };
  }
  const r = await fetch(url, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) return { success: false, error: `cloudflare_ai:${r.status}` };
  const data = await r.json();
  const b64  = data.result?.image || data.result?.data;
  if (!b64) return { success: false, error: "cloudflare_ai:no_image" };
  return { success: true, output: `data:image/png;base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { model } };
}

// ── Pexels ────────────────────────────────────────────────────────────────────
async function callPexels(capability, fileBytes, fileMime, params, env) {
  const key     = env.PEXELS_API_KEY || "";
  if (!key) return { success: false, error: "pexels:no_key" };
  const query   = params.prompt || "professional studio background 4K";
  const isVideo = ["video-gen","temporal","compression","audio-extraction","audio-sync"].includes(capability);
  if (isVideo) {
    const r = await fetch(`https://api.pexels.com/videos/search?query=${encodeURIComponent(query)}&per_page=1&size=large`, { headers: { "Authorization": key } });
    if (!r.ok) return { success: false, error: `pexels:${r.status}` };
    const data   = await r.json();
    const videos = data.videos || [];
    if (!videos.length) return { success: false, error: "pexels:no_results" };
    const files  = (videos[0].video_files || []).sort((a, b) => (b.width || 0) - (a.width || 0));
    return { success: true, output: files[0].link, resolution: `${files[0].width || TARGET_W}x${files[0].height || TARGET_H}`, metadata: { source: "pexels" } };
  }
  const r = await fetch(`https://api.pexels.com/v1/search?query=${encodeURIComponent(query)}&per_page=1&size=large`, { headers: { "Authorization": key } });
  if (!r.ok) return { success: false, error: `pexels:${r.status}` };
  const data   = await r.json();
  const photos = data.photos || [];
  if (!photos.length) return { success: false, error: "pexels:no_results" };
  const imgUrl  = photos[0].src.original || photos[0].src.large2x || "";
  const ir      = await fetch(imgUrl);
  const raw     = await ir.arrayBuffer();
  const ct      = ir.headers.get("content-type") || "image/jpeg";
  const b64     = arrayBufferToBase64(raw);
  return { success: true, output: `data:${ct};base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { source: "pexels" } };
}

// ── Unsplash ──────────────────────────────────────────────────────────────────
async function callUnsplash(capability, fileBytes, fileMime, params, env) {
  const key   = env.UNSPLASH_API_KEY || "";
  if (!key) return { success: false, error: "unsplash:no_key" };
  const query = params.prompt || "professional studio photography 4K";
  const r     = await fetch(`https://api.unsplash.com/search/photos?query=${encodeURIComponent(query)}&per_page=1&orientation=landscape`, {
    headers: { "Authorization": `Client-ID ${key}` },
  });
  if (!r.ok) return { success: false, error: `unsplash:${r.status}` };
  const data    = await r.json();
  const results = data.results || [];
  if (!results.length) return { success: false, error: "unsplash:no_results" };
  const rawUrl  = `${results[0].urls.raw}&w=${TARGET_W}&h=${TARGET_H}&fit=crop&fm=png&q=95`;
  const ir      = await fetch(rawUrl);
  const raw     = await ir.arrayBuffer();
  const ct      = ir.headers.get("content-type") || "image/jpeg";
  const b64     = arrayBufferToBase64(raw);
  const author  = results[0].user?.name || "";
  return { success: true, output: `data:${ct};base64,${b64}`, resolution: `${TARGET_W}x${TARGET_H}`, metadata: { author, source: "unsplash" } };
}

// ── Emergency fallback ────────────────────────────────────────────────────────
async function emergencyFallback(tool, capability, params, env) {
  const key    = env.POLLINATIONS_API_KEY || "";
  const prompt = params.prompt || `Professional ${tool} 4K studio quality`;
  const url    = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=${TARGET_W}&height=${TARGET_H}&model=flux&nologo=true&enhance=true`;
  const headers = key ? { "Authorization": `Bearer ${key}` } : {};
  const r = await fetch(url, { headers });
  if (!r.ok) return { success: false, error: `emergency:${r.status}` };
  const raw = await r.arrayBuffer();
  if (raw.byteLength < 1000) return { success: false, error: "emergency:tiny_payload" };
  const ct  = r.headers.get("content-type") || "image/jpeg";
  const b64 = arrayBufferToBase64(raw);
  return { success: true, output: `data:${ct};base64,${b64}` };
}

// ═══════════════════════════════════════════════════════════════════════════════
// §9  UTILITIES
// ═══════════════════════════════════════════════════════════════════════════════

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function randomId() {
  return Math.random().toString(36).slice(2, 10);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function withTimeout(promise, ms, errorMsg) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(errorMsg)), ms);
  });
  try {
    const result = await Promise.race([promise, timeout]);
    clearTimeout(timer);
    return result;
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

function arrayBufferToBase64(buffer) {
  // CF Workers have btoa but need Uint8Array → string
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  let binary  = "";
  const chunk = 8192;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64Decode(b64) {
  // Returns Uint8Array
  const binary = atob(b64);
  const bytes  = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

"""

_WRANGLER_TOML = """\
# wrangler.toml — Cloudflare Workers deployment config for Luminorbit v22
#
# SETUP:
#   1. npm install -g wrangler
#   2. wrangler login
#   3. wrangler kv:namespace create LUMINORBIT_JOBS
#      → copy the id output below into [[kv_namespaces]] id field
#   4. wrangler secret put API_SECRET
#   5. wrangler secret put ALLOWED_ORIGINS   (e.g. "https://yourname.github.io")
#   6. (Optional) wrangler secret put POLLINATIONS_API_KEY
#      wrangler secret put TOGETHER_API_KEY
#      wrangler secret put HF_API_KEY
#      wrangler secret put GEMINI_API_KEY
#      wrangler secret put GROQ_API_KEY
#      wrangler secret put MISTRAL_API_KEY
#      wrangler secret put OPENROUTER_API_KEY
#      wrangler secret put SEGMIND_API_KEY
#      wrangler secret put KREA_API_KEY
#      wrangler secret put DEEPAI_API_KEY
#      wrangler secret put CF_AI_TOKEN
#      wrangler secret put CF_ACCOUNT_ID
#      wrangler secret put PEXELS_API_KEY
#      wrangler secret put UNSPLASH_API_KEY
#   7. wrangler deploy
#
# After deploy, set window.LUMINORBIT_API_URL in your HTML to:
#   'https://luminorbit.YOUR_SUBDOMAIN.workers.dev'

name = "luminorbit"
main = "worker.js"
compatibility_date = "2024-01-01"

# KV Namespace for job state (async heavy tasks)
# Run: wrangler kv:namespace create LUMINORBIT_JOBS
# Then paste the resulting id below.
[[kv_namespaces]]
binding = "LUMINORBIT_JOBS"
id = "REPLACE_WITH_YOUR_KV_NAMESPACE_ID"

# Routes — optional custom domain
# [[routes]]
# pattern = "api.yourdomain.com/*"
# zone_name = "yourdomain.com"

# Environment variables (non-secret)
[vars]
APP_ENV = "production"

"""

_RENDER_YAML = """\
services:
  - type: web
    name: luminorbit-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn luminorbit_backend_FIXED:app --host 0.0.0.0 --port $PORT --workers 1
    plan: free
    healthCheckPath: /health
    envVars:
      - key: APP_ENV
        value: production
      - key: PORT
        value: 10000
      - key: WORKERS
        value: 1
      - key: API_SECRET
        sync: false
      - key: ALLOWED_ORIGINS
        sync: false
      - key: CLOUDINARY_CLOUD_ID
        value: ""
      - key: CLOUDINARY_UPLOAD_PRESET
        value: luminorbit_unsigned
      - key: REDIS_URL
        value: redis://localhost:6379/0
      - key: RATE_LIMIT_IP
        value: "20/minute"
      - key: RATE_LIMIT_BURST
        value: "60/minute"
      - key: DAILY_REQUEST_LIMIT
        value: "200"
"""

def _run_setup():
    here = pathlib.Path(__file__).parent
    files = {
        "requirements.txt": _REQUIREMENTS_TXT,
        "render.yaml":      _RENDER_YAML,
        "wrangler.toml":    _WRANGLER_TOML,
    }
    for name, body in files.items():
        p = here / name
        p.write_text(body, encoding="utf-8")
        print(f"  ✓ wrote {p}")
    # Write worker.js from the fully embedded content
    wjs = here / "worker.js"
    wjs.write_text(_WORKER_JS_EMBED.strip() + "\n", encoding="utf-8")
    print(f"  ✓ wrote {wjs}")
    print()
    print("Setup complete. Next steps:")
    print("  Render.com: git push → connect repo → set env vars → deploy")
    print("  CF Workers: wrangler kv:namespace create LUMINORBIT_JOBS → wrangler deploy")
    print("  Update LUMINORBIT_API_URL in your HTML to your backend URL")
    print()
    print("Full guide: see the comments at the top of this file (DEPLOY GUIDE section)")

if "--setup" in sys.argv:
    _run_setup()
    sys.exit(0)

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

# ── Structured JSON logging ──────────────────────────────────────────────────
try:
    from pythonjsonlogger import jsonlogger
    _JSON_LOGGING = True
except ImportError:
    _JSON_LOGGING = False

def _setup_logging(app_env: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    if _JSON_LOGGING and app_env == "production":
        fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ"
        )
        handler.setFormatter(fmt)
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return logging.getLogger("luminorbit")

# Temporary logger for pre-settings use
logger = logging.getLogger("luminorbit")

# ── Rate limiting (REQUIRED) ─────────────────────────────────────────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    _RATE_LIMIT_AVAILABLE = True
except ImportError:
    _RATE_LIMIT_AVAILABLE = False

# ── Redis (REQUIRED in production) ───────────────────────────────────────────
try:
    import redis as _redis_module
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# §2  SETTINGS — Strict validation at startup
# ═══════════════════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    # ── APP ────────────────────────────────────────────────────
    APP_ENV:    str = "production"
    API_SECRET: str = ""
    PORT:       int = 8000
    WORKERS:    int = 1

    # ── CORS — comma-separated allowed origins ──────────────────
    # Leave empty to require explicit configuration in production.
    # Example: "https://yourusername.github.io,https://yourdomain.dpdns.org"
    ALLOWED_ORIGINS: str = ""

    # ── OUTPUT ─────────────────────────────────────────────────
    OUTPUT_4K_WIDTH:  int = 3840
    OUTPUT_4K_HEIGHT: int = 2160
    JPEG_QUALITY:     int = 95
    PNG_COMPRESS:     int = 6

    # ── TIMEOUTS ───────────────────────────────────────────────
    REQUEST_TIMEOUT:  int = 120
    PROVIDER_TIMEOUT: int = 13
    MAX_FILE_MB:      int = 50
      # ── RATE LIMITS ────────────────────────────────────────────
    RATE_LIMIT_IP:    str = "10/minute"   # per-IP on /api/process
    RATE_LIMIT_BURST: str = "30/minute"   # global burst cap

    # ── USAGE LIMITS ───────────────────────────────────────────
    DAILY_TOKEN_LIMIT:      int = 500_000
    DAILY_REQUEST_LIMIT:    int = 200
    PROVIDER_REQUEST_LIMIT: int = 500
    GLOBAL_KILL_SWITCH:     bool = False

    # ── VIDEO SAFETY ───────────────────────────────────────────
    VIDEO_MAX_DURATION_S: int  = 20
    VIDEO_MAX_WIDTH:      int  = 3840
    VIDEO_MAX_HEIGHT:     int  = 2160
    VIDEO_MAX_FPS:        int  = 60
    VIDEO_AUTO_COMPRESS:  bool = True

    # ── FILE VALIDATION ────────────────────────────────────────
    MAX_IMAGE_WIDTH:  int = 16000
    MAX_IMAGE_HEIGHT: int = 16000

    # ── CLOUDINARY ─────────────────────────────────────────────
    # CLOUDINARY_CLOUD_ID must be the cloud NAME (e.g. "my-studio"),
    # NOT the numeric account ID (e.g. 465592115187579).
    CLOUDINARY_CLOUD_ID:      str = ""
    CLOUDINARY_UPLOAD_PRESET: str = "luminorbit_unsigned"
    CLOUDINARY_API_KEY:       str = ""
    CLOUDINARY_API_SECRET:    str = ""

    # ── PROVIDER API KEYS ──────────────────────────────────────
    POLLINATIONS_API_KEY: str = "sk_bBl03mf55TNrWCLFEPbemNMEIa3c6ZoX"
    KREA_API_KEY:         str = "c6bdc32d-6c16-465f-9a98-9a1c47f219e2:s7Z2Oq8x8hK9edlNBvFp6yI5T1XrLBkt"
    TOGETHER_API_KEY:     str = "tgp_v1_lwHnHeTk-ooHH-2V5ne_NTPEe_AqnnmKJ4yvU_YLuso"
    HF_API_KEY:           str = "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"
    DEEPAI_API_KEY:       str = "6eb82984-f653-419c-8a3a-7c5ff2a225dd"
    PIXAZO_API_KEY:       str = "f882fc20c4264c48b0400ca4b9b4bdc"
    PEXELS_API_KEY:       str = "gGaEZhdac0414O11gGHDKTnrjFtjprZHP2PZey08A2JbH7qTTMAzECbw"
    UNSPLASH_API_KEY:     str = "GIQkAqSZ9DT704ZuNMoCQMeZemETSOoti21v0xo1NxU"
    OPENROUTER_API_KEY:   str = "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"
    SEGMIND_API_KEY:      str = "SG_f0c0391841af5add"
    CF_AI_TOKEN:          str = "cfut_l5I38Yop3VrVX4493Tp2dwqwbypI2EChxXXl5Zula947b3c0"
    CF_ACCOUNT_ID:        str = "84fc2cd2ac091f95e12ae1960c601fe8"
    GROQ_API_KEY:         str = "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"
    GEMINI_API_KEY:       str = "AIzaSyA9rSbsrmOicBN-KOyL7jVUOmf5RQmz4Kc"
    MISTRAL_API_KEY:      str = "qKwxfw5rabE7yk217B4zWKmKGKQlAL7Y"

    # ── PROVIDER SCORING ───────────────────────────────────────
    PROVIDER_SCORE_DECAY: float = 0.9

    # ── REDIS ──────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def allowed_origins_list(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        if not origins:
            # Dev mode: allow all. Production must set ALLOWED_ORIGINS env var.
            if self.APP_ENV != "production":
                return ["*"]
            return []  # Production with no origins = block all cross-origin (will be caught by validate_production)
        return origins

    def validate_production(self) -> List[str]:
        """Returns list of fatal configuration errors for production."""
        errors: List[str] = []
        if self.APP_ENV == "production":
            # SEC-1: API_SECRET required in production
            if not self.API_SECRET:
                errors.append(
                    "API_SECRET is not set. All endpoints will be unauthenticated. "
                    "Set API_SECRET=<random-secret> in your environment."
                )
            # SEC-6: Cloudinary cloud name must not be numeric or the placeholder default
            if self.CLOUDINARY_CLOUD_ID and self.CLOUDINARY_CLOUD_ID.isdigit():
                errors.append(
                    f"CLOUDINARY_CLOUD_ID='{self.CLOUDINARY_CLOUD_ID}' looks like a numeric "
                    "account ID — it must be your cloud NAME (e.g. 'my-studio'). "
                    "Find it: Cloudinary Dashboard → Settings → Account → Cloud Name"
                )
            if self.CLOUDINARY_CLOUD_ID.lower() == "luminorbit":
                errors.append(
                    "CLOUDINARY_CLOUD_ID is still set to the placeholder 'Luminorbit'. "
                    "Set it to your actual Cloudinary cloud name, or leave it empty to use data-URL fallback."
                )
            if not self.ALLOWED_ORIGINS or self.ALLOWED_ORIGINS.strip() == "*":
                errors.append(
                    "ALLOWED_ORIGINS must be set to your frontend domain(s) in production. "
                    "Example: ALLOWED_ORIGINS=https://yourusername.github.io"
                )
            if not _RATE_LIMIT_AVAILABLE:
                errors.append("slowapi is required in production: pip install slowapi")
            if not _REDIS_AVAILABLE:
                errors.append("redis package is required in production: pip install redis")
        return errors

    def log_startup(self):
        key_map = {
            "POLLINATIONS_API_KEY": self.POLLINATIONS_API_KEY,
            "KREA_API_KEY":         self.KREA_API_KEY,
            "TOGETHER_API_KEY":     self.TOGETHER_API_KEY,
            "HF_API_KEY":           self.HF_API_KEY,
            "DEEPAI_API_KEY":       self.DEEPAI_API_KEY,
            "SEGMIND_API_KEY":      self.SEGMIND_API_KEY,
            "CF_AI_TOKEN":          self.CF_AI_TOKEN,
            "GEMINI_API_KEY":       self.GEMINI_API_KEY,
            "GROQ_API_KEY":         self.GROQ_API_KEY,
            "MISTRAL_API_KEY":      self.MISTRAL_API_KEY,
            "OPENROUTER_API_KEY":   self.OPENROUTER_API_KEY,
            "PEXELS_API_KEY":       self.PEXELS_API_KEY,
            "UNSPLASH_API_KEY":     self.UNSPLASH_API_KEY,
            "CLOUDINARY_CLOUD_ID":  self.CLOUDINARY_CLOUD_ID,
        }
        ok  = [k for k, v in key_map.items() if v]
        mis = [k for k, v in key_map.items() if not v]
        # Never log key values — only which keys are present
        logger.info("[startup] env=%s configured=%d missing=%d origins=%s",
                    self.APP_ENV, len(ok), len(mis), self.allowed_origins_list)
        if mis:
            logger.warning("[startup] Missing provider keys: %s — those providers will be skipped", mis)


# ═══════════════════════════════════════════════════════════════════════════════
# §3  SECURITY MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add HSTS, CSP, X-Frame-Options, X-Content-Type-Options."""
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://res.cloudinary.com https://image.pollinations.ai; "
            "connect-src 'self' https://api.cloudinary.com https://res.cloudinary.com "
            "https://image.pollinations.ai https://api.together.xyz https://api.groq.com "
            "https://api.mistral.ai https://openrouter.ai https://generativelanguage.googleapis.com "
            "https://api.huggingface.co https://api-inference.huggingface.co https://api.deepai.org "
            "https://api.segmind.com https://api.krea.ai https://api.pexels.com "
            "https://api.unsplash.com https://api.cloudflare.com; "
            "frame-ancestors 'none';"
        )
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


# ═══════════════════════════════════════════════════════════════════════════════
# §A  TOKEN + COST CONTROL
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class _UsageBucket:
    tokens:   int = 0
    requests: int = 0
    day:      str = ""

class UsageTracker:
    def __init__(self, settings: "Settings"):
        self.s = settings
        self._user: Dict[str, _UsageBucket]     = {}
        self._provider: Dict[str, _UsageBucket] = {}
        self._lock = asyncio.Lock()

    def _today(self) -> str:
        return datetime.date.today().isoformat()

    def _bucket(self, store: Dict, key: str) -> _UsageBucket:
        today = self._today()
        b = store.get(key)
        if b is None or b.day != today:
            b = _UsageBucket(day=today)
            store[key] = b
        return b

    async def check_and_record(self, user_id: str, provider: str, tokens: int = 0) -> Tuple[bool, str]:
        if self.s.GLOBAL_KILL_SWITCH:
            return False, "global_kill_switch"
        async with self._lock:
            ub = self._bucket(self._user, user_id)
            pb = self._bucket(self._provider, provider)
            if ub.requests >= self.s.DAILY_REQUEST_LIMIT:
                return False, f"user_daily_request_limit:{self.s.DAILY_REQUEST_LIMIT}"
            if ub.tokens + tokens > self.s.DAILY_TOKEN_LIMIT:
                return False, f"user_daily_token_limit:{self.s.DAILY_TOKEN_LIMIT}"
            if pb.requests >= self.s.PROVIDER_REQUEST_LIMIT:
                return False, f"provider_daily_limit:{provider}:{self.s.PROVIDER_REQUEST_LIMIT}"
            ub.requests += 1; ub.tokens += tokens; pb.requests += 1
            return True, "ok"

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        async with self._lock:
            b = self._bucket(self._user, user_id)
            return {"user_id": user_id, "day": b.day, "requests": b.requests,
                    "tokens": b.tokens, "req_limit": self.s.DAILY_REQUEST_LIMIT,
                    "tok_limit": self.s.DAILY_TOKEN_LIMIT}


# ═══════════════════════════════════════════════════════════════════════════════
# §B  PROVIDER SCORING
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProviderScore:
    name:             str
    score:            float = 1.0
    avg_latency_ms:   float = 0.0
    total_calls:      int   = 0
    failures:         int   = 0
    last_failure_ts:  float = 0.0
    rate_limited:     bool  = False
    rate_limit_until: float = 0.0

    def is_rate_limited(self) -> bool:
        if self.rate_limited and time.time() < self.rate_limit_until:
            return True
        if time.time() >= self.rate_limit_until:
            self.rate_limited = False
        return False

    def is_recently_failed(self, window_s: int = 60) -> bool:
        return self.failures > 0 and time.time() - self.last_failure_ts < window_s

    def record_success(self, latency_ms: float, decay: float = 0.9):
        self.total_calls += 1
        self.avg_latency_ms = self.avg_latency_ms * 0.8 + latency_ms * 0.2
        self.score = min(1.0, self.score / decay)

    def record_failure(self, decay: float = 0.9):
        self.total_calls += 1; self.failures += 1
        self.last_failure_ts = time.time()
        self.score = max(0.0, self.score * decay)

    def record_rate_limit(self, backoff_s: int = 120):
        self.rate_limited = True
        self.rate_limit_until = time.time() + backoff_s
        self.score = max(0.0, self.score * 0.5)

    def routing_priority(self) -> float:
        if self.is_rate_limited():
            return 9999.0
        return (1.0 - self.score) + self.avg_latency_ms / 30_000


class ProviderScoreRegistry:
    def __init__(self, decay: float = 0.9):
        self._scores: Dict[str, ProviderScore] = {}
        self._decay = decay
        self._lock  = asyncio.Lock()

    def _ensure(self, name: str) -> ProviderScore:
        if name not in self._scores:
            self._scores[name] = ProviderScore(name=name)
        return self._scores[name]

    async def record_success(self, name: str, latency_ms: float):
        async with self._lock:
            self._ensure(name).record_success(latency_ms, self._decay)

    async def record_failure(self, name: str):
        async with self._lock:
            self._ensure(name).record_failure(self._decay)

    async def record_rate_limit(self, name: str, backoff_s: int = 120):
        async with self._lock:
            self._ensure(name).record_rate_limit(backoff_s)

    async def sort_by_score(self, names: List[str]) -> List[str]:
        async with self._lock:
            scored = [(n, self._ensure(n).routing_priority()) for n in names]
            return [n for n, _ in sorted(scored, key=lambda x: x[1])]

    async def should_skip(self, name: str) -> Tuple[bool, str]:
        async with self._lock:
            s = self._ensure(name)
            if s.is_rate_limited():
                return True, "rate_limited"
            if s.is_recently_failed(30) and s.score < 0.2:
                return True, "recently_failed_low_score"
            return False, ""

    async def dump(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                n: {"score": round(s.score, 3), "avg_latency_ms": round(s.avg_latency_ms),
                    "total_calls": s.total_calls, "failures": s.failures,
                    "rate_limited": s.is_rate_limited(),
                    "routing_priority": round(s.routing_priority(), 3)}
                for n, s in self._scores.items()
            }


# ═══════════════════════════════════════════════════════════════════════════════
# §C  FILE VALIDATION LAYER
# ═══════════════════════════════════════════════════════════════════════════════

_MAGIC: Dict[str, List[Tuple[int, bytes]]] = {
    "image/jpeg":      [(0, b"\xff\xd8\xff")],
    "image/png":       [(0, b"\x89PNG\r\n\x1a\n")],
    "image/webp":      [(0, b"RIFF"), (8, b"WEBP")],
    "image/gif":       [(0, b"GIF87a"), (0, b"GIF89a")],
    "image/bmp":       [(0, b"BM")],
    "video/mp4":       [(4, b"ftyp")],
    "video/webm":      [(0, b"\x1a\x45\xdf\xa3")],
    "video/quicktime": [(4, b"ftyp"), (4, b"moov")],
}
_ALLOWED_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/gif", "image/bmp", "image/tiff",
    "video/mp4", "video/webm", "video/quicktime", "video/mpeg",
}

class FileValidationError(ValueError):
    pass

def _check_magic(data: bytes, mime: str) -> bool:
    sigs = _MAGIC.get(mime)
    if not sigs:
        return True
    for offset, magic in sigs:
        if data[offset:offset+len(magic)] == magic:
            return True
    return False

def validate_file_bytes(data: bytes, declared_mime: str, max_bytes: int,
                        max_img_w: int = 16000, max_img_h: int = 16000) -> Tuple[str, str]:
    if not data:
        raise FileValidationError("empty_file")
    if len(data) > max_bytes:
        raise FileValidationError(f"file_too_large:{len(data)//1024//1024}MB")
    mime = declared_mime.lower().strip()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in _ALLOWED_MIMES:
        raise FileValidationError(f"unsupported_mime:{mime}")
    if not _check_magic(data, mime):
        raise FileValidationError(f"mime_magic_mismatch:{mime}")
    if mime.startswith("image/"):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img.verify()
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if w > max_img_w or h > max_img_h:
                raise FileValidationError(f"image_too_large:{w}x{h}")
            if w < 1 or h < 1:
                raise FileValidationError("image_zero_dimensions")
        except FileValidationError:
            raise
        except Exception as e:
            raise FileValidationError(f"image_corrupt:{e}")
    return mime, "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# §D  VIDEO SAFETY GUARD
# ═══════════════════════════════════════════════════════════════════════════════

def _read_mp4_duration(data: bytes) -> Optional[float]:
    try:
        pos = 0
        while pos < len(data) - 8:
            size = struct.unpack_from(">I", data, pos)[0]
            name = data[pos+4:pos+8]
            if size == 0 or size > len(data):
                break
            if name == b"moov":
                inner = pos + 8
                end   = pos + size
                while inner < end - 8:
                    s2 = struct.unpack_from(">I", data, inner)[0]
                    n2 = data[inner+4:inner+8]
                    if n2 == b"mvhd" and s2 >= 32:
                        version = data[inner+8]
                        if version == 0:
                            ts  = struct.unpack_from(">I", data, inner+20)[0]
                            dur = struct.unpack_from(">I", data, inner+24)[0]
                        else:
                            ts  = struct.unpack_from(">Q", data, inner+20)[0]
                            dur = struct.unpack_from(">Q", data, inner+28)[0]
                        return dur / ts if ts > 0 else None
                    if s2 < 8:
                        break
                    inner += s2
            pos += max(size, 8)
    except Exception:
        pass
    return None

class VideoSafetyError(ValueError):
    pass

def validate_video(data: bytes, mime: str, max_dur_s: int, max_w: int, max_h: int,
                   auto_compress: bool = True) -> bytes:
    if not mime.startswith("video/"):
        return data
    if "mp4" in mime:
        dur = _read_mp4_duration(data)
        if dur is not None and dur > max_dur_s:
            raise VideoSafetyError(f"video_too_long:{dur:.1f}s>max{max_dur_s}s")
    if len(data) > 100 * 1024 * 1024:
        raise VideoSafetyError(f"video_too_large:{len(data)//1024//1024}MB>100MB")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# §E  TOOL→CAPABILITY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

VALID_TOOLS: Dict[str, str] = {
    "Flux 1.1 Pro": "image-gen", "Seedream 5.0": "image-gen",
    "SDXL 1.0": "image-gen", "Stable Diffusion 3.5": "image-gen",
    "Adobe Firefly": "image-gen", "Midjourney v7": "image-gen",
    "ControlNet": "controlnet", "InstructPix2Pix": "inpainting",
    "SUPIR": "super-resolution", "Real-ESRGAN": "super-resolution",
    "GFPGAN": "face-processing", "CodeFormer": "restoration",
    "RestoreFormer": "restoration", "SwinIR": "super-resolution",
    "BSRGAN": "super-resolution", "SAM 2": "segmentation",
    "Grounding DINO": "segmentation", "Florence-2": "captioning",
    "Runway Gen-5": "video-gen", "Seedance 2.0": "video-gen",
    "Kling AI 3.0": "video-gen", "Luma Dream Machine": "video-gen",
    "Pika 2.5": "video-gen", "Hailuo MiniMax": "video-gen",
    "Sora Edit": "video-gen", "Stable Video Diffusion": "video-gen",
    "LivePortrait": "face-processing", "Topaz Video AI 5": "super-resolution",
    "TecoGAN": "temporal", "RIFE": "temporal", "DAIN": "temporal",
    "RAFT + ESRGAN": "temporal", "Temporal GAN": "temporal",
    "AnimateDiff": "video-gen", "Wonder Dynamics": "temporal",
    "Auto Caption Generator": "captioning",
    "Audio Extractor Tool": "audio-extraction",
    "Video Compressor Pro": "compression",
    "Video Speed Controller": "temporal",
    "MultiCam Sync": "color-matching", "Match Cut Flow": "color-matching",
    "Beat Sync Drop": "audio-sync", "Sound Wave Viz": "visualization",
    "Audio Reactive Viz": "visualization",
}

VALID_CAPABILITIES: set = {
    "image-gen", "super-resolution", "segmentation", "inpainting",
    "face-processing", "restoration", "style-transfer", "captioning",
    "audio-extraction", "compression", "temporal", "color-matching",
    "audio-sync", "visualization", "video-gen", "basic-processing",
    "denoising", "image-enhancement", "controlnet",
}

def validate_tool_capability(tool: str, capability: str) -> Tuple[str, str]:
    if not tool or not tool.strip():
        raise HTTPException(422, detail="tool:required")
    if capability and capability != "basic-processing":
        if capability not in VALID_CAPABILITIES:
            raise HTTPException(422, detail=f"capability:unknown:{capability}")
    if capability == "basic-processing" and tool in VALID_TOOLS:
        capability = VALID_TOOLS[tool]
    return capability, "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# §F  CLOUDINARY OUTPUT DELIVERY — secure URLs only, hard fail on error
# ═══════════════════════════════════════════════════════════════════════════════

async def deliver_output(img_bytes: bytes, mime: str, cloud_id: str,
                         upload_preset: str, api_key: str = "",
                         api_secret: str = "") -> str:
    """
    Returns a HTTPS Cloudinary URL when cloud_id is set.
    Falls back to data:URL ONLY when cloud_id is not configured (dev mode).
    Raises RuntimeError when cloud_id is set but upload fails.
    """
    if not cloud_id or not img_bytes:
        # Dev mode: return data URL
        return f"data:{mime};base64," + base64.b64encode(img_bytes).decode()

    media_type = "video" if mime.startswith("video/") else "image"
    b64_data   = base64.b64encode(img_bytes).decode()
    data_uri   = f"data:{mime};base64,{b64_data}"
    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_id}/{media_type}/upload"
    payload    = {
        "file":          data_uri,
        "upload_preset": upload_preset,
        "timestamp":     str(int(time.time())),
        "resource_type": media_type,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(upload_url, data=payload)
            r.raise_for_status()
            data = r.json()
            # Always prefer secure_url (HTTPS)
            url = data.get("secure_url") or ""
            if not url:
                raise RuntimeError(f"Cloudinary response missing secure_url: {list(data.keys())}")
            if not url.startswith("https://"):
                raise RuntimeError(f"Cloudinary returned non-HTTPS URL: {url[:60]}")
            logger.info("[deliver] Cloudinary upload OK → %s", url[:80])
            return url
    except Exception as e:
        # Cloud is configured but upload failed — this is a hard error in production
        logger.error("[deliver] Cloudinary upload failed: %s", e)
        raise RuntimeError(f"Cloudinary upload failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# §G  MONITORING — structured JSON request logs
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RequestMonitorRecord:
    request_id:      str
    tool:            str
    capability:      str
    provider_used:   str   = ""
    latency_ms:      float = 0.0
    fallback_used:   bool  = False
    fallback_reason: str   = ""
    success:         bool  = False
    error:           str   = ""
    file_bytes:      int   = 0
    resolution:      str   = ""
    ip_hash:         str   = ""
    timestamp:       float = field(default_factory=time.time)

    def to_log(self) -> str:
        return json.dumps({
            "request_id": self.request_id, "tool": self.tool,
            "capability": self.capability, "provider": self.provider_used,
            "latency_ms": round(self.latency_ms), "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason, "success": self.success,
            "error": self.error, "file_bytes": self.file_bytes,
            "resolution": self.resolution, "ip_hash": self.ip_hash,
            "ts": self.timestamp,
        })

monitor_log = logging.getLogger("luminorbit.monitor")


# ═══════════════════════════════════════════════════════════════════════════════
# §H  FAILURE TRANSPARENCY
# ═══════════════════════════════════════════════════════════════════════════════

def make_fallback_response(output: str, provider: str, reason: str,
                           resolution: str = "3840x2160",
                           metadata: Optional[Dict] = None) -> Dict[str, Any]:
    return {
        "success": True, "output": output, "provider": provider,
        "resolution": resolution, "metadata": metadata or {},
        "status": "fallback_used", "fallback_reason": reason,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# §I  MEMORY + CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

class TempFileRegistry:
    def __init__(self):
        self._files: Dict[str, List[str]] = collections.defaultdict(list)

    def register(self, request_id: str, path: str):
        self._files[request_id].append(path)

    def cleanup(self, request_id: str):
        for path in self._files.pop(request_id, []):
            try:
                os.unlink(path)
            except OSError:
                pass

    def cleanup_all(self):
        for rid in list(self._files.keys()):
            self.cleanup(rid)

_temp_registry = TempFileRegistry()


# ═══════════════════════════════════════════════════════════════════════════════
# §J  API SECURITY
# ═══════════════════════════════════════════════════════════════════════════════

def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def hash_ip(ip: str) -> str:
    """One-way hash of IP for audit logs — never log raw IPs."""
    return hashlib.sha256(ip.encode()).hexdigest()[:12]

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════════
# §K  FRONTEND CONTRACT ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

_REQUIRED_FIELDS = {"tool", "capability"}

def validate_process_contract(data: Dict[str, Any]) -> List[str]:
    violations = []
    for f in _REQUIRED_FIELDS:
        if not data.get(f):
            violations.append(f"missing_required:{f}")
    cap = data.get("capability", "")
    if cap and cap not in VALID_CAPABILITIES:
        violations.append(f"unknown_capability:{cap}")
    return violations


# ═══════════════════════════════════════════════════════════════════════════════
# §L  KILL SWITCH
# ═══════════════════════════════════════════════════════════════════════════════

_DISABLED_PROVIDERS: set = set()

def is_provider_disabled(name: str) -> bool:
    return name in _DISABLED_PROVIDERS

def disable_provider(name: str):
    _DISABLED_PROVIDERS.add(name)
    logger.warning("[kill_switch] Provider DISABLED: %s", name)

def enable_provider(name: str):
    _DISABLED_PROVIDERS.discard(name)
    logger.info("[kill_switch] Provider RE-ENABLED: %s", name)


# ═══════════════════════════════════════════════════════════════════════════════
# §4  BASE PROVIDER
# ═══════════════════════════════════════════════════════════════════════════════

class ProviderResult:
    def __init__(self, success: bool, output: Optional[bytes] = None,
                 output_url: Optional[str] = None, provider: str = "",
                 resolution: str = "3840x2160", metadata: Optional[Dict] = None,
                 error: Optional[str] = None):
        self.success    = success
        self.output     = output
        self.output_url = output_url
        self.provider   = provider
        self.resolution = resolution
        self.metadata   = metadata or {}
        self.error      = error

    @classmethod
    def fail(cls, provider: str, error: str) -> "ProviderResult":
        return cls(success=False, provider=provider, error=error)


class BaseProvider(abc.ABC):
    name:     str  = "base"
    priority: int  = 50
    enabled:  bool = True
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RESET:     int = 120

    def __init__(self, settings: Settings):
        self.settings      = settings
        self._failures     = 0
        self._last_failure = 0.0
        self._lock         = asyncio.Lock()

    @abc.abstractmethod
    async def process(self, capability: str, file_bytes: Optional[bytes],
                      file_mime: str, params: Dict[str, Any],
                      resolution: str = "4K") -> ProviderResult: ...

    @abc.abstractmethod
    async def health_check(self) -> bool: ...

    def is_circuit_open(self) -> bool:
        if self._failures < self.CIRCUIT_BREAKER_THRESHOLD:
            return False
        if time.time() - self._last_failure > self.CIRCUIT_BREAKER_RESET:
            self._failures = 0
            return False
        return True

    def record_failure(self):
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            logger.warning("[%s] Circuit OPEN — %d failures", self.name, self._failures)

    def record_success(self):
        self._failures = max(0, self._failures - 1)

    async def safe_process(self, capability: str, file_bytes: Optional[bytes],
                           file_mime: str, params: Dict[str, Any],
                           resolution: str = "4K") -> ProviderResult:
        if self.is_circuit_open():
            return ProviderResult.fail(self.name, "circuit-open")
        if not self.enabled:
            return ProviderResult.fail(self.name, "disabled")
        try:
            result = await asyncio.wait_for(
                self.process(capability, file_bytes, file_mime, params, resolution),
                timeout=self.settings.PROVIDER_TIMEOUT,
            )
            (self.record_success if result.success else self.record_failure)()
            return result
        except asyncio.TimeoutError:
            self.record_failure()
            return ProviderResult.fail(self.name, "timeout")
        except Exception as e:
            logger.error("[%s] %s", self.name, e, exc_info=True)
            self.record_failure()
            return ProviderResult.fail(self.name, type(e).__name__)  # No stack trace in result

    def _4k_dims(self) -> Tuple[int, int]:
        return (self.settings.OUTPUT_4K_WIDTH, self.settings.OUTPUT_4K_HEIGHT)
# ═══════════════════════════════════════════════════════════════════════════════
# §4-18  PROVIDERS (15 total — unchanged logic, secrets never logged)
# ═══════════════════════════════════════════════════════════════════════════════

class PollinationsProvider(BaseProvider):
    name = "pollinations"; priority = 10
    def __init__(self, s: Settings):
        super().__init__(s)
        self.api_key  = s.POLLINATIONS_API_KEY
        self.base_url = "https://image.pollinations.ai"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        w, h   = self._4k_dims()
        prompt = params.get("prompt", "professional studio quality photograph ultra high detail")
        model  = {"style-transfer": "flux-pro", "restoration": "flux-pro"}.get(capability, "flux")
        seed   = params.get("seed", 42)
        url = (f"{self.base_url}/prompt/{urllib.parse.quote(prompt)}"
               f"?width={w}&height={h}&model={model}&seed={seed}&nologo=true&enhance=true")
        async with httpx.AsyncClient(timeout=90) as c:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            r = await c.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            ct, raw = r.headers.get("content-type", "image/jpeg"), r.content
        if len(raw) < 1000:
            raise ValueError(f"Pollinations tiny payload: {len(raw)}b")
        b64 = base64.b64encode(raw).decode()
        return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base_url}/prompt/test?width=64&height=64&model=flux&nologo=true")
                return r.status_code == 200
        except Exception:
            return False

_CF_MODELS = {
    "super-resolution": "@cf/microsoft/realsr-esrgan-x4",
    "segmentation":     "@cf/facebook/detr-resnet-50-panoptic",
    "inpainting":       "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "image-gen":        "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "denoising":        "@cf/microsoft/realsr-esrgan-x4",
    "temporal":         "@cf/stabilityai/stable-video-diffusion-img2vid-xt",
    "audio-extraction": "@cf/openai/whisper",
    "basic-processing": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "color-matching":   "@cf/stabilityai/stable-diffusion-xl-base-1.0",
}

class CloudflareProvider(BaseProvider):
    name = "cloudflare"; priority = 20
    def __init__(self, s: Settings):
        super().__init__(s)
        self.token    = s.CF_AI_TOKEN
        self.acct     = s.CF_ACCOUNT_ID
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.acct}/ai/run"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        model   = _CF_MODELS.get(capability, _CF_MODELS["basic-processing"])
        w, h    = self._4k_dims()
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if capability == "audio-extraction" and file_bytes:
            body = {"audio": list(file_bytes)}
        elif capability in ("super-resolution", "segmentation", "denoising") and file_bytes:
            body = {"image": list(file_bytes)}
        else:
            prompt = params.get("prompt", "ultra-detailed professional photo 4K")
            body   = {"prompt": prompt, "width": w, "height": h, "num_steps": 30}
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{self.base_url}/{model}", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        b64 = data.get("result", {}).get("image") or data.get("result", {}).get("data")
        if not b64:
            raise ValueError(f"Cloudflare: no image for {capability}")
        raw = base64.b64decode(b64)
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}", {"model": model})

    async def health_check(self):
        if not self.acct:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"https://api.cloudflare.com/client/v4/accounts/{self.acct}/ai/models/search",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                return r.status_code == 200
        except Exception:
            return False

class GeminiProvider(BaseProvider):
    name = "gemini"; priority = 25
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key          = s.GEMINI_API_KEY
        self.base         = "https://generativelanguage.googleapis.com/v1beta/models"
        self.vision_model = "gemini-2.0-flash-exp"
        self.imagen_model = "imagen-3.0-generate-001"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        if capability in ("image-gen", "style-transfer", "restoration", "basic-processing"):
            return await self._imagen(params)
        return await self._vision(capability, file_bytes, file_mime, params)

    async def _imagen(self, params):
        w, h   = self._4k_dims()
        prompt = params.get("prompt", "professional studio photograph ultra detailed 4K")
        url    = f"{self.base}/{self.imagen_model}:predict?key={self.key}"
        body   = {
            "instances":  [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9", "outputOptions": {"mimeType": "image/png"}},
        }
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            b64 = r.json()["predictions"][0]["bytesBase64Encoded"]
        raw = base64.b64decode(b64)
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}", {"model": self.imagen_model})

    async def _vision(self, capability, file_bytes, file_mime, params):
        prompt = params.get("prompt", f"Analyze this image for {capability}. Be detailed.")
        url    = f"{self.base}/{self.vision_model}:generateContent?key={self.key}"
        parts  = [{"text": prompt}]
        if file_bytes:
            parts.append({"inlineData": {"mimeType": file_mime or "image/jpeg", "data": base64.b64encode(file_bytes).decode()}})
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json={"contents": [{"parts": parts}]})
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return ProviderResult(True, None, f"data:text/plain;charset=utf-8,{text[:500]}", self.name, "N/A", {"caption": text})

    async def health_check(self):
        try:
            url = f"{self.base}/gemini-2.0-flash-exp:generateContent?key={self.key}"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(url, json={"contents": [{"parts": [{"text": "hi"}]}]})
                return r.status_code == 200
        except Exception:
            return False

class GroqProvider(BaseProvider):
    name = "groq"; priority = 30
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key          = s.GROQ_API_KEY
        self.base         = "https://api.groq.com/openai/v1"
        self.vision_model = "llama-3.2-90b-vision-preview"
        self.text_model   = "llama-3.3-70b-versatile"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        prompt  = params.get("prompt", f"Process this for {capability}. Output professional studio quality.")
        model   = self.vision_model if file_bytes else self.text_model
        content: List = []
        if file_bytes:
            content.append({"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{base64.b64encode(file_bytes).decode()}"}})
        content.append({"type": "text", "text": prompt})
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 1024},
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        return ProviderResult(True, None, f"data:text/plain;charset=utf-8,{text[:500]}", self.name, "N/A", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code == 200
        except Exception:
            return False

class MistralProvider(BaseProvider):
    name = "mistral"; priority = 35
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key          = s.MISTRAL_API_KEY
        self.base         = "https://api.mistral.ai/v1"
        self.vision_model = "pixtral-large-latest"
        self.text_model   = "mistral-large-latest"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        prompt = params.get("prompt", f"Professional image processing AI: analyze for '{capability}'.")
        model  = self.vision_model if file_bytes else self.text_model
        if file_bytes:
            content = [
                {"type": "image_url", "image_url": f"data:{file_mime};base64,{base64.b64encode(file_bytes).decode()}"},
                {"type": "text", "text": prompt},
            ]
        else:
            # Mistral API requires content to always be a list, never a raw string
            content = [{"type": "text", "text": prompt}]
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 1024},
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        return ProviderResult(True, None, f"data:text/plain;charset=utf-8,{text[:500]}", self.name, "N/A", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code == 200
        except Exception:
            return False

_OR_MODELS = {
    "image-gen": "google/gemini-flash-1.5", "captioning": "google/gemini-flash-1.5",
    "style-transfer": "anthropic/claude-3.5-sonnet", "visualization": "google/gemini-flash-1.5",
    "basic-processing": "google/gemini-flash-1.5",
}

class OpenRouterProvider(BaseProvider):
    name = "openrouter"; priority = 40
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.OPENROUTER_API_KEY
        self.base = "https://openrouter.ai/api/v1"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        model  = _OR_MODELS.get(capability, "google/gemini-flash-1.5")
        prompt = params.get("prompt", f"Professional AI studio processing: {capability}. 4K quality.")
        content: Any = []
        if file_bytes:
            content.append({"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{base64.b64encode(file_bytes).decode()}"}})
        content.append({"type": "text", "text": prompt})
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}", "HTTP-Referer": "https://luminorbit.app", "X-Title": "Luminorbit"},
                json={"model": model, "messages": [{"role": "user", "content": content}]},
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        return ProviderResult(True, None, f"data:text/plain;charset=utf-8,{text[:500]}", self.name, "N/A", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code == 200
        except Exception:
            return False

_SM_ENDPOINTS = {
    "image-gen": "sdxl1.0-txt2img", "segmentation": "segment-anything",
    "inpainting": "stable-diffusion-inpainting", "style-transfer": "sdxl1.0-txt2img",
    "restoration": "sdxl1.0-txt2img", "face-processing": "sdxl1.0-txt2img",
    "super-resolution": "sdxl1.0-txt2img", "denoising": "sdxl1.0-txt2img",
    "basic-processing": "sdxl1.0-txt2img", "controlnet": "controlnet-canny",
}

class SegmindProvider(BaseProvider):
    name = "segmind"; priority = 22
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.SEGMIND_API_KEY
        self.base = "https://api.segmind.com/v1"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        ep     = _SM_ENDPOINTS.get(capability, "sdxl1.0-txt2img")
        w, h   = self._4k_dims()
        prompt = params.get("prompt", "ultra detailed professional studio photo 4K")
        if ep == "segment-anything" and file_bytes:
            body = {"image": base64.b64encode(file_bytes).decode(), "output_type": "mask"}
        elif ep == "stable-diffusion-inpainting" and file_bytes:
            body = {"prompt": prompt, "image": base64.b64encode(file_bytes).decode(),
                    "strength": params.get("strength", 0.8), "width": w, "height": h,
                    "samples": 1, "num_inference_steps": 30, "guidance_scale": 7.5}
        else:
            body = {"prompt": prompt, "negative_prompt": "blurry, low quality, watermark",
                    "width": w, "height": h, "samples": 1, "num_inference_steps": 30,
                    "guidance_scale": 7.5, "seed": params.get("seed", -1)}
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{self.base}/{ep}", headers={"x-api-key": self.key, "Content-Type": "application/json"}, json=body)
            r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "image" in ct:
            raw = r.content
            b64 = base64.b64encode(raw).decode()
            return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"ep": ep})
        data = r.json()
        b64  = data.get("image", data.get("data", ""))
        raw  = base64.b64decode(b64) if b64 else b""
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}", {"ep": ep})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/sdxl1.0-txt2img", headers={"x-api-key": self.key})
                return r.status_code in (200, 405, 422)
        except Exception:
            return False

class KreaProvider(BaseProvider):
    name = "krea"; priority = 15
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.KREA_API_KEY
        self.base = "https://api.krea.ai/v1"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        w, h    = self._4k_dims()
        prompt  = params.get("prompt", "ultra detailed professional studio quality 4K photograph")
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if capability in ("super-resolution", "restoration", "denoising") and file_bytes:
            ep   = f"{self.base}/images/upscale"
            body = {"image": base64.b64encode(file_bytes).decode(), "scale": 4, "output_size": {"width": w, "height": h}}
        elif capability == "face-processing" and file_bytes:
            ep   = f"{self.base}/images/enhance"
            body = {"image": base64.b64encode(file_bytes).decode(), "enhance_face": True, "output_size": {"width": w, "height": h}}
        else:
            ep   = f"{self.base}/images/generate"
            body = {"prompt": prompt, "model": "flux-pro", "width": w, "height": h, "num_images": 1, "output_format": "png"}
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(ep, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        img_data = (data.get("images", [{}])[0].get("url") or data.get("images", [{}])[0].get("base64")
                    or data.get("image") or data.get("url"))
        if not img_data:
            raise ValueError("Krea: no image data")
        if img_data.startswith("http"):
            async with httpx.AsyncClient(timeout=60) as c:
                ir  = await c.get(img_data)
                raw = ir.content
            b64 = base64.b64encode(raw).decode()
        else:
            b64 = img_data; raw = base64.b64decode(b64)
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}")

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code in (200, 404)
        except Exception:
            return False

_TA_MODELS = {
    "image-gen": "black-forest-labs/FLUX.1-pro", "style-transfer": "black-forest-labs/FLUX.1-pro",
    "inpainting": "black-forest-labs/FLUX.1-pro", "face-processing": "black-forest-labs/FLUX.1-pro",
    "super-resolution": "black-forest-labs/FLUX.1-pro", "restoration": "black-forest-labs/FLUX.1-pro",
    "image-enhancement": "black-forest-labs/FLUX.1-pro", "denoising": "black-forest-labs/FLUX.1-schnell",
    "segmentation": "black-forest-labs/FLUX.1-schnell", "basic-processing": "black-forest-labs/FLUX.1-schnell",
    "video-gen": "stabilityai/stable-video-diffusion-img2vid-xt",
    "captioning": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
}

class TogetherProvider(BaseProvider):
    name = "together"; priority = 18
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.TOGETHER_API_KEY
        self.base = "https://api.together.xyz/v1"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        w, h   = self._4k_dims()
        model  = _TA_MODELS.get(capability, "black-forest-labs/FLUX.1-schnell")
        prompt = params.get("prompt", "ultra detailed professional studio quality 4K photograph")
        body   = {"model": model, "prompt": prompt, "width": w, "height": h,
                  "steps": params.get("steps", 28), "n": 1, "response_format": "b64_json"}
        if file_bytes and capability not in ("image-gen",):
            body["image_base64"] = base64.b64encode(file_bytes).decode()
            body["strength"]     = params.get("strength", 0.75)
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                f"{self.base}/images/generations",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            b64 = r.json()["data"][0]["b64_json"]
        raw = base64.b64decode(b64)
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code == 200
        except Exception:
            return False

_HF_MODELS = {
    "super-resolution": "ai-forever/Real-ESRGAN", "face-processing": "tencentarc/gfpgan",
    "restoration": "sczhou/codeformer", "segmentation": "facebook/sam-vit-huge",
    "inpainting": "runwayml/stable-diffusion-inpainting",
    "image-gen": "stabilityai/stable-diffusion-xl-base-1.0",
    "style-transfer": "lambdalabs/sd-image-variations-diffusers",
    "denoising": "ai-forever/Real-ESRGAN",
    "video-gen": "stabilityai/stable-video-diffusion-img2vid-xt",
    "captioning": "Salesforce/blip-image-captioning-large",
    "temporal": "microsoft/phi-3-vision-128k-instruct",
    "image-enhancement": "stabilityai/stable-diffusion-xl-refiner-1.0",
    "basic-processing": "stabilityai/stable-diffusion-xl-base-1.0",
    "color-matching": "stabilityai/stable-diffusion-xl-base-1.0",
}
_HF_IMAGE_INPUT = {
    "super-resolution", "face-processing", "restoration", "segmentation",
    "inpainting", "denoising", "style-transfer", "captioning", "video-gen", "temporal",
}

class HuggingFaceProvider(BaseProvider):
    name = "huggingface"; priority = 12
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.HF_API_KEY
        self.base = "https://api-inference.huggingface.co/models"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        model   = _HF_MODELS.get(capability, _HF_MODELS["basic-processing"])
        w, h    = self._4k_dims()
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/octet-stream"}
        if capability in _HF_IMAGE_INPUT and file_bytes:
            payload = file_bytes
        else:
            prompt  = params.get("prompt", "ultra detailed professional 4K studio photograph")
            headers["Content-Type"] = "application/json"
            payload = json.dumps({"inputs": prompt,
                                  "parameters": {"width": w, "height": h, "num_inference_steps": 30, "guidance_scale": 7.5}}).encode()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base}/{model}", headers=headers, content=payload)
            if r.status_code == 503:
                logger.info("[huggingface] %s loading — retry in 8s", model)
                await asyncio.sleep(8)
                r = await c.post(f"{self.base}/{model}", headers=headers, content=payload)
            if r.status_code == 503:
                raise ValueError(f"HuggingFace {model} still loading")
            r.raise_for_status()
        ct  = r.headers.get("content-type", "image/png")
        raw = r.content
        if "application/json" in ct:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                raw = base64.b64decode(data[0].get("blob", b""))
        if len(raw) < 100:
            raise ValueError(f"HF empty response for {model}")
        b64 = base64.b64encode(raw).decode()
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}", {"model": model})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{self.base}/stabilityai/stable-diffusion-xl-base-1.0",
                    headers={"Authorization": f"Bearer {self.key}"},
                )
                return r.status_code in (200, 503)
        except Exception:
            return False

_DA_ENDPOINTS = {
    "super-resolution": "torch-srgan", "face-processing": "face-recognition",
    "restoration": "image-editor", "inpainting": "image-editor",
    "image-gen": "text2img", "denoising": "torch-srgan",
    "image-enhancement": "waifu2x", "style-transfer": "fast-style-transfer",
    "basic-processing": "image-editor",
}

class DeepAIProvider(BaseProvider):
    name = "deepai"; priority = 45
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.DEEPAI_API_KEY
        self.base = "https://api.deepai.org/api"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        ep      = _DA_ENDPOINTS.get(capability, "image-editor")
        w, h    = self._4k_dims()
        headers = {"api-key": self.key}
        async with httpx.AsyncClient(timeout=90) as c:
            if file_bytes and capability != "image-gen":
                r = await c.post(
                    f"{self.base}/{ep}", headers=headers,
                    files={"image": ("input.jpg", io.BytesIO(file_bytes), file_mime or "image/jpeg")},
                    data=({"style": params.get("style", "mosaic")} if ep == "fast-style-transfer" else {}),
                )
            else:
                prompt = params.get("prompt", "ultra detailed professional studio photograph 4K")
                r = await c.post(f"{self.base}/{ep}", headers=headers, data={"text": prompt, "grid_size": 1})
            r.raise_for_status()
            out_url = r.json().get("output_url", "")
        if not out_url:
            raise ValueError(f"DeepAI: no output_url for {ep}")
        async with httpx.AsyncClient(timeout=60) as c:
            ir  = await c.get(out_url)
            raw = ir.content
        ct  = ir.headers.get("content-type", "image/jpeg")
        b64 = base64.b64encode(raw).decode()
        return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"ep": ep})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.deepai.org/", headers={"api-key": self.key})
                return r.status_code in (200, 404)
        except Exception:
            return False

class PixazoProvider(BaseProvider):
    name = "pixazo"; priority = 48
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.PIXAZO_API_KEY
        self.base = "https://api.pixazo.ai/v1"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        w, h   = self._4k_dims()
        prompt = params.get("prompt", "ultra detailed professional studio photograph 4K high resolution")
        body   = {"prompt": prompt, "negative_prompt": "blurry, low quality, watermark, nsfw",
                  "model": "sdxl", "width": w, "height": h, "steps": params.get("steps", 30),
                  "guidance_scale": params.get("cfg", 7.5), "samples": 1}
        if file_bytes:
            body["init_image"] = base64.b64encode(file_bytes).decode()
            body["strength"]   = params.get("strength", 0.75)
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{self.base}/generate",
                             headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                             json=body)
            r.raise_for_status()
            data = r.json()
        b64 = data.get("image") or data.get("output") or data.get("data", "")
        if not b64:
            raise ValueError("Pixazo: empty image")
        raw = base64.b64decode(b64)
        return ProviderResult(True, raw, f"data:image/png;base64,{b64}", self.name, f"{w}x{h}")

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
                return r.status_code in (200, 401, 403)
        except Exception:
            return False

class PexelsProvider(BaseProvider):
    name = "pexels"; priority = 60
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key     = s.PEXELS_API_KEY
        self.base    = "https://api.pexels.com/v1"
        self.vid_url = "https://api.pexels.com/videos"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        is_video = capability in ("video-gen", "temporal", "compression", "audio-extraction", "audio-sync")
        query    = params.get("prompt", "professional studio background 4K")
        w, h     = self._4k_dims()
        headers  = {"Authorization": self.key}
        async with httpx.AsyncClient(timeout=30) as c:
            if is_video:
                r = await c.get(f"{self.vid_url}/search", params={"query": query, "per_page": 1, "size": "large"}, headers=headers)
                r.raise_for_status()
                videos = r.json().get("videos", [])
                if not videos:
                    raise ValueError("Pexels: no video results")
                vfiles = sorted(videos[0].get("video_files", []), key=lambda vf: vf.get("width", 0), reverse=True)
                return ProviderResult(True, None, vfiles[0]["link"], self.name,
                                      f"{vfiles[0].get('width',w)}x{vfiles[0].get('height',h)}", {"source": "pexels"})
            else:
                r = await c.get(f"{self.base}/search", params={"query": query, "per_page": 1, "size": "large"}, headers=headers)
                r.raise_for_status()
                photos = r.json().get("photos", [])
                if not photos:
                    raise ValueError("Pexels: no photo results")
                url = photos[0]["src"].get("original", photos[0]["src"].get("large2x", ""))
                ir  = await c.get(url)
                raw = ir.content
                ct  = ir.headers.get("content-type", "image/jpeg")
                b64 = base64.b64encode(raw).decode()
                return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"source": "pexels"})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/curated?per_page=1", headers={"Authorization": self.key})
                return r.status_code == 200
        except Exception:
            return False

class UnsplashProvider(BaseProvider):
    name = "unsplash"; priority = 62
    def __init__(self, s: Settings):
        super().__init__(s)
        self.key  = s.UNSPLASH_API_KEY
        self.base = "https://api.unsplash.com"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        query = params.get("prompt", "professional studio photography 4K")
        w, h  = self._4k_dims()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/search/photos",
                            params={"query": query, "per_page": 1, "orientation": "landscape"},
                            headers={"Authorization": f"Client-ID {self.key}"})
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                raise ValueError("Unsplash: no results")
            raw_url = results[0]["urls"]["raw"] + f"&w={w}&h={h}&fit=crop&fm=png&q=95"
            ir      = await c.get(raw_url)
            raw     = ir.content
        ct     = ir.headers.get("content-type", "image/jpeg")
        b64    = base64.b64encode(raw).decode()
        author = results[0].get("user", {}).get("name", "")
        return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"author": author})

    async def health_check(self):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/photos?per_page=1", headers={"Authorization": f"Client-ID {self.key}"})
                return r.status_code == 200
        except Exception:
            return False

_CL_TRANSFORMS = {
    "super-resolution":  "e_upscale/w_3840,h_2160,c_fill/q_auto:best/f_png",
    "image-enhancement": "e_enhance/e_sharpen:100/e_vibrance:50/q_auto:best/f_png",
    "face-processing":   "e_redeye/e_viesus_correct/e_improve/q_auto:best/f_png",
    "restoration":       "e_upscale/e_improve/e_sharpen:80/q_auto:best/f_png",
    "denoising":         "e_improve/e_sharpen:50/q_auto:best/f_png",
    "compression":       "q_auto:eco/f_webp",
    "image-gen":         "e_gen_fill:prompt_professional_studio_photo/w_3840,h_2160/q_auto:best/f_png",
    "color-matching":    "e_improve:outdoor/e_vibrance:30/q_auto:best/f_png",
    "basic-processing":  "e_improve/q_auto:best/f_png",
    "inpainting":        "e_gen_restore/q_auto:best/f_png",
    "style-transfer":    "e_art:athena/q_auto:best/f_png",
    "segmentation":      "e_background_removal/q_auto:best/f_png",
    "temporal":          "q_auto:best/f_mp4",
    "video-gen":         "q_auto:best/f_mp4",
}

class CloudinaryProvider(BaseProvider):
    name = "cloudinary"; priority = 28
    def __init__(self, s: Settings):
        super().__init__(s)
        self.cloud    = s.CLOUDINARY_CLOUD_ID
        self.preset   = s.CLOUDINARY_UPLOAD_PRESET
        self.base     = f"https://api.cloudinary.com/v1_1/{self.cloud}"

    async def process(self, capability, file_bytes, file_mime, params, resolution="4K"):
        if not file_bytes:
            raise ValueError("Cloudinary requires input file bytes")
        w, h       = self._4k_dims()
        transform  = _CL_TRANSFORMS.get(capability, _CL_TRANSFORMS["basic-processing"])
        media_type = "video" if (file_mime and "video" in file_mime) else "image"
        b64_data   = base64.b64encode(file_bytes).decode()
        data_uri   = f"data:{file_mime};base64,{b64_data}"
        async with httpx.AsyncClient(timeout=90) as c:
            ur = await c.post(
                f"{self.base}/{media_type}/upload",
                data={"file": data_uri, "upload_preset": self.preset, "timestamp": int(time.time())},
            )
            ur.raise_for_status()
            public_id = ur.json().get("public_id", "")
        if not public_id:
            raise ValueError("Cloudinary upload failed — no public_id")
        out_url = f"https://res.cloudinary.com/{self.cloud}/{media_type}/upload/{transform}/{public_id}"
        async with httpx.AsyncClient(timeout=90) as c:
            or_ = await c.get(out_url)
            or_.raise_for_status()
            raw = or_.content
            ct  = or_.headers.get("content-type", "image/png")
        b64 = base64.b64encode(raw).decode()
        return ProviderResult(True, raw, f"data:{ct};base64,{b64}", self.name, f"{w}x{h}", {"transform": transform})

    async def health_check(self):
        if not self.cloud:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"https://res.cloudinary.com/{self.cloud}/image/upload/sample")
                return r.status_code in (200, 404)
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# §19  TOOL → PROVIDER MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_PROVIDERS: Dict[str, List[str]] = {
    "Flux 1.1 Pro":           ["pollinations", "together", "krea"],
    "Seedream 5.0":           ["pollinations", "krea"],
    "SDXL 1.0":               ["huggingface", "pixazo", "deepai"],
    "Stable Diffusion 3.5":   ["segmind", "huggingface"],
    "SUPIR":                  ["cloudflare", "krea", "together"],
    "Real-ESRGAN":            ["huggingface", "cloudflare"],
    "GFPGAN":                 ["huggingface", "deepai"],
    "CodeFormer":             ["huggingface"],
    "RestoreFormer":          ["krea", "cloudflare"],
    "SwinIR":                 ["huggingface", "cloudflare"],
    "BSRGAN":                 ["huggingface"],
    "Adobe Firefly":          ["pollinations"],
    "ControlNet":             ["segmind", "huggingface"],
    "InstructPix2Pix":        ["huggingface"],
    "SAM 2":                  ["huggingface"],
    "Grounding DINO":         ["huggingface"],
    "Florence-2":             ["gemini", "mistral"],
    "Midjourney v7":          ["pollinations", "krea"],
    "Runway Gen-5":           ["pollinations", "together"],
    "Seedance 2.0":           ["pollinations"],
    "Kling AI 3.0":           ["together"],
    "Luma Dream Machine":     ["pollinations"],
    "Pika 2.5":               ["pollinations"],
    "Hailuo MiniMax":         ["together"],
    "Sora Edit":              ["pollinations"],
    "Stable Video Diffusion": ["huggingface"],
    "LivePortrait":           ["huggingface"],
    "Topaz Video AI 5":       ["cloudinary", "krea"],
    "TecoGAN":                ["huggingface"],
    "RIFE":                   ["huggingface"],
    "DAIN":                   ["huggingface"],
    "RAFT + ESRGAN":          ["cloudflare"],
    "Temporal GAN":           ["huggingface"],
    "AnimateDiff":            ["huggingface", "pollinations"],
    "Wonder Dynamics":        ["cloudinary"],
}

CAPABILITY_PROVIDERS: Dict[str, List[str]] = {
    "segmentation":      ["huggingface", "cloudflare", "segmind"],
    "inpainting":        ["huggingface", "segmind", "deepai"],
    "face-processing":   ["huggingface", "deepai", "krea"],
    "super-resolution":  ["huggingface", "cloudflare", "krea"],
    "image-enhancement": ["cloudinary", "huggingface", "segmind"],
    "denoising":         ["huggingface", "cloudflare"],
    "restoration":       ["huggingface", "deepai", "krea"],
    "style-transfer":    ["huggingface", "pollinations", "together"],
    "captioning":        ["gemini", "groq", "mistral"],
    "audio-extraction":  ["cloudflare"],
    "compression":       ["cloudinary", "cloudflare"],
    "temporal":          ["cloudflare", "huggingface"],
    "color-matching":    ["cloudinary", "cloudflare"],
    "audio-sync":        ["cloudflare"],
    "visualization":     ["pollinations", "gemini"],
    "image-gen":         ["pollinations", "together", "krea", "segmind"],
    "video-gen":         ["pollinations", "together"],
    "basic-processing":  ["huggingface", "pollinations", "cloudflare"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# §20  PROVIDER ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

class ProviderRouter:
    def __init__(self, settings: Settings):
        self.settings  = settings
        self._registry: Dict[str, BaseProvider] = {}
        self._scorer   = ProviderScoreRegistry(decay=settings.PROVIDER_SCORE_DECAY)

    async def initialize(self):
        klasses = [
            PollinationsProvider, CloudflareProvider, GeminiProvider,
            GroqProvider, MistralProvider, OpenRouterProvider, SegmindProvider,
            KreaProvider, TogetherProvider, HuggingFaceProvider, DeepAIProvider,
            PixazoProvider, PexelsProvider, UnsplashProvider, CloudinaryProvider,
        ]
        for klass in klasses:
            p = klass(self.settings)
            self._registry[p.name] = p
        logger.info("[router] %d providers loaded: %s", len(self._registry), list(self._registry.keys()))

    async def route(self, tool: str, capability: str, file_bytes: Optional[bytes],
                    file_mime: str, params: Dict[str, Any], resolution: str = "4K",
                    monitor: Optional[RequestMonitorRecord] = None) -> ProviderResult:
        if self.settings.GLOBAL_KILL_SWITCH:
            return ProviderResult.fail("all", "global_kill_switch")

        names = []
        seen: set = set()
        for n in TOOL_PROVIDERS.get(tool, []) + CAPABILITY_PROVIDERS.get(capability, []):
            if n not in seen and n in self._registry:
                seen.add(n); names.append(n)
        names = await self._scorer.sort_by_score(names)

        logger.info("[router] tool=%s cap=%s chain=%s", tool, capability, names)
        last_error    = "no_providers"
        fallback_used = False

        for name in names:
            p = self._registry.get(name)
            if not p or is_provider_disabled(name):
                continue
            skip, reason = await self._scorer.should_skip(name)
            if skip or p.is_circuit_open():
                logger.info("[router] skip %s: %s", name, reason or "circuit_open")
                continue

            logger.info("[router] → trying %s", name)
            t0     = time.monotonic()
            result = await p.safe_process(capability, file_bytes, file_mime, params, resolution)
            lat_ms = (time.monotonic() - t0) * 1000

            if result.success:
                logger.info("[router] ✓ %s (%.0fms)", name, lat_ms)
                await self._scorer.record_success(name, lat_ms)
                if monitor:
                    monitor.provider_used = name
                    monitor.latency_ms    = lat_ms
                    monitor.fallback_used = fallback_used
                return result

            last_error = result.error or "unknown"
            logger.warning("[router] ✗ %s: %s", name, last_error)
            if "429" in str(last_error) or "rate" in str(last_error).lower():
                await self._scorer.record_rate_limit(name)
            else:
                await self._scorer.record_failure(name)
            fallback_used = True

        if monitor:
            monitor.fallback_used   = True
            monitor.fallback_reason = last_error
        logger.error("[router] ALL FAILED for %s. Last: %s", tool, last_error)
        return ProviderResult.fail("all", f"All providers failed: {last_error}")

    async def health_summary(self) -> Dict[str, Any]:
        circuit = {
            n: {"circuit_open": p.is_circuit_open(), "failures": p._failures, "enabled": p.enabled}
            for n, p in self._registry.items()
        }
        return {"circuit_breakers": circuit, "scores": await self._scorer.dump(),
                "disabled": list(_DISABLED_PROVIDERS)}

    async def provider_stats(self) -> Dict[str, Any]:
        return await self.health_summary()

    async def reset_provider(self, name: str):
        if name in self._registry:
            self._registry[name]._failures    = 0
            self._registry[name]._last_failure = 0.0
            enable_provider(name)
            logger.info("[router] Reset: %s", name)


# ═══════════════════════════════════════════════════════════════════════════════
# §21  JOB MANAGER — Redis-backed with in-memory fallback
# ═══════════════════════════════════════════════════════════════════════════════

class JobManager:
    _TTL = 3600

    def __init__(self, redis_url: str, require_redis: bool = False):
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._redis: Optional[Any] = None
        if _REDIS_AVAILABLE:
            try:
                client = _redis_module.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
                client.ping()
                self._redis = client
                logger.info("[jobs] Redis connected at %s", redis_url.split("@")[-1])
            except Exception as e:
                if require_redis:
                    raise RuntimeError(f"Redis required in production but unreachable: {e}") from e
                logger.warning("[jobs] Redis unavailable (%s) — using in-memory (single-worker only)", e)
        elif require_redis:
            raise RuntimeError("Redis package not installed — required in production: pip install redis")

    def _save(self, job_id: str, data: Dict[str, Any]):
        if self._redis:
            try:
                self._redis.setex(f"lmn:job:{job_id}", self._TTL, json.dumps(data))
                return
            except Exception as e:
                logger.warning("[jobs] Redis write failed: %s", e)
        self._mem[job_id] = data

    def _load(self, job_id: str) -> Optional[Dict[str, Any]]:
        if self._redis:
            try:
                raw = self._redis.get(f"lmn:job:{job_id}")
                return json.loads(raw) if raw else None
            except Exception as e:
                logger.warning("[jobs] Redis read failed: %s", e)
        job = self._mem.get(job_id)
        if job and time.time() - job.get("created", 0) > self._TTL:
            self._mem.pop(job_id, None)
            return None
        return job

    def _update(self, job_id: str, patch: Dict[str, Any]):
        job = self._load(job_id)
        if job:
            job.update(patch)
            self._save(job_id, job)

    def create_job(self, job_id: str, tool: str):
        self._save(job_id, {"job_id": job_id, "tool": tool, "status": "pending",
                             "progress": 0, "output": None, "error": None, "created": time.time()})

    def set_status(self, job_id: str, status: str, progress: int = 0):
        self._update(job_id, {"status": status, "progress": progress})

    def set_done(self, job_id: str, output: str):
        self._update(job_id, {"status": "completed", "progress": 100, "output": output})

    def set_failed(self, job_id: str, error: str):
        # Strip internal details from error in production
        self._update(job_id, {"status": "failed", "error": "processing_failed"})

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._load(job_id)


# ═══════════════════════════════════════════════════════════════════════════════
# §22  4K PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

TARGET_W = 3840
TARGET_H = 2160

class Pipeline4K:
    def __init__(self, router: ProviderRouter, settings: Settings, usage: UsageTracker):
        self.router   = router
        self.settings = settings
        self.usage    = usage

    async def run(self, tool: str, capability: str, params: Dict[str, Any],
                  file_bytes: Optional[bytes], file_mime: str, resolution: str = "4K",
                  user_id: str = "anonymous", request_id: str = "") -> Dict[str, Any]:
        if not request_id:
            request_id = str(uuid.uuid4())[:8]
        logger.info("[pipeline:%s] START tool=%s cap=%s", request_id, tool, capability)
        mon = RequestMonitorRecord(request_id=request_id, tool=tool, capability=capability,
                                   file_bytes=len(file_bytes) if file_bytes else 0)
        t0 = time.monotonic()
        try:
            if self.settings.GLOBAL_KILL_SWITCH:
                raise RuntimeError("global_kill_switch_active")

            capability, _ = validate_tool_capability(tool, capability)
            mon.capability = capability

            if file_bytes:
                max_b = self.settings.MAX_FILE_MB * 1024 * 1024
                try:
                    file_mime, _ = validate_file_bytes(file_bytes, file_mime or "application/octet-stream",
                                                       max_b, self.settings.MAX_IMAGE_WIDTH, self.settings.MAX_IMAGE_HEIGHT)
                except FileValidationError as fve:
                    raise ValueError(f"file_validation:{fve}")
                if file_mime.startswith("video/"):
                    try:
                        file_bytes = validate_video(file_bytes, file_mime,
                                                    max_dur_s=self.settings.VIDEO_MAX_DURATION_S,
                                                    max_w=self.settings.VIDEO_MAX_WIDTH,
                                                    max_h=self.settings.VIDEO_MAX_HEIGHT,
                                                    auto_compress=self.settings.VIDEO_AUTO_COMPRESS)
                    except VideoSafetyError as vse:
                        raise ValueError(f"video_safety:{vse}")

            est_tokens = max(100, (len(file_bytes) // 4000)) if file_bytes else 200
            allowed, reason = await self.usage.check_and_record(user_id, "pipeline", est_tokens)
            if not allowed:
                raise ValueError(f"usage_limit:{reason}")

            result = await self.router.route(tool, capability, file_bytes, file_mime, params, resolution, mon)

            fallback_used = False; fallback_reason = ""
            if not result.success:
                logger.warning("[pipeline] Router failed — emergency Pollinations fallback")
                result        = await self._emergency(tool, capability, params)
                fallback_used = True
                fallback_reason = mon.fallback_reason or "all_providers_failed"

            if not result.success:
                raise RuntimeError(f"Pipeline failed for {tool!r}: all_providers_failed")

            out_mime = "video/mp4" if (file_mime and "video" in file_mime) else "image/png"
            if result.output:
                processed = await self._post_process(result.output, file_mime)
                if processed:
                    result.output = processed
                    result.resolution = f"{TARGET_W}x{TARGET_H}"

            # Text-only providers (captioning, Groq, Mistral, OpenRouter) return
            # output=None and output_url=data:text/plain... — skip Cloudinary for these.
            output_bytes = result.output or b""
            is_text_result = (not output_bytes or len(output_bytes) < 100) and result.output_url and "text/plain" in (result.output_url or "")
            if is_text_result:
                final_url = result.output_url or ""
                logger.info("[pipeline] text-only result — skipping Cloudinary delivery")
            else:
                # Deliver binary result via Cloudinary (hard fail if cloud configured but upload fails)
                final_url = await deliver_output(
                    output_bytes, out_mime,
                    cloud_id=self.settings.CLOUDINARY_CLOUD_ID,
                    upload_preset=self.settings.CLOUDINARY_UPLOAD_PRESET,
                    api_key=self.settings.CLOUDINARY_API_KEY,
                    api_secret=self.settings.CLOUDINARY_API_SECRET,
                )
            if not final_url:
                raise RuntimeError("Pipeline produced no output")

            mon.success    = True
            mon.resolution = result.resolution or f"{TARGET_W}x{TARGET_H}"
            mon.latency_ms = (time.monotonic() - t0) * 1000
            monitor_log.info(mon.to_log())
            logger.info("[pipeline:%s] DONE provider=%s res=%s latency=%.0fms fallback=%s",
                        request_id, result.provider, result.resolution, mon.latency_ms, fallback_used)

            resp: Dict[str, Any] = {
                "output": final_url, "provider": result.provider,
                "resolution": result.resolution or f"{TARGET_W}x{TARGET_H}",
                "metadata": result.metadata, "request_id": request_id,
                "status": "fallback_used" if fallback_used else "ok",
            }
            if fallback_used:
                resp["fallback_reason"] = fallback_reason
            return resp

        except Exception as e:
            mon.success    = False
            mon.error      = type(e).__name__  # No leaking stack traces
            mon.latency_ms = (time.monotonic() - t0) * 1000
            monitor_log.error(mon.to_log())
            raise
        finally:
            _temp_registry.cleanup(request_id)

    async def _post_process(self, img_bytes: bytes, file_mime: str) -> Optional[bytes]:
        if not img_bytes or len(img_bytes) < 100:
            return img_bytes
        try:
            from PIL import Image, ImageEnhance, ImageFilter
        except ImportError:
            return img_bytes
        try:
            if file_mime and "video" in file_mime:
                return img_bytes
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            ow, oh = img.size
            if ow < TARGET_W or oh < TARGET_H:
                img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
            img = ImageEnhance.Sharpness(img).enhance(1.5)
            img = ImageEnhance.Contrast(img).enhance(1.15)
            img = ImageEnhance.Color(img).enhance(1.1)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True, compress_level=self.settings.PNG_COMPRESS, dpi=(300, 300))
            return out.getvalue()
        except Exception as e:
            logger.error("[pipeline] post_process: %s", e)
            return img_bytes

    async def _emergency(self, tool: str, capability: str, params: Dict) -> ProviderResult:
        prompt = params.get("prompt", f"Professional {tool} 4K studio quality")
        url    = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
                  f"?width={TARGET_W}&height={TARGET_H}&model=flux&nologo=true&enhance=true")
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r   = await c.get(url, follow_redirects=True)
                r.raise_for_status()
                raw = r.content
                ct  = r.headers.get("content-type", "image/jpeg")
                b64 = base64.b64encode(raw).decode()
                return ProviderResult(True, raw, f"data:{ct};base64,{b64}",
                                      "pollinations-emergency", f"{TARGET_W}x{TARGET_H}")
        except Exception as e:
            return ProviderResult.fail("emergency", str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# §25  FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════

class ProcessRequest(BaseModel):
    tool:       str
    capability: str              = "basic-processing"
    params:     Dict[str, Any]   = Field(default_factory=dict)
    inputType:  str              = "unknown"
    inputSize:  int              = 0
    resolution: str              = "4K"
    timestamp:  Optional[int]    = None
    file_data:  Optional[str]    = None
    file_mime:  Optional[str]    = None

    @field_validator("tool")
    @classmethod
    def tool_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("tool cannot be empty")
        return v.strip()

    @field_validator("capability")
    @classmethod
    def capability_must_be_valid(cls, v: str) -> str:
        if v and v not in VALID_CAPABILITIES:
            raise ValueError(f"unknown capability: {v}")
        return v

class ProcessResponse(BaseModel):
    success:         bool
    output:          Optional[str]       = None
    output_url:      Optional[str]       = None
    job_id:          Optional[str]       = None
    provider:        Optional[str]       = None
    resolution:      Optional[str]       = None
    metadata:        Dict[str, Any]      = Field(default_factory=dict)
    error:           Optional[str]       = None
    status:          str                 = "ok"
    fallback_reason: Optional[str]       = None
    request_id:      Optional[str]       = None

class JobStatusResponse(BaseModel):
    job_id:     str
    status:     str
    progress:   int          = 0
    output:     Optional[str] = None
    output_url: Optional[str] = None
    error:      Optional[str] = None

# ── App init ─────────────────────────────────────────────────────────────────

_settings = Settings()
_APP_START = time.time()

# Re-init logging with actual env
logger = _setup_logging(_settings.APP_ENV)

# Validate production config — FAIL FAST
_prod_errors = _settings.validate_production()
if _prod_errors:
    for err in _prod_errors:
        logger.critical("[startup:FATAL] %s", err)
    sys.exit(1)

_usage_tracker = UsageTracker(_settings)
_job_manager   = JobManager(
    redis_url=_settings.REDIS_URL,
    require_redis=(_settings.APP_ENV == "production"),
)
_router   = ProviderRouter(_settings)
_pipeline = Pipeline4K(_router, _settings, _usage_tracker)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Luminorbit PRODUCTION — 15 providers — security-hardened")
    _settings.log_startup()
    await _router.initialize()
    yield
    _temp_registry.cleanup_all()
    logger.info("🛑 Luminorbit shutting down")

app = FastAPI(
    title="Luminorbit",
    version="22.1.0",
    description="15-provider AI backend — TRUE 4K — Production Hardened",
    lifespan=lifespan,
    # Never expose internal docs in production
    docs_url=None if _settings.APP_ENV == "production" else "/docs",
    redoc_url=None if _settings.APP_ENV == "production" else "/redoc",
    openapi_url=None if _settings.APP_ENV == "production" else "/openapi.json",
)

# ── Middlewares (order matters: outermost = first) ───────────────────────────
# NOTE: HTTPSRedirectMiddleware removed — Cloudflare/reverse-proxy already enforces HTTPS at the edge.

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Rate limiting ─────────────────────────────────────────────────────────────
if _RATE_LIMIT_AVAILABLE:
    _limiter = Limiter(key_func=get_remote_address, default_limits=[_settings.RATE_LIMIT_BURST])
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info("[app] Rate limiting: IP=%s burst=%s", _settings.RATE_LIMIT_IP, _settings.RATE_LIMIT_BURST)
else:
    # NOTE: HTTPSRedirectMiddleware removed — Cloudflare/reverse-proxy already enforces HTTPS at the edge.
    logger.critical("[app] Rate limiting required in production but slowapi not installed")
    sys.exit(1)

# ── Auth ──────────────────────────────────────────────────────────────────────

async def verify_auth(request: Request):
    """Enforces Bearer token auth when API_SECRET is set."""
    if not _settings.API_SECRET:
        return  # Dev mode: no auth
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth[len("Bearer "):]
    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(token, _settings.API_SECRET):
        ip_hash = hash_ip(get_client_ip(request))
        logger.warning("[auth] Invalid token from ip_hash=%s", ip_hash)
        raise HTTPException(status_code=401, detail="Invalid token")

# ── Heavy tool detection ──────────────────────────────────────────────────────

_HEAVY_CAPABILITIES = {"video-gen", "temporal", "audio-extraction", "audio-sync", "compression"}
_HEAVY_TOOLS = {
    "Runway Gen-5", "Seedance 2.0", "Kling AI 3.0", "Luma Dream Machine", "Pika 2.5",
    "Hailuo MiniMax", "Sora Edit", "Stable Video Diffusion", "LivePortrait", "Topaz Video AI 5",
    "TecoGAN", "RIFE", "DAIN", "RAFT + ESRGAN", "Temporal GAN", "AnimateDiff", "Wonder Dynamics",
    "Auto Caption Generator", "Audio Extractor Tool", "Video Compressor Pro",
    "Video Speed Controller", "MultiCam Sync", "Match Cut Flow", "Beat Sync Drop",
}

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — includes Redis, provider circuit status, uptime. No rate limiting."""
    redis_ok = False
    if _job_manager._redis:
        try:
            _job_manager._redis.ping()
            redis_ok = True
        except Exception:
            pass
    return {
        "status": "ok",
        "version": "22.1.0",
        "uptime_s": round(time.time() - _APP_START),
        "redis": "connected" if redis_ok else "unavailable",
        "providers": await _router.health_summary(),
        "timestamp": int(time.time()),
    }


@app.post("/api/process", response_model=ProcessResponse)
async def process_json(
    req: ProcessRequest, request: Request,
    background_tasks: BackgroundTasks, _auth=Depends(verify_auth)
):
    """Main processing endpoint. Rate limiting applied globally via slowapi Limiter default_limits."""
    client_ip  = get_client_ip(request)
    ip_hash    = hash_ip(client_ip)
    request_id = str(uuid.uuid4())[:8]
    logger.info("[api] /api/process ip_hash=%s request_id=%s tool=%s", ip_hash, request_id, req.tool)

    violations = validate_process_contract(req.model_dump())
    if violations:
        raise HTTPException(status_code=422, detail={"contract_violations": violations})

    raw: Optional[bytes] = None
    if req.file_data:
        try:
            # Support both raw base64 and data:URL format
            file_b64 = req.file_data.split(",", 1)[-1] if "," in req.file_data else req.file_data
            raw = base64.b64decode(file_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid file_data encoding: {type(e).__name__}")

    user_id = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    is_heavy = req.tool in _HEAVY_TOOLS or req.capability in _HEAVY_CAPABILITIES

    if is_heavy:
        job_id = str(uuid.uuid4())
        _job_manager.create_job(job_id, req.tool)

        async def _bg():
            try:
                _job_manager.set_status(job_id, "processing", 20)
                result = await _pipeline.run(
                    tool=req.tool, capability=req.capability, params=req.params,
                    file_bytes=raw, file_mime=req.file_mime or req.inputType,
                    resolution=req.resolution, user_id=user_id, request_id=request_id,
                )
                _job_manager.set_done(job_id, result["output"])
            except Exception as e:
                logger.error("[heavy_bg:%s] %s", job_id, type(e).__name__, exc_info=True)
                _job_manager.set_failed(job_id, str(e))

        background_tasks.add_task(_bg)
        return ProcessResponse(
            success=True, job_id=job_id, provider="async",
            resolution="3840x2160", request_id=request_id,
            metadata={"async": True, "poll": f"/api/jobs/{job_id}"},
        )

    try:
        result = await _pipeline.run(
            tool=req.tool, capability=req.capability, params=req.params,
            file_bytes=raw, file_mime=req.file_mime or req.inputType,
            resolution=req.resolution, user_id=user_id, request_id=request_id,
        )
        return ProcessResponse(
            success=True, output=result["output"], output_url=result["output"],
            provider=result.get("provider"), resolution=result.get("resolution", "3840x2160"),
            metadata=result.get("metadata", {}), status=result.get("status", "ok"),
            fallback_reason=result.get("fallback_reason"), request_id=result.get("request_id", request_id),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[/api/process] %s", type(e).__name__, exc_info=True)
        # Never leak internal error details to the client
        raise HTTPException(status_code=500, detail="processing_failed")


# Alias for frontend backward compatibility
@app.post("/process", response_model=ProcessResponse, include_in_schema=False)
async def process_alias(req: ProcessRequest, request: Request,
                        background_tasks: BackgroundTasks, _auth=Depends(verify_auth)):
    return await process_json(req, request, background_tasks, _auth)


@app.post("/api/process/upload", response_model=ProcessResponse)
async def process_upload(
    request:    Request,
    tool:       str,
    capability: str        = "basic-processing",
    resolution: str        = "4K",
    params:     str        = "{}",
    file:       UploadFile = File(...),
    _auth=Depends(verify_auth),
):
    """Multipart upload endpoint for large files (preferred over base64)."""
    ct = file.content_type or ""
    if ct and ct not in _ALLOWED_MIMES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {ct}")

    raw  = await file.read()
    mime = file.content_type or "application/octet-stream"
    try:
        mime, _ = validate_file_bytes(raw, mime,
                                      max_bytes=_settings.MAX_FILE_MB * 1024 * 1024,
                                      max_img_w=_settings.MAX_IMAGE_WIDTH,
                                      max_img_h=_settings.MAX_IMAGE_HEIGHT)
    except FileValidationError as fve:
        raise HTTPException(status_code=422, detail=f"file_validation:{fve}")

    client_ip  = get_client_ip(request)
    user_id    = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    request_id = str(uuid.uuid4())[:8]

    try:
        parsed_params = json.loads(params or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="params must be valid JSON")

    try:
        result = await _pipeline.run(
            tool=tool, capability=capability, params=parsed_params,
            file_bytes=raw, file_mime=mime, resolution=resolution,
            user_id=user_id, request_id=request_id,
        )
        return ProcessResponse(
            success=True, output=result["output"], output_url=result["output"],
            provider=result.get("provider"), resolution=result.get("resolution", "3840x2160"),
            metadata=result.get("metadata", {}), status=result.get("status", "ok"),
            fallback_reason=result.get("fallback_reason"), request_id=result.get("request_id", request_id),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[/api/process/upload] %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="processing_failed")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, _auth=Depends(verify_auth)):
    if not job_id or len(job_id) > 64:
        raise HTTPException(status_code=400, detail="invalid_job_id")
    job = _job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_val = job.get("output")
    return JobStatusResponse(
        job_id=job["job_id"], status=job["status"],
        progress=job.get("progress", 0), output=output_val, output_url=output_val,
        error=job.get("error"),
    )


@app.get("/api/providers")
async def get_providers(_auth=Depends(verify_auth)):
    return await _router.provider_stats()


@app.post("/api/providers/{provider}/reset")
async def reset_provider(provider: str, _auth=Depends(verify_auth)):
    if provider not in ["pollinations", "cloudflare", "gemini", "groq", "mistral",
                         "openrouter", "segmind", "krea", "together", "huggingface",
                         "deepai", "pixazo", "pexels", "unsplash", "cloudinary"]:
        raise HTTPException(status_code=400, detail="unknown_provider")
    await _router.reset_provider(provider)
    return {"ok": True, "provider": provider}


@app.post("/api/providers/{provider}/disable")
async def admin_disable(provider: str, _auth=Depends(verify_auth)):
    disable_provider(provider)
    return {"ok": True, "provider": provider, "status": "disabled"}


@app.post("/api/providers/{provider}/enable")
async def admin_enable(provider: str, _auth=Depends(verify_auth)):
    enable_provider(provider)
    await _router.reset_provider(provider)
    return {"ok": True, "provider": provider, "status": "enabled"}


@app.get("/api/usage/{user_id}")
async def get_usage(user_id: str, _auth=Depends(verify_auth)):
    return await _usage_tracker.get_user_stats(user_id)


@app.get("/api/monitoring/scores")
async def get_scores(_auth=Depends(verify_auth)):
    return await _router._scorer.dump()


@app.get("/api/tools")
async def get_valid_tools():
    return {"tools": VALID_TOOLS, "capabilities": list(VALID_CAPABILITIES)}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    """Pass HTTPException through with its proper status code (don't swallow into 500)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    # Log full details internally, return only generic error to client
    logger.error("[global_error] %s: %s", type(exc).__name__, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "internal_server_error"},
    )

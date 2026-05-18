"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LUMINORBIT v26 — PRODUCTION PIPELINE ENGINE (STABILIZED)                  ║
║  luminorbit_pipelines.py                                                    ║
║                                                                             ║
║  Deploy alongside luminorbit_backend.py on Railway.                        ║
║  Imported by luminorbit_backend.py via:                                     ║
║    from luminorbit_pipelines import CORS_ALLOWED_ORIGINS, build_pipeline_engine ║
║                                                                             ║
║  REPAIR CHANGELOG v26:                                                     ║
║   FIX-1  HuggingFace segmentation: Accept:image/png header added;          ║
║          dual-path JSON/binary response parsing; PIL mask application;      ║
║          503 retry with backoff; RMBG-2.0 + BiRefNet fallback models.      ║
║   FIX-2  Segmind: bg-removal endpoint hardened; 404 detection with         ║
║          per-model fallback chain; payload normalisation.                   ║
║   FIX-3  Cloudflare AI: ESRGAN model removed (unavailable); segmentation   ║
║          via @hf/facebook/sam-vit-base properly implemented; startup        ║
║          credential validation; runtime 401 detection with safe disable.   ║
║   FIX-4  Cloudinary: Signature computation FIXED — all non-excluded         ║
║          params signed alphabetically per Cloudinary spec; transformation  ║
║          uses eager param (included in sig); URL-injection fallback.        ║
║   FIX-5  PipelineEngine.run() wrapped in global try/except — RuntimeError  ║
║          never propagates to frontend; all failures return structured JSON. ║
║   FIX-6  build_pipeline_engine: full startup health registry per provider. ║
║   FIX-7  _validate_response_image: expanded magic byte coverage.           ║
║   FIX-8  Segmentation pipeline: fake-generation fallback explicitly         ║
║          blocked — only real AI providers (HF, Segmind, CF) allowed.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ── Optional Pillow import (used for HF mask application) ─────────────────────
try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


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
    # FIX-8: segmentation uses ONLY real AI providers — no pollinations fake fallback
    "segmentation":      ["huggingface", "segmind", "cloudflare"],
    "inpainting":        ["segmind", "huggingface", "deepai"],
    "face-processing":   ["huggingface", "deepai", "krea"],
    "restoration":       ["huggingface", "krea", "deepai"],
    "image-enhancement": ["segmind", "huggingface", "cloudflare", "cloudinary"],
    "style-transfer":    ["huggingface", "together", "pollinations"],
    "video-gen":         ["pollinations", "together"],
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
#     FIX-1: Updated to confirmed-working inference API models.
#     RMBG-1.4 and RMBG-2.0 support Accept:image/png for direct transparent PNG.
# ══════════════════════════════════════════════════════════════════════════════

HF_MODELS: Dict[str, str] = {
    # Background removal / segmentation — primary model
    "segmentation":        "briaai/RMBG-1.4",
    # Background removal fallback — newer higher quality
    "segmentation_alt1":   "briaai/RMBG-2.0",
    # Background removal fallback — BiRefNet architecture
    "segmentation_alt2":   "ZhengPeng7/BiRefNet",
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

# HuggingFace Inference API base
HF_API_BASE = "https://api-inference.huggingface.co/models"

# Segmentation model priority list — tried in order by HuggingFaceAdapter
HF_SEGMENTATION_MODELS: List[str] = [
    "briaai/RMBG-1.4",
    "briaai/RMBG-2.0",
    "ZhengPeng7/BiRefNet",
]


# ══════════════════════════════════════════════════════════════════════════════
# §5  PROVIDER ADAPTERS
# ══════════════════════════════════════════════════════════════════════════════

class ProviderError(Exception):
    """Raised when a provider fails. Message logged and fallback triggered."""
    def __init__(self, provider: str, reason: str, status_code: int = 0):
        super().__init__(f"[{provider}] {reason}")
        self.provider = provider
        self.reason = reason
        self.status_code = status_code


def _bytes_to_data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _validate_response_image(data: bytes, provider: str) -> None:
    """
    FIX-7: Ensure response bytes look like a real image, not an error payload.
    Expanded magic-byte coverage for WEBP, AVIF, TIFF.
    """
    if len(data) < 512:
        try:
            decoded = data.decode("utf-8", errors="replace")
            raise ProviderError(provider, f"Response too small ({len(data)}B): {decoded[:200]}")
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(provider, f"Response too small ({len(data)}B)")

    # PNG
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return
    # JPEG
    if data[:3] == b'\xff\xd8\xff':
        return
    # GIF
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return
    # WEBP (RIFF....WEBP)
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return
    # AVIF / HEIF (ftyp box)
    if data[4:8] in (b'ftyp', b'ftypavif', b'ftyphei'):
        return
    # TIFF
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return
    # Accept any large-enough unknown binary (might be valid format we don't recognise)
    if len(data) > 8192:
        return
    raise ProviderError(provider, f"Response not a valid image (magic: {data[:8].hex()}, size: {len(data)}B)")


def _apply_hf_mask_to_image(image_bytes: bytes, mask_bytes: bytes, provider: str) -> bytes:
    """
    FIX-1 (PIL path): Apply a grayscale segmentation mask to original image
    to produce a transparent RGBA PNG. Used when HF returns JSON mask data
    instead of a binary PNG directly.
    """
    if not _PIL_AVAILABLE:
        raise ProviderError(provider, "PIL not available for mask application — install Pillow")

    try:
        img = _PILImage.open(io.BytesIO(image_bytes)).convert("RGBA")
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
# 5A  HuggingFace Adapter
#     FIX-1: Complete segmentation rewrite with dual-path response handling.
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
        FIX-1: Tries each segmentation model in HF_SEGMENTATION_MODELS order.

        Strategy:
          1. POST raw image bytes with Accept:image/png → expect binary transparent PNG.
          2. If Content-Type of response is JSON (or JSON parsed successfully),
             extract mask from response and apply to original image using PIL.
          3. Retry once on 503 (model loading) with 8 s backoff.
          4. Raise ProviderError if all models fail — no fake fallback.
        """
        last_err = "no models attempted"

        for model in HF_SEGMENTATION_MODELS:
            url = f"{HF_API_BASE}/{model}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  file_mime or "image/png",
                "Accept":        "image/png",    # ← FIX: request binary PNG directly
            }

            logger.info("[HF-SEG] Trying model=%s bytes=%d", model, len(file_bytes))

            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=90.0) as client:
                        resp = await client.post(url, content=file_bytes, headers=headers)

                    if resp.status_code == 503:
                        if attempt == 0:
                            logger.info("[HF-SEG] 503 model loading, waiting 8s model=%s", model)
                            await asyncio.sleep(8)
                            continue
                        else:
                            last_err = f"{model}: model still loading after retry"
                            break  # Try next model

                    if resp.status_code == 404:
                        logger.warning("[HF-SEG] 404 model not found model=%s", model)
                        last_err = f"{model}: 404 not found"
                        break  # Try next model

                    if resp.status_code == 401:
                        # Auth failure — no point trying other models
                        raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)

                    if resp.status_code != 200:
                        last_err = f"{model}: HTTP {resp.status_code} {resp.text[:200]}"
                        break

                    content_type = resp.headers.get("content-type", "")
                    raw = resp.content

                    # ── Path A: Got binary image back ─────────────────────────
                    if (
                        "image" in content_type
                        or raw[:8] == b'\x89PNG\r\n\x1a\n'
                        or raw[:3] == b'\xff\xd8\xff'
                        or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
                    ):
                        _validate_response_image(raw, cls.NAME)
                        logger.info("[HF-SEG] Binary PNG path model=%s bytes=%d", model, len(raw))
                        return {
                            "success": True,
                            "output":  _bytes_to_data_uri(raw, "image/png"),
                            "provider": cls.NAME,
                            "model":   model,
                        }

                    # ── Path B: Got JSON — parse mask array ───────────────────
                    try:
                        data = resp.json()
                    except Exception:
                        last_err = f"{model}: response not image or JSON ({len(raw)}B)"
                        break

                    mask_bytes: Optional[bytes] = None

                    # HF image-segmentation models return:
                    # [{"label": "...", "mask": "data:image/png;base64,...", "score": 0.9}]
                    if isinstance(data, list) and data:
                        entry = data[0]
                        mask_val = entry.get("mask", "")
                        if mask_val and isinstance(mask_val, str):
                            if mask_val.startswith("data:"):
                                # Data URI — decode base64 portion
                                try:
                                    mask_b64 = mask_val.split(",", 1)[1]
                                    mask_bytes = base64.b64decode(mask_b64)
                                except Exception as e:
                                    last_err = f"{model}: mask decode failed: {e}"
                                    break
                            else:
                                # Plain base64
                                try:
                                    mask_bytes = base64.b64decode(mask_val)
                                except Exception as e:
                                    last_err = f"{model}: mask b64decode failed: {e}"
                                    break

                    if mask_bytes:
                        logger.info("[HF-SEG] JSON-mask path model=%s, applying to original", model)
                        transparent_png = _apply_hf_mask_to_image(file_bytes, mask_bytes, cls.NAME)
                        _validate_response_image(transparent_png, cls.NAME)
                        return {
                            "success": True,
                            "output":  _bytes_to_data_uri(transparent_png, "image/png"),
                            "provider": cls.NAME,
                            "model":   model,
                        }

                    # ── Path C: JSON but no mask — try next model ─────────────
                    last_err = f"{model}: JSON response had no usable mask data: {str(data)[:150]}"
                    logger.warning("[HF-SEG] %s", last_err)
                    break

                except ProviderError:
                    raise
                except asyncio.TimeoutError:
                    last_err = f"{model}: timeout"
                    logger.warning("[HF-SEG] Timeout model=%s", model)
                    break
                except Exception as e:
                    last_err = f"{model}: {e}"
                    logger.warning("[HF-SEG] Exception model=%s: %s", model, e)
                    break

        raise ProviderError(cls.NAME, f"All HF segmentation models failed. Last: {last_err}")

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
        api_key = settings.HF_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "HF_API_KEY not configured")

        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        # ── Segmentation: dedicated multi-model path (FIX-1) ─────────────────
        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image provided for segmentation")
            return await cls._call_segmentation(api_key, file_bytes, file_mime, logger)

        model = params.get("hf_model") or HF_MODELS.get(capability) or HF_MODELS["image-gen"]
        url   = f"{HF_API_BASE}/{model}"
        headers: Dict[str, str] = {"Authorization": f"Bearer {api_key}"}

        # ── Super-resolution / restoration ────────────────────────────────────
        if capability in ("super-resolution", "restoration"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            headers["Content-Type"] = file_mime or "image/jpeg"
            logger.info("[HF] %s model=%s bytes=%d", capability, model, len(file_bytes))

            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, content=file_bytes, headers=headers)

            if resp.status_code == 503:
                raise ProviderError(cls.NAME, f"Model loading ({model})", 503)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success": True,
                "output":  _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME, "model": model,
            }

        # ── Image generation ──────────────────────────────────────────────────
        if capability == "image-gen":
            prompt = params.get("prompt", "a beautiful high quality image")
            headers["Content-Type"] = "application/json"
            payload: Dict[str, Any] = {"inputs": prompt}
            if params.get("width"):
                payload["parameters"] = {
                    "width":  params["width"],
                    "height": params.get("height", params["width"]),
                }

            logger.info("[HF] image-gen model=%s prompt=%s", model, prompt[:80])
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code == 503:
                raise ProviderError(cls.NAME, f"Model loading ({model})", 503)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success": True,
                "output":  _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME, "model": model,
            }

        # ── Captioning ────────────────────────────────────────────────────────
        if capability == "captioning":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for captioning")

            cap_url = f"{HF_API_BASE}/{HF_MODELS.get('captioning', 'Salesforce/blip-image-captioning-large')}"
            headers["Content-Type"] = file_mime or "image/jpeg"

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(cap_url, content=file_bytes, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            data = resp.json()
            caption = ""
            if isinstance(data, list) and data:
                caption = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                caption = data.get("generated_text", "")
            return {"success": True, "output": caption, "provider": cls.NAME, "output_type": "text"}

        # ── Style transfer / enhancement / inpainting / face-processing ───────
        if capability in ("style-transfer", "image-enhancement", "inpainting", "face-processing"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            prompt   = params.get("prompt", f"Apply {capability} to this image, high quality result")
            gen_url  = f"{HF_API_BASE}/{HF_MODELS.get('image-gen', 'black-forest-labs/FLUX.1-schnell')}"
            headers["Content-Type"] = "application/json"
            img_b64  = base64.b64encode(file_bytes).decode()
            payload  = {"inputs": prompt, "image": img_b64}

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(gen_url, json=payload, headers=headers)

            if resp.status_code == 503:
                raise ProviderError(cls.NAME, f"Model loading", 503)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            result_bytes = resp.content
            _validate_response_image(result_bytes, cls.NAME)
            return {
                "success": True,
                "output":  _bytes_to_data_uri(result_bytes, "image/jpeg"),
                "provider": cls.NAME,
            }

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ─────────────────────────────────────────────────────────────────────────────
# 5B  Pollinations Adapter  (free, no key required)
#     NOTE: NOT in segmentation chain (FIX-8 — no fake outputs for bg removal)
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
        # FIX-8: Explicitly block segmentation — would return fake stylized images
        if capability == "segmentation":
            raise ProviderError(cls.NAME, "Pollinations BLOCKED for segmentation (fake output prevention)")

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

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

        result_bytes = resp.content
        _validate_response_image(result_bytes, cls.NAME)
        return {"success": True, "output": _bytes_to_data_uri(result_bytes, "image/jpeg"), "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5C  Segmind Adapter
#     FIX-2: bg-removal endpoint hardened; 404 detection; payload normalised.
# ─────────────────────────────────────────────────────────────────────────────

class SegmindAdapter:
    NAME = "segmind"
    CAPABILITIES = {"image-gen", "segmentation", "inpainting", "image-enhancement",
                    "super-resolution", "controlnet"}
    BASE = "https://api.segmind.com/v1"

    # FIX-2: Model endpoint list for segmentation — tried in order
    SEGMENTATION_MODELS: List[str] = [
        "bg-removal",           # Primary: Segmind Background Removal
        "remove-background",    # Alternate name some API versions use
    ]

    MODELS: Dict[str, str] = {
        "image-gen":         "sdxl1.0-txt2img",
        "inpainting":        "sdxl-inpainting",
        "image-enhancement": "esrgan-v1-x2plus",
        "super-resolution":  "esrgan-v1-x2plus",
        "controlnet":        "sd1.5-controlnet-canny",
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
        api_key = settings.SEGMIND_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "SEGMIND_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        # ── Background removal (FIX-2: multi-endpoint fallback) ───────────────
        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image provided for background removal")

            img_b64 = base64.b64encode(file_bytes).decode()
            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
            last_err = "no models tried"

            for model_endpoint in cls.SEGMENTATION_MODELS:
                url = f"{cls.BASE}/{model_endpoint}"
                # FIX-2: Both endpoint variants accept image as data URI
                payload = {
                    "image":          f"data:{file_mime};base64,{img_b64}",
                    "output_format":  "PNG",        # request transparent PNG
                }

                logger.info("[Segmind] bg-removal endpoint=%s bytes=%d", model_endpoint, len(file_bytes))
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post(url, json=payload, headers=headers)

                    if resp.status_code == 404:
                        last_err = f"{model_endpoint}: 404 — endpoint not found"
                        logger.warning("[Segmind] 404 on endpoint=%s", model_endpoint)
                        continue  # Try next endpoint name

                    if resp.status_code == 422:
                        # Unprocessable entity — payload format issue
                        # Try with image_url key variant
                        payload_alt = {"image_url": f"data:{file_mime};base64,{img_b64}"}
                        async with httpx.AsyncClient(timeout=60.0) as client:
                            resp = await client.post(url, json=payload_alt, headers=headers)

                    if resp.status_code == 402:
                        raise ProviderError(cls.NAME, "SEGMIND_API_KEY quota exhausted (402)", 402)

                    if resp.status_code == 401:
                        raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)

                    if resp.status_code != 200:
                        last_err = f"{model_endpoint}: HTTP {resp.status_code} {resp.text[:200]}"
                        logger.warning("[Segmind] %s", last_err)
                        continue

                    result_bytes = resp.content

                    # FIX-2: Some Segmind responses return JSON with base64 inside
                    content_type = resp.headers.get("content-type", "")
                    if "json" in content_type:
                        try:
                            data = resp.json()
                            img_b64_out = (
                                data.get("image")
                                or data.get("output")
                                or (data.get("images") or [None])[0]
                            )
                            if img_b64_out:
                                if img_b64_out.startswith("data:"):
                                    raw_b64 = img_b64_out.split(",", 1)[1]
                                    result_bytes = base64.b64decode(raw_b64)
                                else:
                                    result_bytes = base64.b64decode(img_b64_out)
                            else:
                                last_err = f"{model_endpoint}: JSON response, no image key"
                                continue
                        except Exception as e:
                            last_err = f"{model_endpoint}: JSON parse failed: {e}"
                            continue

                    _validate_response_image(result_bytes, cls.NAME)
                    logger.info("[Segmind] bg-removal SUCCESS endpoint=%s bytes=%d", model_endpoint, len(result_bytes))
                    return {
                        "success": True,
                        "output":  _bytes_to_data_uri(result_bytes, "image/png"),
                        "provider": cls.NAME,
                    }

                except ProviderError:
                    raise
                except asyncio.TimeoutError:
                    last_err = f"{model_endpoint}: timeout"
                    logger.warning("[Segmind] Timeout endpoint=%s", model_endpoint)
                    continue
                except Exception as e:
                    last_err = f"{model_endpoint}: {e}"
                    logger.warning("[Segmind] Exception endpoint=%s: %s", model_endpoint, e)
                    continue

            raise ProviderError(cls.NAME, f"All Segmind bg-removal endpoints failed. Last: {last_err}")

        # ── Image generation ───────────────────────────────────────────────────
        if capability == "image-gen":
            model   = cls.MODELS["image-gen"]
            url     = f"{cls.BASE}/{model}"
            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
            prompt  = params.get("prompt", "a high quality image")
            payload_gen = {
                "prompt":               prompt,
                "negative_prompt":      params.get("negative_prompt", "low quality, blurry"),
                "samples":              1,
                "num_inference_steps":  params.get("steps", 20),
                "guidance_scale":       params.get("guidance_scale", 7.5),
                "img_width":            params.get("width", 1024),
                "img_height":           params.get("height", 1024),
                "base64":               True,
            }
            logger.info("[Segmind] text2img prompt=%s", prompt[:80])
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload_gen, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            data = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64_out}", "provider": cls.NAME}

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
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload_sr, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            data = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64_out}", "provider": cls.NAME}

        # ── Inpainting ────────────────────────────────────────────────────────
        if capability == "inpainting":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for inpainting")

            model   = cls.MODELS["inpainting"]
            url     = f"{cls.BASE}/{model}"
            headers = {"x-api-key": api_key, "Content-Type": "application/json"}
            img_b64 = base64.b64encode(file_bytes).decode()
            mask_b64 = params.get("mask_b64", img_b64)
            payload_inp = {
                "prompt":               params.get("prompt", "fill seamlessly"),
                "image":                f"data:{file_mime};base64,{img_b64}",
                "mask":                 f"data:image/png;base64,{mask_b64}",
                "samples":              1,
                "num_inference_steps":  20,
                "base64":               True,
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload_inp, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

            data = resp.json()
            img_b64_out = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64_out:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64_out}", "provider": cls.NAME}

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
        api_key = settings.TOGETHER_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "TOGETHER_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        if capability == "captioning":
            model    = "meta-llama/Llama-Vision-Free"
            prompt   = params.get("prompt", "Describe this image in detail.")
            messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
            if file_bytes:
                img_b64 = base64.b64encode(file_bytes).decode()
                messages = [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ]
                }]

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{cls.BASE}/chat/completions",
                    json={"model": model, "messages": messages, "max_tokens": 256},
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}

        prompt = params.get("prompt", "a high quality image")
        model  = cls.IMAGE_MODELS.get(params.get("preset", ""), cls.IMAGE_MODELS["default"])
        payload = {
            "model":  model,
            "prompt": prompt,
            "width":  params.get("width", 1024),
            "height": params.get("height", 1024),
            "steps":  params.get("steps", 4),
            "n":      1,
        }

        logger.info("[Together] image-gen model=%s prompt=%s", model, prompt[:80])
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{cls.BASE}/images/generations",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

        data     = resp.json()
        img_data = (data.get("data") or [{}])[0]
        url_out  = img_data.get("url") or img_data.get("b64_json")
        if not url_out:
            raise ProviderError(cls.NAME, "No image URL in response")
        if img_data.get("b64_json"):
            url_out = f"data:image/jpeg;base64,{url_out}"
        return {"success": True, "output": url_out, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5E  Gemini Adapter  (captioning / vision)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiAdapter:
    NAME = "gemini"
    CAPABILITIES = {"captioning", "visualization", "image-gen"}
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
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "GEMINI_API_KEY not configured")

        model  = "gemini-1.5-flash"
        prompt = params.get("prompt", "Describe and analyze this image in detail.")
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if file_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": file_mime or "image/jpeg",
                    "data":      base64.b64encode(file_bytes).decode(),
                }
            })

        payload = {"contents": [{"parts": parts}]}
        url     = f"{cls.BASE}/models/{model}:generateContent?key={api_key}"

        logger.info("[Gemini] captioning model=%s", model)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderError(cls.NAME, f"Unexpected response structure: {e}")

        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ─────────────────────────────────────────────────────────────────────────────
# 5F  Groq Adapter  (fast text/captioning)
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
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "GROQ_API_KEY not configured")

        model    = "llava-v1.5-7b-4096-preview"
        prompt   = params.get("prompt", "Describe this image.")
        messages: List[Dict[str, Any]] = []

        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{cls.BASE}/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 256},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ─────────────────────────────────────────────────────────────────────────────
# 5G  Mistral Adapter  (text/captioning)
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
        api_key = settings.MISTRAL_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "MISTRAL_API_KEY not configured")

        model    = "pixtral-12b-2409"
        prompt   = params.get("prompt", "Describe this image.")
        messages: List[Dict[str, Any]]

        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": f"data:{file_mime};base64,{img_b64}"},
                    {"type": "text", "text": prompt},
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{cls.BASE}/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 256},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

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
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "OPENROUTER_API_KEY not configured")

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

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{cls.BASE}/chat/completions",
                    json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 256},
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}

        prompt = params.get("prompt", "a high quality image")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{cls.BASE}/images/generations",
                json={"model": "stability/stable-diffusion-3-medium", "prompt": prompt, "n": 1},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        data    = resp.json()
        url_out = (data.get("data") or [{}])[0].get("url", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No image URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5I  Cloudflare AI Adapter
#     FIX-3: Removed invalid @cf/esrgan model; proper segmentation via SAM;
#            401 detection; startup credential validation.
# ─────────────────────────────────────────────────────────────────────────────

class CloudflareAdapter:
    NAME = "cloudflare"
    CAPABILITIES = {
        "segmentation",
        "image-gen",
        "compression",
        "basic-processing",
        "audio-extraction",
        "audio-sync",
        "color-matching",
        "temporal",
    }

    # FIX-3: Only confirmed CF Workers AI models. @cf/esrgan removed (not available).
    CF_MODELS: Dict[str, str] = {
        "image-gen":    "@cf/black-forest-labs/flux-1-schnell",
        "image-gen-sd": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "image-gen-xl": "@cf/bytedance/stable-diffusion-xl-lightning",
        "segmentation": "@hf/facebook/sam-vit-base",
    }

    @classmethod
    def _base_url(cls, settings: Any, model: str) -> str:
        acct = settings.CLOUDFLARE_ACCOUNT_ID
        return f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"

    @classmethod
    def _auth_headers(cls, settings: Any) -> Dict[str, str]:
        return {"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"}

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
        # FIX-3: Validate credentials present
        if not settings.CLOUDFLARE_ACCOUNT_ID:
            raise ProviderError(cls.NAME, "CLOUDFLARE_ACCOUNT_ID not configured", 0)
        if not settings.CLOUDFLARE_API_TOKEN:
            raise ProviderError(cls.NAME, "CLOUDFLARE_API_TOKEN not configured", 0)

        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = cls._auth_headers(settings)

        # ── Image generation ──────────────────────────────────────────────────
        if capability == "image-gen":
            prompt    = params.get("prompt", "a high quality photorealistic image")
            model_key = "image-gen"
            model_url = cls._base_url(settings, cls.CF_MODELS[model_key])

            payload   = {
                "prompt": prompt,
                "num_steps": params.get("steps", 4),
            }
            logger.info("[Cloudflare] image-gen model=%s prompt=%s", cls.CF_MODELS[model_key], prompt[:60])

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    model_url,
                    json=payload,
                    headers={**headers, "Content-Type": "application/json"},
                )

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "CF token invalid or missing AI permission (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            # CF image-gen returns binary PNG or JSON with base64
            content_type = resp.headers.get("content-type", "")
            if "image" in content_type or resp.content[:8] == b'\x89PNG\r\n\x1a\n':
                result_bytes = resp.content
                _validate_response_image(result_bytes, cls.NAME)
                return {
                    "success": True,
                    "output":  _bytes_to_data_uri(result_bytes, "image/png"),
                    "provider": cls.NAME,
                }
            else:
                try:
                    data = resp.json()
                    # CF wraps in {"result": {"image": "<b64>"}, "success": true}
                    img_b64 = (
                        data.get("result", {}).get("image")
                        or data.get("image")
                    )
                    if img_b64:
                        return {
                            "success": True,
                            "output":  f"data:image/png;base64,{img_b64}",
                            "provider": cls.NAME,
                        }
                except Exception:
                    pass
                raise ProviderError(cls.NAME, "Could not extract image from CF response")

        # ── Segmentation via SAM (FIX-3: properly implemented) ────────────────
        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for CF segmentation")

            model_url = cls._base_url(settings, cls.CF_MODELS["segmentation"])
            logger.info("[Cloudflare] SAM segmentation bytes=%d", len(file_bytes))

            # CF SAM accepts raw binary image bytes
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    model_url,
                    content=file_bytes,
                    headers={**headers, "Content-Type": file_mime or "image/jpeg"},
                )

            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "CF token invalid or missing AI permission (401)", 401)
            if resp.status_code == 404:
                raise ProviderError(cls.NAME, "CF SAM model not available on this account (404)", 404)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            content_type = resp.headers.get("content-type", "")

            # CF SAM may return binary PNG mask
            if "image" in content_type or resp.content[:8] == b'\x89PNG\r\n\x1a\n':
                result_bytes = resp.content
                if _PIL_AVAILABLE and file_bytes:
                    # Apply mask to original image to produce transparent PNG
                    try:
                        transparent = _apply_hf_mask_to_image(file_bytes, result_bytes, cls.NAME)
                        return {
                            "success": True,
                            "output":  _bytes_to_data_uri(transparent, "image/png"),
                            "provider": cls.NAME,
                        }
                    except ProviderError:
                        pass  # Fall through to returning raw mask

                _validate_response_image(result_bytes, cls.NAME)
                return {
                    "success": True,
                    "output":  _bytes_to_data_uri(result_bytes, "image/png"),
                    "provider": cls.NAME,
                }

            # CF SAM may return JSON with masks array
            try:
                data = resp.json()
                masks = (
                    data.get("result", {}).get("masks")
                    or data.get("masks")
                    or []
                )
                if masks and isinstance(masks, list):
                    # Take first mask, apply to original image
                    mask_val = masks[0]
                    if isinstance(mask_val, str):
                        mask_bytes = base64.b64decode(mask_val.split(",", 1)[-1] if "," in mask_val else mask_val)
                        if _PIL_AVAILABLE:
                            transparent = _apply_hf_mask_to_image(file_bytes, mask_bytes, cls.NAME)
                            return {
                                "success": True,
                                "output":  _bytes_to_data_uri(transparent, "image/png"),
                                "provider": cls.NAME,
                            }
            except Exception as e:
                logger.warning("[Cloudflare] SAM JSON parse failed: %s", e)

            raise ProviderError(cls.NAME, "CF SAM: could not extract usable mask from response")

        # ── Fallback for other capabilities ───────────────────────────────────
        raise ProviderError(cls.NAME, f"Capability '{capability}' not yet implemented in CF adapter")


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
        api_key = settings.DEEPAI_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "DEEPAI_API_KEY not configured")

        endpoint = cls.ENDPOINTS.get(capability)
        if not endpoint:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        url     = f"{cls.BASE}/{endpoint}"
        headers = {"api-key": api_key}

        if file_bytes:
            files = {"image": ("image.jpg", io.BytesIO(file_bytes), file_mime or "image/jpeg")}
            data_form: Dict[str, str] = {}
            if capability == "image-gen":
                data_form["text"] = params.get("prompt", "high quality image")
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, files=files, data=data_form, headers=headers)
        else:
            data_text = {"text": params.get("prompt", "a high quality image")}
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, data=data_text, headers=headers)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        result  = resp.json()
        out_url = result.get("output_url", "")
        if not out_url:
            raise ProviderError(cls.NAME, "No output_url in response")
        return {"success": True, "output": out_url, "provider": cls.NAME}


# ─────────────────────────────────────────────────────────────────────────────
# 5K  Cloudinary Adapter
#     FIX-4: Signature computation FIXED — all non-excluded params signed
#            in alphabetical order per Cloudinary specification.
#            Transformation uses 'eager' parameter (properly signed).
# ─────────────────────────────────────────────────────────────────────────────

class CloudinaryAdapter:
    NAME = "cloudinary"
    CAPABILITIES = {"compression", "basic-processing", "image-enhancement"}
    BASE = "https://api.cloudinary.com/v1_1"

    # FIX-4: Params excluded from signature per Cloudinary docs
    _SIG_EXCLUDE = frozenset({"file", "api_key", "resource_type", "cloud_name"})

    @classmethod
    def _compute_signature(cls, params_to_sign: Dict[str, str], api_secret: str) -> str:
        """
        FIX-4: Correct Cloudinary signature.
        1. Collect all params NOT in _SIG_EXCLUDE.
        2. Sort by key alphabetically.
        3. Join as 'key=value&key2=value2...'.
        4. Append api_secret (no separator).
        5. SHA1 the entire string.
        """
        filtered = {k: v for k, v in params_to_sign.items() if k not in cls._SIG_EXCLUDE}
        sorted_pairs = sorted(filtered.items())
        sig_string = "&".join(f"{k}={v}" for k, v in sorted_pairs) + api_secret
        return hashlib.sha1(sig_string.encode("utf-8")).hexdigest()

    @classmethod
    def _inject_transform_into_url(cls, secure_url: str, transform: str) -> str:
        """
        Build a transformed Cloudinary URL by injecting transformation string
        after the /upload/ segment. This avoids re-signing.

        e.g. https://res.cloudinary.com/{cloud}/image/upload/v123/foo.jpg
          → https://res.cloudinary.com/{cloud}/image/upload/q_80,f_auto/v123/foo.jpg
        """
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
        cloud      = settings.CLOUDINARY_CLOUD_NAME
        api_key    = settings.CLOUDINARY_API_KEY
        api_secret = settings.CLOUDINARY_API_SECRET

        if not all([cloud, api_key, api_secret]):
            raise ProviderError(cls.NAME, "CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET not configured")

        if not file_bytes:
            raise ProviderError(cls.NAME, "No file for Cloudinary processing")

        # ── Determine eager transformation string ─────────────────────────────
        transform_str = ""
        if capability == "compression":
            quality = params.get("quality", 80)
            transform_str = f"q_{quality},f_auto"
        elif capability == "image-enhancement":
            transform_str = "e_improve,q_auto:best"
        elif capability == "basic-processing":
            mode = params.get("mode", "resize")
            w    = params.get("width", 1024)
            h    = params.get("height", 1024)
            if mode == "resize":
                transform_str = f"w_{w},h_{h},c_fit,q_auto"
            elif mode in ("crop", "smart_crop"):
                transform_str = f"w_{w},h_{h},c_thumb,g_auto,q_auto"
            else:
                transform_str = "q_auto"

        timestamp = str(int(time.time()))

        # FIX-4: Build params dict that will be BOTH sent and signed
        upload_params: Dict[str, str] = {
            "api_key":   api_key,
            "timestamp": timestamp,
        }
        if transform_str:
            upload_params["eager"] = transform_str

        # FIX-4: Compute signature over ALL non-excluded params
        upload_params["signature"] = cls._compute_signature(upload_params, api_secret)

        upload_url = f"{cls.BASE}/{cloud}/image/upload"
        files      = {"file": ("image.jpg", io.BytesIO(file_bytes), file_mime or "image/jpeg")}

        logger.info("[Cloudinary] upload cap=%s bytes=%d eager=%s", capability, len(file_bytes), transform_str or "none")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(upload_url, files=files, data=upload_params)

        if resp.status_code == 401:
            # Attempt to surface the exact Cloudinary error message
            try:
                err_detail = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                err_detail = resp.text[:200]
            raise ProviderError(
                cls.NAME,
                f"Cloudinary auth failed (401): {err_detail}. "
                "Check CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET and ensure they match the correct cloud account.",
                401,
            )

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        result     = resp.json()
        secure_url = result.get("secure_url", "")
        if not secure_url:
            raise ProviderError(cls.NAME, "No secure_url in Cloudinary response")

        # FIX-4: If eager transform was requested, return the eagerly-transformed URL
        output_url = secure_url
        if transform_str:
            eager_results = result.get("eager", [])
            if eager_results and isinstance(eager_results, list):
                eager_url = eager_results[0].get("secure_url", "")
                if eager_url:
                    output_url = eager_url
                    logger.info("[Cloudinary] Using eager-transformed URL")
                else:
                    # Fallback: inject transform into base URL
                    output_url = cls._inject_transform_into_url(secure_url, transform_str)
                    logger.info("[Cloudinary] Using URL-injected transform")
            else:
                # No eager results yet — inject into URL (synchronous transform)
                output_url = cls._inject_transform_into_url(secure_url, transform_str)

        return {"success": True, "output": output_url, "provider": cls.NAME}


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
        api_key = settings.KREA_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "KREA_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        if capability == "image-gen":
            prompt = params.get("prompt", "a high quality image")
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{cls.BASE}/images/generations",
                    json={"prompt": prompt, "num_images": 1},
                    headers=headers,
                )
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            data    = resp.json()
            url_out = (data.get("images") or [{}])[0].get("url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No image URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        if capability in ("super-resolution", "face-processing", "restoration"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")

            img_b64  = base64.b64encode(file_bytes).decode()
            payload  = {
                "image":            f"data:{file_mime};base64,{img_b64}",
                "enhancement_type": capability,
            }
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(f"{cls.BASE}/images/enhance", json=payload, headers=headers)

            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            data    = resp.json()
            url_out = data.get("url") or data.get("output_url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No output URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ─────────────────────────────────────────────────────────────────────────────
# 5M  Pexels Adapter  (stock search)
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
        api_key = settings.PEXELS_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "PEXELS_API_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature landscape"))
        headers = {"Authorization": api_key}

        if capability == "video-gen":
            url = f"https://api.pexels.com/videos/search?query={query}&per_page=1&orientation=landscape"
            async with httpx.AsyncClient(timeout=15.0) as client:
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
            return {"success": True, "output": hd_file["link"], "provider": cls.NAME,
                    "metadata": {"source": "pexels", "query": query}}

        url = f"{cls.BASE}/search?query={query}&per_page=1"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)

        data   = resp.json()
        photos = data.get("photos", [])
        if not photos:
            raise ProviderError(cls.NAME, f"No photos for query: {query}")

        url_out = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No photo URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME,
                "metadata": {"source": "pexels", "query": query}}


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
        access_key = settings.UNSPLASH_ACCESS_KEY
        if not access_key:
            raise ProviderError(cls.NAME, "UNSPLASH_ACCESS_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature"))
        url     = f"{cls.BASE}/search/photos?query={query}&per_page=1&orientation=landscape"

        async with httpx.AsyncClient(timeout=15.0) as client:
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
        return {"success": True, "output": url_out, "provider": cls.NAME,
                "metadata": {"source": "unsplash", "query": query}}


# ══════════════════════════════════════════════════════════════════════════════
# §6  PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

PROVIDER_REGISTRY: Dict[str, Any] = {
    "huggingface":  HuggingFaceAdapter,
    "pollinations":  PollinationsAdapter,
    "segmind":       SegmindAdapter,
    "together":      TogetherAdapter,
    "gemini":        GeminiAdapter,
    "groq":          GroqAdapter,
    "mistral":       MistralAdapter,
    "openrouter":    OpenRouterAdapter,
    "cloudflare":    CloudflareAdapter,
    "deepai":        DeepAIAdapter,
    "cloudinary":    CloudinaryAdapter,
    "krea":          KreaAdapter,
    "pexels":        PexelsAdapter,
    "unsplash":      UnsplashAdapter,
}


# ══════════════════════════════════════════════════════════════════════════════
# §7  PIPELINE EXECUTION ENGINE
#     FIX-5: Global try/except in run() — RuntimeError never reaches frontend.
# ══════════════════════════════════════════════════════════════════════════════

class PipelineEngine:
    """
    Core execution engine.
    run() implements:
      1. Resolve tool → pipeline → capability
      2. Validate payload
      3. Execute provider chain with fallback
      4. Validate output (no fake success)
      5. Return standardized result dict — NEVER raises to caller.
    """

    def __init__(self, settings: Any, logger: logging.Logger):
        self._settings = settings
        self._log      = logger
        self._health:  Dict[str, float] = {p: 1.0 for p in PROVIDER_REGISTRY}

    def _record_success(self, provider: str) -> None:
        s = self._health.get(provider, 1.0)
        self._health[provider] = min(1.0, s * 1.05 + 0.05)

    def _record_failure(self, provider: str) -> None:
        s = self._health.get(provider, 1.0)
        self._health[provider] = max(0.1, s * 0.92)

    def _sorted_providers(self, capability: str) -> List[str]:
        base = CAPABILITY_PROVIDERS.get(capability, [])
        # FIX-5: Only include providers with health > 0 (0 = no key / disabled)
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
        """
        FIX-5: Entire body wrapped in try/except — zero RuntimeError propagation.
        """
        try:
            return await self._run_inner(
                tool, capability, params, file_bytes, file_mime,
                resolution, user_id, request_id,
            )
        except Exception as e:
            # Absolute last-resort catch — should never be reached due to inner guards
            self._log.exception(
                "[pipeline] UNHANDLED EXCEPTION tool=%s cap=%s req=%s: %s",
                tool, capability, request_id, e,
            )
            return {
                "success":    False,
                "error_code": "INTERNAL_ENGINE_ERROR",
                "message":    f"Internal pipeline engine error: {type(e).__name__}: {str(e)[:200]}",
                "tool":       tool,
                "capability": capability,
                "request_id": request_id,
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
            f"{len(file_bytes)}B" if file_bytes else "none",
        )

        # ── Step 1: Resolve pipeline name ─────────────────────────────────────
        pipeline_name = TOOL_PIPELINE_MAP.get(tool)
        if not pipeline_name:
            self._log.warning(
                "[pipeline] Tool '%s' not in TOOL_PIPELINE_MAP — using capability=%s", tool, capability
            )
            pipeline_name = "basic"

        # ── Step 2: Resolve capability ────────────────────────────────────────
        resolved_cap = PIPELINE_CAPABILITY.get(pipeline_name, capability)
        if resolved_cap != capability:
            self._log.info(
                "[pipeline] Capability override: request=%s → pipeline-resolved=%s (tool=%s pipeline=%s)",
                capability, resolved_cap, tool, pipeline_name,
            )
        capability = resolved_cap

        # ── Step 3: Get provider list ─────────────────────────────────────────
        providers = self._sorted_providers(capability)
        if not providers:
            self._log.error("[pipeline] No providers for capability=%s", capability)
            return {
                "success":    False,
                "error_code": "NO_PROVIDERS",
                "message":    f"No configured providers for capability '{capability}'",
                "tool":       tool,
                "pipeline":   pipeline_name,
                "capability": capability,
            }

        self._log.info("[pipeline] Providers for %s: %s", capability, providers)

        # ── Step 4: Execute provider chain ────────────────────────────────────
        last_error = "unknown"
        attempted:  List[str] = []

        for provider_name in providers:
            adapter = PROVIDER_REGISTRY.get(provider_name)
            if not adapter:
                self._log.warning("[pipeline] Unknown provider: %s", provider_name)
                continue

            if capability not in getattr(adapter, "CAPABILITIES", set()):
                self._log.debug("[pipeline] %s doesn't support %s — skip", provider_name, capability)
                continue

            attempted.append(provider_name)
            self._log.info("[pipeline] Trying provider=%s cap=%s req=%s", provider_name, capability, request_id)

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

                # For image data URIs: verify they decode to real image bytes
                if isinstance(output, str) and output.startswith("data:image"):
                    try:
                        raw    = output.split(",", 1)[1]
                        img_bytes = base64.b64decode(raw)
                        _validate_response_image(img_bytes, provider_name)
                    except ProviderError:
                        raise
                    except Exception as e:
                        raise ProviderError(provider_name, f"Output validation failed: {e}")

                exec_ms = int((time.monotonic() - t0) * 1000)
                self._record_success(provider_name)

                self._log.info(
                    "[pipeline] SUCCESS tool=%s provider=%s cap=%s ms=%d req=%s",
                    tool, provider_name, capability, exec_ms, request_id,
                )

                return {
                    "success":       True,
                    "tool":          tool,
                    "pipeline":      pipeline_name,
                    "capability":    capability,
                    "provider":      provider_name,
                    "output":        output,
                    "execution_ms":  exec_ms,
                    "metadata":      result.get("metadata", {}),
                    "fallback_used": len(attempted) > 1,
                    "warnings":      [],
                    "output_type":   result.get("output_type", "image"),
                }

            except ProviderError as e:
                last_error = e.reason
                self._record_failure(provider_name)
                self._log.warning(
                    "[pipeline] FAIL provider=%s cap=%s reason=%s req=%s",
                    provider_name, capability, e.reason[:200], request_id,
                )
                continue

            except asyncio.TimeoutError:
                last_error = f"Timeout on {provider_name}"
                self._record_failure(provider_name)
                self._log.warning("[pipeline] TIMEOUT provider=%s req=%s", provider_name, request_id)
                continue

            except Exception as e:
                last_error = str(e)
                self._record_failure(provider_name)
                self._log.exception(
                    "[pipeline] EXCEPTION provider=%s cap=%s req=%s: %s",
                    provider_name, capability, request_id, e,
                )
                continue

        # ── All providers exhausted — NO FAKE FALLBACK ────────────────────────
        exec_ms = int((time.monotonic() - t0) * 1000)
        self._log.error(
            "[pipeline] ALL FAILED tool=%s cap=%s attempted=%s last=%s req=%s ms=%d",
            tool, capability, attempted, last_error, request_id, exec_ms,
        )

        return {
            "success":             False,
            "error_code":          "PROVIDER_EXECUTION_FAILED",
            "message":             f"All providers failed for '{capability}'. Last error: {last_error}",
            "tool":                tool,
            "pipeline":            pipeline_name,
            "capability":          capability,
            "providers_tried":     attempted,
            "last_error":          last_error,
            "fallback_attempted":  True,
            "execution_ms":        exec_ms,
        }


# ══════════════════════════════════════════════════════════════════════════════
# §8  PROVIDER ROUTER (stats / admin)
# ══════════════════════════════════════════════════════════════════════════════

class ProviderRouter:
    def __init__(self, engine: PipelineEngine):
        self._engine = engine

    async def provider_stats(self) -> Dict[str, Any]:
        return {
            "providers": {
                name: {
                    "health":       round(self._engine._health.get(name, 1.0), 3),
                    "capabilities": list(getattr(PROVIDER_REGISTRY.get(name), "CAPABILITIES", set())),
                }
                for name in PROVIDER_REGISTRY
            }
        }

    async def reset_provider(self, provider: str) -> None:
        self._engine._health[provider] = 1.0


# ══════════════════════════════════════════════════════════════════════════════
# §9  FACTORY + STARTUP HEALTH REGISTRY
#     FIX-6: Full per-provider credential validation at startup.
#     Disabled providers (health=0) are excluded from all routing.
# ══════════════════════════════════════════════════════════════════════════════

def _validate_cloudflare(settings: Any) -> Tuple[bool, str]:
    """FIX-3: Validate Cloudflare credentials exist and are non-empty."""
    acct  = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", None)
    token = getattr(settings, "CLOUDFLARE_API_TOKEN", None)
    if not acct:
        return False, "CLOUDFLARE_ACCOUNT_ID not set"
    if not token:
        return False, "CLOUDFLARE_API_TOKEN not set"
    if len(token) < 20:
        return False, f"CLOUDFLARE_API_TOKEN suspiciously short ({len(token)} chars) — may be invalid"
    return True, "ok"


def _validate_cloudinary(settings: Any) -> Tuple[bool, str]:
    """FIX-4: Validate all three required Cloudinary credentials."""
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

    FIX-6: Full startup health registry.
    Providers with missing/invalid credentials get health=0.0 and are
    excluded from all routing automatically.
    """
    engine = PipelineEngine(settings, logger)
    router = ProviderRouter(engine)

    # ── Per-provider credential checks ────────────────────────────────────────
    # Returns (is_configured: bool, reason: str)
    credential_checks: Dict[str, Tuple[bool, str]] = {
        "huggingface":  (bool(getattr(settings, "HF_API_KEY", None)),
                         "HF_API_KEY" if not getattr(settings, "HF_API_KEY", None) else "ok"),
        "pollinations":  (True, "free tier — no key required"),
        "segmind":       (bool(getattr(settings, "SEGMIND_API_KEY", None)),
                         "SEGMIND_API_KEY" if not getattr(settings, "SEGMIND_API_KEY", None) else "ok"),
        "together":      (bool(getattr(settings, "TOGETHER_API_KEY", None)),
                         "TOGETHER_API_KEY" if not getattr(settings, "TOGETHER_API_KEY", None) else "ok"),
        "gemini":        (bool(getattr(settings, "GEMINI_API_KEY", None)),
                         "GEMINI_API_KEY" if not getattr(settings, "GEMINI_API_KEY", None) else "ok"),
        "groq":          (bool(getattr(settings, "GROQ_API_KEY", None)),
                         "GROQ_API_KEY" if not getattr(settings, "GROQ_API_KEY", None) else "ok"),
        "mistral":       (bool(getattr(settings, "MISTRAL_API_KEY", None)),
                         "MISTRAL_API_KEY" if not getattr(settings, "MISTRAL_API_KEY", None) else "ok"),
        "openrouter":    (bool(getattr(settings, "OPENROUTER_API_KEY", None)),
                         "OPENROUTER_API_KEY" if not getattr(settings, "OPENROUTER_API_KEY", None) else "ok"),
        "cloudflare":    _validate_cloudflare(settings),
        "deepai":        (bool(getattr(settings, "DEEPAI_API_KEY", None)),
                         "DEEPAI_API_KEY" if not getattr(settings, "DEEPAI_API_KEY", None) else "ok"),
        "cloudinary":    _validate_cloudinary(settings),
        "krea":          (bool(getattr(settings, "KREA_API_KEY", None)),
                         "KREA_API_KEY" if not getattr(settings, "KREA_API_KEY", None) else "ok"),
        "pexels":        (bool(getattr(settings, "PEXELS_API_KEY", None)),
                         "PEXELS_API_KEY" if not getattr(settings, "PEXELS_API_KEY", None) else "ok"),
        "unsplash":      (bool(getattr(settings, "UNSPLASH_ACCESS_KEY", None)),
                         "UNSPLASH_ACCESS_KEY" if not getattr(settings, "UNSPLASH_ACCESS_KEY", None) else "ok"),
    }

    # ── Build startup health registry and log ─────────────────────────────────
    health_registry: Dict[str, Dict[str, Any]] = {}
    configured:      List[str] = []
    unconfigured:    List[str] = []
    warnings:        List[str] = []

    for name, (ok, reason) in credential_checks.items():
        health_registry[name] = {
            "provider":     name,
            "enabled":      ok,
            "auth_valid":   ok,
            "reason":       reason,
            "capabilities": list(getattr(PROVIDER_REGISTRY.get(name), "CAPABILITIES", set())),
        }

        if ok:
            configured.append(name)
        else:
            unconfigured.append(name)
            engine._health[name] = 0.0  # Disable: excluded from all routing

            if reason not in ("ok",):
                warnings.append(f"  ✗ {name}: missing {reason}")

    # ── Log startup summary ───────────────────────────────────────────────────
    logger.info(
        "[pipelines] ══════════════ STARTUP HEALTH REGISTRY ══════════════"
    )
    logger.info(
        "[pipelines] Configured providers (%d/%d): %s",
        len(configured), len(credential_checks), configured,
    )

    if unconfigured:
        logger.warning(
            "[pipelines] Disabled providers (%d): %s",
            len(unconfigured), unconfigured,
        )
        for w in warnings:
            logger.warning("[pipelines] %s", w)

    # Cloudflare-specific extended warning
    cf_ok, cf_reason = credential_checks["cloudflare"]
    if not cf_ok:
        logger.warning(
            "[pipelines] ⚠ Cloudflare AI disabled: %s. "
            "Segmentation/upscaling will fall back to HuggingFace/Segmind.",
            cf_reason,
        )
    else:
        logger.info(
            "[pipelines] ✓ Cloudflare AI enabled. "
            "Note: account must have 'AI' permission scope on the API token."
        )

    # Cloudinary-specific extended warning
    cld_ok, cld_reason = credential_checks["cloudinary"]
    if not cld_ok:
        logger.warning(
            "[pipelines] ⚠ Cloudinary disabled: %s. "
            "Compression/basic transforms will fall back to Cloudflare AI.",
            cld_reason,
        )

    # PIL availability
    if _PIL_AVAILABLE:
        logger.info("[pipelines] ✓ Pillow available — HF/CF mask application enabled")
    else:
        logger.warning(
            "[pipelines] ⚠ Pillow not installed — HF segmentation mask-application path "
            "will be skipped. Install with: pip install Pillow"
        )

    logger.info(
        "[pipelines] ══ Pipeline engine ready | tools=%d pipelines=%d providers=%d ══",
        len(TOOL_PIPELINE_MAP), len(PIPELINE_CAPABILITY), len(configured),
    )

    return engine, router

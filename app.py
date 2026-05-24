"""
Luminorbit v37 — Production AI Orchestration Backend
app.py — Railway entrypoint: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import base64
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

try:
    from PIL import Image as _PILImage, ImageFilter as _PILFilter, ImageStat as _PILStat
    _PIL_AVAILABLE = True
except ImportError:
    _PILFilter = None
    _PILStat = None
    _PIL_AVAILABLE = False

try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except ImportError:
    _np = None
    _NUMPY_AVAILABLE = False


# ── Public exports ────────────────────────────────────────────────────────────

CORS_ALLOWED_ORIGINS: List[str] = [
    "https://luminorbit1.dpdns.org",
    "https://luminorbit-1.pages.dev",
    "https://luminorbit.pages.dev",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]


# ── Settings ──────────────────────────────────────────────────────────────────

class _Settings:
    """Reads all required env vars at startup. Missing = None (not fatal)."""

    def __init__(self):
        self.POLLINATIONS_API_KEY  = os.environ.get("POLLINATIONS_API_KEY")
        self.KREA_API_KEY          = os.environ.get("KREA_API_KEY")
        self.TOGETHER_API_KEY      = os.environ.get("TOGETHER_API_KEY")
        self.HF_API_KEY            = os.environ.get("HF_API_KEY")
        self.DEEPAI_API_KEY        = os.environ.get("DEEPAI_API_KEY")
        self.PIXAZO_API_KEY        = os.environ.get("PIXAZO_API_KEY")
        self.PEXELS_API_KEY        = os.environ.get("PEXELS_API_KEY")
        self.UNSPLASH_ACCESS_KEY   = os.environ.get("UNSPLASH_API_KEY")
        self.OPENROUTER_API_KEY    = os.environ.get("OPENROUTER_API_KEY")
        self.SEGMIND_API_KEY       = os.environ.get("SEGMIND_API_KEY")
        self.CLOUDINARY_UPLOAD_PRESET = os.environ.get("CLOUDINARY_UPLOAD_PRESET")
        self.CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY")
        self.CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
        self.CF_AI_TOKEN           = os.environ.get("CF_AI_TOKEN")
        self.CF_ACCOUNT_ID         = os.environ.get("CF_ACCOUNT_ID")
        self.GROQ_API_KEY          = os.environ.get("GROQ_API_KEY")
        self.GEMINI_API_KEY        = os.environ.get("GEMINI_API_KEY")
        self.MISTRAL_API_KEY       = os.environ.get("MISTRAL_API_KEY")

        # Derive cloud name from Cloudinary API key or preset if not set directly
        self.CLOUDINARY_CLOUD_NAME = self._resolve_cloud_name()

    def _resolve_cloud_name(self) -> Optional[str]:
        # Primary: explicit env var (always add this to Railway)
        direct = os.environ.get("CLOUDINARY_CLOUD_NAME")
        if direct and direct.strip():
            return direct.strip()

        # Fallback 1: upload preset stored as full URL
        preset = self.CLOUDINARY_UPLOAD_PRESET or ""
        if preset.startswith("https://"):
            m = re.search(r"cloudinary\.com/([^/]+)/", preset)
            if m:
                return m.group(1)

        # Fallback 2: some integrations encode cloud name in API key as "<cloudname>-<hex>"
        key = self.CLOUDINARY_API_KEY or ""
        if key and "-" in key:
            candidate = key.split("-")[0]
            # Cloud names are lowercase alphanumeric + hyphens, 3–20 chars
            if re.fullmatch(r"[a-z][a-z0-9\-]{2,19}", candidate):
                return candidate

        return None


_settings = _Settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("luminorbit")


# ═══════════════════════════════════════════════════════════════════════════════
# §1  PIPELINE CAPABILITY MAP
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# §2  CAPABILITY → PROVIDER PRIORITY CHAINS
# ═══════════════════════════════════════════════════════════════════════════════

CAPABILITY_PROVIDERS: Dict[str, List[str]] = {
    "image-gen":         ["pollinations", "together", "segmind", "huggingface", "openrouter"],
    "super-resolution":  ["segmind", "huggingface", "cloudflare"],
    "segmentation":      ["huggingface"],  # ONLY true background-removal models — no generative fallback
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


# ═══════════════════════════════════════════════════════════════════════════════
# §3  TOOL → PIPELINE MAP
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_PIPELINE_MAP: Dict[str, str] = {
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
    "Background Remover":               "segmentation",
    "Background Changer":               "segmentation",
    "Sky Replacer":                     "segmentation",
    "Transparent Background":           "segmentation",
    "Smart Crop":                       "segmentation",
    "Sticker Maker":                    "segmentation",
    "AI Smart Object & Background Remover": "segmentation",
    "SAM 2":                            "segmentation",
    "Grounding DINO":                   "segmentation",
    "Object Remover":                   "inpainting",
    "Object Remover Pro":               "inpainting",
    "Watermark Remover":                "inpainting",
    "Photo Cleaner":                    "inpainting",
    "AI Generative Fill Pro":           "inpainting",
    "Real-ESRGAN":                      "upscale",
    "SUPIR":                            "upscale",
    "SwinIR":                           "upscale",
    "BSRGAN":                           "upscale",
    "Image UpScaler":                   "upscale",
    "AI 4K Image Upscaler":             "upscale",
    "AI Micro Detail Booster":          "upscale",
    "Topaz Video AI 5":                 "upscale",
    "Photo Restorer":                   "restoration",
    "CodeFormer":                       "restoration",
    "RestoreFormer":                    "restoration",
    "GFPGAN":                           "face_processing",
    "Face Retouch":                     "face_processing",
    "Portrait Pro":                     "face_processing",
    "Beauty Shot":                      "face_processing",
    "Beauty Filter":                    "face_processing",
    "Face Editor":                      "face_processing",
    "AI Portrait Depth Enhancer":       "face_processing",
    "LivePortrait":                     "face_processing",
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
    "Auto Caption Generator":           "captioning",
    "Subtitle Manual Editor":           "captioning",
    "Florence-2":                       "captioning",
    "Audio Extractor Tool":             "audio",
    "Beat Sync Drop":                   "audio",
    "Sound Wave Viz":                   "audio",
    "Audio Reactive Viz":               "audio",
    "Audio Sync Editor":                "audio",
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


# ═══════════════════════════════════════════════════════════════════════════════
# §4  HUGGINGFACE MODEL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

HF_API_BASE      = "https://api-inference.huggingface.co/models"
HF_PIPELINE_BASE = "https://api-inference.huggingface.co/pipeline"

HF_MODELS: Dict[str, str] = {
    "segmentation":        "briaai/RMBG-1.4",
    "segmentation_alt1":   "briaai/RMBG-2.0",
    "segmentation_alt2":   "ZhengPeng7/BiRefNet",
    "segmentation_alt3":   "ZhengPeng7/BiRefNet-portrait",
    "super-resolution":    "caidas/swin2SR-classical-sr-x4-64",
    "face-processing":     "microsoft/beit-base-patch16-224-pt22k-ft22k",
    "image-gen":           "black-forest-labs/FLUX.1-schnell",
    "image-gen-sd":        "stabilityai/stable-diffusion-xl-base-1.0",
    "style-transfer":      "lllyasviel/sd-controlnet-canny",
    "inpainting":          "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
    "restoration":         "caidas/swin2SR-compressed-sr-x4-48",
    "captioning":          "Salesforce/blip-image-captioning-large",
    "image-enhancement":   "black-forest-labs/FLUX.1-schnell",
}

# (model_id, prefer_pipeline_url, use_json_payload)
HF_SEGMENTATION_MODELS: List[Tuple[str, bool, bool]] = [
    ("briaai/RMBG-1.4",              False, False),
    ("briaai/RMBG-2.0",              False, False),
    ("ZhengPeng7/BiRefNet",           False, True),
]

# ═══════════════════════════════════════════════════════════════════════════════
# §5  QUALITY INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════

class AIQualityIntelligence:
    """Scores AI output quality. Rejects blank, corrupt, or fake images."""

    MIN_ENTROPY_SCORE:    float = 0.08
    MIN_SIZE_SCORE:       float = 0.20
    MIN_OVERALL_SCORE:    float = 0.30
    TINY_IMAGE_THRESHOLD: int   = 4096

    @dataclass
    class QualityReport:
        accepted:         bool
        overall_score:    float
        entropy_score:    float
        size_score:       float
        dimension_ok:     bool
        is_blank:         bool
        is_corrupted:     bool
        rejection_reason: Optional[str] = None
        metadata:         Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def analyze(
        cls,
        image_bytes: bytes,
        provider: str,
        capability: str,
        log: Optional[logging.Logger] = None,
    ) -> "AIQualityIntelligence.QualityReport":
        _log = log or logging.getLogger(__name__)

        if not image_bytes or len(image_bytes) < cls.TINY_IMAGE_THRESHOLD:
            size_score = len(image_bytes) / cls.TINY_IMAGE_THRESHOLD if image_bytes else 0.0
            return cls.QualityReport(
                accepted=False, overall_score=size_score, entropy_score=0.0,
                size_score=size_score, dimension_ok=False, is_blank=False,
                is_corrupted=True,
                rejection_reason=f"Output too small ({len(image_bytes or b'')} bytes)",
            )

        size_score = min(1.0, math.log(len(image_bytes) / cls.TINY_IMAGE_THRESHOLD + 1) / 5.0)

        if not _PIL_AVAILABLE:
            return cls.QualityReport(
                accepted=True, overall_score=0.6, entropy_score=0.5,
                size_score=size_score, dimension_ok=True, is_blank=False, is_corrupted=False,
            )

        try:
            img = _PILImage.open(io.BytesIO(image_bytes))
            w, h = img.size
            if not (w >= 32 and h >= 32):
                return cls.QualityReport(
                    accepted=False, overall_score=0.1, entropy_score=0.0,
                    size_score=size_score, dimension_ok=False, is_blank=False,
                    is_corrupted=True,
                    rejection_reason=f"Dimensions too small: {w}x{h}",
                )

            try:
                stat = _PILStat.Stat(img.convert("RGB"))
                avg_std = sum(stat.stddev[:3]) / 3.0
                entropy_score = min(1.0, avg_std / 30.0)
                is_blank = avg_std < 2.0
            except Exception:
                entropy_score = 0.5
                is_blank = False

            if capability == "segmentation" and img.mode in ("RGBA", "LA"):
                try:
                    alpha_mean = _PILStat.Stat(img.split()[-1]).mean[0]
                    if alpha_mean < 1.0 or alpha_mean > 254.0:
                        return cls.QualityReport(
                            accepted=False, overall_score=0.15, entropy_score=entropy_score,
                            size_score=size_score, dimension_ok=True,
                            is_blank=True, is_corrupted=False,
                            rejection_reason=f"Uniform alpha ({alpha_mean:.1f}) — segmentation failed",
                        )
                except Exception:
                    pass

            overall_score = entropy_score * 0.5 + size_score * 0.3 + 0.2
            accepted = (
                entropy_score >= cls.MIN_ENTROPY_SCORE
                and size_score  >= cls.MIN_SIZE_SCORE
                and overall_score >= cls.MIN_OVERALL_SCORE
                and not is_blank
            )
            rejection_reason = None
            if not accepted:
                if is_blank:
                    rejection_reason = "Output is blank/solid — AI generation failed"
                elif entropy_score < cls.MIN_ENTROPY_SCORE:
                    rejection_reason = f"Low content variation (entropy={entropy_score:.2f})"
                else:
                    rejection_reason = f"Overall quality too low ({overall_score:.2f})"

            return cls.QualityReport(
                accepted=accepted, overall_score=overall_score, entropy_score=entropy_score,
                size_score=size_score, dimension_ok=True, is_blank=is_blank,
                is_corrupted=False, rejection_reason=rejection_reason,
                metadata={"width": w, "height": h, "mode": img.mode},
            )

        except Exception as e:
            _log.debug("[QualityIntelligence] Analysis failed: %s — defaulting accept", e)
            return cls.QualityReport(
                accepted=True, overall_score=0.5, entropy_score=0.5,
                size_score=size_score, dimension_ok=True, is_blank=False, is_corrupted=False,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# §6  SEGMENTATION REFINER
# ═══════════════════════════════════════════════════════════════════════════════

class SegmentationRefiner:
    """Multi-pass mask refinement. Degrades gracefully without Pillow/NumPy."""

    @staticmethod
    def refine_mask(
        original_bytes: bytes,
        mask_bytes: bytes,
        provider: str,
        log: Optional[logging.Logger] = None,
    ) -> bytes:
        _log = log or logging.getLogger(__name__)

        if not _PIL_AVAILABLE:
            try:
                img  = _PILImage.open(io.BytesIO(original_bytes)).convert("RGBA")
                mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size, _PILImage.LANCZOS)
                img.putalpha(mask)
                out = io.BytesIO()
                img.save(out, format="PNG")
                return out.getvalue()
            except Exception as e:
                raise ProviderError(provider, f"Basic mask application failed: {e}")

        try:
            img  = _PILImage.open(io.BytesIO(original_bytes)).convert("RGBA")
            mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")
            if mask.size != img.size:
                mask = mask.resize(img.size, _PILImage.LANCZOS)

            mask = SegmentationRefiner._adaptive_threshold(mask)
            if _NUMPY_AVAILABLE:
                mask = SegmentationRefiner._morphological_cleanup(mask)
            mask = SegmentationRefiner._fill_holes(mask)
            mask = SegmentationRefiner._feather_edges(mask)

            img.putalpha(mask)
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()

        except ProviderError:
            raise
        except Exception as e:
            _log.debug("[SegRefiner] Refinement failed (%s) — using raw mask", e)
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
                raise ProviderError(provider, f"Mask application failed: {e2}")

    @staticmethod
    def _adaptive_threshold(mask: "_PILImage.Image") -> "_PILImage.Image":
        try:
            data = list(mask.getdata())
            hist = [0] * 256
            for p in data:
                hist[p] += 1
            total = len(data)
            sum_total = sum(i * hist[i] for i in range(256))
            sum_bg = 0; weight_bg = 0
            max_var = 0.0; optimal_t = 128
            for t in range(256):
                weight_bg += hist[t]
                if weight_bg == 0:
                    continue
                weight_fg = total - weight_bg
                if weight_fg == 0:
                    break
                sum_bg += t * hist[t]
                mean_bg = sum_bg / weight_bg
                mean_fg = (sum_total - sum_bg) / weight_fg
                var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
                if var > max_var:
                    max_var = var
                    optimal_t = t
            new_data = []
            for p in data:
                if p < optimal_t * 0.7:
                    new_data.append(0)
                elif p > optimal_t * 1.3 or p > 200:
                    new_data.append(255)
                else:
                    normalized = (p - optimal_t * 0.7) / (optimal_t * 0.6 + 1e-6)
                    new_data.append(min(255, int(normalized * 255)))
            result = _PILImage.new("L", mask.size)
            result.putdata(new_data)
            return result
        except Exception:
            return mask

    @staticmethod
    def _morphological_cleanup(mask: "_PILImage.Image") -> "_PILImage.Image":
        if not _NUMPY_AVAILABLE:
            return mask
        try:
            arr = _np.array(mask, dtype=_np.uint8)
            binary = (arr > 127).astype(_np.uint8)
            kernel_size = max(3, min(arr.shape) // 80)
            result_img = _PILImage.fromarray((binary * 255).astype(_np.uint8), mode="L")
            return result_img.filter(_PILFilter.ModeFilter(size=kernel_size))
        except Exception:
            return mask

    @staticmethod
    def _fill_holes(mask: "_PILImage.Image") -> "_PILImage.Image":
        try:
            smoothed = mask.copy().convert("L").filter(_PILFilter.MedianFilter(size=5))
            data_orig   = list(mask.getdata())
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
        try:
            blurred   = mask.filter(_PILFilter.GaussianBlur(radius=radius))
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
        if not _PIL_AVAILABLE:
            return 0.7
        try:
            mask = _PILImage.open(io.BytesIO(mask_bytes)).convert("L")
            stat = _PILStat.Stat(mask)
            mean = stat.mean[0]
            std  = stat.stddev[0]
            mean_score = 1.0 - abs(mean - 100) / 150.0
            std_score  = min(1.0, std / 60.0) if std < 100 else max(0.0, 1.0 - (std - 100) / 100.0)
            return max(0.0, min(1.0, mean_score * 0.4 + std_score * 0.6))
        except Exception:
            return 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# §7  PROVIDER ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class _ProviderCallRecord:
    timestamp:  float
    latency_ms: int
    success:    bool
    capability: str
    error_code: int = 0


class ProviderAnalytics:
    """Rolling per-provider statistics with circuit breaker."""

    WINDOW_SIZE:       int   = 50
    CIRCUIT_TRIP_RATE: float = 0.70
    CIRCUIT_COOLDOWN:  float = 120.0

    def __init__(self):
        self._records: Dict[str, deque] = {}
        self._tripped: Dict[str, float] = {}

    def record(self, provider: str, latency_ms: int, success: bool, capability: str, error_code: int = 0) -> None:
        if provider not in self._records:
            self._records[provider] = deque(maxlen=self.WINDOW_SIZE)
        self._records[provider].append(_ProviderCallRecord(
            timestamp=time.monotonic(), latency_ms=latency_ms,
            success=success, capability=capability, error_code=error_code,
        ))
        stats = self.stats(provider)
        if stats["call_count"] >= 5 and stats["error_rate"] > self.CIRCUIT_TRIP_RATE:
            self._tripped.setdefault(provider, time.monotonic())

    def is_circuit_open(self, provider: str) -> bool:
        trip_time = self._tripped.get(provider)
        if trip_time is None:
            return False
        if time.monotonic() - trip_time > self.CIRCUIT_COOLDOWN:
            del self._tripped[provider]
            return False
        return True

    def reset_circuit(self, provider: str) -> None:
        self._tripped.pop(provider, None)

    def stats(self, provider: str) -> Dict[str, Any]:
        records = list(self._records.get(provider, []))
        if not records:
            return {"call_count": 0, "error_rate": 0.0, "avg_latency_ms": 0, "p95_latency_ms": 0}
        total     = len(records)
        failures  = sum(1 for r in records if not r.success)
        latencies = sorted(r.latency_ms for r in records)
        p95_idx   = max(0, int(total * 0.95) - 1)
        return {
            "call_count":     total,
            "error_rate":     failures / total,
            "avg_latency_ms": sum(r.latency_ms for r in records) // total,
            "p95_latency_ms": latencies[p95_idx],
            "circuit_open":   self.is_circuit_open(provider),
        }

    def all_stats(self) -> Dict[str, Any]:
        return {p: self.stats(p) for p in self._records}


# ═══════════════════════════════════════════════════════════════════════════════
# §8  EXECUTION PLANNER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionPlan:
    tool:                 str
    capability:           str
    intent:               str
    stages:               List[str]
    quality_gate:         float
    max_refinement_passes: int
    provider_hints:       List[str]
    metadata:             Dict[str, Any] = field(default_factory=dict)


class ExecutionPlanner:
    """Classifies tool intent and builds an optimal execution plan."""

    INTENT_QUALITY_GATES: Dict[str, float] = {
        "background_removal": 0.55,
        "face_enhancement":   0.60,
        "image_restoration":  0.50,
        "super_resolution":   0.45,
        "image_generation":   0.35,
        "style_transfer":     0.30,
        "captioning":         0.20,
        "basic_processing":   0.20,
    }

    INTENT_STAGES: Dict[str, List[str]] = {
        "background_removal": ["validate_input", "preprocess", "segment", "mask_refinement", "quality_check", "deliver"],
        "face_enhancement":   ["validate_input", "face_detect", "enhance", "quality_check", "deliver"],
        "image_restoration":  ["validate_input", "restore", "quality_check", "deliver"],
        "super_resolution":   ["validate_input", "upscale", "quality_check", "deliver"],
        "image_generation":   ["prompt_enhance", "generate", "quality_check", "deliver"],
        "default":            ["validate_input", "process", "quality_check", "deliver"],
    }

    @classmethod
    def plan(cls, tool: str, capability: str, params: Dict[str, Any], log: Optional[logging.Logger] = None) -> ExecutionPlan:
        intent     = cls._classify_intent(capability, tool)
        stages     = cls.INTENT_STAGES.get(intent, cls.INTENT_STAGES["default"])
        gate       = cls.INTENT_QUALITY_GATES.get(intent, 0.30)
        max_passes = 2 if capability in {"segmentation", "face-processing"} else 1
        return ExecutionPlan(
            tool=tool, capability=capability, intent=intent,
            stages=stages, quality_gate=gate,
            max_refinement_passes=max_passes,
            provider_hints=cls._provider_hints(intent),
        )

    @classmethod
    def _classify_intent(cls, capability: str, tool: str) -> str:
        mapping = {
            "segmentation":    "background_removal",
            "face-processing": "face_enhancement",
            "restoration":     "image_restoration",
            "super-resolution": "super_resolution",
            "image-gen":       "image_generation",
            "captioning":      "captioning",
        }
        if capability in mapping:
            return mapping[capability]
        if capability in ("style-transfer", "image-enhancement"):
            return "style_transfer"
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


# ═══════════════════════════════════════════════════════════════════════════════
# §9  SECURITY GATE
# ═══════════════════════════════════════════════════════════════════════════════

class SecurityGate:
    """Sanitizes prompts and validates uploaded files."""

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

    MAX_PROMPT_LENGTH: int = 2000

    @classmethod
    def sanitize_prompt(cls, prompt: Optional[str]) -> Optional[str]:
        if not prompt:
            return prompt
        prompt = prompt[:cls.MAX_PROMPT_LENGTH]
        for pattern in cls._INJECTION_PATTERNS:
            if pattern.search(prompt):
                prompt = pattern.sub("[removed]", prompt)
        prompt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", prompt)
        return prompt.strip()

    @classmethod
    def validate_file_bytes(cls, data: bytes, declared_mime: str, provider: str) -> None:
        if not data:
            raise ProviderError(provider, "Upload is empty (0 bytes)", 400)
        if len(data) > 100 * 1024 * 1024:
            raise ProviderError(provider, f"Upload exceeds 100MB ({len(data)} bytes)", 413)
        if data[:2] == b'MZ' or data[:4] == b'ELF ' or data[:4] == b'%PDF':
            raise ProviderError(provider, "Upload rejected: file appears to be an executable or PDF", 400)
        if data[:256].lower().startswith(b'<!doctype') or b'<html' in data[:512].lower():
            raise ProviderError(provider, "Upload rejected: HTML content detected in file", 400)

    @classmethod
    def sanitize_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, str):
                result[k] = cls.sanitize_prompt(v) or v
            elif isinstance(v, (int, float, bool)):
                result[k] = v
            elif isinstance(v, dict):
                result[k] = cls.sanitize_params(v)
            elif isinstance(v, list):
                result[k] = [(cls.sanitize_prompt(i) if isinstance(i, str) else i) for i in v]
            else:
                result[k] = v
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# §10  EXECUTION CACHE
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionCache:
    """In-process LRU-TTL cache for AI execution results."""

    DEFAULT_TTL: float = 300.0
    MAX_ENTRIES: int   = 256

    def __init__(self, ttl: float = DEFAULT_TTL):
        self._ttl   = ttl
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._order: deque = deque(maxlen=self.MAX_ENTRIES)

    def _evict_expired(self) -> None:
        now     = time.monotonic()
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
        if len(self._store) >= self.MAX_ENTRIES and self._order:
            self._store.pop(self._order[0], None)
        self._store[key] = (time.monotonic(), value)
        self._order.append(key)

    @staticmethod
    def make_key(tool: str, capability: str, params: Dict[str, Any], file_bytes: Optional[bytes]) -> str:
        file_hash = hashlib.md5(file_bytes).hexdigest()[:16] if file_bytes else "nofile"
        param_str = json.dumps(params, sort_keys=True, default=str)[:200]
        return f"{tool}:{capability}:{file_hash}:{hashlib.md5(param_str.encode()).hexdigest()[:8]}"


_provider_analytics = ProviderAnalytics()
_execution_cache    = ExecutionCache()


# ═══════════════════════════════════════════════════════════════════════════════
# §11  PROVIDER BASE + UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

class ProviderError(Exception):
    def __init__(self, provider: str, reason: str, status_code: int = 0):
        super().__init__(f"[{provider}] {reason}")
        self.provider    = provider
        self.reason      = reason
        self.status_code = status_code


def _bytes_to_data_uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _validate_response_image(data: bytes, provider: str) -> None:
    if len(data) == 0:
        raise ProviderError(provider, "Response is 0 bytes")
    if len(data) < 1024:
        decoded = data.decode("utf-8", errors="replace")
        raise ProviderError(provider, f"Response too small ({len(data)}B): {decoded[:200]}")
    if b'<!DOCTYPE' in data[:256] or b'<html' in data[:256].lower():
        raise ProviderError(provider, f"Response is an HTML error page: {data[:200].decode('utf-8', errors='replace')[:150]}")
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return
    if data[:3] == b'\xff\xd8\xff':
        return
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return
    if data[4:8] in (b'ftyp', b'ftypavif', b'ftyphei'):
        return
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return
    if len(data) > 8192:
        return
    raise ProviderError(provider, f"Response is not a valid image (magic={data[:8].hex()}, size={len(data)}B)")


def _apply_hf_mask_to_image(image_bytes: bytes, mask_bytes: bytes, provider: str) -> bytes:
    if not _PIL_AVAILABLE:
        raise ProviderError(provider, "Pillow not available for mask application")
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
        raise ProviderError(provider, f"Mask application failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# §12  CLOUDINARY DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

_CLOUDINARY_AUTH_FAILED_SESSION: bool = False


async def _validate_cloudinary_credentials_live(settings: _Settings, log: logging.Logger) -> None:
    """Background startup task — validates Cloudinary credentials via lightweight API call."""
    global _CLOUDINARY_AUTH_FAILED_SESSION

    cloud  = settings.CLOUDINARY_CLOUD_NAME
    key    = settings.CLOUDINARY_API_KEY
    secret = settings.CLOUDINARY_API_SECRET

    if not (cloud and key and secret):
        return

    try:
        url     = f"https://api.cloudinary.com/v1_1/{cloud}/resources/image?max_results=1"
        timeout = httpx.Timeout(connect=8.0, read=15.0, write=5.0, pool=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, auth=(key, secret))

        if resp.status_code == 200:
            log.info("[startup] ✓ Cloudinary live validation PASSED (cloud=%s)", cloud)
        elif resp.status_code in (401, 403):
            _CLOUDINARY_AUTH_FAILED_SESSION = True
            log.error(
                "[startup] ✗ Cloudinary live validation FAILED (HTTP %d) — credentials invalid.\n"
                "Verify all three variables in Railway belong to the SAME Cloudinary account:\n"
                "  CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET, CLOUDINARY_CLOUD_NAME\n"
                "See: https://console.cloudinary.com/settings/api-keys\n"
                "Cloudinary CDN disabled — inline base64 fallback active.",
                resp.status_code,
            )
        else:
            log.warning("[startup] Cloudinary validation returned HTTP %d — assuming OK", resp.status_code)
    except Exception as e:
        log.warning("[startup] Cloudinary validation network error: %s — assuming OK", e)


async def _upload_or_inline(
    image_bytes: bytes,
    mime: str,
    settings: _Settings,
    log: logging.Logger,
    is_png: bool = False,
) -> Tuple[str, str]:
    """Upload to Cloudinary CDN or fall back to inline base64. Never raises."""
    global _CLOUDINARY_AUTH_FAILED_SESSION

    mime = mime or ("image/png" if is_png else "image/jpeg")

    cloud  = settings.CLOUDINARY_CLOUD_NAME
    key    = settings.CLOUDINARY_API_KEY
    secret = settings.CLOUDINARY_API_SECRET

    if _CLOUDINARY_AUTH_FAILED_SESSION:
        return _bytes_to_data_uri(image_bytes, mime), "inline_base64"

    # Cloud name is the most common missing variable — log clearly and fall back
    if not cloud:
        log.warning(
            "[delivery] CLOUDINARY_CLOUD_NAME missing — cannot upload to CDN. "
            "Add CLOUDINARY_CLOUD_NAME to Railway env vars. "
            "Find it at: https://console.cloudinary.com → top-left account menu → Cloud Name. "
            "Falling back to inline base64 delivery (larger payload to frontend)."
        )
        return _bytes_to_data_uri(image_bytes, mime), "inline_base64"

    if not key or not secret:
        log.warning("[delivery] Cloudinary API credentials missing — inline_base64 fallback")
        return _bytes_to_data_uri(image_bytes, mime), "inline_base64"

    try:
        timestamp      = str(int(time.time()))
        params_to_sign: Dict[str, str] = {"timestamp": timestamp}
        if is_png:
            params_to_sign["format"] = "png"

        _excl    = frozenset({"file", "api_key", "resource_type", "cloud_name"})
        filtered = {k: v for k, v in params_to_sign.items() if k not in _excl}
        sig_str  = "&".join(f"{k}={v}" for k, v in sorted(filtered.items())) + secret
        signature = hashlib.sha1(sig_str.encode("utf-8")).hexdigest()

        upload_data: Dict[str, str] = {"api_key": key, "timestamp": timestamp, "signature": signature}
        if is_png:
            upload_data["format"] = "png"

        ext        = "image.png" if is_png else "image.jpg"
        upload_url = f"https://api.cloudinary.com/v1_1/{cloud}/image/upload"

        log.info("[delivery] Cloudinary upload cloud=%s bytes=%d is_png=%s", cloud, len(image_bytes), is_png)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                upload_url,
                files={"file": (ext, io.BytesIO(image_bytes), mime)},
                data=upload_data,
            )

        if resp.status_code == 200:
            secure_url = resp.json().get("secure_url", "")
            if secure_url:
                log.info("[delivery] Cloudinary OK url=%s", secure_url[:80])
                return secure_url, "cloudinary"
            log.warning("[delivery] Cloudinary 200 but no secure_url in response — inline_base64 fallback")
        elif resp.status_code in (401, 403):
            _CLOUDINARY_AUTH_FAILED_SESSION = True
            try:
                err_detail = resp.json().get("error", {}).get("message", resp.text[:150])
            except Exception:
                err_detail = resp.text[:150]
            log.error(
                "[delivery] Cloudinary auth failure HTTP %d — disabling CDN for this session.\n"
                "Error: %s\n"
                "Verify these THREE variables in Railway are from the SAME Cloudinary account:\n"
                "  CLOUDINARY_CLOUD_NAME  (e.g. 'myapp123')\n"
                "  CLOUDINARY_API_KEY     (numeric, e.g. '123456789012345')\n"
                "  CLOUDINARY_API_SECRET  (long alphanumeric string)\n"
                "All three are on the same page: https://console.cloudinary.com/settings/api-keys",
                resp.status_code, err_detail,
            )
        else:
            log.warning("[delivery] Cloudinary HTTP %d — falling back to inline_base64", resp.status_code)

    except Exception as e:
        log.warning("[delivery] Cloudinary upload exception: %s — inline_base64 fallback", e)

    return _bytes_to_data_uri(image_bytes, mime), "inline_base64"


# ═══════════════════════════════════════════════════════════════════════════════
# §13  PROVIDER ADAPTERS
# ═══════════════════════════════════════════════════════════════════════════════

# ── HuggingFace ───────────────────────────────────────────────────────────────

class HuggingFaceAdapter:
    NAME = "huggingface"
    CAPABILITIES = {
        "segmentation", "super-resolution", "face-processing",
        "restoration", "image-gen", "style-transfer", "inpainting",
        "captioning", "image-enhancement",
    }

    @classmethod
    async def _call_segmentation(
        cls, api_key: str, file_bytes: bytes, file_mime: str, log: logging.Logger,
    ) -> Dict[str, Any]:
        last_err = "no models attempted"

        for (model, prefer_pipeline, use_json) in HF_SEGMENTATION_MODELS:
            url_models   = f"{HF_API_BASE}/{model}"
            url_pipeline = f"{HF_PIPELINE_BASE}/image-segmentation/{model}"
            urls_to_try  = [url_pipeline, url_models] if prefer_pipeline else [url_models, url_pipeline]

            retry_wait_503 = 20 if use_json else 15
            log.info("[HF-SEG] model=%s json=%s bytes=%d", model, use_json, len(file_bytes))

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
                                await asyncio.sleep(retry_wait_503)
                                continue
                            last_err = f"{model} ({url_label}): still loading after 503 retry"
                            break

                        if resp.status_code == 500:
                            if attempt == 0:
                                await asyncio.sleep(8)
                                continue
                            last_err = f"{model} ({url_label}): HTTP 500 after retry"
                            break

                        if resp.status_code == 404:
                            last_err = f"{model} ({url_label}): 404"
                            break

                        if resp.status_code == 401:
                            raise ProviderError(cls.NAME, "HF_API_KEY invalid or expired (401)", 401)

                        if resp.status_code == 429:
                            await asyncio.sleep(10)
                            continue

                        if resp.status_code != 200:
                            last_err = f"{model} ({url_label}): HTTP {resp.status_code}"
                            break

                        content_type = resp.headers.get("content-type", "")
                        raw = resp.content

                        # Binary image response path
                        if (
                            "image" in content_type
                            or raw[:8] == b'\x89PNG\r\n\x1a\n'
                            or raw[:3] == b'\xff\xd8\xff'
                            or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
                        ):
                            _validate_response_image(raw, cls.NAME)
                            return {
                                "success": True, "output": _bytes_to_data_uri(raw, "image/png"),
                                "provider": cls.NAME, "model": model,
                            }

                        # JSON response — extract mask
                        try:
                            data = resp.json()
                        except Exception:
                            last_err = f"{model} ({url_label}): not image or JSON"
                            break

                        mask_bytes: Optional[bytes] = None

                        if isinstance(data, dict):
                            out_list = data.get("output") or []
                            if isinstance(out_list, list) and out_list:
                                entry    = out_list[0] if isinstance(out_list[0], dict) else {}
                                mask_val = entry.get("image") or entry.get("mask") or ""
                            else:
                                mask_val = data.get("image") or data.get("mask") or ""
                            if mask_val and isinstance(mask_val, str):
                                try:
                                    raw_b64    = mask_val.split(",", 1)[1] if "," in mask_val else mask_val
                                    mask_bytes = base64.b64decode(raw_b64)
                                except Exception as e:
                                    last_err = f"{model} ({url_label}): mask decode failed: {e}"
                                    break

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
                            last_err = f"{model} ({url_label}): no mask in JSON"
                            break

                        if _PIL_AVAILABLE and file_bytes:
                            try:
                                transparent = _apply_hf_mask_to_image(file_bytes, mask_bytes, cls.NAME)
                                return {
                                    "success": True, "output": _bytes_to_data_uri(transparent, "image/png"),
                                    "provider": cls.NAME, "model": model,
                                }
                            except ProviderError as mask_err:
                                log.warning("[HF-SEG] Mask application failed: %s", mask_err.reason)

                        _validate_response_image(mask_bytes, cls.NAME)
                        return {
                            "success": True, "output": _bytes_to_data_uri(mask_bytes, "image/png"),
                            "provider": cls.NAME, "model": model,
                        }

                    except ProviderError:
                        raise
                    except asyncio.TimeoutError:
                        last_err = f"{model} ({url_label}): timeout"
                        break
                    except Exception as e:
                        last_err = f"{model} ({url_label}): {e}"
                        break

        raise ProviderError(cls.NAME, f"All HF segmentation models exhausted. Last: {last_err}")

    @classmethod
    async def call(
        cls,
        settings: _Settings,
        capability: str,
        file_bytes: Optional[bytes],
        file_mime: str,
        params: Dict[str, Any],
        log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.HF_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "HF_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=5.0)

        if capability == "segmentation":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image provided for segmentation")
            return await cls._call_segmentation(api_key, file_bytes, file_mime, log)

        if capability == "super-resolution":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for super-resolution")
            model = HF_MODELS.get("super-resolution", "caidas/swin2SR-classical-sr-x4-64")
            headers["Content-Type"] = file_mime or "image/jpeg"
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{HF_API_BASE}/{model}", content=file_bytes, headers=headers)
            if resp.status_code == 503:
                await asyncio.sleep(15)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(f"{HF_API_BASE}/{model}", content=file_bytes, headers=headers)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            _validate_response_image(resp.content, cls.NAME)
            return {"success": True, "output": _bytes_to_data_uri(resp.content, "image/jpeg"), "provider": cls.NAME, "model": model}

        if capability == "image-gen":
            prompt = params.get("prompt", "a beautiful high quality image")
            model  = HF_MODELS.get("image-gen", "black-forest-labs/FLUX.1-schnell")
            headers["Content-Type"] = "application/json"
            payload: Dict[str, Any] = {"inputs": prompt}
            if params.get("width"):
                payload["parameters"] = {"width": params["width"], "height": params.get("height", params["width"])}
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{HF_API_BASE}/{model}", json=payload, headers=headers)
            if resp.status_code == 503:
                raise ProviderError(cls.NAME, f"Model loading ({model})", 503)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            _validate_response_image(resp.content, cls.NAME)
            return {"success": True, "output": _bytes_to_data_uri(resp.content, "image/jpeg"), "provider": cls.NAME, "model": model}

        if capability == "captioning":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for captioning")
            cap_url = f"{HF_API_BASE}/{HF_MODELS.get('captioning', 'Salesforce/blip-image-captioning-large')}"
            headers["Content-Type"] = file_mime or "image/jpeg"
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(cap_url, content=file_bytes, headers=headers)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            data = resp.json()
            caption = ""
            if isinstance(data, list) and data:
                caption = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                caption = data.get("generated_text", "")
            return {"success": True, "output": caption, "provider": cls.NAME, "output_type": "text"}

        if capability in ("style-transfer", "image-enhancement", "inpainting", "face-processing"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")
            prompt  = params.get("prompt", f"Apply {capability} to this image, high quality result")
            gen_url = f"{HF_API_BASE}/{HF_MODELS.get('image-gen', 'black-forest-labs/FLUX.1-schnell')}"
            headers["Content-Type"] = "application/json"
            img_b64 = base64.b64encode(file_bytes).decode()
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(gen_url, json={"inputs": prompt, "image": img_b64}, headers=headers)
            if resp.status_code == 503:
                raise ProviderError(cls.NAME, "Model loading", 503)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "HF_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            _validate_response_image(resp.content, cls.NAME)
            return {"success": True, "output": _bytes_to_data_uri(resp.content, "image/jpeg"), "provider": cls.NAME}

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ── Pollinations ──────────────────────────────────────────────────────────────

class PollinationsAdapter:
    NAME = "pollinations"
    CAPABILITIES = {"image-gen", "style-transfer", "visualization", "video-gen"}
    BASE = "https://image.pollinations.ai/prompt"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        if capability == "segmentation":
            raise ProviderError(cls.NAME, "Pollinations blocked for segmentation — would produce fake output")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        import urllib.parse
        prompt  = params.get("prompt", "a beautiful high quality photorealistic image")
        width   = params.get("width", 1024)
        height  = params.get("height", 1024)
        model   = params.get("model", "flux")
        seed    = params.get("seed", "")
        url     = f"{cls.BASE}/{urllib.parse.quote(prompt)}?width={width}&height={height}&model={model}&nologo=true"
        if seed:
            url += f"&seed={seed}"

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)
        _validate_response_image(resp.content, cls.NAME)
        return {"success": True, "output": _bytes_to_data_uri(resp.content, "image/jpeg"), "provider": cls.NAME}


# ── Segmind ───────────────────────────────────────────────────────────────────

class SegmindAdapter:
    NAME = "segmind"
    CAPABILITIES = {
        "image-gen", "inpainting",
        "image-enhancement", "super-resolution", "controlnet",
    }
    BASE = "https://api.segmind.com/v1"

    MODELS: Dict[str, str] = {
        "image-gen":         "sdxl1.0-txt2img",
        "inpainting":        "sdxl-inpainting",
        "image-enhancement": "esrgan-v1-x2plus",
        "super-resolution":  "esrgan-v1-x2plus",
        "controlnet":        "sd1.5-controlnet-canny",
    }

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.SEGMIND_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "SEGMIND_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        if capability == "image-gen":
            prompt = params.get("prompt", "a high quality image")
            payload = {
                "prompt":              prompt,
                "negative_prompt":     params.get("negative_prompt", "low quality, blurry"),
                "samples":             1,
                "num_inference_steps": params.get("steps", 20),
                "guidance_scale":      params.get("guidance_scale", 7.5),
                "img_width":           params.get("width", 1024),
                "img_height":          params.get("height", 1024),
                "base64":              True,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{cls.BASE}/{cls.MODELS['image-gen']}", json=payload, headers=headers)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            data = resp.json()
            img_b64 = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64}", "provider": cls.NAME}

        if capability in ("super-resolution", "image-enhancement"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")
            img_b64 = base64.b64encode(file_bytes).decode()
            payload = {
                "image":        f"data:{file_mime};base64,{img_b64}",
                "scale":        params.get("scale", 2),
                "face_enhance": params.get("face_enhance", False),
                "base64":       True,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{cls.BASE}/{cls.MODELS[capability]}", json=payload, headers=headers)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            data = resp.json()
            img_b64 = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64}", "provider": cls.NAME}

        if capability == "inpainting":
            if not file_bytes:
                raise ProviderError(cls.NAME, "No image for inpainting")
            img_b64  = base64.b64encode(file_bytes).decode()
            mask_b64 = params.get("mask_b64", img_b64)
            payload = {
                "prompt":              params.get("prompt", "fill seamlessly"),
                "image":               f"data:{file_mime};base64,{img_b64}",
                "mask":                f"data:image/png;base64,{mask_b64}",
                "samples":             1,
                "num_inference_steps": 20,
                "base64":              True,
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{cls.BASE}/{cls.MODELS['inpainting']}", json=payload, headers=headers)
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "SEGMIND_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            data = resp.json()
            img_b64 = data.get("image") or (data.get("images") or [None])[0]
            if not img_b64:
                raise ProviderError(cls.NAME, "No image in response")
            return {"success": True, "output": f"data:image/jpeg;base64,{img_b64}", "provider": cls.NAME}

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ── Together AI ───────────────────────────────────────────────────────────────

class TogetherAdapter:
    NAME = "together"
    CAPABILITIES = {"image-gen", "style-transfer", "captioning", "video-gen"}
    BASE = "https://api.together.xyz/v1"
    IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell-Free"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.TOGETHER_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "TOGETHER_API_KEY not configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        auth_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}

        prompt = params.get("prompt", "a high quality image")
        width  = params.get("width", 1024)
        height = params.get("height", 1024)

        for attempt in range(2):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/images/generations",
                    json={"model": cls.IMAGE_MODEL, "prompt": prompt, "n": 1,
                          "width": width, "height": height, "response_format": "b64_json"},
                    headers=auth_headers,
                )
            if resp.status_code == 429:
                await asyncio.sleep(5)
                continue
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "TOGETHER_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            break

        img_data = (resp.json().get("data") or [{}])[0]
        if img_data.get("b64_json"):
            img_bytes = base64.b64decode(img_data["b64_json"])
            _validate_response_image(img_bytes, cls.NAME)
            return {"success": True, "output": _bytes_to_data_uri(img_bytes, "image/jpeg"), "provider": cls.NAME}
        elif img_data.get("url"):
            return {"success": True, "output": img_data["url"], "provider": cls.NAME}
        raise ProviderError(cls.NAME, "No image in Together response")


# ── Gemini ────────────────────────────────────────────────────────────────────

class GeminiAdapter:
    NAME = "gemini"
    CAPABILITIES = {"captioning"}
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "GEMINI_API_KEY not configured")

        model   = "gemini-1.5-flash"
        prompt  = params.get("prompt", "Describe this image in detail.")
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            parts.insert(0, {"inline_data": {"mime_type": file_mime or "image/jpeg", "data": img_b64}})

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/models/{model}:generateContent?key={api_key}",
                json={"contents": [{"parts": parts}]},
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "GEMINI_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            text = ""
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ── Groq ──────────────────────────────────────────────────────────────────────

class GroqAdapter:
    NAME = "groq"
    CAPABILITIES = {"captioning"}
    BASE = "https://api.groq.com/openai/v1"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "GROQ_API_KEY not configured")

        model   = "llava-v1.5-7b-4096-preview"
        prompt  = params.get("prompt", "Describe this image.")
        content: Any = prompt
        if file_bytes:
            img_b64 = base64.b64encode(file_bytes).decode()
            content = [
                {"type": "image_url", "image_url": {"url": f"data:{file_mime};base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ]

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cls.BASE}/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 256},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "GROQ_API_KEY invalid (401)", 401)
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ── Mistral ───────────────────────────────────────────────────────────────────

class MistralAdapter:
    NAME = "mistral"
    CAPABILITIES = {"captioning"}
    BASE = "https://api.mistral.ai/v1"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.MISTRAL_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "MISTRAL_API_KEY not configured")

        model    = "pixtral-12b-2409"
        prompt   = params.get("prompt", "Describe this image.")
        messages: List[Dict[str, Any]]
        if file_bytes:
            img_b64  = base64.b64encode(file_bytes).decode()
            messages = [{"role": "user", "content": [
                {"type": "image_url", "image_url": f"data:{file_mime};base64,{img_b64}"},
                {"type": "text", "text": prompt},
            ]}]
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
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "output": text, "provider": cls.NAME, "output_type": "text"}


# ── OpenRouter ────────────────────────────────────────────────────────────────

class OpenRouterAdapter:
    NAME = "openrouter"
    CAPABILITIES = {"image-gen", "captioning"}
    BASE = "https://openrouter.ai/api/v1"
    IMAGE_MODEL = "black-forest-labs/FLUX-1-schnell"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "OPENROUTER_API_KEY not configured")

        auth_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
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
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        url_out = (resp.json().get("data") or [{}])[0].get("url", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No image URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME}


# ── Cloudflare AI ─────────────────────────────────────────────────────────────

class CloudflareAdapter:
    NAME = "cloudflare"
    CAPABILITIES = {
        "image-gen", "compression", "basic-processing",
        "audio-extraction", "audio-sync", "color-matching", "temporal",
    }

    CF_MODELS: Dict[str, str] = {
        "image-gen":     "@cf/black-forest-labs/flux-1-schnell",
        "image-gen-sd":  "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "image-gen-xl":  "@cf/bytedance/stable-diffusion-xl-lightning",
    }

    @classmethod
    def _base_url(cls, settings: _Settings, model: str) -> str:
        acct = settings.CF_ACCOUNT_ID or ""
        return f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"

    @classmethod
    def _auth_headers(cls, settings: _Settings) -> Dict[str, str]:
        return {"Authorization": f"Bearer {settings.CF_AI_TOKEN or ''}"}

    @classmethod
    def _handle_auth_error(cls, status_code: int, log: logging.Logger) -> None:
        if status_code == 401:
            log.error(
                "[Cloudflare] 401 Unauthorized — CF_AI_TOKEN is invalid or expired.\n"
                "Fix: https://dash.cloudflare.com/profile/api-tokens\n"
                "Create a token with permission: Account → Workers AI → Edit\n"
                "Set CF_AI_TOKEN in Railway environment variables."
            )
            raise ProviderError(cls.NAME, "CF_AI_TOKEN invalid or expired (401)", 401)
        if status_code == 403:
            log.error(
                "[Cloudflare] 403 Forbidden — CF_AI_TOKEN lacks Workers AI permission.\n"
                "Edit your token and add: Account → Workers AI → Edit"
            )
            raise ProviderError(cls.NAME, "CF_AI_TOKEN missing Workers AI permission (403)", 403)

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        if not settings.CF_ACCOUNT_ID:
            raise ProviderError(cls.NAME, "CF_ACCOUNT_ID not configured", 0)
        if not settings.CF_AI_TOKEN:
            raise ProviderError(cls.NAME, "CF_AI_TOKEN not configured", 0)

        # Runtime format guard (catches copy-paste errors)
        acct_str = str(settings.CF_ACCOUNT_ID).strip()
        if not re.fullmatch(r'[0-9a-f]{32}', acct_str.lower()):
            raise ProviderError(
                cls.NAME,
                f"CF_ACCOUNT_ID invalid format (len={len(acct_str)}). "
                "Must be 32-char lowercase hex from https://dash.cloudflare.com sidebar.",
                0,
            )

        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")

        headers = cls._auth_headers(settings)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0)

        if capability == "image-gen":
            model_url = cls._base_url(settings, cls.CF_MODELS["image-gen"])
            prompt    = params.get("prompt", "a high quality photorealistic image")
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    model_url,
                    json={"prompt": prompt, "num_steps": params.get("steps", 4)},
                    headers={**headers, "Content-Type": "application/json"},
                )
            if resp.status_code in (401, 403):
                cls._handle_auth_error(resp.status_code, log)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

            if "image" in resp.headers.get("content-type", "") or resp.content[:8] == b'\x89PNG\r\n\x1a\n':
                _validate_response_image(resp.content, cls.NAME)
                return {"success": True, "output": _bytes_to_data_uri(resp.content, "image/png"), "provider": cls.NAME}
            try:
                data = resp.json()
                img_b64 = data.get("result", {}).get("image") or data.get("image")
                if img_b64:
                    return {"success": True, "output": f"data:image/png;base64,{img_b64}", "provider": cls.NAME}
            except Exception:
                pass
            raise ProviderError(cls.NAME, "Could not extract image from CF response")

        raise ProviderError(cls.NAME, f"Capability '{capability}' not fully implemented")


# ── DeepAI ────────────────────────────────────────────────────────────────────

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
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key  = settings.DEEPAI_API_KEY
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
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, data={"text": params.get("prompt", "a high quality image")}, headers=headers)

        if resp.status_code == 401:
            raise ProviderError(cls.NAME, "DEEPAI_API_KEY invalid or expired (401)", 401)
        if resp.status_code == 402:
            raise ProviderError(cls.NAME, "DeepAI quota exceeded (402)", 402)
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        out_url = resp.json().get("output_url", "")
        if not out_url:
            raise ProviderError(cls.NAME, "No output_url in response")
        return {"success": True, "output": out_url, "provider": cls.NAME}


# ── Cloudinary ────────────────────────────────────────────────────────────────

class CloudinaryAdapter:
    NAME = "cloudinary"
    CAPABILITIES = {"compression", "basic-processing", "image-enhancement"}
    BASE = "https://api.cloudinary.com/v1_1"
    _SIG_EXCLUDE = frozenset({"file", "api_key", "resource_type", "cloud_name"})

    @classmethod
    def _compute_signature(cls, params_to_sign: Dict[str, str], api_secret: str) -> str:
        filtered = {k: v for k, v in params_to_sign.items() if k not in cls._SIG_EXCLUDE}
        sig_str  = "&".join(f"{k}={v}" for k, v in sorted(filtered.items())) + api_secret
        return hashlib.sha1(sig_str.encode("utf-8")).hexdigest()

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        global _CLOUDINARY_AUTH_FAILED_SESSION

        cloud  = settings.CLOUDINARY_CLOUD_NAME
        key    = settings.CLOUDINARY_API_KEY
        secret = settings.CLOUDINARY_API_SECRET

        if not (cloud and key and secret):
            raise ProviderError(cls.NAME, "Cloudinary credentials not fully configured")
        if capability not in cls.CAPABILITIES:
            raise ProviderError(cls.NAME, f"Capability '{capability}' not supported")
        if _CLOUDINARY_AUTH_FAILED_SESSION:
            raise ProviderError(cls.NAME, "Cloudinary credentials invalid (cached auth failure)")
        if not file_bytes:
            raise ProviderError(cls.NAME, "No image provided")

        timestamp     = str(int(time.time()))
        signature     = cls._compute_signature({"timestamp": timestamp}, secret)
        upload_url    = f"{cls.BASE}/{cloud}/image/upload"
        upload_data   = {"api_key": key, "timestamp": timestamp, "signature": signature}
        ext           = "image.png" if (file_mime or "").endswith("png") else "image.jpg"
        transform     = params.get("transform", "")

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
                "All three credentials must be from the same account.",
                resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)

        secure_url = resp.json().get("secure_url", "")
        if not secure_url:
            raise ProviderError(cls.NAME, "No secure_url in Cloudinary response")
        if transform:
            secure_url = secure_url.replace("/upload/", f"/upload/{transform}/", 1)

        return {"success": True, "output": secure_url, "provider": cls.NAME}


# ── Krea ──────────────────────────────────────────────────────────────────────

class KreaAdapter:
    NAME = "krea"
    CAPABILITIES = {"image-gen", "super-resolution", "face-processing", "restoration"}
    BASE = "https://api.krea.ai/v1"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.KREA_API_KEY
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
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            url_out = (resp.json().get("images") or [{}])[0].get("url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No image URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        if capability in ("super-resolution", "face-processing", "restoration"):
            if not file_bytes:
                raise ProviderError(cls.NAME, f"No image for {capability}")
            img_b64 = base64.b64encode(file_bytes).decode()
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{cls.BASE}/images/enhance",
                    json={"image": f"data:{file_mime};base64,{img_b64}", "enhancement_type": capability},
                    headers=headers,
                )
            if resp.status_code == 401:
                raise ProviderError(cls.NAME, "KREA_API_KEY invalid (401)", 401)
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
            url_out = resp.json().get("url") or resp.json().get("output_url", "")
            if not url_out:
                raise ProviderError(cls.NAME, "No output URL in Krea response")
            return {"success": True, "output": url_out, "provider": cls.NAME}

        raise ProviderError(cls.NAME, f"Unhandled capability: {capability}")


# ── Pexels ────────────────────────────────────────────────────────────────────

class PexelsAdapter:
    NAME = "pexels"
    CAPABILITIES = {"video-gen", "image-gen"}
    BASE = "https://api.pexels.com/v1"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        api_key = settings.PEXELS_API_KEY
        if not api_key:
            raise ProviderError(cls.NAME, "PEXELS_API_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature landscape"))
        headers = {"Authorization": api_key}
        timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)

        if capability == "video-gen":
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    f"https://api.pexels.com/videos/search?query={query}&per_page=1&orientation=landscape",
                    headers=headers,
                )
            if resp.status_code != 200:
                raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)
            videos = resp.json().get("videos", [])
            if not videos:
                raise ProviderError(cls.NAME, f"No videos for query: {query}")
            hd_file = next((f for f in videos[0].get("video_files", []) if f.get("quality") in ("hd", "sd")), None)
            if not hd_file:
                raise ProviderError(cls.NAME, "No downloadable video file found")
            return {"success": True, "output": hd_file["link"], "provider": cls.NAME, "metadata": {"source": "pexels", "query": query}}

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{cls.BASE}/search?query={query}&per_page=1", headers=headers)
        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)
        photos = resp.json().get("photos", [])
        if not photos:
            raise ProviderError(cls.NAME, f"No photos for query: {query}")
        url_out = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No photo URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME, "metadata": {"source": "pexels", "query": query}}


# ── Unsplash ──────────────────────────────────────────────────────────────────

class UnsplashAdapter:
    NAME = "unsplash"
    CAPABILITIES = {"image-gen"}
    BASE = "https://api.unsplash.com"

    @classmethod
    async def call(
        cls, settings: _Settings, capability: str, file_bytes: Optional[bytes],
        file_mime: str, params: Dict[str, Any], log: logging.Logger,
    ) -> Dict[str, Any]:
        access_key = settings.UNSPLASH_ACCESS_KEY
        if not access_key:
            raise ProviderError(cls.NAME, "UNSPLASH_API_KEY not configured")

        query   = params.get("prompt", params.get("query", "nature"))
        timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{cls.BASE}/search/photos?query={query}&per_page=1&orientation=landscape",
                headers={"Authorization": f"Client-ID {access_key}"},
            )

        if resp.status_code != 200:
            raise ProviderError(cls.NAME, f"HTTP {resp.status_code}", resp.status_code)
        results = resp.json().get("results", [])
        if not results:
            raise ProviderError(cls.NAME, f"No photos for query: {query}")
        url_out = results[0].get("urls", {}).get("full") or results[0].get("urls", {}).get("regular", "")
        if not url_out:
            raise ProviderError(cls.NAME, "No photo URL in response")
        return {"success": True, "output": url_out, "provider": cls.NAME, "metadata": {"source": "unsplash", "query": query}}


# ═══════════════════════════════════════════════════════════════════════════════
# §14  PROVIDER REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# §15  PIPELINE EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class PipelineEngine:
    """
    Executes AI tool requests through the provider chain.
    All errors are caught — never raises to the caller.
    """

    def __init__(self, settings: _Settings, log: logging.Logger):
        self._settings = settings
        self._log      = log
        self._health:  Dict[str, float] = {p: 1.0 for p in PROVIDER_REGISTRY}

    def _record_success(self, provider: str) -> None:
        s = self._health.get(provider, 1.0)
        self._health[provider] = min(1.0, s * 1.05 + 0.05)

    def _record_failure(self, provider: str, status_code: int = 0) -> None:
        if provider == "cloudflare" and status_code in (401, 403):
            self._log.warning("[pipeline] Cloudflare auth error (%d) — disabled for session", status_code)
            self._health["cloudflare"] = 0.0
            return
        if provider == "segmind" and status_code in (401, 402, 403):
            self._log.warning("[pipeline] Segmind auth/quota error (%d) — disabled for session", status_code)
            self._health["segmind"] = 0.0
            return
        if provider == "cloudinary" and status_code in (401, 403):
            self._log.warning("[pipeline] Cloudinary auth error (%d) — disabled for session", status_code)
            self._health["cloudinary"] = 0.0
            return
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
        try:
            return await self._run_inner(tool, capability, params, file_bytes, file_mime, resolution, user_id, request_id)
        except Exception as e:
            self._log.exception("[pipeline] UNHANDLED EXCEPTION tool=%s cap=%s req=%s", tool, capability, request_id)
            return {
                "success": False, "error_code": "INTERNAL_ENGINE_ERROR",
                "message": f"Internal error: {type(e).__name__}: {str(e)[:200]}",
                "tool": tool, "capability": capability, "request_id": request_id,
                "providers_attempted": [], "execution_ms": 0,
                "fallback_used": False, "warnings": [],
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

        self._log.info("[pipeline] START tool=%s cap=%s req=%s", tool, capability, request_id)

        # Resolve pipeline → capability
        pipeline_name = TOOL_PIPELINE_MAP.get(tool, "basic")
        resolved_cap  = PIPELINE_CAPABILITY.get(pipeline_name, capability)
        if resolved_cap != capability:
            self._log.info("[pipeline] Capability: %s → %s (tool=%s)", capability, resolved_cap, tool)
        capability = resolved_cap

        # MIME guard for image-requiring capabilities
        IMAGE_CAPABILITIES = {
            "segmentation", "super-resolution", "inpainting",
            "face-processing", "restoration", "image-enhancement",
        }
        if capability in IMAGE_CAPABILITIES and file_bytes:
            low_mime = (file_mime or "").lower()
            if low_mime and not any(low_mime.startswith(pfx) for pfx in ("image/", "application/octet")):
                return {
                    "success": False, "error_code": "INVALID_MIME_TYPE",
                    "error_user_message": "Please upload a valid image file (JPEG, PNG, or WebP).",
                    "message": f"'{capability}' requires an image; received MIME '{file_mime}'",
                    "tool": tool, "pipeline": pipeline_name, "capability": capability,
                    "providers_attempted": [], "execution_ms": int((time.monotonic() - t0) * 1000),
                    "fallback_used": False, "warnings": [],
                }

        # Security gate
        try:
            params = SecurityGate.sanitize_params(params)
            if file_bytes:
                SecurityGate.validate_file_bytes(file_bytes, file_mime, "upload_gate")
        except ProviderError as sec_err:
            return {
                "success": False, "error_code": "SECURITY_REJECTED",
                "error_user_message": sec_err.reason, "message": str(sec_err),
                "tool": tool, "pipeline": pipeline_name, "capability": capability,
                "providers_attempted": [], "execution_ms": int((time.monotonic() - t0) * 1000),
                "fallback_used": False, "warnings": [],
            }

        # Build execution plan
        exec_plan = ExecutionPlanner.plan(tool, capability, params, self._log)

        # Cache lookup (skip generative tasks)
        cache_key = _execution_cache.make_key(tool, capability, params, file_bytes)
        if capability not in {"image-gen"}:
            cached = _execution_cache.get(cache_key)
            if cached is not None:
                self._log.info("[pipeline] CACHE HIT tool=%s req=%s", tool, request_id)
                cached["request_id"] = request_id
                cached["from_cache"] = True
                return cached

        # Provider selection with circuit-breaker
        providers = self._sorted_providers(capability)
        if not providers:
            # Segmentation-specific: never fake with generative providers
            if capability == "segmentation":
                return {
                    "success":            False,
                    "error_code":         "SEGMENTATION_UNAVAILABLE",
                    "error_user_message": "Background removal is currently unavailable. HF_API_KEY is required.",
                    "message":            "No segmentation providers configured. Set HF_API_KEY in Railway environment variables.",
                    "tool":               tool,
                    "pipeline":           pipeline_name,
                    "capability":         capability,
                    "provider":           None,
                    "output":             None,
                    "output_url":         None,
                    "preview_url":        None,
                    "fallback_used":      False,
                    "fallback_attempted": False,
                    "providers_attempted": [],
                    "execution_ms":       int((time.monotonic() - t0) * 1000),
                    "warnings":           [],
                }
            return {
                "success": False, "error_code": "NO_PROVIDERS",
                "error_user_message": "This tool is temporarily unavailable. Please try again shortly.",
                "message": f"No configured providers for capability '{capability}'",
                "tool": tool, "pipeline": pipeline_name, "capability": capability,
                "provider": None, "output": None, "output_url": None, "preview_url": None,
                "providers_attempted": [], "execution_ms": int((time.monotonic() - t0) * 1000),
                "fallback_used": False, "fallback_attempted": False, "warnings": [],
            }

        providers = [p for p in providers if not _provider_analytics.is_circuit_open(p)]
        if not providers:
            all_p = self._sorted_providers(capability)
            if all_p:
                _provider_analytics.reset_circuit(all_p[-1])
                providers = [all_p[-1]]
                self._log.warning("[pipeline] All circuits open — force-resetting %s", providers)

        self._log.info("[pipeline] chain=%s cap=%s req=%s", providers, capability, request_id)

        last_error  = "unknown"
        last_status = 0
        attempted:  List[str] = []
        refinement_pass = 0

        for provider_name in providers:
            adapter = PROVIDER_REGISTRY.get(provider_name)
            if not adapter:
                continue
            if capability not in getattr(adapter, "CAPABILITIES", set()):
                continue

            attempted.append(provider_name)

            try:
                result = await adapter.call(
                    settings=self._settings,
                    capability=capability,
                    file_bytes=file_bytes,
                    file_mime=file_mime,
                    params=params,
                    log=self._log,
                )

                output = result.get("output") if isinstance(result, dict) else None
                if not output:
                    raise ProviderError(provider_name, "Empty output from provider")

                # Validate image outputs
                if isinstance(output, str) and output.startswith("data:image"):
                    try:
                        img_bytes = base64.b64decode(output.split(",", 1)[1])
                        _validate_response_image(img_bytes, provider_name)
                    except ProviderError:
                        raise
                    except Exception as e:
                        raise ProviderError(provider_name, f"Output validation failed: {e}")

                exec_ms = int((time.monotonic() - t0) * 1000)
                self._record_success(provider_name)

                # Quality gate
                quality_report = None
                if isinstance(output, str) and output.startswith("data:image"):
                    try:
                        img_bytes_qa = base64.b64decode(output.split(",", 1)[1])
                        quality_report = AIQualityIntelligence.analyze(img_bytes_qa, provider_name, capability, self._log)
                        if not quality_report.accepted and refinement_pass < exec_plan.max_refinement_passes:
                            refinement_pass += 1
                            self._log.warning(
                                "[pipeline] Quality gate FAILED provider=%s score=%.2f reason=%s — retry pass %d",
                                provider_name, quality_report.overall_score,
                                quality_report.rejection_reason, refinement_pass,
                            )
                            _provider_analytics.record(provider_name, exec_ms, False, capability, 0)
                            self._record_failure(provider_name, 0)
                            last_error = f"Quality gate failed: {quality_report.rejection_reason}"
                            continue
                    except Exception as qa_err:
                        self._log.debug("[pipeline] Quality analysis error: %s", qa_err)

                # Segmentation mask refinement
                if (capability == "segmentation"
                    and isinstance(output, str)
                    and output.startswith("data:image/png")
                    and file_bytes
                    and _PIL_AVAILABLE
                ):
                    try:
                        raw_seg = base64.b64decode(output.split(",", 1)[1])
                        if SegmentationRefiner.score_mask(raw_seg) < 0.4:
                            refined = SegmentationRefiner.refine_mask(file_bytes, raw_seg, provider_name, self._log)
                            output  = f"data:image/png;base64,{base64.b64encode(refined).decode()}"
                    except Exception as ref_err:
                        self._log.debug("[pipeline] Segmentation refinement skipped: %s", ref_err)

                _provider_analytics.record(provider_name, exec_ms, True, capability, 0)

                output_type = result.get("output_type", "text" if capability == "captioning" else "image")
                self._log.info("[pipeline] SUCCESS provider=%s cap=%s ms=%d req=%s", provider_name, capability, exec_ms, request_id)

                # Delivery normalization
                raw_output  = output
                delivery    = "provider_direct"
                preview_url = ""

                if isinstance(output, str) and output.startswith("data:image"):
                    is_png  = "image/png" in output[:30]
                    img_raw = base64.b64decode(output.split(",", 1)[1])
                    cdn_out, delivery = await _upload_or_inline(
                        img_raw,
                        "image/png" if is_png else "image/jpeg",
                        self._settings, self._log, is_png=is_png,
                    )
                    if delivery == "cloudinary":
                        # CDN URL — use as primary output_url; keep base64 as output for direct embed
                        preview_url = cdn_out
                        raw_output  = cdn_out          # frontend should use output_url = preview_url
                    else:
                        # inline_base64 — output IS the data URI
                        raw_output  = cdn_out
                        preview_url = ""

                elif isinstance(output, str) and output.startswith("http"):
                    preview_url = output
                    raw_output  = output
                    delivery    = "provider_url"

                # output_url: always the most useful URL for the frontend to render
                # if CDN: cloudinary URL; if inline: data URI; if provider URL: that URL
                effective_output_url = preview_url if preview_url else raw_output

                success_result = {
                    "success":            True,
                    "tool":               tool,
                    "pipeline":           pipeline_name,
                    "capability":         capability,
                    "provider":           provider_name,
                    "output":             raw_output,
                    "output_url":         effective_output_url,
                    "preview_url":        preview_url or effective_output_url,
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
                if capability not in {"image-gen"}:
                    _execution_cache.set(cache_key, {**success_result})
                return success_result

            except ProviderError as e:
                last_error  = e.reason
                last_status = e.status_code
                self._record_failure(provider_name, e.status_code)
                _provider_analytics.record(provider_name, int((time.monotonic() - t0) * 1000), False, capability, e.status_code)
                self._log.warning("[pipeline] FAIL provider=%s status=%d reason=%s req=%s", provider_name, e.status_code, e.reason[:200], request_id)
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
                self._log.exception("[pipeline] EXCEPTION provider=%s req=%s", provider_name, request_id)
                continue

        exec_ms = int((time.monotonic() - t0) * 1000)
        self._log.error(
            "[pipeline] ALL_FAILED tool=%s cap=%s attempted=%s last_err=%s last_status=%d req=%s ms=%d",
            tool, capability, attempted, last_error, last_status, request_id, exec_ms,
        )

        return {
            "success":             False,
            "error_code":          "PROVIDER_EXECUTION_FAILED",
            "error_user_message":  "AI processing failed. Please try again.",
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


# ═══════════════════════════════════════════════════════════════════════════════
# §16  PROVIDER ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

class ProviderRouter:
    def __init__(self, engine: PipelineEngine):
        self._engine = engine

    async def provider_stats(self) -> Dict[str, Any]:
        analytics = _provider_analytics.all_stats()
        return {
            "providers": {
                name: {
                    "health":       round(self._engine._health.get(name, 1.0), 3),
                    "enabled":      self._engine._health.get(name, 1.0) > 0.0,
                    "capabilities": list(getattr(PROVIDER_REGISTRY.get(name), "CAPABILITIES", set())),
                    "analytics":    analytics.get(name, {}),
                    "circuit_open": _provider_analytics.is_circuit_open(name),
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


# ═══════════════════════════════════════════════════════════════════════════════
# §17  STARTUP + FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_cf_credentials(settings: _Settings) -> Tuple[bool, str]:
    acct  = settings.CF_ACCOUNT_ID
    token = settings.CF_AI_TOKEN

    if not acct:
        return False, "CF_ACCOUNT_ID not set"
    if not token:
        return False, "CF_AI_TOKEN not set"
    if not re.fullmatch(r'[0-9a-f]{32}', str(acct).lower()):
        return False, (
            f"CF_ACCOUNT_ID invalid (got '{str(acct)[:20]}...' len={len(str(acct))}). "
            "Must be 32-char lowercase hex. Find at: https://dash.cloudflare.com → sidebar → Account ID."
        )
    if len(token) < 20:
        return False, f"CF_AI_TOKEN suspiciously short ({len(token)} chars)"
    if str(token).startswith("v1.0-"):
        return False, (
            "CF_AI_TOKEN starts with 'v1.0-' — this is a User API Token, not a Workers AI token. "
            "Create a new token at https://dash.cloudflare.com/profile/api-tokens "
            "with permission: Account → Workers AI → Edit"
        )
    return True, "ok"


def _validate_cloudinary_credentials(settings: _Settings) -> Tuple[bool, str]:
    if not settings.CLOUDINARY_API_KEY:
        return False, "CLOUDINARY_API_KEY not set"
    if not settings.CLOUDINARY_API_SECRET:
        return False, "CLOUDINARY_API_SECRET not set"
    if not settings.CLOUDINARY_CLOUD_NAME:
        return False, (
            "CLOUDINARY_CLOUD_NAME missing and could not be inferred. "
            "Add CLOUDINARY_CLOUD_NAME to Railway env vars. "
            "Find it at: https://console.cloudinary.com → top-left account selector → Cloud Name."
        )
    return True, f"cloud={settings.CLOUDINARY_CLOUD_NAME}"


def build_pipeline_engine(
    settings: _Settings,
    log: logging.Logger,
) -> Tuple[PipelineEngine, ProviderRouter]:
    """
    Called at app startup. Returns (PipelineEngine, ProviderRouter).
    Never crashes — returns a degraded engine on exception.
    """
    try:
        return _build_pipeline_engine_inner(settings, log)
    except Exception as exc:
        log.exception("[pipelines] Startup exception — returning degraded engine: %s", exc)
        engine = PipelineEngine(settings, log)
        for name in PROVIDER_REGISTRY:
            engine._health[name] = 0.0
        return engine, ProviderRouter(engine)


def _build_pipeline_engine_inner(
    settings: _Settings,
    log: logging.Logger,
) -> Tuple[PipelineEngine, ProviderRouter]:
    engine = PipelineEngine(settings, log)
    router = ProviderRouter(engine)

    credential_checks: Dict[str, Tuple[bool, str]] = {
        "huggingface":  (bool(settings.HF_API_KEY), "HF_API_KEY missing" if not settings.HF_API_KEY else "ok"),
        "pollinations": (True, "free — no key required"),
        "segmind":      (bool(settings.SEGMIND_API_KEY), "SEGMIND_API_KEY missing" if not settings.SEGMIND_API_KEY else "ok"),
        "together":     (bool(settings.TOGETHER_API_KEY), "TOGETHER_API_KEY missing" if not settings.TOGETHER_API_KEY else "ok"),
        "gemini":       (bool(settings.GEMINI_API_KEY), "GEMINI_API_KEY missing" if not settings.GEMINI_API_KEY else "ok"),
        "groq":         (bool(settings.GROQ_API_KEY), "GROQ_API_KEY missing" if not settings.GROQ_API_KEY else "ok"),
        "mistral":      (bool(settings.MISTRAL_API_KEY), "MISTRAL_API_KEY missing" if not settings.MISTRAL_API_KEY else "ok"),
        "openrouter":   (bool(settings.OPENROUTER_API_KEY), "OPENROUTER_API_KEY missing" if not settings.OPENROUTER_API_KEY else "ok"),
        "cloudflare":   _validate_cf_credentials(settings),
        "deepai":       (bool(settings.DEEPAI_API_KEY), "DEEPAI_API_KEY missing" if not settings.DEEPAI_API_KEY else "ok"),
        "cloudinary":   _validate_cloudinary_credentials(settings),
        "krea":         (bool(settings.KREA_API_KEY), "KREA_API_KEY missing" if not settings.KREA_API_KEY else "ok"),
        "pexels":       (bool(settings.PEXELS_API_KEY), "PEXELS_API_KEY missing" if not settings.PEXELS_API_KEY else "ok"),
        "unsplash":     (bool(settings.UNSPLASH_ACCESS_KEY), "UNSPLASH_API_KEY missing" if not settings.UNSPLASH_ACCESS_KEY else "ok"),
    }

    configured:   List[str] = []
    unconfigured: List[str] = []

    for name, (ok, reason) in credential_checks.items():
        if ok:
            configured.append(name)
        else:
            unconfigured.append(name)
            engine._health[name] = 0.0

    log.info("[pipelines] ══ Luminorbit v37 Startup ══")
    log.info("[pipelines] Configured providers (%d/%d): %s", len(configured), len(credential_checks), configured)

    if unconfigured:
        log.warning("[pipelines] Disabled providers (%d): %s", len(unconfigured), unconfigured)
        for name in unconfigured:
            log.warning("[pipelines]   ✗ %s: %s", name, credential_checks[name][1])

    seg_chain  = CAPABILITY_PROVIDERS["segmentation"]
    seg_active = [p for p in seg_chain if engine._health.get(p, 1.0) > 0.0]
    if not seg_active:
        log.error("[pipelines] ⚠ All segmentation providers disabled — set HF_API_KEY to enable")
    else:
        log.info("[pipelines] Segmentation chain: active=%s", seg_active)

    cf_ok, cf_reason = credential_checks["cloudflare"]
    if not cf_ok:
        log.warning("[pipelines] Cloudflare disabled: %s", cf_reason)
    else:
        acct_preview = str(settings.CF_ACCOUNT_ID or "")[:8]
        log.info("[pipelines] ✓ Cloudflare: account=%s... — Workers AI enabled", acct_preview)

    cld_ok, cld_reason = credential_checks["cloudinary"]
    if not cld_ok:
        log.warning("[pipelines] Cloudinary disabled: %s — inline base64 delivery active", cld_reason)
    else:
        log.info("[pipelines] ✓ Cloudinary: cloud=%s — CDN delivery enabled", _settings.CLOUDINARY_CLOUD_NAME)
        # Launch live credential validation as non-blocking background task
        try:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_validate_cloudinary_credentials_live(settings, log))
            except RuntimeError:
                pass  # No running loop at module-load time — validation skipped safely
        except Exception as loop_err:
            log.warning("[pipelines] Cloudinary live validation scheduling failed: %s", loop_err)

    if _PIL_AVAILABLE:
        log.info("[pipelines] ✓ Pillow available — mask application enabled")
    else:
        log.warning("[pipelines] ⚠ Pillow not installed — HF mask application disabled. pip install Pillow")

    log.info(
        "[pipelines] ══ Ready | tools=%d pipelines=%d providers=%d ══",
        len(TOOL_PIPELINE_MAP), len(PIPELINE_CAPABILITY), len(configured),
    )

    return engine, router


# ═══════════════════════════════════════════════════════════════════════════════
# §18  FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Luminorbit v37", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pipeline, _router = build_pipeline_engine(_settings, logger)


def _error_response(
    error_code: str,
    message: str,
    provider: str = "",
    details: str = "",
    fallback_attempted: bool = False,
    status: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "success":            False,
            "error_code":         error_code,
            "message":            message,
            "provider":           provider,
            "details":            details,
            "fallback_attempted": fallback_attempted,
        },
    )


# Root endpoint
@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({
        "status": "Luminorbit backend running",
        "version": "v37"
    })


@app.get("/health")
async def health() -> JSONResponse:
    stats = await _router.provider_stats()
    return JSONResponse({
        "status":   "ok",
        "version":  "v37",
        "providers": stats,
    })


@app.post("/api/process")
async def process(request: Request) -> JSONResponse:

    body = await request.json()

    tool       = body.get("tool", "")
    capability = body.get("capability", "basic-processing")
    params     = body.get("params", {})
    file_b64   = body.get("file", "")
    file_mime  = body.get("mime", "image/jpeg")
    resolution = body.get("resolution", "1024x1024")
    user_id    = body.get("user_id", "anonymous")
    request_id = body.get("request_id", str(uuid.uuid4()))

    if not tool:
        return _error_response(
            "MISSING_TOOL",
            "Required field 'tool' is missing",
            status=400
        )

    file_bytes: Optional[bytes] = None

    if file_b64:
        try:
            raw_b64 = file_b64.split(",", 1)[1] if "," in file_b64 else file_b64
            file_bytes = base64.b64decode(raw_b64)

        except Exception:
            return _error_response(
                "INVALID_FILE",
                "File field is not valid base64",
                status=400
            )

    result = await _pipeline.run(
        tool=tool,
        capability=capability,
        params=params,
        file_bytes=file_bytes,
        file_mime=file_mime,
        resolution=resolution,
        user_id=user_id,
        request_id=request_id,
    )

    return JSONResponse(content=result)

    # Defensive normalization — guarantee frontend never receives missing keys
    result.setdefault("success",             False)
    result.setdefault("output",              None)
    result.setdefault("output_url",          result.get("output") or None)
    result.setdefault("preview_url",         result.get("output_url") or None)
    result.setdefault("provider",            None)
    result.setdefault("error_code",          None)
    result.setdefault("message",             None)
    result.setdefault("error_user_message",  None)
    result.setdefault("delivery",            None)
    result.setdefault("output_type",         None)
    result.setdefault("execution_ms",        0)
    result.setdefault("fallback_used",       False)
    result.setdefault("fallback_attempted",  False)
    result.setdefault("providers_attempted", [])
    result.setdefault("warnings",            [])
    result.setdefault("request_id",          request_id)

    return JSONResponse(result)


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    tool: str        = Form(""),
    capability: str  = Form("segmentation"),
) -> JSONResponse:
    try:
        file_bytes = await file.read()
        file_mime  = file.content_type or "image/jpeg"
        request_id = str(uuid.uuid4())

        result = await _pipeline.run(
            tool=tool or capability, capability=capability, params={},
            file_bytes=file_bytes, file_mime=file_mime,
            resolution="", user_id="upload", request_id=request_id,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("[upload] Unhandled exception")
        return _error_response("UPLOAD_FAILED", f"Upload processing failed: {type(e).__name__}: {str(e)[:200]}")


@app.get("/api/tools")
async def list_tools() -> JSONResponse:
    return JSONResponse({
        "tools":      list(TOOL_PIPELINE_MAP.keys()),
        "pipelines":  list(PIPELINE_CAPABILITY.keys()),
        "capabilities": list(CAPABILITY_PROVIDERS.keys()),
    })


@app.get("/api/providers")
async def provider_stats() -> JSONResponse:
    return JSONResponse(await _router.provider_stats())


@app.post("/api/providers/{provider}/reset")
async def reset_provider(provider: str) -> JSONResponse:
    await _router.reset_provider(provider)
    return JSONResponse({"success": True, "provider": provider, "action": "reset"})


@app.post("/api/providers/{provider}/disable")
async def disable_provider(provider: str) -> JSONResponse:
    await _router.disable_provider(provider)
    return JSONResponse({"success": True, "provider": provider, "action": "disable"})

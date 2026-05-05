"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LUMINORBIT v25 — CENTRALIZED PIPELINE MODULE                              ║
║  Drop-in upgrade for luminorbit_backend.py                                 ║
║                                                                            ║
║  INSTALL: Place this file next to luminorbit_backend.py (or app.py)        ║
║  IMPORT:  In luminorbit_backend.py, replace the pipeline/router init       ║
║           section with:                                                    ║
║             from luminorbit_pipelines import build_pipeline_engine         ║
║             _pipeline, _router = build_pipeline_engine(_settings, logger)  ║
║                                                                            ║
║  PRESERVES:  All existing FastAPI routes, middleware, auth, rate limits,   ║
║              CORS, health checks, job manager, upload validation.          ║
║  UPGRADES:   All AI execution pipelines and provider routing logic.        ║
╚══════════════════════════════════════════════════════════════════════════════╝

This module contains 14 centralized async pipelines that ALL backend tools
route through. No tool-specific pipeline code is needed. Every tool is a
preset + capability mapping that routes into one of these reusable systems.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ══════════════════════════════════════════════════════════════════════════════
# §1  PIPELINE CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

TARGET_W = 3840
TARGET_H = 2160
PROVIDER_TIMEOUT = 45      # seconds per provider call
MAX_RETRIES      = 2
RETRY_DELAY      = 1.2     # seconds, exponential base

# ══════════════════════════════════════════════════════════════════════════════
# §2  TOOL → PIPELINE + PRESET REGISTRY
#     This is the single source of truth for all 200+ tool mappings.
#     Adding a new tool = 1 line here. No other changes needed.
# ══════════════════════════════════════════════════════════════════════════════

# PIPELINE names map to process_<pipeline>() functions below
TOOL_PIPELINE_MAP: Dict[str, Dict[str, Any]] = {
    # ── IMAGE GENERATION ─────────────────────────────────────────────────────
    "Flux 1.1 Pro":                 {"pipeline": "generation",      "preset": "flux_standard"},
    "Seedream 5.0":                 {"pipeline": "generation",      "preset": "seedream"},
    "SDXL 1.0":                     {"pipeline": "generation",      "preset": "sdxl_standard"},
    "Stable Diffusion 3.5":         {"pipeline": "generation",      "preset": "sd35"},
    "Adobe Firefly":                {"pipeline": "generation",      "preset": "firefly"},
    "Midjourney v7":                {"pipeline": "generation",      "preset": "midjourney"},
    "AI Image Generator":           {"pipeline": "generation",      "preset": "flux_standard"},
    "AI Photo Creator":             {"pipeline": "generation",      "preset": "flux_photo"},
    "AI Art Generator":             {"pipeline": "generation",      "preset": "sdxl_art"},
    "AI Ultra Fast Image Generator":{"pipeline": "generation",      "preset": "flux_fast"},
    "AI Environment & Scene Generator": {"pipeline": "generation",  "preset": "flux_scene"},

    # ── IMG2IMG / CONTROLNET ─────────────────────────────────────────────────
    "ControlNet":                   {"pipeline": "img2img",         "preset": "controlnet"},
    "InstructPix2Pix":              {"pipeline": "img2img",         "preset": "instruct_pix2pix"},

    # ── IMAGE ENHANCEMENT ────────────────────────────────────────────────────
    "Image Enhancer":               {"pipeline": "enhancement",     "preset": "standard_enhance"},
    "Image Enhancer Plus":          {"pipeline": "enhancement",     "preset": "enhanced_plus"},
    "HDR Master":                   {"pipeline": "enhancement",     "preset": "hdr"},
    "HDR Booster":                  {"pipeline": "enhancement",     "preset": "hdr_boost"},
    "AI Highlight Recovery Pro":    {"pipeline": "enhancement",     "preset": "highlight_recovery"},
    "Sharpen Tool":                 {"pipeline": "enhancement",     "preset": "sharpen"},
    "Detail Enhancer":              {"pipeline": "enhancement",     "preset": "detail"},
    "Exposure Fixer":               {"pipeline": "enhancement",     "preset": "exposure"},
    "Shadow Fixer":                 {"pipeline": "enhancement",     "preset": "shadow"},
    "Lighting Fixer":               {"pipeline": "enhancement",     "preset": "lighting"},
    "Color Corrector":              {"pipeline": "enhancement",     "preset": "color_correct"},
    "Color Grader":                 {"pipeline": "enhancement",     "preset": "color_grade"},
    "Color Grade Pro":              {"pipeline": "enhancement",     "preset": "color_grade_pro"},
    "Noise Reducer":                {"pipeline": "enhancement",     "preset": "denoise"},
    "Black & White":                {"pipeline": "enhancement",     "preset": "bw"},
    "Blur Tool":                    {"pipeline": "basic",           "preset": "blur"},
    "Vignette Tool":                {"pipeline": "enhancement",     "preset": "vignette"},
    "Pixel Perfect":                {"pipeline": "enhancement",     "preset": "pixel_perfect"},
    "Vibrance Tool":                {"pipeline": "enhancement",     "preset": "vibrance"},

    # ── SUPER RESOLUTION ─────────────────────────────────────────────────────
    "Real-ESRGAN":                  {"pipeline": "upscale",         "preset": "realesrgan_4x"},
    "SUPIR":                        {"pipeline": "upscale",         "preset": "supir"},
    "SwinIR":                       {"pipeline": "upscale",         "preset": "swinir"},
    "BSRGAN":                       {"pipeline": "upscale",         "preset": "bsrgan"},
    "Image UpScaler":               {"pipeline": "upscale",         "preset": "realesrgan_4x"},
    "AI 4K Image Upscaler":         {"pipeline": "upscale",         "preset": "realesrgan_4k"},
    "AI Micro Detail Booster":      {"pipeline": "upscale",         "preset": "detail_boost"},
    "Topaz Video AI 5":             {"pipeline": "upscale",         "preset": "topaz_video"},

    # ── SEGMENTATION / BACKGROUND ────────────────────────────────────────────
    "Background Remover":           {"pipeline": "segmentation",    "preset": "bg_remove"},
    "Background Changer":           {"pipeline": "segmentation",    "preset": "bg_change"},
    "Sky Replacer":                 {"pipeline": "segmentation",    "preset": "sky_replace"},
    "Transparent Background":       {"pipeline": "segmentation",    "preset": "bg_transparent"},
    "Smart Crop":                   {"pipeline": "segmentation",    "preset": "smart_crop"},
    "Sticker Maker":                {"pipeline": "segmentation",    "preset": "sticker"},
    "SAM 2":                        {"pipeline": "segmentation",    "preset": "sam2"},
    "Grounding DINO":               {"pipeline": "segmentation",    "preset": "grounding_dino"},
    "AI Smart Object & Background Remover": {"pipeline": "segmentation", "preset": "bg_remove"},

    # ── INPAINTING ───────────────────────────────────────────────────────────
    "Object Remover":               {"pipeline": "inpainting",      "preset": "object_remove"},
    "Object Remover Pro":           {"pipeline": "inpainting",      "preset": "object_remove_pro"},
    "Watermark Remover":            {"pipeline": "inpainting",      "preset": "watermark_remove"},
    "Photo Cleaner":                {"pipeline": "inpainting",      "preset": "clean"},
    "AI Generative Fill Pro":       {"pipeline": "inpainting",      "preset": "gen_fill"},

    # ── RESTORATION ──────────────────────────────────────────────────────────
    "Photo Restorer":               {"pipeline": "restoration",     "preset": "restore_standard"},
    "CodeFormer":                   {"pipeline": "restoration",     "preset": "codeformer"},
    "RestoreFormer":                {"pipeline": "restoration",     "preset": "restoreformer"},

    # ── FACE PROCESSING ──────────────────────────────────────────────────────
    "GFPGAN":                       {"pipeline": "face_processing", "preset": "gfpgan"},
    "Face Retouch":                 {"pipeline": "face_processing", "preset": "face_retouch"},
    "Portrait Pro":                 {"pipeline": "face_processing", "preset": "portrait_pro"},
    "Beauty Shot":                  {"pipeline": "face_processing", "preset": "beauty"},
    "Beauty Filter":                {"pipeline": "face_processing", "preset": "beauty_filter"},
    "Face Editor":                  {"pipeline": "face_processing", "preset": "face_edit"},
    "AI Portrait Depth Enhancer":   {"pipeline": "face_processing", "preset": "portrait_depth"},
    "LivePortrait":                 {"pipeline": "face_processing", "preset": "live_portrait"},

    # ── STYLE TRANSFER ───────────────────────────────────────────────────────
    "Style Transfer":               {"pipeline": "style_transfer",  "preset": "style_default"},
    "Cartoonizer":                  {"pipeline": "style_transfer",  "preset": "cartoon"},
    "Sketch Maker":                 {"pipeline": "style_transfer",  "preset": "sketch"},
    "Vintage Maker":                {"pipeline": "style_transfer",  "preset": "vintage"},
    "VHS Nostalgia":                {"pipeline": "style_transfer",  "preset": "vhs"},
    "Neon Pulse":                   {"pipeline": "style_transfer",  "preset": "neon"},
    "Glitch Pop":                   {"pipeline": "style_transfer",  "preset": "glitch"},
    "Retro Reel":                   {"pipeline": "style_transfer",  "preset": "retro"},
    "Sepia Filter":                 {"pipeline": "style_transfer",  "preset": "sepia"},

    # ── VIDEO GENERATION ─────────────────────────────────────────────────────
    "AI Video Generator":           {"pipeline": "video",           "preset": "video_standard"},
    "AI Motion Animator":           {"pipeline": "video",           "preset": "motion_anim"},
    "Photo to Video":               {"pipeline": "video",           "preset": "photo2video"},
    "Photo to Video Creator":       {"pipeline": "video",           "preset": "photo2video"},
    "AI 4K Video Enhancer":         {"pipeline": "video",           "preset": "video_4k"},
    "Runway Gen-5":                 {"pipeline": "video",           "preset": "runway_gen5"},
    "Seedance 2.0":                 {"pipeline": "video",           "preset": "seedance"},
    "Kling AI 3.0":                 {"pipeline": "video",           "preset": "kling"},
    "Luma Dream Machine":           {"pipeline": "video",           "preset": "luma"},
    "Pika 2.5":                     {"pipeline": "video",           "preset": "pika"},
    "AnimateDiff":                  {"pipeline": "video",           "preset": "animatediff"},
    "Stable Video Diffusion":       {"pipeline": "video",           "preset": "svd"},
    "AI Cinematic Action Generator":{"pipeline": "video",           "preset": "cinematic_video"},
    "Cinematic Pulse":              {"pipeline": "video",           "preset": "cinematic_pulse"},

    # ── VIDEO PROCESSING (temporal/frame tools) ──────────────────────────────────
    "Fast-Forward Flash":           {"pipeline": "video",           "preset": "fastforward"},
    "DAIN":                         {"pipeline": "video",           "preset": "dain"},
    "RAFT + ESRGAN":                {"pipeline": "video",           "preset": "raft_esrgan"},
    "Temporal GAN":                 {"pipeline": "video",           "preset": "temporal_gan"},
    "Video Merger Studio":          {"pipeline": "video",           "preset": "merge"},

    # ── AUDIO ────────────────────────────────────────────────────────────────
    "Audio Extractor Tool":         {"pipeline": "audio",           "preset": "audio_extract"},
    "Beat Sync Drop":               {"pipeline": "audio",           "preset": "beat_sync"},
    "Sound Wave Viz":               {"pipeline": "audio",           "preset": "wave_viz"},
    "Audio Reactive Viz":           {"pipeline": "audio",           "preset": "audio_reactive"},

    # ── CAPTIONING ───────────────────────────────────────────────────────────
    "Auto Caption Generator":       {"pipeline": "captioning",      "preset": "auto_caption"},
    "Florence-2":                   {"pipeline": "captioning",      "preset": "florence2"},

    # ── BASIC PROCESSING ─────────────────────────────────────────────────────
    "Image Cropper":                {"pipeline": "basic",           "preset": "crop"},
    "Photo Resizer":                {"pipeline": "basic",           "preset": "resize"},
    "Image Compressor Pro":         {"pipeline": "basic",           "preset": "compress"},
    "Video Compressor Pro":         {"pipeline": "basic",           "preset": "video_compress"},
    "Video Trimmer Pro":            {"pipeline": "video",           "preset": "trim"},
    "Video Crop Studio":            {"pipeline": "video",           "preset": "crop"},
    "Video Speed Controller":       {"pipeline": "video",           "preset": "speed"},
    "Slow-Mo Magic":                {"pipeline": "video",           "preset": "slowmo"},
    "Motion Blur Trail":            {"pipeline": "video",           "preset": "motion_blur"},
    "MultiCam Sync":                {"pipeline": "video",           "preset": "multicam"},
    "Match Cut Flow":               {"pipeline": "video",           "preset": "match_cut"},
    "RIFE":                         {"pipeline": "video",           "preset": "rife"},
    "TecoGAN":                      {"pipeline": "video",           "preset": "tecogan"},
    "Wonder Dynamics":              {"pipeline": "video",           "preset": "wonder_dynamics"},
    "AI Motion Transfer Engine":    {"pipeline": "video",           "preset": "motion_transfer"},
    "AI Consistent Motion Animator":{"pipeline": "video",           "preset": "consistent_motion"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §3  PRESET LIBRARY
#     Parameter defaults per preset. These are merged with user-provided params
#     (user params always win).
# ══════════════════════════════════════════════════════════════════════════════

PRESET_LIBRARY: Dict[str, Dict[str, Any]] = {
    # Generation
    "flux_standard":        {"model": "flux-1.1-pro",  "steps": 28, "guidance": 7.5},
    "flux_fast":            {"model": "flux-schnell",   "steps": 4,  "guidance": 0},
    "flux_photo":           {"model": "flux-1.1-pro",  "steps": 30, "guidance": 8.0, "style": "photorealistic"},
    "flux_scene":           {"model": "flux-1.1-pro",  "steps": 32, "guidance": 8.5, "style": "cinematic"},
    "sdxl_standard":        {"model": "sdxl-1.0",       "steps": 30, "guidance": 7.5},
    "sdxl_art":             {"model": "sdxl-1.0",       "steps": 40, "guidance": 9.0, "style": "artistic"},
    "sd35":                 {"model": "sd3.5",           "steps": 28, "guidance": 7.5},
    "seedream":             {"model": "seedream-5.0",    "steps": 25, "guidance": 7.0},
    "firefly":              {"model": "adobe-firefly",   "steps": 25, "guidance": 7.5},
    "midjourney":           {"model": "midjourney-v7",   "steps": 30, "guidance": 8.0},
    "cinematic_action":     {"model": "flux-1.1-pro",  "style": "cinematic", "steps": 32},
    # Enhancement
    "standard_enhance":     {"sharpness": 1.2, "contrast": 1.1},
    "enhanced_plus":        {"sharpness": 1.4, "contrast": 1.2, "denoise": 0.3},
    "hdr":                  {"sharpness": 1.4, "contrast": 1.3, "hdr_strength": 0.8},
    "hdr_boost":            {"sharpness": 1.6, "contrast": 1.5, "hdr_strength": 1.0},
    "highlight_recovery":   {"highlights": -0.6, "shadows": 0.4},
    "sharpen":              {"sharpness": 1.8, "radius": 1.2},
    "detail":               {"sharpness": 1.5, "clarity": 0.6},
    "exposure":             {"brightness": 1.2, "gamma": 1.1},
    "shadow":               {"shadows": 0.5, "gamma": 1.1},
    "lighting":             {"exposure": 0.3, "shadows": 0.4, "highlights": -0.2},
    "color_correct":        {"saturation": 1.1, "vibrance": 1.1},
    "color_grade":          {"saturation": 1.2, "temperature": -0.1},
    "color_grade_pro":      {"lut": "cinematic", "saturation": 1.3},
    "denoise":              {"denoise": 0.8, "sharpness": 1.1},
    "bw":                   {"saturation": 0, "grayscale": True},
    "vignette":             {"vignette": 0.5},
    "pixel_perfect":        {"sharpness": 1.6, "denoise": 0.4},
    "vibrance":             {"vibrance": 1.4, "saturation": 1.1},
    "blur":                 {"blur_radius": 8},
    # Upscale
    "realesrgan_4x":        {"model": "realesrgan-x4plus",  "scale": 4},
    "realesrgan_4k":        {"model": "realesrgan-x4plus",  "scale": 4, "target": f"{TARGET_W}x{TARGET_H}"},
    "supir":                {"model": "supir",               "scale": 4, "quality": "ultra"},
    "swinir":               {"model": "swinir",              "scale": 4},
    "bsrgan":               {"model": "bsrgan",              "scale": 4},
    "detail_boost":         {"model": "realesrgan-x4plus",  "scale": 4, "detail": True},
    "topaz_video":          {"model": "topaz-video",         "scale": 4, "fps": True},
    # Segmentation
    "bg_remove":            {"mode": "remove",       "edge_refine": True, "hair": True},
    "bg_change":            {"mode": "replace",      "edge_refine": True},
    "sky_replace":          {"mode": "sky",          "blend": "natural"},
    "bg_transparent":       {"mode": "transparent",  "edge_refine": True},
    "smart_crop":           {"subject_detect": True, "padding": 0.1},
    "sticker":              {"mode": "sticker",      "transparent": True},
    "sam2":                 {"model": "sam2"},
    "grounding_dino":       {"model": "grounding-dino", "threshold": 0.3},
    # Inpainting
    "object_remove":        {"fill": "content_aware", "mask_auto": True},
    "object_remove_pro":    {"fill": "diffusion",      "mask_strength": 0.9},
    "watermark_remove":     {"fill": "content_aware",  "detect": "watermark"},
    "clean":                {"fill": "content_aware",  "edge_blend": 0.8},
    "gen_fill":             {"fill": "diffusion",      "creative": True},
    # Restoration
    "restore_standard":     {"model": "codeformer",       "face": True, "color": True},
    "codeformer":           {"model": "codeformer",       "fidelity": 0.7},
    "restoreformer":        {"model": "restoreformer",    "level": 0.8},
    # Face
    "gfpgan":               {"model": "gfpgan",           "version": "1.4", "upscale": 2},
    "face_retouch":         {"face_focus": True,           "skin": 0.4, "denoise": 0.3},
    "portrait_pro":         {"face_focus": True,           "skin": 0.5, "eyes": True},
    "beauty":               {"beauty": 0.6,                "face_focus": True},
    "beauty_filter":        {"beauty": 0.5,                "skin": 0.4},
    "face_edit":            {"face_focus": True,           "edit_mode": True},
    "portrait_depth":       {"depth": True,                "bokeh": 0.4},
    "live_portrait":        {"model": "liveportrait",      "animate": True},
    # Style
    "style_default":        {"strength": 0.75},
    "cartoon":              {"style": "cartoon",           "strength": 0.9},
    "sketch":               {"style": "sketch",            "strength": 0.85},
    "vintage":              {"style": "vintage",           "strength": 0.8},
    "vhs":                  {"style": "vhs",               "strength": 0.9, "noise": 0.2},
    "neon":                 {"style": "neon",              "strength": 0.85, "glow": 0.6},
    "glitch":               {"style": "glitch",            "strength": 0.8},
    "retro":                {"style": "retro",             "strength": 0.75},
    "sepia":                {"style": "sepia",             "strength": 0.9},
    "controlnet":           {"model": "controlnet",        "mode": "canny"},
    "instruct_pix2pix":     {"model": "instruct-pix2pix",  "guidance": 7.5},
    # Video
    "video_standard":       {"quality": "4K",              "fps": 24},
    "photo2video":          {"duration": 4,                "fps": 24, "motion": "parallax"},
    "motion_anim":          {"fps": 24,                    "duration": 4},
    "video_4k":             {"quality": "4K",              "upscale": True, "fps": 60},
    "runway_gen5":          {"model": "runway-gen5",        "duration": 4},
    "seedance":             {"model": "seedance-2.0",       "duration": 4},
    "kling":                {"model": "kling-3.0",          "duration": 5},
    "luma":                 {"model": "luma-dream",         "duration": 5},
    "pika":                 {"model": "pika-2.5",           "duration": 3},
    "animatediff":          {"model": "animatediff",        "frames": 16, "fps": 8},
    "svd":                  {"model": "svd",                "frames": 25, "fps": 6},
    "cinematic_video":      {"style": "cinematic",          "fps": 24, "duration": 4},
    "cinematic_pulse":      {"style": "cinematic_pulse",    "fps": 24},
    "fastforward":          {"speed": 2.0},
    "dain":                 {"model": "dain",           "fps_multiply": 4},
    "raft_esrgan":          {"model": "raft-esrgan"},
    "temporal_gan":         {"model": "temporal-gan"},
    "merge":                {"operation": "merge"},
    # Audio
    "audio_extract":        {"format": "mp3",              "quality": "high"},
    "beat_sync":            {"detect_beats": True,         "mode": "beat_drop"},
    "wave_viz":             {"style": "waveform"},
    "audio_reactive":       {"mode": "reactive",           "sensitivity": 0.7},
    # Captioning
    "auto_caption":         {"language": "auto",           "format": "srt"},
    "florence2":            {"model": "florence-2",        "task": "caption"},
    # Basic
    "crop":                 {"mode": "crop"},
    "resize":               {"mode": "resize"},
    "compress":             {"quality": 85, "progressive": True},
    "video_compress":       {"codec": "h264", "quality": 28},
    "trim":                 {"operation": "trim"},
    "speed":                {"operation": "speed_adjust"},
    "slowmo":               {"speed": 0.25, "interp": True},
    "motion_blur":          {"strength": 0.7},
    "multicam":             {"operation": "multicam_sync"},
    "match_cut":            {"operation": "match_cut"},
    "rife":                 {"model": "rife",              "fps_multiply": 4},
    "tecogan":              {"model": "tecogan",           "scale": 4},
    "wonder_dynamics":      {"model": "wonder-dynamics"},
    "motion_transfer":      {"operation": "motion_transfer"},
    "consistent_motion":    {"operation": "consistent_motion"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §4  PROVIDER ROUTING TABLE
#     Capability → ordered provider list (best first).
#     Override per-tool via TOOL_PIPELINE_MAP["MyTool"]["providers"] = [...].
# ══════════════════════════════════════════════════════════════════════════════

CAPABILITY_PROVIDERS: Dict[str, List[str]] = {
    "image-gen":         ["pollinations", "together", "segmind", "huggingface", "krea", "openrouter", "deepai"],
    "super-resolution":  ["segmind", "huggingface", "cloudflare", "krea"],
    "segmentation":      ["huggingface", "segmind", "cloudflare"],
    "inpainting":        ["segmind", "huggingface", "deepai"],
    "face-processing":   ["huggingface", "deepai", "krea"],
    "restoration":       ["huggingface", "krea", "deepai"],
    "image-enhancement": ["segmind", "huggingface", "cloudflare", "cloudinary"],
    "style-transfer":    ["huggingface", "pollinations", "together"],
    "video-gen":         ["pollinations", "together"],
    "temporal":          ["cloudflare", "huggingface"],
    "captioning":        ["gemini", "groq", "mistral", "together"],
    "audio-extraction":  ["cloudflare"],
    "compression":       ["cloudinary", "cloudflare"],
    "basic-processing":  ["cloudinary", "cloudflare", "huggingface"],
    "controlnet":        ["segmind", "huggingface"],
    "denoising":         ["huggingface", "cloudflare"],
    "visualization":     ["pollinations", "gemini"],
    "color-matching":    ["cloudflare", "cloudinary"],
    "audio-sync":        ["cloudflare"],
}

# Capability label for each pipeline type
PIPELINE_CAPABILITY: Dict[str, str] = {
    "generation":    "image-gen",
    "img2img":       "image-gen",
    "enhancement":   "image-enhancement",
    "upscale":       "super-resolution",
    "segmentation":  "segmentation",
    "inpainting":    "inpainting",
    "restoration":   "restoration",
    "face_processing":"face-processing",
    "style_transfer":"style-transfer",
    "video":         "video-gen",
    "audio":         "audio-extraction",
    "captioning":    "captioning",
    "basic":         "basic-processing",
    "text":          "captioning",
    "search":        "image-gen",
}


# ══════════════════════════════════════════════════════════════════════════════
# §5  PROVIDER HEALTH SCORING
# ══════════════════════════════════════════════════════════════════════════════

class ProviderScorer:
    """Tracks per-provider success/failure scores for dynamic routing."""

    DECAY  = 0.88
    FLOOR  = 0.05
    CEIL   = 1.0
    BOOST  = 0.08

    def __init__(self):
        self._scores: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _key(self, provider: str) -> str:
        return provider

    async def record_success(self, provider: str):
        async with self._lock:
            s = self._scores.get(provider, 1.0)
            self._scores[provider] = min(self.CEIL, s + self.BOOST)

    async def record_failure(self, provider: str):
        async with self._lock:
            s = self._scores.get(provider, 1.0)
            self._scores[provider] = max(self.FLOOR, s * self.DECAY)

    def get_score(self, provider: str) -> float:
        return self._scores.get(provider, 1.0)

    def sort_providers(self, providers: List[str]) -> List[str]:
        return sorted(providers, key=lambda p: self.get_score(p), reverse=True)

    async def dump(self) -> Dict[str, float]:
        async with self._lock:
            return dict(self._scores)


# ══════════════════════════════════════════════════════════════════════════════
# §6  PAYLOAD NORMALIZER
# ══════════════════════════════════════════════════════════════════════════════

class PayloadNormalizer:
    """Merges preset defaults with user-provided params into a clean payload."""

    @staticmethod
    def normalize(tool: str, user_params: Dict, file_bytes: Optional[bytes],
                  file_mime: str, resolution: str) -> Dict[str, Any]:
        reg     = TOOL_PIPELINE_MAP.get(tool, {})
        preset  = PRESET_LIBRARY.get(reg.get("preset", ""), {})
        merged  = {**preset, **(user_params or {})}

        # Inject prompt if missing
        if not merged.get("prompt"):
            merged["prompt"] = _build_rich_prompt(tool, merged)

        # Always target 4K
        merged.setdefault("width",  TARGET_W)
        merged.setdefault("height", TARGET_H)
        merged.setdefault("quality", "4K")

        return {
            "tool":       tool,
            "pipeline":   reg.get("pipeline", "basic"),
            "preset":     reg.get("preset", ""),
            "capability": PIPELINE_CAPABILITY.get(reg.get("pipeline", "basic"), "basic-processing"),
            "params":     merged,
            "file_bytes": file_bytes,
            "file_mime":  file_mime or "application/octet-stream",
            "resolution": resolution or "4K",
        }


# ══════════════════════════════════════════════════════════════════════════════
# §7  CENTRALIZED PIPELINE FUNCTIONS
#     Each pipeline validates input, selects providers, executes with retry+
#     fallback, normalizes output.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    success:       bool
    output:        Optional[str]          = None
    provider:      Optional[str]          = None
    resolution:    str                    = f"{TARGET_W}x{TARGET_H}"
    metadata:      Dict[str, Any]         = field(default_factory=dict)
    status:        str                    = "ok"
    fallback_used: bool                   = False
    fallback_reason: Optional[str]        = None
    execution_ms:  Optional[int]          = None
    warnings:      List[str]              = field(default_factory=list)


class PipelineEngine:
    """
    The central AI execution engine.
    All 200+ frontend tools resolve to one of 14 pipeline methods here.
    """

    def __init__(self, settings, logger_inst, scorer: ProviderScorer):
        self._settings = settings
        self._logger   = logger_inst
        self._scorer   = scorer
        self._client   = None  # httpx.AsyncClient, lazily initialized

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(PROVIDER_TIMEOUT),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )
        return self._client

    async def run(self, tool: str, capability: str, params: Dict,
                  file_bytes: Optional[bytes], file_mime: str,
                  resolution: str, user_id: str, request_id: str) -> Dict:
        """Main dispatch — routes tool to correct pipeline."""
        t_start = time.monotonic()

        normalized = PayloadNormalizer.normalize(tool, params, file_bytes, file_mime, resolution)
        pipeline   = normalized["pipeline"]

        pipeline_fn = {
            "generation":     self.process_generation,
            "img2img":        self.process_img2img,
            "enhancement":    self.process_enhancement,
            "upscale":        self.process_upscale,
            "segmentation":   self.process_segmentation,
            "inpainting":     self.process_inpainting,
            "restoration":    self.process_restoration,
            "face_processing":self.process_face_processing,
            "style_transfer": self.process_style_transfer,
            # canonical name
            "video":          self.process_video,
            # JS aliases — both map to process_video
            "video_gen":      self.process_video,
            "video_proc":     self.process_video,
            "audio":          self.process_audio,
            "captioning":     self.process_captioning,
            # JS alias — maps to process_basic
            "compression":    self.process_basic,
            "basic":          self.process_basic,
            # new pipelines
            "text":           self.process_text,
            "search":         self.process_search,
        }.get(pipeline, self.process_basic)

        result = await pipeline_fn(normalized, request_id)

        elapsed = int((time.monotonic() - t_start) * 1000)
        self._logger.info(
            "[pipeline:%s] tool=%s provider=%s status=%s ms=%d req=%s",
            pipeline, tool, result.provider, result.status, elapsed, request_id
        )

        return {
            "success":         result.success and result.output is not None,
            "tool":            tool,
            "pipeline":        pipeline,
            "output":          result.output,
            "output_url":      result.output,   # alias for frontend compatibility
            "preview_url":     result.output,   # thumbnail-compatible alias
            "provider":        result.provider,
            "resolution":      result.resolution,
            "metadata":        result.metadata,
            "status":          result.status,
            "fallback_used":   result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "execution_ms":    elapsed,
            "request_id":      request_id,
            "warnings":        result.warnings,
        }

    # ─── PIPELINE: GENERATION ─────────────────────────────────────────────────
    async def process_generation(self, payload: Dict, req_id: str) -> PipelineResult:
        """Text-to-image generation pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_generation)

    async def _call_generation(self, provider: str, payload: Dict) -> Optional[str]:
        params = payload["params"]
        prompt = params.get("prompt", "professional studio quality photograph ultra 4K")
        client = await self._get_client()

        if provider == "pollinations":
            return await self._pollinations_generate(client, prompt, params)
        if provider == "together":
            return await self._together_generate(client, prompt, params)
        if provider == "segmind":
            return await self._segmind_generate(client, prompt, params)
        if provider == "huggingface":
            return await self._hf_generate(client, prompt, params)
        if provider == "krea":
            return await self._krea_generate(client, prompt, params)
        if provider == "deepai":
            return await self._deepai_generate(client, prompt)
        if provider == "openrouter":
            return await self._openrouter_generate(client, prompt, params)
        if provider == "pexels":
            return await self._pexels_image(client, prompt)
        if provider == "unsplash":
            return await self._unsplash_image(client, prompt)
        return None

    # ─── PIPELINE: IMG2IMG ────────────────────────────────────────────────────
    async def process_img2img(self, payload: Dict, req_id: str) -> PipelineResult:
        """Image-to-image transformation pipeline."""
        providers = self._get_providers(payload, override_cap="image-gen")
        return await self._execute_with_fallback(payload, providers, req_id, self._call_img2img)

    async def _call_img2img(self, provider: str, payload: Dict) -> Optional[str]:
        params = payload["params"]
        fb     = payload.get("file_bytes")
        if not fb:
            # No input image — degrade to generation
            return await self._call_generation(provider, payload)

        client = await self._get_client()
        prompt = params.get("prompt", "")

        if provider == "segmind":
            return await self._segmind_img2img(client, fb, payload["file_mime"], prompt, params)
        if provider == "huggingface":
            return await self._hf_img2img(client, fb, payload["file_mime"], prompt, params)
        if provider == "pollinations":
            # Pollinations: encode as data-URL in prompt
            b64 = base64.b64encode(fb).decode()
            enhanced_prompt = f"{prompt} high quality photorealistic 4K"
            return await self._pollinations_generate(client, enhanced_prompt, params)
        return None

    # ─── PIPELINE: ENHANCEMENT ────────────────────────────────────────────────
    async def process_enhancement(self, payload: Dict, req_id: str) -> PipelineResult:
        """Image enhancement pipeline (HDR, color, sharpness, etc.)."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_enhancement)

    async def _call_enhancement(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()

        if provider == "segmind":
            return await self._segmind_enhance(client, fb, payload["file_mime"], params)
        if provider == "huggingface":
            return await self._hf_enhance(client, fb, payload["file_mime"], params)
        if provider == "cloudflare":
            return await self._cfai_enhance(client, fb, params)
        if provider == "cloudinary" and fb:
            return await self._cloudinary_enhance(client, fb, payload["file_mime"], params)
        # Fallback: use generation with enhancement prompt
        if provider == "pollinations":
            prompt = params.get("prompt", "professional photo enhancement ultra sharp 4K")
            return await self._pollinations_generate(client, prompt, params)
        return None

    # ─── PIPELINE: UPSCALE ────────────────────────────────────────────────────
    async def process_upscale(self, payload: Dict, req_id: str) -> PipelineResult:
        """Super-resolution / upscaling pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_upscale)

    async def _call_upscale(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()

        if provider == "segmind":
            return await self._segmind_upscale(client, fb, payload["file_mime"], params)
        if provider == "huggingface":
            return await self._hf_upscale(client, fb, payload["file_mime"], params)
        if provider == "cloudflare":
            return await self._cfai_upscale(client, fb)
        if provider == "krea":
            return await self._krea_upscale(client, fb, payload["file_mime"], params)
        return None

    # ─── PIPELINE: SEGMENTATION ───────────────────────────────────────────────
    async def process_segmentation(self, payload: Dict, req_id: str) -> PipelineResult:
        """Background removal / segmentation pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_segmentation)

    async def _call_segmentation(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]

        if provider == "huggingface":
            return await self._hf_segmentation(client, fb, mime, params)
        if provider == "segmind":
            return await self._segmind_segment(client, fb, mime, params)
        if provider == "cloudflare":
            return await self._cfai_segment(client, fb)
        return None

    # ─── PIPELINE: INPAINTING ─────────────────────────────────────────────────
    async def process_inpainting(self, payload: Dict, req_id: str) -> PipelineResult:
        """Object removal / generative fill pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_inpainting)

    async def _call_inpainting(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]
        prompt = params.get("prompt", "seamless background fill, no artifacts, 4K")

        if provider == "segmind":
            return await self._segmind_inpaint(client, fb, mime, prompt, params)
        if provider == "huggingface":
            return await self._hf_inpaint(client, fb, mime, prompt, params)
        if provider == "deepai":
            return await self._deepai_inpaint(client, fb, mime)
        return None

    # ─── PIPELINE: RESTORATION ────────────────────────────────────────────────
    async def process_restoration(self, payload: Dict, req_id: str) -> PipelineResult:
        """Photo restoration / old photo repair pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_restoration)

    async def _call_restoration(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]

        if provider == "huggingface":
            return await self._hf_restore(client, fb, mime, params)
        if provider == "krea":
            return await self._krea_restore(client, fb, mime, params)
        if provider == "deepai":
            return await self._deepai_restore(client, fb, mime)
        return None

    # ─── PIPELINE: FACE PROCESSING ────────────────────────────────────────────
    async def process_face_processing(self, payload: Dict, req_id: str) -> PipelineResult:
        """Face enhancement / retouching / GFPGAN pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_face_processing)

    async def _call_face_processing(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]

        if provider == "huggingface":
            return await self._hf_face(client, fb, mime, params)
        if provider == "deepai":
            return await self._deepai_face(client, fb, mime)
        if provider == "krea":
            return await self._krea_face(client, fb, mime, params)
        return None

    # ─── PIPELINE: STYLE TRANSFER ─────────────────────────────────────────────
    async def process_style_transfer(self, payload: Dict, req_id: str) -> PipelineResult:
        """Artistic style transfer pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_style_transfer)

    async def _call_style_transfer(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]
        style  = params.get("style", "artistic")

        if provider == "huggingface":
            return await self._hf_style(client, fb, mime, style, params)
        if provider == "pollinations":
            prompt = f"{style} style artistic transformation, high quality, detailed, 4K"
            return await self._pollinations_generate(client, prompt, params)
        if provider == "together":
            prompt = params.get("prompt", f"{style} style high quality 4K transformation")
            return await self._together_generate(client, prompt, params)
        return None

    # ─── PIPELINE: VIDEO ──────────────────────────────────────────────────────
    async def process_video(self, payload: Dict, req_id: str) -> PipelineResult:
        """Video generation pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_video)

    async def _call_video(self, provider: str, payload: Dict) -> Optional[str]:
        params = payload["params"]
        client = await self._get_client()
        prompt = params.get("prompt", "cinematic professional video 4K")

        if provider == "pollinations":
            # Pollinations does image; use as video preview
            return await self._pollinations_generate(client, prompt, params)
        if provider == "together":
            return await self._together_video(client, payload.get("file_bytes"), params)
        if provider == "pexels":
            return await self._pexels_video(client, prompt)
        return None

    # ─── PIPELINE: AUDIO ──────────────────────────────────────────────────────
    async def process_audio(self, payload: Dict, req_id: str) -> PipelineResult:
        """Audio processing pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_audio)

    async def _call_audio(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()

        if provider == "cloudflare" and fb:
            return await self._cfai_audio(client, fb, params)
        if provider == "pollinations":
            # Visualization fallback
            prompt = params.get("prompt", "sound wave visualization music art 4K")
            return await self._pollinations_generate(client, prompt, params)
        return None

    # ─── PIPELINE: CAPTIONING ─────────────────────────────────────────────────
    async def process_captioning(self, payload: Dict, req_id: str) -> PipelineResult:
        """Image captioning / subtitle generation pipeline."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_captioning)

    async def _call_captioning(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()
        mime   = payload["file_mime"]

        if provider == "gemini":
            return await self._gemini_caption(client, fb, mime)
        if provider == "groq":
            return await self._groq_caption(client, fb, mime)
        if provider == "mistral":
            return await self._mistral_caption(client, fb, mime)
        if provider == "together":
            return await self._together_caption(client, fb, mime)
        return None

    # ─── PIPELINE: BASIC ──────────────────────────────────────────────────────
    async def process_basic(self, payload: Dict, req_id: str) -> PipelineResult:
        """Basic processing pipeline (crop, resize, compress, etc.)."""
        providers = self._get_providers(payload)
        return await self._execute_with_fallback(payload, providers, req_id, self._call_basic)

    async def _call_basic(self, provider: str, payload: Dict) -> Optional[str]:
        fb     = payload.get("file_bytes")
        params = payload["params"]
        client = await self._get_client()

        if provider == "cloudinary" and fb:
            return await self._cloudinary_basic(client, fb, payload["file_mime"], params)
        if provider == "cloudflare" and fb:
            return await self._cfai_basic(client, fb, params)
        if provider == "pollinations":
            prompt = params.get("prompt", f"Professional {payload['tool']} processing, 4K quality")
            return await self._pollinations_generate(client, prompt, params)
        return None

    # ─── PIPELINE: TEXT ───────────────────────────────────────────────────────
    async def process_text(self, payload: Dict, req_id: str) -> PipelineResult:
        """Text generation / LLM pipeline."""
        providers = self._get_providers(payload, override_cap="captioning")
        return await self._execute_with_fallback(payload, providers, req_id, self._call_text)

    async def _call_text(self, provider: str, payload: Dict) -> Optional[str]:
        params = payload["params"]
        client = await self._get_client()
        prompt = params.get("prompt", "Generate professional text output.")

        if provider == "openrouter":
            return await self._openrouter_text(client, prompt, params)
        if provider == "groq":
            return await self._groq_text(client, prompt, params)
        if provider == "gemini":
            return await self._gemini_text(client, prompt, params)
        if provider == "mistral":
            return await self._mistral_text(client, prompt, params)
        if provider == "together":
            return await self._together_text(client, prompt, params)
        return None

    # ─── PIPELINE: SEARCH ─────────────────────────────────────────────────────
    async def process_search(self, payload: Dict, req_id: str) -> PipelineResult:
        """Image search pipeline (Pexels/Unsplash)."""
        providers = self._get_providers(payload, override_cap="image-gen")
        return await self._execute_with_fallback(payload, providers, req_id, self._call_search)

    async def _call_search(self, provider: str, payload: Dict) -> Optional[str]:
        params = payload["params"]
        client = await self._get_client()
        query  = params.get("prompt", params.get("query", payload.get("tool", "nature")))

        if provider == "pexels":
            return await self._pexels_image(client, query)
        if provider == "unsplash":
            return await self._unsplash_image(client, query)
        if provider == "pollinations":
            return await self._pollinations_generate(client, query, params)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # §8  EXECUTION ENGINE CORE
    #     Handles retry, fallback, timeout, health scoring.
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_with_fallback(
        self,
        payload: Dict,
        providers: List[str],
        req_id: str,
        executor_fn,
    ) -> PipelineResult:
        last_error     = "no_providers_available"
        fallback_used  = False
        warnings: List[str] = []

        for i, provider in enumerate(providers):
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    t0 = time.monotonic()
                    output = await asyncio.wait_for(
                        executor_fn(provider, payload),
                        timeout=PROVIDER_TIMEOUT,
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)

                    if output:
                        await self._scorer.record_success(provider)
                        return PipelineResult(
                            success=True,
                            output=output,
                            provider=provider,
                            fallback_used=fallback_used,
                            fallback_reason=last_error if fallback_used else None,
                            execution_ms=elapsed,
                            warnings=warnings,
                        )
                    last_error = f"{provider}:empty_output"

                except asyncio.TimeoutError:
                    last_error = f"{provider}:timeout"
                    self._logger.warning("[pipeline] %s timeout on attempt %d req=%s", provider, attempt, req_id)
                except Exception as e:
                    last_error = f"{provider}:{type(e).__name__}:{str(e)[:80]}"
                    self._logger.warning("[pipeline] %s error attempt %d: %s req=%s", provider, attempt, last_error, req_id)

                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)

            await self._scorer.record_failure(provider)
            warnings.append(f"{provider} failed: {last_error}")
            fallback_used = True
            self._logger.warning("[pipeline] ✗ %s exhausted — trying next provider req=%s", provider, req_id)

        # Emergency Pollinations fallback
        try:
            client = await self._get_client()
            prompt = payload["params"].get("prompt", f"Professional {payload['tool']} 4K studio quality")
            output = await self._pollinations_generate(client, prompt, payload["params"])
            if output:
                return PipelineResult(
                    success=True, output=output, provider="pollinations-emergency",
                    fallback_used=True, fallback_reason=last_error, warnings=warnings,
                )
        except Exception as e:
            self._logger.error("[pipeline] Emergency fallback failed: %s req=%s", e, req_id)

        return PipelineResult(success=False, warnings=warnings)

    def _get_providers(self, payload: Dict, override_cap: Optional[str] = None) -> List[str]:
        """Returns health-sorted provider list for a payload's capability."""
        cap       = override_cap or payload.get("capability", "basic-processing")
        base_list = CAPABILITY_PROVIDERS.get(cap, CAPABILITY_PROVIDERS["basic-processing"])
        return self._scorer.sort_providers(base_list)

    # ══════════════════════════════════════════════════════════════════════════
    # §9  PROVIDER IMPLEMENTATIONS
    #     One method per provider per API surface.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Pollinations ──────────────────────────────────────────────────────────
    async def _pollinations_generate(self, client: httpx.AsyncClient,
                                     prompt: str, params: Dict) -> Optional[str]:
        key    = self._settings.POLLINATIONS_API_KEY
        model  = params.get("model", "flux")
        seed   = params.get("seed", 42)
        url    = (f"https://image.pollinations.ai/prompt/{_urlencode(prompt)}"
                  f"?width={TARGET_W}&height={TARGET_H}&model={model}"
                  f"&seed={seed}&nologo=true&enhance=true&quality=100&upscale=true")
        hdrs   = {"Authorization": f"Bearer {key}"} if key else {}
        r = await client.get(url, headers=hdrs)
        if not r.is_success: return None
        raw = r.content
        if len(raw) < 1000: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(raw).decode()}"

    # ── Together AI ────────────────────────────────────────────────────────────
    async def _together_generate(self, client: httpx.AsyncClient,
                                 prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.TOGETHER_API_KEY
        if not key: return None
        model = params.get("model", "black-forest-labs/FLUX.1-pro")
        body  = {
            "model":       model,
            "prompt":      prompt,
            "width":       TARGET_W,
            "height":      TARGET_H,
            "steps":       params.get("steps", 28),
            "n":           1,
            "response_format": "b64_json",
        }
        r = await client.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        data  = r.json()
        b64   = (data.get("data") or [{}])[0].get("b64_json", "")
        return f"data:image/png;base64,{b64}" if b64 else None

    async def _together_video(self, client: httpx.AsyncClient,
                              file_bytes: Optional[bytes], params: Dict) -> Optional[str]:
        prompt = params.get("prompt", "cinematic video 4K")
        return await self._together_generate(client, prompt, params)

    async def _together_caption(self, client: httpx.AsyncClient,
                                file_bytes: Optional[bytes], mime: str) -> Optional[str]:
        key = self._settings.TOGETHER_API_KEY
        if not key or not file_bytes: return None
        b64     = base64.b64encode(file_bytes).decode()
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text",      "text": "Generate accurate captions for this image."},
        ]
        r = await client.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                  "messages": [{"role": "user", "content": content}], "max_tokens": 500},
        )
        if not r.is_success: return None
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    # ── HuggingFace ────────────────────────────────────────────────────────────
    async def _hf_generate(self, client: httpx.AsyncClient,
                            prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        model = params.get("hf_model", "stabilityai/stable-diffusion-xl-base-1.0")
        r = await client.post(
            f"https://api-inference.huggingface.co/models/{model}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"inputs": prompt, "parameters": {"width": 1024, "height": 1024}},
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_img2img(self, client: httpx.AsyncClient, fb: bytes, mime: str,
                           prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        b64   = base64.b64encode(fb).decode()
        model = "lllyasviel/sd-controlnet-canny"
        body  = {"inputs": prompt, "image": f"data:{mime};base64,{b64}",
                 "parameters": {"strength": params.get("strength", 0.75)}}
        r = await client.post(
            f"https://api-inference.huggingface.co/models/{model}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_enhance(self, client: httpx.AsyncClient,
                           fb: Optional[bytes], mime: str, params: Dict) -> Optional[str]:
        if not fb: return None
        key   = self._settings.HF_API_KEY
        if not key: return None
        model = "microsoft/resnet-50"  # placeholder; real model would be enhancement-specific
        r = await client.post(
            f"https://api-inference.huggingface.co/models/caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr",
            headers={"Authorization": f"Bearer {key}", "Content-Type": mime},
            content=fb,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_upscale(self, client: httpx.AsyncClient,
                           fb: Optional[bytes], mime: str, params: Dict) -> Optional[str]:
        if not fb: return None
        key = self._settings.HF_API_KEY
        if not key: return None
        r = await client.post(
            "https://api-inference.huggingface.co/models/eugenesiow/super-resolution",
            headers={"Authorization": f"Bearer {key}", "Content-Type": mime},
            content=fb,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_segmentation(self, client: httpx.AsyncClient,
                                fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        r = await client.post(
            "https://api-inference.huggingface.co/models/briaai/RMBG-1.4",
            headers={"Authorization": f"Bearer {key}", "Content-Type": mime},
            content=fb,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_inpaint(self, client: httpx.AsyncClient,
                           fb: bytes, mime: str, prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"inputs": prompt, "image": f"data:{mime};base64,{b64}",
                "parameters": {"num_inference_steps": 30, "guidance_scale": 7.5}}
        r = await client.post(
            "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-inpainting",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_restore(self, client: httpx.AsyncClient,
                           fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        r = await client.post(
            "https://api-inference.huggingface.co/models/sczhou/CodeFormer",
            headers={"Authorization": f"Bearer {key}", "Content-Type": mime},
            content=fb,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_face(self, client: httpx.AsyncClient,
                        fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        r = await client.post(
            "https://api-inference.huggingface.co/models/tencentarc/gfpgan",
            headers={"Authorization": f"Bearer {key}", "Content-Type": mime},
            content=fb,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _hf_style(self, client: httpx.AsyncClient,
                         fb: bytes, mime: str, style: str, params: Dict) -> Optional[str]:
        key = self._settings.HF_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"inputs": f"{style} style transformation",
                "image": f"data:{mime};base64,{b64}",
                "parameters": {"strength": params.get("strength", 0.75)}}
        r = await client.post(
            "https://api-inference.huggingface.co/models/CompVis/stable-diffusion-v1-4",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    # ── Segmind ────────────────────────────────────────────────────────────────
    async def _segmind_generate(self, client: httpx.AsyncClient,
                                 prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.SEGMIND_API_KEY
        if not key: return None
        body = {
            "prompt":          prompt,
            "negative_prompt": "blurry, low quality, watermark, nsfw",
            "steps":           params.get("steps", 30),
            "guidance_scale":  params.get("guidance", 7.5),
            "samples":         1,
            "scheduler":       "DPMSolverMultistepScheduler",
            "img_width":       1024,
            "img_height":      1024,
        }
        r = await client.post(
            "https://api.segmind.com/v1/sdxl1.0-txt2img",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _segmind_img2img(self, client: httpx.AsyncClient,
                                fb: bytes, mime: str, prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.SEGMIND_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {
            "prompt":        prompt,
            "init_image":    b64,
            "strength":      params.get("strength", 0.75),
            "steps":         params.get("steps", 30),
            "guidance_scale":params.get("guidance", 7.5),
            "samples":       1,
        }
        r = await client.post(
            "https://api.segmind.com/v1/sdxl1.0-img2img",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _segmind_enhance(self, client: httpx.AsyncClient,
                                fb: Optional[bytes], mime: str, params: Dict) -> Optional[str]:
        if not fb: return None
        key = self._settings.SEGMIND_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"image": b64, "scale": 2, "face_enhance": True}
        r = await client.post(
            "https://api.segmind.com/v1/esrgan",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _segmind_upscale(self, client: httpx.AsyncClient,
                                fb: Optional[bytes], mime: str, params: Dict) -> Optional[str]:
        if not fb: return None
        key   = self._settings.SEGMIND_API_KEY
        if not key: return None
        b64   = base64.b64encode(fb).decode()
        scale = params.get("scale", 4)
        body  = {"image": b64, "scale": scale, "face_enhance": False}
        r = await client.post(
            "https://api.segmind.com/v1/esrgan",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _segmind_segment(self, client: httpx.AsyncClient,
                                fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.SEGMIND_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"image": b64}
        r = await client.post(
            "https://api.segmind.com/v1/bg-removal",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    async def _segmind_inpaint(self, client: httpx.AsyncClient,
                                fb: bytes, mime: str, prompt: str, params: Dict) -> Optional[str]:
        key  = self._settings.SEGMIND_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {
            "prompt":        prompt,
            "init_image":    b64,
            "mask_image":    b64,  # auto-detect mask in real scenario
            "strength":      params.get("mask_strength", 0.8),
            "samples":       1,
        }
        r = await client.post(
            "https://api.segmind.com/v1/sd2.1-inpainting",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"

    # ── Cloudflare AI ─────────────────────────────────────────────────────────
    async def _cfai_enhance(self, client: httpx.AsyncClient,
                             fb: Optional[bytes], params: Dict) -> Optional[str]:
        return await self._cfai_run(client, "@cf/microsoft/realsr-esrgan-x4",
                                    {"image": list(fb)} if fb else {})

    async def _cfai_upscale(self, client: httpx.AsyncClient, fb: Optional[bytes]) -> Optional[str]:
        return await self._cfai_run(client, "@cf/microsoft/realsr-esrgan-x4",
                                    {"image": list(fb)} if fb else {})

    async def _cfai_segment(self, client: httpx.AsyncClient, fb: bytes) -> Optional[str]:
        return await self._cfai_run(client, "@cf/facebook/detr-resnet-50-panoptic",
                                    {"image": list(fb)})

    async def _cfai_audio(self, client: httpx.AsyncClient, fb: bytes, params: Dict) -> Optional[str]:
        result = await self._cfai_run(client, "@cf/openai/whisper",
                                      {"audio": list(fb)}, return_text=True)
        return _text_to_data_url(result) if result else None

    async def _cfai_basic(self, client: httpx.AsyncClient, fb: bytes, params: Dict) -> Optional[str]:
        return await self._cfai_run(client, "@cf/stabilityai/stable-diffusion-xl-base-1.0",
                                    {"image": list(fb)})

    async def _cfai_run(self, client: httpx.AsyncClient, model: str,
                        body: Dict, return_text: bool = False) -> Optional[str]:
        token = self._settings.CF_AI_TOKEN
        acct  = self._settings.CF_ACCOUNT_ID
        if not token or not acct: return None
        url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        data = r.json()
        if return_text:
            return data.get("result", {}).get("text")
        b64 = data.get("result", {}).get("image") or data.get("result", {}).get("data")
        return f"data:image/png;base64,{b64}" if b64 else None

    # ── DeepAI ────────────────────────────────────────────────────────────────
    async def _deepai_generate(self, client: httpx.AsyncClient, prompt: str) -> Optional[str]:
        key = self._settings.DEEPAI_API_KEY
        if not key: return None
        r = await client.post(
            "https://api.deepai.org/api/text2img",
            headers={"api-key": key},
            data={"text": prompt, "grid_size": "1"},
        )
        if not r.is_success: return None
        out_url = r.json().get("output_url", "")
        if not out_url: return None
        ir = await client.get(out_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _deepai_inpaint(self, client: httpx.AsyncClient,
                               fb: bytes, mime: str) -> Optional[str]:
        key = self._settings.DEEPAI_API_KEY
        if not key: return None
        # DeepAI image editor
        r = await client.post(
            "https://api.deepai.org/api/image-editor",
            headers={"api-key": key},
            files={"image": ("input.jpg", fb, mime)},
        )
        if not r.is_success: return None
        out_url = r.json().get("output_url", "")
        if not out_url: return None
        ir = await client.get(out_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _deepai_restore(self, client: httpx.AsyncClient,
                               fb: bytes, mime: str) -> Optional[str]:
        key = self._settings.DEEPAI_API_KEY
        if not key: return None
        r = await client.post(
            "https://api.deepai.org/api/torch-srgan",
            headers={"api-key": key},
            files={"image": ("input.jpg", fb, mime)},
        )
        if not r.is_success: return None
        out_url = r.json().get("output_url", "")
        if not out_url: return None
        ir = await client.get(out_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _deepai_face(self, client: httpx.AsyncClient,
                            fb: bytes, mime: str) -> Optional[str]:
        key = self._settings.DEEPAI_API_KEY
        if not key: return None
        r = await client.post(
            "https://api.deepai.org/api/torch-srgan",
            headers={"api-key": key},
            files={"image": ("input.jpg", fb, mime)},
        )
        if not r.is_success: return None
        out_url = r.json().get("output_url", "")
        if not out_url: return None
        ir = await client.get(out_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    # ── Krea ──────────────────────────────────────────────────────────────────
    async def _krea_generate(self, client: httpx.AsyncClient,
                              prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.KREA_API_KEY
        if not key: return None
        body = {"prompt": prompt, "width": 1024, "height": 1024,
                "guidance": params.get("guidance", 7.5), "num_outputs": 1}
        r = await client.post(
            "https://api.krea.ai/v1/images/generate",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        data = r.json()
        url  = (data.get("images") or [{}])[0].get("url", "")
        if not url: return None
        ir = await client.get(url)
        ct = ir.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _krea_upscale(self, client: httpx.AsyncClient,
                             fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.KREA_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"image": f"data:{mime};base64,{b64}", "scale": params.get("scale", 4)}
        r = await client.post(
            "https://api.krea.ai/v1/images/upscale",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        data = r.json()
        url  = data.get("url", "")
        if not url: return None
        ir = await client.get(url)
        ct = ir.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _krea_restore(self, client: httpx.AsyncClient,
                             fb: bytes, mime: str, params: Dict) -> Optional[str]:
        return await self._krea_upscale(client, fb, mime, params)

    async def _krea_face(self, client: httpx.AsyncClient,
                          fb: bytes, mime: str, params: Dict) -> Optional[str]:
        key = self._settings.KREA_API_KEY
        if not key: return None
        b64  = base64.b64encode(fb).decode()
        body = {"image": f"data:{mime};base64,{b64}", "enhancement": "face", "scale": 2}
        r = await client.post(
            "https://api.krea.ai/v1/images/enhance",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        data = r.json()
        url  = data.get("url", "")
        if not url: return None
        ir = await client.get(url)
        ct = ir.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    # ── Gemini ────────────────────────────────────────────────────────────────
    async def _gemini_caption(self, client: httpx.AsyncClient,
                               fb: Optional[bytes], mime: str) -> Optional[str]:
        key = self._settings.GEMINI_API_KEY
        if not key: return None
        parts: list = [{"text": "Generate accurate, professional captions for this image. Return the text caption only."}]
        if fb:
            b64 = base64.b64encode(fb).decode()
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        body = {"contents": [{"parts": parts}]}
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={key}",
            headers={"Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        text = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return _text_to_data_url(text) if text else None

    # ── Groq ──────────────────────────────────────────────────────────────────
    async def _groq_caption(self, client: httpx.AsyncClient,
                             fb: Optional[bytes], mime: str) -> Optional[str]:
        key = self._settings.GROQ_API_KEY
        if not key or not fb: return None
        b64 = base64.b64encode(fb).decode()
        body = {
            "model": "llama-3.2-11b-vision-preview",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text",      "text": "Generate accurate captions for this image."},
            ]}],
            "max_tokens": 500,
        }
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    # ── Mistral ───────────────────────────────────────────────────────────────
    async def _mistral_caption(self, client: httpx.AsyncClient,
                                fb: Optional[bytes], mime: str) -> Optional[str]:
        key = self._settings.MISTRAL_API_KEY
        if not key or not fb: return None
        b64 = base64.b64encode(fb).decode()
        body = {
            "model": "pixtral-12b-2409",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": f"data:{mime};base64,{b64}"},
                {"type": "text",      "text": "Generate accurate captions for this image."},
            ]}],
        }
        r = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success: return None
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    # ── Cloudinary ────────────────────────────────────────────────────────────
    async def _cloudinary_enhance(self, client: httpx.AsyncClient,
                                   fb: bytes, mime: str, params: Dict) -> Optional[str]:
        cloud_id = self._settings.CLOUDINARY_CLOUD_ID
        preset   = self._settings.CLOUDINARY_UPLOAD_PRESET
        if not cloud_id: return None
        # Upload with transformations
        b64  = base64.b64encode(fb).decode()
        body = {
            "file":           f"data:{mime};base64,{b64}",
            "upload_preset":  preset,
            "transformation": "e_enhance,q_auto:best,f_auto",
        }
        r = await client.post(
            f"https://api.cloudinary.com/v1_1/{cloud_id}/image/upload",
            data=body,
        )
        if not r.is_success: return None
        url = r.json().get("secure_url", "")
        if not url: return None
        ir = await client.get(url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _cloudinary_basic(self, client: httpx.AsyncClient,
                                 fb: bytes, mime: str, params: Dict) -> Optional[str]:
        return await self._cloudinary_enhance(client, fb, mime, params)

    # ── Pexels ────────────────────────────────────────────────────────────────
    async def _pexels_image(self, client: httpx.AsyncClient, prompt: str) -> Optional[str]:
        key = self._settings.PEXELS_API_KEY
        if not key: return None
        r = await client.get(
            f"https://api.pexels.com/v1/search?query={_urlencode(prompt)}&per_page=1&size=large",
            headers={"Authorization": key},
        )
        if not r.is_success: return None
        photos = r.json().get("photos", [])
        if not photos: return None
        img_url = photos[0]["src"].get("original") or photos[0]["src"].get("large2x", "")
        ir = await client.get(img_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    async def _pexels_video(self, client: httpx.AsyncClient, prompt: str) -> Optional[str]:
        key = self._settings.PEXELS_API_KEY
        if not key: return None
        r = await client.get(
            f"https://api.pexels.com/videos/search?query={_urlencode(prompt)}&per_page=1&size=large",
            headers={"Authorization": key},
        )
        if not r.is_success: return None
        videos = r.json().get("videos", [])
        if not videos: return None
        files  = sorted(videos[0].get("video_files", []), key=lambda f: f.get("width", 0), reverse=True)
        return files[0]["link"] if files else None

    # ── Unsplash ──────────────────────────────────────────────────────────────
    async def _unsplash_image(self, client: httpx.AsyncClient, prompt: str) -> Optional[str]:
        key = self._settings.UNSPLASH_API_KEY
        if not key: return None
        r = await client.get(
            f"https://api.unsplash.com/search/photos?query={_urlencode(prompt)}&per_page=1&orientation=landscape",
            headers={"Authorization": f"Client-ID {key}"},
        )
        if not r.is_success: return None
        results = r.json().get("results", [])
        if not results: return None
        raw_url = f"{results[0]['urls']['raw']}&w={TARGET_W}&h={TARGET_H}&fit=crop&fm=jpg&q=95"
        ir = await client.get(raw_url)
        ct = ir.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"

    # ── OpenRouter ────────────────────────────────────────────────────────────
    async def _openrouter_text(self, client: httpx.AsyncClient,
                               prompt: str, params: Dict) -> Optional[str]:
        key = getattr(self._settings, "OPENROUTER_API_KEY", None)
        if not key:
            return None
        model = params.get("model", "openai/gpt-4o-mini")
        body = {
            "model":    model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": params.get("max_tokens", 1024),
        }
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization":  f"Bearer {key}",
                "Content-Type":   "application/json",
                "HTTP-Referer":   "https://luminorbit.com",
                "X-Title":        "Luminorbit",
            },
            json=body,
        )
        if not r.is_success:
            return None
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    async def _openrouter_generate(self, client: httpx.AsyncClient,
                                   prompt: str, params: Dict) -> Optional[str]:
        """OpenRouter image-gen via supported multimodal models."""
        key = getattr(self._settings, "OPENROUTER_API_KEY", None)
        if not key:
            return None
        model = params.get("model", "openai/dall-e-3")
        body = {
            "model":    model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 256,
        }
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "https://luminorbit.com",
                "X-Title":       "Luminorbit",
            },
            json=body,
        )
        if not r.is_success:
            return None
        data  = r.json()
        # Some image-capable models return an image_url in content
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    if url:
                        ir = await client.get(url)
                        if ir.is_success:
                            ct = ir.headers.get("content-type", "image/png").split(";")[0]
                            return f"data:{ct};base64,{base64.b64encode(ir.content).decode()}"
        # Fallback: treat text content as prompt, route through Pollinations
        if isinstance(content, str) and content:
            return await self._pollinations_generate(client, content or prompt, params)
        return None

    # ── Text helpers (Groq / Gemini / Mistral / Together) ─────────────────────
    async def _groq_text(self, client: httpx.AsyncClient,
                         prompt: str, params: Dict) -> Optional[str]:
        key = getattr(self._settings, "GROQ_API_KEY", None)
        if not key:
            return None
        model = params.get("model", "llama3-8b-8192")
        body  = {
            "model":    model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": params.get("max_tokens", 1024),
        }
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success:
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    async def _gemini_text(self, client: httpx.AsyncClient,
                           prompt: str, params: Dict) -> Optional[str]:
        key = getattr(self._settings, "GEMINI_API_KEY", None)
        if not key:
            return None
        model = params.get("model", "gemini-1.5-flash")
        body  = {"contents": [{"parts": [{"text": prompt}]}]}
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            headers={"Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success:
            return None
        cands = r.json().get("candidates", [{}])
        text  = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return _text_to_data_url(text) if text else None

    async def _mistral_text(self, client: httpx.AsyncClient,
                            prompt: str, params: Dict) -> Optional[str]:
        key = getattr(self._settings, "MISTRAL_API_KEY", None)
        if not key:
            return None
        model = params.get("model", "mistral-small-latest")
        body  = {
            "model":    model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": params.get("max_tokens", 1024),
        }
        r = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success:
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    async def _together_text(self, client: httpx.AsyncClient,
                             prompt: str, params: Dict) -> Optional[str]:
        key = self._settings.TOGETHER_API_KEY
        if not key:
            return None
        model = params.get("model", "meta-llama/Llama-3-8b-chat-hf")
        body  = {
            "model":    model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": params.get("max_tokens", 1024),
        }
        r = await client.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        if not r.is_success:
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        return _text_to_data_url(text) if text else None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
# §10  PROVIDER ROUTER (wraps PipelineEngine for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

class ProviderRouter:
    """Exposes provider stats and reset endpoints used by existing routes."""

    def __init__(self, scorer: ProviderScorer):
        self._scorer = scorer

    async def provider_stats(self) -> Dict:
        scores = await self._scorer.dump()
        all_providers = sorted({
            p
            for providers in CAPABILITY_PROVIDERS.values()
            for p in providers
        })
        return {
            "providers": {
                p: {
                    "score":  scores.get(p, 1.0),
                    "status": "active" if scores.get(p, 1.0) > 0.3 else "degraded",
                }
                for p in all_providers
            }
        }

    async def reset_provider(self, provider: str):
        async with self._scorer._lock:
            self._scorer._scores[provider] = 1.0

    @property
    def _scorer(self) -> ProviderScorer:
        return self.__scorer

    @_scorer.setter
    def _scorer(self, v):
        self.__scorer = v


# ══════════════════════════════════════════════════════════════════════════════
# §11  FACTORY FUNCTION
#      Call this from luminorbit_backend.py to get the upgraded pipeline.
# ══════════════════════════════════════════════════════════════════════════════

def build_pipeline_engine(settings, logger_inst) -> Tuple[PipelineEngine, ProviderRouter]:
    """
    Factory — creates and returns the PipelineEngine and ProviderRouter.

    Usage in luminorbit_backend.py:
        from luminorbit_pipelines import build_pipeline_engine
        _pipeline, _router = build_pipeline_engine(_settings, logger)
    """
    scorer  = ProviderScorer()
    engine  = PipelineEngine(settings, logger_inst, scorer)
    router  = ProviderRouter(scorer)
    logger_inst.info(
        "[pipelines] v25 engine initialized | tools=%d pipelines=15 providers=%d",
        len(TOOL_PIPELINE_MAP),
        len(CAPABILITY_PROVIDERS),
    )
    return engine, router


# ══════════════════════════════════════════════════════════════════════════════
# §12  PRIVATE UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _urlencode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def _text_to_data_url(text: str) -> str:
    """Encodes a text string as a data: URL for uniform output handling."""
    encoded = base64.b64encode(text.encode("utf-8")).decode()
    return f"data:text/plain;base64,{encoded}"


def _build_rich_prompt(tool: str, params: Dict) -> str:
    _PROMPTS = {
        "Background Remover":     "Remove background completely, isolate subject with pixel-perfect edges, transparent PNG output",
        "Background Changer":     "Replace background with professional studio backdrop, cinematic lighting, 4K ultra HD",
        "Object Remover":         "Remove object seamlessly using AI inpainting, reconstruct background naturally, no artifacts",
        "Object Remover Pro":     "Professional AI object removal, seamless fill matching surrounding texture and lighting",
        "Watermark Remover":      "Remove watermark completely, restore original content underneath, 4K professional output",
        "Sky Replacer":           "Replace sky with dramatic golden hour sunset, volumetric clouds, cinematic HDR, 4K",
        "Face Retouch":           "Professional face retouching: smooth skin, reduce blemishes, enhance eyes, natural result",
        "Portrait Pro":           "Studio portrait enhancement: perfect skin, sharp eyes, professional lighting, magazine quality",
        "Image Enhancer":         "AI image enhancement: ultra-sharp details, perfect exposure, vivid colors, 4K studio quality",
        "Image Enhancer Plus":    "Advanced AI enhancement: maximum detail recovery, HDR tone mapping, professional color grade",
        "HDR Master":             "Full HDR processing: expand dynamic range, recover highlights and shadows, cinematic tone mapping",
        "Noise Reducer":          "AI noise reduction: remove grain completely, preserve fine detail, clean professional output",
        "Detail Enhancer":        "Ultra-sharp detail enhancement: reveal micro-textures, professional sharpening, 4K clarity",
        "Image UpScaler":         "AI super-resolution 4K upscaling: quadruple resolution, add realistic details, ultra-sharp",
        "AI 4K Image Upscaler":   "Real-ESRGAN 4K upscaling to 3840x2160, maximum quality, professional detail restoration",
        "Photo Restorer":         "Restore old photo: remove damage and scratches, enhance colors, modern professional quality",
        "Style Transfer":         "Artistic style transfer: apply painterly style while preserving content, high quality rendering",
        "Cartoonizer":            "Cartoon cel-shading: bold outlines, flat vibrant colors, anime-style rendering, 4K",
        "Sketch Maker":           "Pencil sketch effect: detailed line art, realistic pencil texture, professional rendering",
        "Vintage Maker":          "Vintage film effect: faded colors, film grain, light leaks, authentic analog aesthetic",
        "Color Grader":           "Professional cinematic color grade: teal-orange LUT, film emulation, Hollywood look",
        "Slow-Mo Magic":          "AI frame interpolation: ultra-smooth slow motion 240fps, temporal super-resolution, 4K",
        "Cinematic Pulse":        "Cinematic color grade: film emulation, anamorphic lens flare, Hollywood grade, 4K",
        "VHS Nostalgia":          "VHS tape effect: scan lines, color bleeding, retro 80s video aesthetic, authentic",
        "Neon Pulse":             "Neon glow effect: vibrant colors, cyber aesthetic, professional grade enhancement",
        "Glitch Pop":             "Digital glitch effect: RGB split, scan lines, digital distortion art, professional",
        "Retro Reel":             "Retro film effect: grain, color shifts, vintage film aesthetic, professional output",
        "AI Image Generator":     "Ultra-detailed professional studio photograph, photorealistic, perfect lighting, 4K HDR",
        "AI Video Generator":     "Cinematic professional video, smooth motion, 4K Ultra HD, professional grade production",
        "Photo to Video Creator": "Animate photo with natural parallax motion, cinematic 4K, smooth temporal consistency",
    }
    base = _PROMPTS.get(tool, f"Professional {tool} processing: ultra high quality, 4K studio output, photorealistic")
    extra = params.get("style", "") or params.get("effect", "")
    return f"{base}{', ' + extra if extra else ''}"

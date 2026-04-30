"""Google Gemini client — mannequin generation + sketch overlay."""

import io
import logging
import time
from pathlib import Path

from PIL import Image
from google import genai
from google.genai import types

from prompts.mannequin_library.loader import assemble_prompt as assemble_frozen_prompt
from app.cost_logger import log_api_call, estimate_gemini_cost

MODEL = "gemini-2.5-flash-image"

log = logging.getLogger(__name__)

# Test result cache
_test_cache: dict[str, tuple[float, str, str]] = {}
_CACHE_TTL = 300

# Aspect ratios Gemini accepts (map from w/h ratio to string)
_ASPECT_RATIOS = {
    (2, 3): "2:3",   # 1024x1536 portrait
    (3, 2): "3:2",   # 1536x1024 landscape
    (3, 4): "3:4",
    (4, 3): "4:3",
    (9, 16): "9:16",
    (16, 9): "16:9",
    (1, 1): "1:1",
}


def _read_image_dimensions(path: Path) -> tuple[int, int] | None:
    """Read image width and height without loading full image."""
    try:
        with Image.open(path) as img:
            return img.size  # (width, height)
    except Exception:
        return None


def _dimensions_to_aspect_ratio(w: int, h: int) -> str | None:
    """Convert pixel dimensions to a Gemini-supported aspect ratio string."""
    from math import gcd
    g = gcd(w, h)
    ratio = (w // g, h // g)
    # Check exact match first
    if ratio in _ASPECT_RATIOS:
        return _ASPECT_RATIOS[ratio]
    # Try common simplifications
    for (rw, rh), label in _ASPECT_RATIOS.items():
        if abs(w / h - rw / rh) < 0.02:
            return label
    return None


def _validate_output_dimensions(
    output_path: Path,
    target_w: int,
    target_h: int,
) -> tuple[bool, str]:
    """Check output image matches target dimensions. Returns (ok, message)."""
    dims = _read_image_dimensions(output_path)
    if dims is None:
        return False, "Could not read output dimensions"
    out_w, out_h = dims
    if out_w == target_w and out_h == target_h:
        return True, f"Dimensions match: {out_w}x{out_h}"
    # Check aspect ratio match even if pixel dims differ
    target_ratio = target_w / target_h
    out_ratio = out_w / out_h
    if abs(target_ratio - out_ratio) < 0.05:
        return True, f"Aspect ratio matches ({out_w}x{out_h} vs target {target_w}x{target_h})"
    return False, f"MISMATCH: output {out_w}x{out_h} vs target {target_w}x{target_h}"


def test_connection(api_key: str, bypass_cache: bool = False) -> tuple[str, str]:
    """Validate API key. Returns (status, message)."""
    cache_key = api_key[:8]
    now = time.time()

    if not bypass_cache and cache_key in _test_cache:
        ts, cached_status, cached_msg = _test_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return cached_status, f"{cached_msg} (cached)"

    try:
        client = genai.Client(api_key=api_key)
        client.models.generate_content(
            model=MODEL,
            contents="Generate a 1x1 pixel white square.",
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"],
            ),
        )
        result = ("ok", f"Connected (image-capable). Model: {MODEL}")
    except Exception as e:
        err = str(e)
        err_lower = err.lower()
        if "401" in err or "api_key_invalid" in err_lower or "api key not valid" in err_lower:
            result = ("invalid", "Invalid API key (401).")
        elif "403" in err or "permission" in err_lower:
            result = ("invalid", f"Permission denied (403): {err[:80]}")
        elif "429" in err or "rate" in err_lower or "quota" in err_lower or "resource_exhausted" in err_lower:
            result = ("rate_limited", "Rate limited — key is valid but throttled.")
        elif "404" in err or "not found" in err_lower:
            result = ("warning", f"Model {MODEL} not available on this key.")
        elif "timeout" in err_lower or "connect" in err_lower:
            result = ("error", f"Network error: {err[:100]}")
        else:
            result = ("error", f"Connection failed: {err[:120]}")

    _test_cache[cache_key] = (now, result[0], result[1])
    return result


def generate_mannequin(
    api_key: str,
    pose_metadata: dict,
    archetype_info: dict,
    output_path: Path,
    reference_images: list[Path] | None = None,
    use_strong_prefix: bool = False,
) -> dict:
    """Generate a single mannequin base template using Gemini."""
    client = genai.Client(api_key=api_key)

    head_count = archetype_info.get("head_count", 8)
    prompt_number = pose_metadata.get("number", 1)

    prompt = assemble_frozen_prompt(prompt_number, head_count, use_strong_prefix)
    if prompt is None:
        return {"success": False, "error": f"No frozen prompt for #{prompt_number}"}

    contents = []
    if reference_images:
        for ref_path in reference_images:
            if ref_path.exists():
                contents.append(types.Part.from_bytes(
                    data=ref_path.read_bytes(), mime_type="image/png"))
    contents.append(types.Part.from_text(text=prompt))

    try:
        response = client.models.generate_content(
            model=MODEL, contents=contents,
            config=types.GenerateContentConfig(response_modalities=["image", "text"]),
        )
        image_saved = False
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(part.inline_data.data)
                image_saved = True
                break
        if not image_saved:
            text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
            error_msg = " ".join(text_parts) if text_parts else "No image in response"
            log_api_call(provider="google", model=MODEL, operation="mannequin_generation",
                         images_generated=0, estimated_cost_usd=0,
                         pose_id=pose_metadata["filename"], status=f"error: {error_msg}")
            return {"success": False, "error": error_msg}

        cost = estimate_gemini_cost(1, batch=False)
        log_api_call(provider="google", model=MODEL, operation="mannequin_generation",
                     images_generated=1, estimated_cost_usd=cost,
                     pose_id=pose_metadata["filename"], status="success")
        return {"success": True, "output_path": str(output_path), "cost": cost}

    except Exception as e:
        err_str = str(e)
        is_content_policy = any(kw in err_str.lower() for kw in
                                ["safety", "content_policy", "blocked", "harmful"])
        log_api_call(provider="google", model=MODEL, operation="mannequin_generation",
                     images_generated=0, estimated_cost_usd=0,
                     pose_id=pose_metadata["filename"], status=f"error: {err_str[:200]}")
        return {"success": False, "error": err_str, "content_policy": is_content_policy}


def generate_sketch(
    api_key: str,
    prompt_text: str,
    mannequin_image_path: Path,
    character_sheet_path: Path,
    output_path: Path,
    character_id: str = "",
    pose_id: str = "",
) -> dict:
    """Generate a character sketch overlay using Gemini.

    Now restored as the default sketch provider. Aspect ratio enforcement
    via prompt text (ImageGenerationConfig not available in current SDK).
    """
    client = genai.Client(api_key=api_key)

    # Read mannequin dimensions for aspect ratio lock
    target_w, target_h = 1024, 1536  # default portrait
    aspect_ratio_str = "2:3"
    if mannequin_image_path.exists():
        dims = _read_image_dimensions(mannequin_image_path)
        if dims:
            target_w, target_h = dims
            ar = _dimensions_to_aspect_ratio(target_w, target_h)
            if ar:
                aspect_ratio_str = ar

    # Build content: mannequin FIRST (primary spatial reference), then character sheet
    contents = []
    if mannequin_image_path.exists():
        contents.append(types.Part.from_bytes(
            data=mannequin_image_path.read_bytes(), mime_type="image/png"))
    if character_sheet_path.exists():
        suffix = character_sheet_path.suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp"}.get(suffix.lstrip("."), "image/png")
        contents.append(types.Part.from_bytes(
            data=character_sheet_path.read_bytes(), mime_type=mime))

    # Prepend aspect ratio and dimension lock to the prompt
    dimension_lock = (
        f"\n\nOUTPUT DIMENSIONS: Match the attached mannequin reference exactly.\n"
        f"Aspect ratio: {aspect_ratio_str} ({target_w}x{target_h} pixels).\n"
        f"The character must fill the frame the same way the mannequin fills its frame — "
        f"head crown near the top edge, feet near the bottom edge, no excessive white space.\n"
    )
    full_prompt = prompt_text + dimension_lock
    contents.append(types.Part.from_text(text=full_prompt))

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"],
                # LEGACY: ImageGenerationConfig removed — attribute does not exist
                # in the installed google-genai SDK version. Aspect ratio is not
                # enforced in this legacy path.
            ),
        )

        image_saved = False
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(part.inline_data.data)
                image_saved = True
                break

        if not image_saved:
            text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
            error_msg = " ".join(text_parts) if text_parts else "No image in response"
            log_api_call(provider="google", model=MODEL, operation="sketch_generation",
                         images_generated=0, estimated_cost_usd=0,
                         character_id=character_id, pose_id=pose_id,
                         status=f"error: {error_msg}")
            return {"success": False, "error": error_msg}

        # Validate output dimensions
        dim_ok, dim_msg = _validate_output_dimensions(output_path, target_w, target_h)
        if not dim_ok:
            log.warning("Sketch dimension mismatch for %s: %s", pose_id, dim_msg)

        cost = estimate_gemini_cost(1, batch=False)
        log_api_call(provider="google", model=MODEL, operation="sketch_generation",
                     images_generated=1, estimated_cost_usd=cost,
                     character_id=character_id, pose_id=pose_id, status="success")
        return {
            "success": True, "output_path": str(output_path), "cost": cost,
            "dimensions_match": dim_ok, "dimensions_msg": dim_msg,
        }

    except Exception as e:
        err_str = str(e)
        log_api_call(provider="google", model=MODEL, operation="sketch_generation",
                     images_generated=0, estimated_cost_usd=0,
                     character_id=character_id, pose_id=pose_id,
                     status=f"error: {err_str[:200]}")
        return {"success": False, "error": err_str}

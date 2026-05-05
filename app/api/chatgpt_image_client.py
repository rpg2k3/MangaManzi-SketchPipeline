"""OpenAI gpt-image-1 wrappers for the Chat_GPT pipeline.

Three thin entry points:
- generate_base(prompt, orientation)               — text-to-image (images.generate)
- sketch_over_base(base, character, orientation)   — image edit with two refs
- generate_freeform(prompt, orientation, ref)      — freeform sketch, optional ref

All return raw PNG bytes plus a cost estimate. The UI layer is responsible
for displaying and saving — this module never touches disk.
"""

import base64
import os
import sys
from pathlib import Path

import openai

from app.cost_logger import log_api_call
from app import settings_manager

MODEL = "gpt-image-1"

# Sketch prompts are built in three priority sections, highest first:
#   1) Character sheet (Image 2) — absolute source of truth.
#   2) Pose reference (Image 1).
#   3) Style and quality tags — explicitly subordinate.
# Every prompt ends with the conflict-resolution line so gpt-image-1
# falls back to the character sheet whenever style instructions
# disagree with what's drawn in the reference.

# DRAFT mode — keep the blue construction lines visible under the inked
# character so the artist can verify pose alignment. {orientation} is the
# only template token.
SKETCH_OVER_BASE_INSTRUCTION = """
The character design in Image 2 is the absolute source of truth. Reproduce every detail exactly:
- Face structure, eye shape, expression style
- Hair texture, volume, and style precisely as drawn
- Every outfit element: garments, accessories, straps, belts, boots, gloves, stockings
- Body proportions as shown in the reference
- Any unique features: ears, tail, markings
Do not invent, simplify, or substitute any character detail. If it is in the reference, it must appear in the output.

Image 1 defines the pose only.
Match every limb position, angle, and weight distribution exactly as shown.
Keep the blue construction lines visible underneath as a transparent guide layer showing through the black ink character.

Apply these style qualities without overriding the character design:
- Professional manga artist treatment — clean confident black ink manga lineart
- Professional line weight variation — thicker on silhouette edges, thinner on interior detail
- A4 {orientation} format, print ready
- White background only

If style instructions conflict with the character sheet, always follow the character sheet.
""".strip()

# RENDER mode — finished illustration, no construction lines retained.
SKETCH_OVER_BASE_RENDER_INSTRUCTION = """
The character design in Image 2 is the absolute source of truth. Reproduce every detail exactly:
- Face structure, eye shape, expression style
- Hair texture, volume, and style precisely as drawn
- Every outfit element: garments, accessories, straps, belts, boots, gloves, stockings
- Body proportions as shown in the reference
- Any unique features: ears, tail, markings
Do not invent, simplify, or substitute any character detail. If it is in the reference, it must appear in the output.

Image 1 defines the pose only.
Match every limb position, angle, and weight distribution exactly as shown.
Use the blue figure as a pose reference only — do not reproduce the blue lines in the output.

Apply these style qualities without overriding the character design:
- Professional manga artist treatment — finished illustration, no construction lines, no wireframe, no blue guide lines
- Polished ink linework with confident line weight variation
- Thick silhouette lines, fine interior detail lines
- Expressive face matching the character's design
- A4 {orientation} format, print ready
- Clean white background

If style instructions conflict with the character sheet, always follow the character sheet.
""".strip()


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _decode(response) -> bytes:
    b64 = response.data[0].b64_json
    if b64:
        return base64.b64decode(b64)
    url = getattr(response.data[0], "url", None)
    if url:
        import urllib.request
        return urllib.request.urlopen(url).read()
    raise RuntimeError("OpenAI returned no image data")


def _estimate_cost(quality: str) -> float:
    return settings_manager.OPENAI_PRICING.get(quality, 0.042)


def _auto_orientation_from_image(path: Path) -> str:
    """Read an image's pixel dimensions; return 'landscape' or 'portrait'.
    Square or unreadable defaults to 'portrait' per spec."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
        return "landscape" if w > h else "portrait"
    except Exception:
        return "portrait"


def _log_sketch_inputs(base_path: Path, character_path: Path,
                       size: str, quality: str) -> None:
    """Print the exact pixel dimensions, file sizes and API params being
    sent to gpt-image-1. Lets us verify nothing is downsampling input
    images before they hit the API. Output goes to stdout (terminal) so
    it survives even when the Qt log panel is not visible."""
    try:
        from PIL import Image
        for idx, p in ((1, base_path), (2, character_path)):
            try:
                with Image.open(p) as img:
                    w, h = img.size
                kb = os.path.getsize(p) / 1024.0
                print(f"[Sketch] Input image {idx} size: {w}x{h} px, "
                      f"{kb:.1f} KB — {p}", flush=True)
            except Exception as e:
                print(f"[Sketch] Input image {idx} probe failed for {p}: {e}",
                      flush=True)
    except Exception as e:
        print(f"[Sketch] PIL unavailable for input probe: {e}", flush=True)
    print(f"[Sketch] API params: model={MODEL} quality={quality} size={size}",
          flush=True)


def resolve_orientation(orientation: str, base_image_path: Path | None = None) -> str:
    """Resolve 'auto' to 'landscape' or 'portrait' by reading the base image.
    'auto' without a base image defaults to 'portrait'."""
    if orientation == "auto":
        if base_image_path is not None:
            return _auto_orientation_from_image(Path(base_image_path))
        return "portrait"
    return orientation if orientation in ("landscape", "portrait") else "portrait"


def size_for(orientation: str) -> str:
    """Map 'landscape'/'portrait' to OpenAI gpt-image-1's nearest A4-ratio
    supported size. (gpt-image-1 supports 1024x1024, 1024x1536, 1536x1024.)"""
    return "1536x1024" if orientation == "landscape" else "1024x1536"


# ─────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────

def generate_base(api_key: str, prompt: str, orientation: str = "portrait",
                  quality: str = "high") -> dict:
    """Text-to-image via images.generate."""
    resolved = resolve_orientation(orientation)
    size = size_for(resolved)
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.images.generate(
            model=MODEL, prompt=prompt, size=size, quality=quality, n=1,
        )
        img_bytes = _decode(response)
        cost = _estimate_cost(quality)
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_base_generate",
            images_generated=1, estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "image_bytes": img_bytes, "size": size,
                "orientation": resolved, "cost": cost, "error": ""}
    except openai.AuthenticationError:
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": "Invalid OpenAI API key (401)."}
    except openai.APIStatusError as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_base_generate",
            images_generated=0, estimated_cost_usd=0, status=f"error: {e.status_code}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": f"API error {e.status_code}: {e.message}"}
    except Exception as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_base_generate",
            images_generated=0, estimated_cost_usd=0, status=f"error: {str(e)[:100]}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0, "error": str(e)}


def sketch_over_base(api_key: str, base_image_path: Path, character_image_path: Path,
                     orientation: str = "auto", quality: str = "high",
                     instruction: str | None = None) -> dict:
    """Two-image overlay via images.edit. Auto orientation reads the base file.

    If `instruction` is provided it is sent verbatim to gpt-image-1; the caller
    is responsible for any orientation interpolation. When None (default) the
    legacy SKETCH_OVER_BASE_INSTRUCTION is used.
    """
    resolved = resolve_orientation(orientation, base_image_path)
    size = size_for(resolved)
    if instruction is None:
        instruction = SKETCH_OVER_BASE_INSTRUCTION.format(orientation=resolved)
    _log_sketch_inputs(base_image_path, character_image_path, size, quality)
    image_files = []
    try:
        client = openai.OpenAI(api_key=api_key)
        # Open both reference images in binary mode and forward the raw
        # file bytes to gpt-image-1. No resize, no recompression — the
        # SDK reads the files as-is and uploads them via multipart form.
        image_files.append(open(base_image_path, "rb"))
        image_files.append(open(character_image_path, "rb"))
        response = client.images.edit(
            model=MODEL, image=image_files, prompt=instruction,
            size=size, quality=quality, n=1,
        )
        img_bytes = _decode(response)
        cost = _estimate_cost(quality)
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=1, estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "image_bytes": img_bytes, "size": size,
                "orientation": resolved, "cost": cost, "error": ""}
    except openai.AuthenticationError:
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": "Invalid OpenAI API key (401)."}
    except openai.APIStatusError as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=0, estimated_cost_usd=0, status=f"error: {e.status_code}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": f"API error {e.status_code}: {e.message}"}
    except Exception as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=0, estimated_cost_usd=0, status=f"error: {str(e)[:100]}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0, "error": str(e)}
    finally:
        for f in image_files:
            try:
                f.close()
            except Exception:
                pass


def generate_freeform(api_key: str, prompt: str, orientation: str = "portrait",
                      character_image_path: Path | None = None,
                      quality: str = "high") -> dict:
    """Freeform line-art sketch generation.

    If `character_image_path` is provided, calls images.edit with the ref so
    gpt-image-1 can match the character design. Otherwise plain text-to-image.
    """
    resolved = resolve_orientation(orientation)  # no base, ignore "auto"
    size = size_for(resolved)
    image_files = []
    try:
        client = openai.OpenAI(api_key=api_key)
        if character_image_path and Path(character_image_path).exists():
            image_files.append(open(character_image_path, "rb"))
            response = client.images.edit(
                model=MODEL, image=image_files, prompt=prompt,
                size=size, quality=quality, n=1,
            )
        else:
            response = client.images.generate(
                model=MODEL, prompt=prompt, size=size, quality=quality, n=1,
            )
        img_bytes = _decode(response)
        cost = _estimate_cost(quality)
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_freeform",
            images_generated=1, estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "image_bytes": img_bytes, "size": size,
                "orientation": resolved, "cost": cost, "error": ""}
    except openai.AuthenticationError:
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": "Invalid OpenAI API key (401)."}
    except openai.APIStatusError as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_freeform",
            images_generated=0, estimated_cost_usd=0, status=f"error: {e.status_code}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0,
                "error": f"API error {e.status_code}: {e.message}"}
    except Exception as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_freeform",
            images_generated=0, estimated_cost_usd=0, status=f"error: {str(e)[:100]}",
        )
        return {"success": False, "image_bytes": b"", "size": size,
                "orientation": resolved, "cost": 0.0, "error": str(e)}
    finally:
        for f in image_files:
            try:
                f.close()
            except Exception:
                pass

"""OpenAI gpt-image-1 wrappers for the Chat_GPT pipeline.

Three thin entry points:
- generate_base(prompt, orientation)               — text-to-image (images.generate)
- sketch_over_base(base, character, orientation)   — image edit with two refs
- generate_freeform(prompt, orientation, ref)      — freeform sketch, optional ref

All return raw PNG bytes plus a cost estimate. The UI layer is responsible
for displaying and saving — this module never touches disk.
"""

import base64
from pathlib import Path

import openai

from app.cost_logger import log_api_call
from app import settings_manager

MODEL = "gpt-image-1"

# The substantive line-art-over-blue instruction is preserved verbatim;
# only the orientation token at the end is parametrised so the same
# instruction works for portrait or landscape generation.
SKETCH_OVER_BASE_INSTRUCTION = """
Draw the character from the second reference image over the blue construction base figure shown in the first image.

CRITICAL RULES:
- Match the pose of the blue base figure EXACTLY — every joint angle, weight shift, and limb position must align with the underlying construction.
- Keep the light blue construction lines, wireframe contour bands, joint ovals, head-height grid, and red line of action visible underneath the new line art.
- Render the character as line art only — clean black ink lines, varied line weight. No color fill, no shading, no rendering.
- Preserve the character's design features (hair, face, clothing silhouette, accessories, body proportions) from the second reference image.
- Pure white background, A4 {orientation} orientation, print-friendly at maximum resolution.
- Do not redraw or alter the blue base figure — overlay only.
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
    image_files = []
    try:
        client = openai.OpenAI(api_key=api_key)
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

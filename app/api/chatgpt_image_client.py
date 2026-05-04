"""OpenAI gpt-image-1 wrappers for the Chat_GPT pipeline.

Two thin entry points:
- generate_base(prompt, orientation) → text-to-image (images.generate)
- sketch_over_base(base_path, character_path) → image edit with two refs

Both return raw PNG bytes plus a cost estimate. The UI layer is responsible
for displaying and saving — this module never touches disk.
"""

import base64
from pathlib import Path

import openai

from app.cost_logger import log_api_call
from app import settings_manager

MODEL = "gpt-image-1"

SKETCH_OVER_BASE_INSTRUCTION = """
Draw the character from the second reference image over the blue construction base figure shown in the first image.

CRITICAL RULES:
- Match the pose of the blue base figure EXACTLY — every joint angle, weight shift, and limb position must align with the underlying construction.
- Keep the light blue construction lines, wireframe contour bands, joint ovals, head-height grid, and red line of action visible underneath the new line art.
- Render the character as line art only — clean black ink lines, varied line weight. No color fill, no shading, no rendering.
- Preserve the character's design features (hair, face, clothing silhouette, accessories, body proportions) from the second reference image.
- Pure white background, A4 landscape orientation, print-friendly at maximum resolution.
- Do not redraw or alter the blue base figure — overlay only.
""".strip()


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


def generate_base(api_key: str, prompt: str, orientation: str = "portrait",
                  quality: str = "high") -> dict:
    """Text-to-image via images.generate. Returns {"success", "image_bytes", "size", "cost", "error"}."""
    size = "1536x1024" if orientation == "landscape" else "1024x1536"
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
                "cost": cost, "error": ""}
    except openai.AuthenticationError:
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": "Invalid OpenAI API key (401)."}
    except openai.APIStatusError as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_base_generate",
            images_generated=0, estimated_cost_usd=0, status=f"error: {e.status_code}",
        )
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": f"API error {e.status_code}: {e.message}"}
    except Exception as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_base_generate",
            images_generated=0, estimated_cost_usd=0, status=f"error: {str(e)[:100]}",
        )
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": str(e)}


def sketch_over_base(api_key: str, base_image_path: Path, character_image_path: Path,
                     quality: str = "high") -> dict:
    """Two-image overlay via images.edit. Returns {"success", "image_bytes", "size", "cost", "error"}."""
    size = "1536x1024"  # A4 landscape — print friendly per spec
    image_files = []
    try:
        client = openai.OpenAI(api_key=api_key)
        image_files.append(open(base_image_path, "rb"))
        image_files.append(open(character_image_path, "rb"))
        response = client.images.edit(
            model=MODEL, image=image_files,
            prompt=SKETCH_OVER_BASE_INSTRUCTION,
            size=size, quality=quality, n=1,
        )
        img_bytes = _decode(response)
        cost = _estimate_cost(quality)
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=1, estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "image_bytes": img_bytes, "size": size,
                "cost": cost, "error": ""}
    except openai.AuthenticationError:
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": "Invalid OpenAI API key (401)."}
    except openai.APIStatusError as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=0, estimated_cost_usd=0, status=f"error: {e.status_code}",
        )
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": f"API error {e.status_code}: {e.message}"}
    except Exception as e:
        log_api_call(
            provider="openai", model=MODEL, operation="chatgpt_sketch_over_base",
            images_generated=0, estimated_cost_usd=0, status=f"error: {str(e)[:100]}",
        )
        return {"success": False, "image_bytes": b"", "size": size, "cost": 0.0,
                "error": str(e)}
    finally:
        for f in image_files:
            try:
                f.close()
            except Exception:
                pass

"""OpenAI client — image generation via gpt-image-1 (mannequin bases + sketch overlays)."""

import base64
import time
from pathlib import Path

import openai
from PIL import Image

from prompts.mannequin_library.loader import assemble_prompt as assemble_frozen_prompt
from app.cost_logger import log_api_call

MODEL = "gpt-image-1"

# Test result cache
_test_cache: dict[str, tuple[float, str, str]] = {}
_CACHE_TTL = 300


def test_connection(api_key: str, bypass_cache: bool = False) -> tuple[str, str]:
    """Validate API key. Returns (status, message)."""
    cache_key = api_key[:8]
    now = time.time()

    if not bypass_cache and cache_key in _test_cache:
        ts, cached_status, cached_msg = _test_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return cached_status, f"{cached_msg} (cached)"

    try:
        client = openai.OpenAI(api_key=api_key)
        # Minimal validation — list models to confirm key works
        client.models.list()
        result = ("ok", f"Connected. Model: {MODEL}")
    except openai.AuthenticationError:
        result = ("invalid", "Invalid API key (401).")
    except openai.PermissionDeniedError:
        result = ("invalid", "Permission denied (403).")
    except openai.RateLimitError:
        result = ("rate_limited",
                  "Rate limited — key is valid but throttled. "
                  "Will likely work for production image calls.")
    except Exception as e:
        err = str(e).lower()
        if "timeout" in err or "connect" in err:
            result = ("error", f"Network error: {str(e)[:100]}")
        else:
            result = ("error", f"Connection failed: {str(e)[:100]}")

    _test_cache[cache_key] = (now, result[0], result[1])
    return result


def generate_mannequin(
    api_key: str,
    pose_metadata: dict,
    archetype_info: dict,
    output_path: Path,
    reference_images: list[Path] | None = None,
    use_strong_prefix: bool = False,
    quality: str = "medium",
    prompt_override: str | None = None,
) -> dict:
    """Generate a single mannequin base template using OpenAI gpt-image-1.

    reference_images: list of Paths. For dual-reference mode, pass [csp_ref, gpt_ref].
    Both are attached to the images.edit call as a list — CSP first (anatomy), GPT second (style).
    """
    client = openai.OpenAI(api_key=api_key)

    if prompt_override:
        prompt = prompt_override
    else:
        head_count = archetype_info.get("head_count", 8)
        prompt_number = pose_metadata.get("number", 1)
        prompt = assemble_frozen_prompt(prompt_number, head_count, use_strong_prefix)
        if prompt is None:
            return {"success": False, "error": f"No frozen prompt for #{prompt_number}"}

    orientation = pose_metadata.get("orientation", "portrait")
    size = "1536x1024" if orientation == "landscape" else "1024x1536"

    max_retries = 4
    backoff_times = [5, 10, 20, 40]

    for attempt in range(max_retries):
        image_files = []
        try:
            if reference_images:
                for ref_path in reference_images:
                    if ref_path and Path(ref_path).exists():
                        image_files.append(open(ref_path, "rb"))

            response = client.images.edit(
                model=MODEL,
                image=image_files if image_files else None,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )

            for f in image_files:
                f.close()

            b64 = response.data[0].b64_json
            if not b64:
                url = getattr(response.data[0], "url", None)
                if url:
                    import urllib.request
                    img_data = urllib.request.urlopen(url).read()
                else:
                    return {"success": False, "error": "No image data in response"}
            else:
                img_data = base64.b64decode(b64)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_data)

            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
            total_tokens = input_tokens + output_tokens
            from app.settings_manager import OPENAI_PRICING
            cost = total_tokens * 0.000004 if total_tokens > 0 else OPENAI_PRICING.get(quality, 0.042)

            log_api_call(
                provider="openai", model=MODEL, operation="mannequin_generation",
                input_tokens=input_tokens, output_tokens=output_tokens,
                images_generated=1, estimated_cost_usd=cost,
                pose_id=pose_metadata["filename"], status="success",
            )
            return {
                "success": True, "output_path": str(output_path),
                "cost": cost, "prefix_used": "strong" if use_strong_prefix else "standard",
            }

        except openai.RateLimitError as e:
            for f in image_files:
                f.close()
            if attempt < max_retries - 1:
                wait = backoff_times[attempt]
                time.sleep(wait)
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="mannequin_generation",
                    images_generated=0, estimated_cost_usd=0,
                    pose_id=pose_metadata["filename"],
                    status=f"error: rate_limit after {max_retries} retries",
                )
                return {"success": False, "error": f"Rate limit after {max_retries} retries: {e}"}

        except openai.APIStatusError as e:
            for f in image_files:
                f.close()
            err_str = str(e).lower()

            # Content policy detection
            if e.status_code == 400 and any(kw in err_str for kw in
                    ["content_policy", "safety", "content policy"]):
                log_api_call(
                    provider="openai", model=MODEL, operation="mannequin_generation",
                    images_generated=0, estimated_cost_usd=0,
                    pose_id=pose_metadata["filename"],
                    status=f"error: content_policy",
                )
                return {"success": False, "error": f"Content policy: {e.message}", "content_policy": True}

            if e.status_code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(10)
            elif e.status_code == 401:
                return {"success": False, "error": "Invalid API key (401)"}
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="mannequin_generation",
                    images_generated=0, estimated_cost_usd=0,
                    pose_id=pose_metadata["filename"],
                    status=f"error: {e.status_code}",
                )
                return {"success": False, "error": f"API error {e.status_code}: {e.message}"}

        except Exception as e:
            for f in image_files:
                try:
                    f.close()
                except Exception:
                    pass
            if attempt < 1:
                time.sleep(10)
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="mannequin_generation",
                    images_generated=0, estimated_cost_usd=0,
                    pose_id=pose_metadata["filename"],
                    status=f"error: {str(e)[:100]}",
                )
                return {"success": False, "error": str(e)}

    return {"success": False, "error": "Max retries exceeded"}


def _read_image_size(path: Path) -> tuple[int, int]:
    """Read image dimensions without loading full image data."""
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return (1024, 1536)


def generate_sketch(
    api_key: str,
    prompt_text: str,
    mannequin_image_path: Path,
    character_sheet_path: Path,
    output_path: Path,
    character_id: str = "",
    pose_id: str = "",
    quality: str = "medium",
) -> dict:
    """Generate a character sketch overlay using OpenAI gpt-image-1.

    Attaches the mannequin base as a reference image so the model can match
    the pose, proportions, and spatial layout. Output dimensions are read
    from the mannequin file at runtime.
    """
    client = openai.OpenAI(api_key=api_key)

    # Read mannequin dimensions for matching output size
    target_w, target_h = _read_image_size(mannequin_image_path)
    size = f"{target_w}x{target_h}"

    max_retries = 4
    backoff_times = [5, 10, 20, 40]

    for attempt in range(max_retries):
        image_files = []
        try:
            # Attach mannequin as primary reference
            if mannequin_image_path.exists():
                image_files.append(open(mannequin_image_path, "rb"))

            # Attach character sheet as secondary reference
            if character_sheet_path.exists():
                image_files.append(open(character_sheet_path, "rb"))

            response = client.images.edit(
                model=MODEL,
                image=image_files if image_files else None,
                prompt=prompt_text,
                size=size,
                quality=quality,
                n=1,
            )

            for f in image_files:
                f.close()

            b64 = response.data[0].b64_json
            if not b64:
                url = getattr(response.data[0], "url", None)
                if url:
                    import urllib.request
                    img_data = urllib.request.urlopen(url).read()
                else:
                    return {"success": False, "error": "No image data in response"}
            else:
                img_data = base64.b64decode(b64)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_data)

            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
            total_tokens = input_tokens + output_tokens
            from app.settings_manager import OPENAI_PRICING as _SP
            cost = total_tokens * 0.000004 if total_tokens > 0 else _SP.get(quality, 0.042)

            log_api_call(
                provider="openai", model=MODEL, operation="sketch_generation",
                input_tokens=input_tokens, output_tokens=output_tokens,
                images_generated=1, estimated_cost_usd=cost,
                character_id=character_id, pose_id=pose_id, status="success",
            )
            return {"success": True, "output_path": str(output_path), "cost": cost}

        except openai.RateLimitError as e:
            for f in image_files:
                f.close()
            if attempt < max_retries - 1:
                time.sleep(backoff_times[attempt])
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="sketch_generation",
                    images_generated=0, estimated_cost_usd=0,
                    character_id=character_id, pose_id=pose_id,
                    status="error: rate_limit",
                )
                return {"success": False, "error": f"Rate limit after {max_retries} retries: {e}"}

        except openai.APIStatusError as e:
            for f in image_files:
                f.close()
            err_str = str(e).lower()
            if e.status_code == 400 and any(kw in err_str for kw in
                    ["content_policy", "safety", "content policy"]):
                log_api_call(
                    provider="openai", model=MODEL, operation="sketch_generation",
                    images_generated=0, estimated_cost_usd=0,
                    character_id=character_id, pose_id=pose_id,
                    status="error: content_policy",
                )
                return {"success": False, "error": f"Content policy: {e.message}", "content_policy": True}
            if e.status_code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(10)
            elif e.status_code == 401:
                return {"success": False, "error": "Invalid API key (401)"}
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="sketch_generation",
                    images_generated=0, estimated_cost_usd=0,
                    character_id=character_id, pose_id=pose_id,
                    status=f"error: {e.status_code}",
                )
                return {"success": False, "error": f"API error {e.status_code}: {e.message}"}

        except Exception as e:
            for f in image_files:
                try:
                    f.close()
                except Exception:
                    pass
            if attempt < 1:
                time.sleep(10)
            else:
                log_api_call(
                    provider="openai", model=MODEL, operation="sketch_generation",
                    images_generated=0, estimated_cost_usd=0,
                    character_id=character_id, pose_id=pose_id,
                    status=f"error: {str(e)[:100]}",
                )
                return {"success": False, "error": str(e)}

    return {"success": False, "error": "Max retries exceeded"}

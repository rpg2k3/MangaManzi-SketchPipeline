"""Claude Haiku-based per-pose prompt assembly for mannequin generation.

System prompt: loaded from 9LK9_PROMPT_INSTRUCTIONS.md (behavioral rules).
Project spec: passed as a document block in the user message (reference data).
Reference images: attached as image blocks (style anchor).

No hardcoded prompt constants — all knowledge comes from the .md files.
"""

import base64
from pathlib import Path

import anthropic

from app.knowledge_loader import (
    load_prompt_instructions,
    load_project_spec,
    knowledge_files_present,
    check_reload_needed,
)
from app.cost_logger import log_api_call, estimate_claude_cost
from app.keyring_store import get_anthropic_key

MODEL = "claude-haiku-4-5-20251001"


def assemble_mannequin_prompt(
    archetype: dict,
    pose_metadata: dict,
    quality_tag: str = "",
    log_fn=None,
) -> dict:
    """Ask Claude Haiku to generate a GPT image prompt for one mannequin pose.

    Args:
        archetype: dict from archetype_scanner with code, label, head_count, references.
        pose_metadata: dict from pose_library with view, pose, category, pose_description.
        quality_tag: user-defined style modifier string.
        log_fn: optional callable for logging reload events.

    Returns:
        dict with keys: success, prompt, cost, input_tokens, output_tokens, error.
    """
    # Check knowledge files
    present, missing = knowledge_files_present()
    if not present:
        return {"success": False, "prompt": "", "cost": 0,
                "error": f"Missing knowledge files: {missing}"}

    # Hot-reload check
    reloaded = check_reload_needed()
    if reloaded and log_fn:
        for name in reloaded:
            log_fn(f"[Knowledge] Reloaded {name}")

    api_key = get_anthropic_key()
    if not api_key:
        return {"success": False, "prompt": "", "cost": 0,
                "error": "Anthropic API key not set."}

    client = anthropic.Anthropic(api_key=api_key)

    # Load knowledge from files (cached with hot-reload)
    system_prompt = load_prompt_instructions()
    project_spec = load_project_spec()

    # Build structured request
    orientation = pose_metadata.get("orientation", "portrait")
    pose_desc = pose_metadata.get("pose_description", pose_metadata.get("pose", ""))

    request_text = (
        f"Assemble the image-generation prompt for this pose:\n\n"
        f"Archetype: {archetype['code']} ({archetype['label']}, {archetype['age']}, "
        f"{archetype['head_count']} head-heights, range {archetype.get('head_range', '?')})\n"
        f"Gender: {archetype.get('gender', 'N')}\n"
        f"View: {pose_metadata['view']}\n"
        f"Pose: {pose_metadata.get('pose', '')}\n"
        f"Pose category: {pose_metadata.get('category', '')}\n"
        f"Pose description: {pose_desc}\n"
        f"Orientation: A4 {orientation}\n"
        f"Quality tag: {quality_tag or '(none)'}\n\n"
        f"Output the prompt as plain text. No commentary."
    )

    # Build user content array: document block + reference images + request text
    user_content = []

    # 1. Project spec as document block
    user_content.append({
        "type": "document",
        "source": {
            "type": "text",
            "media_type": "text/plain",
            "data": project_spec,
        },
        "title": "9LivesK9 Project Specification",
        "context": "Reference data for archetypes, views, poses, and proportions.",
    })

    # 2. Dual-layer references: CSP (anatomy) then GPT (style) for the matching view
    view = pose_metadata.get("view", "front")
    csp_refs = archetype.get("csp_references", {})
    gpt_refs = archetype.get("gpt_references", {})

    def _attach_image(path, label=""):
        if path and Path(path).exists():
            img_bytes = Path(path).read_bytes()
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            suffix = Path(path).suffix.lower()
            media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix, "image/png")
            user_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": b64},
            })

    # Attach references based on dual-reference mode setting
    from app import settings_manager as _sm
    dual_mode = _sm.get("dual_reference_mode")
    if dual_mode:
        _attach_image(csp_refs.get(view))
        _attach_image(gpt_refs.get(view))
    else:
        # Single-reference mode: GPT style only (safer for content moderation)
        _attach_image(gpt_refs.get(view))

    # 3. Structured request text
    user_content.append({"type": "text", "text": request_text})

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        prompt_text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_claude_cost(input_tokens, output_tokens)

        log_api_call(
            provider="anthropic", model=MODEL,
            operation="mannequin_prompt_assembly",
            input_tokens=input_tokens, output_tokens=output_tokens,
            estimated_cost_usd=cost,
            pose_id=pose_metadata.get("filename", ""),
            status="success",
        )

        return {
            "success": True,
            "prompt": prompt_text,
            "cost": cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    except Exception as e:
        log_api_call(
            provider="anthropic", model=MODEL,
            operation="mannequin_prompt_assembly",
            estimated_cost_usd=0,
            pose_id=pose_metadata.get("filename", ""),
            status=f"error: {str(e)[:200]}",
        )
        return {"success": False, "prompt": "", "cost": 0, "error": str(e)}

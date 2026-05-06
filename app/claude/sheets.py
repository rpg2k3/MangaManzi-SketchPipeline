"""Sheet operations driven by Claude (interprets natural-language deltas).

Structured mutations should hit app/sheets/storage.py directly. This
module is for the case where Claude needs to translate free-text feedback
into a sheet mutation (e.g. user says "she's slightly taller than I drew her"
→ adjust build.height_relative).
"""

import json

from .client import MODEL_HAIKU, call_with_tool

_SYSTEM = """Translate a free-text update request into a JSON-Patch-style
mutation against a character sheet. Preserve all unrelated fields. Reject
mutations that conflict with continuityRules without an explicit override."""


_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["set", "append", "remove"]},
                    "path": {"type": "string", "description": "Dot path, e.g. build.muscle_definition"},
                    "value": {"description": "Replacement / appended value (any JSON type)."},
                    "reason": {"type": "string"},
                },
                "required": ["op", "path", "reason"],
            },
        },
        "audit_summary": {"type": "string"},
    },
    "required": ["operations", "audit_summary"],
}


def interpret_sheet_update(
    api_key: str,
    sheet: dict,
    user_request: str,
    *,
    character_id: str = "",
) -> dict:
    """Returns {operations, audit_summary}. Caller applies the operations."""
    user = (
        f"CURRENT SHEET:\n```json\n{json.dumps(sheet, indent=2)}\n```\n\n"
        f"REQUEST:\n{user_request}\n\n"
        "Emit the patch via the tool."
    )
    return call_with_tool(
        api_key,
        model=MODEL_HAIKU,
        system=_SYSTEM,
        user_content=user,
        tool_name="emit_patch",
        tool_description="Emit a JSON patch against the sheet.",
        tool_input_schema=_TOOL_SCHEMA,
        operation="interpret_sheet_update",
        max_tokens=1024,
        character_id=character_id,
    )

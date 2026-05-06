"""Claude / Anthropic client — the director.

Houses prompt generation, sheet operations, critique, and scene composition.
Models: claude-opus-4-7 (heavy reasoning), claude-haiku-4-5-20251001 (cheap
structured tasks).
"""

from .client import MODEL_HAIKU, MODEL_OPUS, call_with_tool, encode_image_block, get_client
from .critique import critique_image
from .extraction import extract_character, test_connection
from .prompts import generate_prompt
from .scene import compose_scene
from .sheets import interpret_sheet_update

__all__ = [
    "MODEL_OPUS",
    "MODEL_HAIKU",
    "call_with_tool",
    "encode_image_block",
    "get_client",
    "extract_character",
    "test_connection",
    "generate_prompt",
    "critique_image",
    "interpret_sheet_update",
    "compose_scene",
]

"""Frozen prompt library loader.

Loads the verbatim PDF-extracted prompts and wraps them with the safety prefix
and mandatory elements block. Both providers receive byte-for-byte identical
prompt content — the only difference is API endpoint and request format.
"""

import json
from pathlib import Path

_DIR = Path(__file__).parent
_APP_DIR = _DIR.parent.parent
_TEMPLATES_DIR = _APP_DIR / "templates"

# Load frozen prompts (extracted from F_adult_instructions.pdf)
_PROMPTS_PATH = _DIR / "F_adult_prompts.json"
_PROMPTS: list[dict] = []
if _PROMPTS_PATH.exists():
    _PROMPTS = json.loads(_PROMPTS_PATH.read_text(encoding="utf-8"))

# Load enforcement layers
_SAFETY_PREFIX = ""
_SAFETY_PREFIX_STRONG = ""
_MANDATORY_BLOCK = ""
_SUBSTITUTIONS: list[dict] = []

_sp = _TEMPLATES_DIR / "safety_prefix.txt"
if _sp.exists():
    _SAFETY_PREFIX = _sp.read_text(encoding="utf-8").strip()

_sps = _TEMPLATES_DIR / "safety_prefix_strong.txt"
if _sps.exists():
    _SAFETY_PREFIX_STRONG = _sps.read_text(encoding="utf-8").strip()

_mb = _TEMPLATES_DIR / "mandatory_elements.txt"
if _mb.exists():
    _MANDATORY_BLOCK = _mb.read_text(encoding="utf-8").strip()

_sub_path = _TEMPLATES_DIR / "prompt_substitutions.json"
if _sub_path.exists():
    _SUBSTITUTIONS = json.loads(_sub_path.read_text(encoding="utf-8")).get("substitutions", [])


def get_prompt_count() -> int:
    return len(_PROMPTS)


def get_prompt_metadata(number: int) -> dict | None:
    """Get metadata for a prompt by number (1-62). Returns dict without prompt text."""
    for p in _PROMPTS:
        if p["number"] == number:
            return {k: v for k, v in p.items() if k != "prompt"}
    return None


def get_all_metadata() -> list[dict]:
    """Get metadata for all prompts (without prompt text)."""
    return [{k: v for k, v in p.items() if k != "prompt"} for p in _PROMPTS]


def _apply_substitutions(text: str) -> str:
    """Apply safety substitutions in order, case-sensitive, exact match."""
    for sub in _SUBSTITUTIONS:
        text = text.replace(sub["find"], sub["replace"])
    return text


def assemble_prompt(
    number: int,
    head_count: int = 8,
    use_strong_prefix: bool = False,
) -> str | None:
    """Assemble the final prompt for a given pose number.

    Returns the complete prompt string: safety prefix + substituted PDF prompt + mandatory block.
    This is the SAME prompt sent to both OpenAI and Gemini — provider-agnostic.
    Returns None if the prompt number is not found.
    """
    raw_prompt = None
    for p in _PROMPTS:
        if p["number"] == number:
            raw_prompt = p["prompt"]
            break

    if raw_prompt is None:
        return None

    prefix = _SAFETY_PREFIX_STRONG if use_strong_prefix else _SAFETY_PREFIX
    substituted = _apply_substitutions(raw_prompt)
    mandatory = _MANDATORY_BLOCK.replace("{HEAD_COUNT}", str(head_count))

    return f"{prefix}\n\n{substituted}\n\n{mandatory}"


def get_prompt_by_filename(filename: str) -> dict | None:
    """Look up a prompt entry by filename."""
    for p in _PROMPTS:
        if p["filename"] == filename:
            return p
    return None

"""Runtime loader for master prompt knowledge files with hot-reload support.

Single source of truth: the .md files in prompts/main_prompts/.
No fallback constants — if files are missing, generation must surface an error.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "prompts" / "main_prompts"
SPEC_FILE = KNOWLEDGE_DIR / "9LK9_PROJECT_SPEC.md"
INSTRUCTIONS_FILE = KNOWLEDGE_DIR / "9LK9_PROMPT_INSTRUCTIONS.md"

# Cache: (content, mtime)
_cache: dict[str, tuple[str, float]] = {}


def _load_with_cache(path: Path) -> str:
    """Load file content, using cache if mtime hasn't changed."""
    key = str(path)
    try:
        current_mtime = path.stat().st_mtime
    except FileNotFoundError:
        _cache.pop(key, None)
        raise FileNotFoundError(f"Knowledge file missing: {path}")

    cached = _cache.get(key)
    if cached and cached[1] == current_mtime:
        return cached[0]

    content = path.read_text(encoding="utf-8")
    _cache[key] = (content, current_mtime)

    if cached and cached[1] != current_mtime:
        log.info("Reloaded %s (modified)", path.name)

    return content


def load_project_spec() -> str:
    """Load the project specification (reference data for archetypes, poses, proportions)."""
    return _load_with_cache(SPEC_FILE)


def load_prompt_instructions() -> str:
    """Load the prompt assembly behavioral instructions (system prompt for Claude Haiku)."""
    return _load_with_cache(INSTRUCTIONS_FILE)


def knowledge_files_present() -> tuple[bool, list[str]]:
    """Check if all required knowledge files exist. Returns (all_present, missing_list)."""
    missing = []
    if not SPEC_FILE.exists():
        missing.append(str(SPEC_FILE))
    if not INSTRUCTIONS_FILE.exists():
        missing.append(str(INSTRUCTIONS_FILE))
    return (len(missing) == 0, missing)


def get_file_info(path: Path) -> dict:
    """Get file metadata: exists, size, mtime."""
    if not path.exists():
        return {"exists": False, "size": 0, "mtime": 0, "mtime_str": ""}
    stat = path.stat()
    from datetime import datetime
    mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_str": mtime_str,
    }


def get_spec_info() -> dict:
    return get_file_info(SPEC_FILE)


def get_instructions_info() -> dict:
    return get_file_info(INSTRUCTIONS_FILE)


def check_reload_needed() -> list[str]:
    """Check if any cached files have been modified. Returns list of reloaded file names."""
    reloaded = []
    for path in [SPEC_FILE, INSTRUCTIONS_FILE]:
        key = str(path)
        if not path.exists():
            continue
        current_mtime = path.stat().st_mtime
        cached = _cache.get(key)
        if cached and cached[1] != current_mtime:
            _load_with_cache(path)
            reloaded.append(path.name)
    return reloaded


def force_reload():
    """Force reload all knowledge files, clearing cache."""
    _cache.clear()
    results = []
    for path in [SPEC_FILE, INSTRUCTIONS_FILE]:
        if path.exists():
            _load_with_cache(path)
            results.append(path.name)
    return results

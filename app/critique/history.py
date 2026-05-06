"""Per-scene iteration history.

One JSONL file per scene at data/history/<sheet_id>/<scene_id>.jsonl.
Each line is an Iteration dict: prompt + critique + output + timestamp +
manual feedback (if supplied). Append-only.
"""

import json
from datetime import datetime
from pathlib import Path

HISTORY_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "history"


def _path(sheet_id: str, scene_id: str) -> Path:
    return HISTORY_ROOT / sheet_id / f"{scene_id}.jsonl"


def append_iteration(
    sheet_id: str,
    scene_id: str,
    *,
    prompt: dict,
    critique: dict,
    output_path: str | Path,
    manual_feedback: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Persist one iteration record. Returns the stored dict."""
    p = _path(sheet_id, scene_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = list(load_iterations(sheet_id, scene_id))
    record = {
        "ts": datetime.now().isoformat(),
        "sheet_id": sheet_id,
        "scene_id": scene_id,
        "iteration_index": len(existing),
        "prompt": prompt,
        "critique": critique,
        "output_path": str(output_path),
        "manual_feedback": manual_feedback,
    }
    if extra:
        record["extra"] = extra
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_iterations(sheet_id: str, scene_id: str) -> list[dict]:
    p = _path(sheet_id, scene_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def recent_iterations(sheet_id: str, scene_id: str, n: int = 3) -> list[dict]:
    return load_iterations(sheet_id, scene_id)[-n:]


def all_iterations_for_character(sheet_id: str) -> list[dict]:
    """Aggregate iterations across every scene for one character.

    Used by app/critique/learning.py to detect recurring drifts.
    """
    char_dir = HISTORY_ROOT / sheet_id
    if not char_dir.exists():
        return []
    out: list[dict] = []
    for jsonl in sorted(char_dir.glob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out

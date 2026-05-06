"""Character sheet CRUD — JSON files in data/sheets/<id>.json."""

import json
from datetime import datetime
from pathlib import Path

SHEETS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sheets"


def _path(sheet_id: str) -> Path:
    if not sheet_id:
        raise ValueError("sheet_id is empty")
    return SHEETS_DIR / f"{sheet_id}.json"


def exists(sheet_id: str) -> bool:
    return _path(sheet_id).exists()


def load(sheet_id: str) -> dict:
    return json.loads(_path(sheet_id).read_text(encoding="utf-8"))


def save(sheet: dict) -> Path:
    sid = sheet.get("id") or sheet.get("character_id")
    if not sid:
        raise ValueError("Sheet has neither 'id' nor 'character_id'")
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(sid)
    p.write_text(json.dumps(sheet, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def list_ids() -> list[str]:
    if not SHEETS_DIR.exists():
        return []
    return sorted(p.stem for p in SHEETS_DIR.glob("*.json"))


def delete(sheet_id: str) -> bool:
    p = _path(sheet_id)
    if p.exists():
        p.unlink()
        return True
    return False


def apply_patch(sheet: dict, operations: list[dict], summary: str = "") -> dict:
    """Apply a list of {op, path, value} operations and append an audit entry.

    `path` is a dot-separated key path, e.g. "build.muscle_definition".
    """
    out = json.loads(json.dumps(sheet))  # deep copy via JSON round-trip

    for op in operations:
        action = op.get("op")
        path = op.get("path", "")
        if not path:
            continue
        keys = path.split(".")
        cursor = out
        for k in keys[:-1]:
            cursor = cursor.setdefault(k, {})
        last = keys[-1]
        if action == "set":
            cursor[last] = op.get("value")
        elif action == "append":
            cursor.setdefault(last, [])
            if isinstance(cursor[last], list):
                cursor[last].append(op.get("value"))
        elif action == "remove":
            cursor.pop(last, None)

    out.setdefault("audit", []).append({
        "ts": datetime.now().isoformat(),
        "summary": summary,
        "operations": operations,
    })
    return out

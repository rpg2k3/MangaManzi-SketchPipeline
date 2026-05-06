"""One-shot, idempotent migration of alpha-era characters/ → data/sheets/.

For each `characters/<id>/extracted.json`, upgrade to the BetaStage schema
(adds new fields non-destructively) and write to `data/sheets/<id>.json`.
Already-migrated sheets are skipped unless `force=True`.

Run from the CLI: `python -m app.sheets.migration`
"""

import json
from pathlib import Path

from .schema import upgrade_sheet
from .storage import SHEETS_DIR, exists, save


def migrate_alpha_characters(
    characters_root: Path | None = None,
    force: bool = False,
) -> list[str]:
    src = characters_root or (Path(__file__).resolve().parent.parent.parent / "characters")
    if not src.exists():
        return []

    migrated: list[str] = []
    for char_dir in sorted(src.iterdir()):
        if not char_dir.is_dir():
            continue
        ej = char_dir / "extracted.json"
        if not ej.exists():
            continue
        sheet = json.loads(ej.read_text(encoding="utf-8"))
        upgraded = upgrade_sheet(sheet)
        sid = upgraded["id"]
        if not sid:
            continue
        if exists(sid) and not force:
            continue
        save(upgraded)
        migrated.append(sid)
    return migrated


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    out = migrate_alpha_characters(force=force)
    if out:
        print(f"Migrated {len(out)} sheets to {SHEETS_DIR}:")
        for sid in out:
            print(f"  - {sid}")
    else:
        print(f"No sheets migrated. (Already up to date in {SHEETS_DIR})")

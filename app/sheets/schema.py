"""Character sheet schema helpers.

Sheets are dicts (JSON-backed). The alpha schema is preserved as-is;
new BetaStage fields (linkedLoraId, triggerWords, loraWeight, designNotes,
outfitVariants, continuityRules, learnedDrifts, audit) are added as
siblings, non-destructively.
"""

NEW_FIELD_DEFAULTS = {
    "linkedLoraId": None,
    "triggerWords": [],
    "loraWeight": 0.75,
    "designNotes": "",
    "outfitVariants": [],
    "continuityRules": [],
    "referenceAnchors": [],
    "learnedDrifts": [],
    "audit": [],
}


def _name_from_id(cid: str) -> str:
    return cid.replace("_", " ").replace("-", " ").strip().title() if cid else ""


def upgrade_sheet(alpha_or_existing: dict) -> dict:
    """Return a dict with every BetaStage field present.

    Behavior:
    - `id`: prefers existing `id`, falls back to `character_id`.
    - `name`: derives Title-Case from id if missing.
    - `designNotes`: seeds from alpha `notes_for_generation` if missing.
    - All other new fields: filled with their default if missing.
    - Existing fields: never overwritten.
    """
    d = dict(alpha_or_existing)
    cid = d.get("id") or d.get("character_id") or ""
    d.setdefault("id", cid)
    if not d.get("name"):
        d["name"] = _name_from_id(cid)

    if "designNotes" not in d:
        d["designNotes"] = d.get("notes_for_generation", "")

    for k, default in NEW_FIELD_DEFAULTS.items():
        if k in d:
            continue
        if isinstance(default, list):
            d[k] = []
        elif isinstance(default, dict):
            d[k] = {}
        else:
            d[k] = default
    return d


def is_upgraded(sheet: dict) -> bool:
    return all(k in sheet for k in NEW_FIELD_DEFAULTS)

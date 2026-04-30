"""Auto-discover archetypes from dual-layer reference folders (CSP anatomy + GPT style)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BASES_CSP_DIR = PROJECT_ROOT / "bases" / "csp_tvd"
BASES_GPT_DIR = PROJECT_ROOT / "bases" / "gpt_tvd"
OUTPUT_DIR = PROJECT_ROOT / "output"

REQUIRED_VIEWS = ["front", "back", "side_L", "side_R", "3q_front_L", "3q_front_R"]

_ARCHETYPE_META = {
    "F_adult": {"label": "Female Adult", "age": "25+", "head_count": 8, "head_range": "7.5-8", "gender": "F"},
    "M_adult": {"label": "Male Adult", "age": "25+", "head_count": 8, "head_range": "7.5-8", "gender": "M"},
    "F_yadult": {"label": "Female Young Adult", "age": "18+", "head_count": 7.5, "head_range": "7.0-7.5", "gender": "F"},
    "M_yadult": {"label": "Male Young Adult", "age": "18+", "head_count": 7.5, "head_range": "7.0-7.5", "gender": "M"},
    "F_teenM": {"label": "Female Teen Mature", "age": "16+", "head_count": 7, "head_range": "6.5-7", "gender": "F"},
    "M_teenM": {"label": "Male Teen Mature", "age": "16+", "head_count": 7, "head_range": "6.5-7", "gender": "M"},
    "F_teenY": {"label": "Female Teen Young", "age": "14+", "head_count": 6.5, "head_range": "6.0-6.5", "gender": "F"},
    "M_teenY": {"label": "Male Teen Young", "age": "14+", "head_count": 6.5, "head_range": "6.0-6.5", "gender": "M"},
    "F_preteen": {"label": "Female Pre-Teen", "age": "12+", "head_count": 6, "head_range": "5.5-6.0", "gender": "F"},
    "M_preteen": {"label": "Male Pre-Teen", "age": "12+", "head_count": 6, "head_range": "5.5-6.0", "gender": "M"},
    "child": {"label": "Child", "age": "8-11", "head_count": 5.5, "head_range": "5.0-5.5", "gender": "N"},
    "toddler": {"label": "Toddler", "age": "2-4", "head_count": 4.5, "head_range": "4.0-4.5", "gender": "N"},
    "baby": {"label": "Baby", "age": "0-1", "head_count": 3.5, "head_range": "3.0-3.5", "gender": "N"},
}


def _find_reference(folder: Path, view_name: str) -> Path | None:
    """Find a reference file matching view_name, case-insensitive."""
    if not folder.exists():
        return None
    for f in folder.iterdir():
        if f.is_file() and f.stem.lower() == view_name.lower() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
            return f
    return None


def _count_views(folder: Path) -> tuple[int, dict[str, Path]]:
    """Count found views and return mapping."""
    refs = {}
    for view in REQUIRED_VIEWS:
        ref = _find_reference(folder, view)
        if ref:
            refs[view] = ref
    return len(refs), refs


def _extract_archetype_code(folder_name: str) -> str:
    for code in _ARCHETYPE_META:
        if folder_name.startswith(code):
            return code
    if "-(" in folder_name:
        return folder_name.split("-(")[0]
    if "(" in folder_name:
        return folder_name.split("(")[0].rstrip("-_ ")
    return folder_name


def scan_archetypes() -> list[dict]:
    """Scan both CSP and GPT reference folders. Returns list of archetype dicts.

    Each dict has:
      folder_name, code, label, age, head_count, head_range, gender,
      csp_references: dict[str, Path], csp_count: int,
      gpt_references: dict[str, Path], gpt_count: int,
      status: str ("ready" | "incomplete: ..."),
      complete: bool (both layers have all 6 views),
      csp_dir: Path, gpt_dir: Path, output_dir: Path,
    """
    csp_names = {f.name for f in BASES_CSP_DIR.iterdir() if f.is_dir()} if BASES_CSP_DIR.exists() else set()
    gpt_names = {f.name for f in BASES_GPT_DIR.iterdir() if f.is_dir()} if BASES_GPT_DIR.exists() else set()
    all_names = sorted(csp_names | gpt_names)

    archetypes = []
    for folder_name in all_names:
        code = _extract_archetype_code(folder_name)
        meta = _ARCHETYPE_META.get(code, {
            "label": code.replace("_", " ").title(), "age": "?",
            "head_count": 8, "head_range": "?", "gender": "N",
        })

        csp_dir = BASES_CSP_DIR / folder_name
        gpt_dir = BASES_GPT_DIR / folder_name
        output_dir = OUTPUT_DIR / folder_name

        csp_count, csp_refs = _count_views(csp_dir)
        gpt_count, gpt_refs = _count_views(gpt_dir)

        if csp_count == 6 and gpt_count == 6:
            status = "ready"
        elif csp_count == 0 and gpt_count > 0:
            status = "incomplete: missing CSP anatomy reference"
        elif csp_count > 0 and gpt_count == 0:
            status = "incomplete: missing GPT style reference"
        else:
            status = f"incomplete: CSP {csp_count}/6, GPT {gpt_count}/6"

        archetypes.append({
            "folder_name": folder_name,
            "code": code,
            "label": meta["label"],
            "age": meta["age"],
            "head_count": meta["head_count"],
            "head_range": meta["head_range"],
            "gender": meta["gender"],
            "csp_references": csp_refs,
            "csp_count": csp_count,
            "gpt_references": gpt_refs,
            "gpt_count": gpt_count,
            "status": status,
            "complete": csp_count == 6 and gpt_count == 6,
            "csp_dir": csp_dir,
            "gpt_dir": gpt_dir,
            "output_dir": output_dir,
            # Legacy compat — merged references dict for code that reads arch["references"]
            "references": {**csp_refs},
        })

    return archetypes


def get_dual_references(archetype: dict, view: str) -> tuple[Path | None, Path | None]:
    """Get (csp_ref, gpt_ref) for a specific view. Returns None for missing."""
    csp = archetype.get("csp_references", {}).get(view)
    gpt = archetype.get("gpt_references", {}).get(view)
    return csp, gpt


def get_all_csp_references(archetype: dict) -> list[Path]:
    return [archetype["csp_references"][v] for v in REQUIRED_VIEWS if v in archetype.get("csp_references", {})]


def get_all_gpt_references(archetype: dict) -> list[Path]:
    return [archetype["gpt_references"][v] for v in REQUIRED_VIEWS if v in archetype.get("gpt_references", {})]

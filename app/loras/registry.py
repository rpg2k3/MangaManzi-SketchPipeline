"""LoRA registry — id, purpose, triggers, default weight, base model, stage.

Seeded with the production-ready `9k9base` LoRA (locked). Sketch and
per-character LoRAs land here once their PixAI model IDs are provided.
"""

import warnings
from dataclasses import dataclass, field
from typing import Literal

from app.pixai.defaults import DEFAULT_BASE_MODEL

# Authoritative set of valid `architecture` values for the LoRA dataclass.
# Used by Stage 3 prompt assembly to fork DiT.2 (no negative prompt) vs
# SDXL/Illustrious (negative-prompt template + drift-as-negative injection).
LORA_ARCHITECTURES = ("sdxl", "illustrious", "dit1", "dit2", "unknown")
LoRAArchitecture = Literal["sdxl", "illustrious", "dit1", "dit2", "unknown"]


@dataclass(frozen=True)
class LoRA:
    """A LoRA in the registry.

    `base_model_id` is the PixAI model-version id of the checkpoint this
    LoRA was trained on. SDXL LoRAs MUST be paired with their native
    training base or output is degraded — the runtime always sends the
    LoRA's `base_model_id` as the request's `modelId`, never the global
    default.

    `architecture` drives Stage 3 prompt assembly: DiT.2 LoRAs cannot use
    negative prompts, so drift correction goes positive. SDXL/Illustrious
    LoRAs use the negative-prompt template with drifts as absences. New
    entries default to "unknown" and emit a one-shot warning when fetched.
    """
    name: str
    pixai_model_id: str
    purpose: str
    trigger_words: str
    weight: float
    base_model: str
    base_model_id: str
    used_in_stage: int
    positive_append: str = ""
    default_negative: str = ""
    locked: bool = False
    architecture: LoRAArchitecture = "unknown"


# Phase 1C Stage 1 negative — underscored booru tokens, Phase 1C spec.
# (`_POS_9K9BASE` removed: it was dead code. Stage 1 prompt assembly never
# used it, and the comment chain in stages.py noted that "blueprint style /
# technical drawing" tokens pulled the model toward architectural diagrams.)
_NEG_9K9BASE = (
    "nsfw, worst_quality, bad_quality, low_quality, lowres, "
    "bad_anatomy, multiple_figures, clothing, hair, face_features, "
    "shading, finished_illustration, color, photo_realistic"
)

NINEK9BASE = LoRA(
    name="9k9base",
    pixai_model_id="2006655610114208859",
    purpose="base mannequin style (light blue pencil construction)",
    trigger_words=(
        "9k9base, light blue pencil construction, atari bands, "
        "joint ovals, faceless bald head, head height grid"
    ),
    # Phase 1B baseline: 0.9 (down from 1.0). The Illustrious base does
    # most of the work; full LoRA strength was over-applying the pencil
    # construction style.
    weight=0.9,
    # Training base per the LoRA's PixAI page. Illustrious-XL-v1.0 — SDXL LoRA,
    # must be paired with its native base or output is degraded. The
    # API-callable id is taken from a known-working web-UI reference task
    # (id 2006991601815684685 / 2006996847850078063): both `parameters.modelId`
    # and `outputs.detailParameters.modelId` show this value, with no mapping.
    # The shorter URL id (1844843518698131638) is the model-page id, NOT an
    # API checkpoint id — it returned 403 "Invalid modelId" when sent.
    base_model="Illustrious-XL-v1.0",
    base_model_id="1844843519625072849",
    used_in_stage=1,
    default_negative=_NEG_9K9BASE,
    locked=True,
    architecture="illustrious",
)


# ─────────────────────────────────────────────────────────────────────
# Faye-Lyn character LoRAs (D4 unblock — registered 2026-05-06).
#
# Both variants supplied by the user. Two architectures so the team can
# benchmark DiT.2 (no-negative, positive-respec drift correction) against
# SDXL/Illustrious (negative-template + drift-as-absence). The character
# sheet at data/sheets/faye_lyn.json initially binds to the SDXL variant
# for full negative-prompt support; swap `linkedLoraId` to the DiT.2 id
# (2007394339034365733) to test that path.
#
# Trigger words and recommended weight could not be parsed from the
# public model pages — those values live in PixAI's authenticated
# hydrated GraphQL response, not in the static HTML. Per spec, fell back
# to trigger_words="faye_lyn" + weight=0.75. User must verify the
# canonical values from the model page UI and update via register() if
# they differ.
# ─────────────────────────────────────────────────────────────────────

# Sentinel value so the DiT.2 variant fails loudly at PixAI validation if
# someone binds the sheet to it before the actual base checkpoint id is
# supplied. PixAI rejects unknown modelIds with "Invalid modelId" — see
# the comment chain on NINEK9BASE.base_model_id.
_DIT2_BASE_MODEL_ID_TBD = "DIT2_BASE_MODEL_ID_REQUIRED"

FAYE_LYN_SDXL = LoRA(
    name="faye_lyn_sdxl",
    pixai_model_id="2007725844888836295",
    purpose=(
        "9k9_Faye_Lyn-GlitchArcade-SDXL — character LoRA, "
        "Illustrious-XL-v1.0 family. Initial sheet binding."
    ),
    trigger_words="faye_lyn",  # FALLBACK — verify canonical from PixAI UI
    weight=0.75,                # FALLBACK — verify canonical from PixAI UI
    base_model="Illustrious-XL-v1.0",
    base_model_id="1844843519625072849",  # same as 9k9base SDXL base
    used_in_stage=3,
    locked=True,
    architecture="illustrious",
)

FAYE_LYN_DIT2 = LoRA(
    name="faye_lyn_dit2",
    pixai_model_id="2007394339034365733",
    purpose=(
        "9k9_fayeLyn_glitchArcade — character LoRA, DiT.2 architecture. "
        "Drift correction goes through positive re-specification "
        "(no negative prompt). base_model_id REQUIRED before runtime "
        "use — DiT.2 base checkpoint id was not exposed on the model "
        "page; supply via register() override."
    ),
    trigger_words="faye_lyn",  # FALLBACK — verify canonical from PixAI UI
    weight=0.75,                # FALLBACK — verify canonical from PixAI UI
    base_model="DiT.2 (TBD)",
    base_model_id=_DIT2_BASE_MODEL_ID_TBD,
    used_in_stage=3,
    locked=True,
    architecture="dit2",
)


_REGISTRY: dict[str, LoRA] = {
    NINEK9BASE.name: NINEK9BASE,
    FAYE_LYN_SDXL.name: FAYE_LYN_SDXL,
    FAYE_LYN_DIT2.name: FAYE_LYN_DIT2,
}

_WARNED_UNKNOWN_ARCH: set[str] = set()


def get(name: str) -> LoRA:
    if name not in _REGISTRY:
        raise KeyError(
            f"LoRA '{name}' not in registry. Known: {sorted(_REGISTRY)}. "
            "If this is the sketch or a character LoRA, register it via register()."
        )
    lora = _REGISTRY[name]
    if lora.architecture == "unknown" and name not in _WARNED_UNKNOWN_ARCH:
        _WARNED_UNKNOWN_ARCH.add(name)
        warnings.warn(
            f"LoRA '{name}' has architecture='unknown'. Stage 3 prompt "
            "assembly cannot fork DiT.2 vs SDXL correctly until this is set. "
            f"Valid values: {LORA_ARCHITECTURES}.",
            stacklevel=2,
        )
    return lora


def register(lora: LoRA) -> None:
    if lora.name in _REGISTRY and _REGISTRY[lora.name].locked:
        raise ValueError(f"LoRA '{lora.name}' is locked and cannot be replaced.")
    _REGISTRY[lora.name] = lora


def all_loras() -> dict[str, LoRA]:
    return dict(_REGISTRY)


def stage_loras(stage: int) -> list[LoRA]:
    return [l for l in _REGISTRY.values() if l.used_in_stage == stage]


def find_by_pixai_id(pixai_id: str) -> LoRA | None:
    """Reverse-lookup: registry-name is the dict key, but Stage 3 only knows
    the PixAI model id (from sheet.linkedLoraId). Returns None if no LoRA
    in the registry has that id.
    """
    for lora in _REGISTRY.values():
        if lora.pixai_model_id == pixai_id:
            return lora
    return None

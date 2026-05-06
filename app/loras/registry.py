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


# P18: drastically simplified. The previous long negative was stacking
# band-aids for failures the new tight prompt no longer produces. Reference
# web-UI tests achieved clean output with an empty negative — we keep just
# enough to ward off the most obvious failure modes.
_NEG_9K9BASE = (
    "nsfw, worst quality, bad quality, low quality, lowres, "
    "bad anatomy, multiple figures, "
    "clothing, hair, face, shading, finished anime"
)

_POS_9K9BASE = (
    "flat line drawing, pencil sketch, construction lines visible, "
    "no shading, no rendering, blueprint style, technical drawing"
)

NINEK9BASE = LoRA(
    name="9k9base",
    pixai_model_id="2006655610114208859",
    purpose="base mannequin style (light blue pencil construction)",
    trigger_words=(
        "9k9base, light blue pencil construction, atari bands, "
        "joint ovals, faceless bald head, head height grid"
    ),
    weight=1.0,
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
    positive_append=_POS_9K9BASE,
    default_negative=_NEG_9K9BASE,
    locked=True,
    architecture="illustrious",
)


_REGISTRY: dict[str, LoRA] = {
    NINEK9BASE.name: NINEK9BASE,
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

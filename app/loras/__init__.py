"""LoRA registry.

9k9base is locked-in production. Sketch + per-character LoRAs are added
via register() once their PixAI model IDs are provided.
"""

from .registry import (
    FAYE_LYN_DIT2,
    FAYE_LYN_SDXL,
    LORA_ARCHITECTURES,
    NINEK9BASE,
    LoRA,
    all_loras,
    find_by_pixai_id,
    get,
    register,
    stage_loras,
)

__all__ = [
    "FAYE_LYN_DIT2",
    "FAYE_LYN_SDXL",
    "LORA_ARCHITECTURES",
    "LoRA",
    "NINEK9BASE",
    "all_loras",
    "find_by_pixai_id",
    "get",
    "register",
    "stage_loras",
]

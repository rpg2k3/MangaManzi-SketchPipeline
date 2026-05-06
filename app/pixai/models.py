"""Dataclasses describing PixAI request/response shapes.

`TaskParameters.to_pixai_dict()` produces the JSONObject payload for the
`createGenerationTask(parameters: JSONObject!)` mutation. Field naming
matches the PixAI GraphQL schema verbatim (see app/pixai/client.py).

Phase 3: Booster (`qualityTag`) is gated. Callers must pass
`allow_booster=True` explicitly to include the field in the request
payload. A `quality_tag` set without `allow_booster=True` is dropped at
serialization time and a warning is emitted, so accidental Booster runs
can never reach PixAI silently.
"""

import warnings
from dataclasses import dataclass, field

from .defaults import (
    DEFAULT_BASE_MODEL_ID,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CFG_SCALE,
    DEFAULT_HEIGHT,
    DEFAULT_SAMPLING_METHOD,
    DEFAULT_SAMPLING_STEPS,
    DEFAULT_WIDTH,
)


@dataclass(frozen=True)
class LoraSpec:
    """One LoRA in the stack.

    PixAI serializes the whole stack as a single object keyed by model id:
        "lora": { "<modelId>": <weight>, ... }
    (See TaskParameters.lora type in the official JS client.)
    """
    model_id: str
    weight: float = 1.0


@dataclass(frozen=True)
class ControlNetSpec:
    """Reference image + control type. PixAI accepts: dwpose, canny, depth,
    hed, mlsd, openpose, seg, normal, scribble.
    """
    type: str
    media_id: str
    weight: float = 1.0

    def to_pixai_dict(self) -> dict:
        return {"type": self.type, "mediaId": self.media_id, "weight": self.weight}


@dataclass
class TaskParameters:
    prompts: str
    negative_prompts: str = ""
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    cfg_scale: float = DEFAULT_CFG_SCALE
    sampling_steps: int = DEFAULT_SAMPLING_STEPS
    sampling_method: str = DEFAULT_SAMPLING_METHOD
    model_id: str | None = DEFAULT_BASE_MODEL_ID
    seed: int | None = None
    batch_size: int = DEFAULT_BATCH_SIZE
    # PixAI: send 1000 for the immediate-processing (high-priority, ~2× cost)
    # path. Omit (None) for the public queue. Per the official Go client docs.
    priority: int | None = None
    loras: list[LoraSpec] = field(default_factory=list)
    control_nets: list[ControlNetSpec] = field(default_factory=list)
    media_id: str | None = None
    strength: float | None = None
    # PixAI web UI defaults — discovered via reference task 2006996847850078063.
    # `clip_skip=2` is the web-UI default for Illustrious; omitted-from-API runs
    # were getting whatever server-side default and producing different output.
    clip_skip: int = 2
    # `quality_tag` is the web UI's "Booster" — appends quality boosters to the
    # prompt. Gated: only included in the request when `allow_booster` is True.
    # Stage 1/2/3 set quality_tag=None and never opt in. A non-None value
    # without allow_booster=True is dropped + warned, NOT sent silently.
    quality_tag: dict | None = None
    allow_booster: bool = False

    def to_pixai_dict(self) -> dict:
        d: dict = {
            "prompts": self.prompts,
            "negativePrompts": self.negative_prompts,
            "width": self.width,
            "height": self.height,
            "cfgScale": self.cfg_scale,
            "samplingSteps": self.sampling_steps,
            "samplingMethod": self.sampling_method,
            "batchSize": self.batch_size,
            "clipSkip": self.clip_skip,
        }
        if self.quality_tag is not None:
            if self.allow_booster:
                d["qualityTag"] = self.quality_tag
            else:
                warnings.warn(
                    "TaskParameters.quality_tag is set but allow_booster is False. "
                    "Dropping qualityTag from the PixAI request to honor the Phase 3 "
                    "booster gate. Pass allow_booster=True explicitly to send it.",
                    stacklevel=2,
                )
        if self.model_id is not None:
            d["modelId"] = self.model_id
        if self.seed is not None:
            d["seed"] = self.seed
        if self.priority is not None:
            d["priority"] = self.priority
        if self.loras:
            # PixAI expects an object keyed by model version id, not an array.
            # If the same id appears twice the later weight wins.
            d["lora"] = {l.model_id: l.weight for l in self.loras}
        if self.control_nets:
            d["controlNets"] = [c.to_pixai_dict() for c in self.control_nets]
        if self.media_id is not None:
            d["mediaId"] = self.media_id
        if self.strength is not None:
            d["strength"] = self.strength
        return d


@dataclass
class GenerationResult:
    task_id: str
    status: str
    media_ids: list[str]
    public_urls: list[str]
    raw_task: dict

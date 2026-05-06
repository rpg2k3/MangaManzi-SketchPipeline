"""PixAI client — the studio (all image generation).

Async task lifecycle: createGenerationTask → poll getTaskById → download media.
Concurrency cap: 10 in-flight tasks (PixAI hard limit).
Polling: ≥1.5s, exponential backoff (1.5×, capped at 30s), 180s timeout default.
"""

from .client import PixAIClient, media_ids_from_task, test_connection
from .concurrency import inflight_slot
from .credits import estimate_credits
from .errors import (
    PixAIAuthError,
    PixAIError,
    PixAITaskFailedError,
    PixAITimeoutError,
)
from .models import ControlNetSpec, GenerationResult, LoraSpec, TaskParameters
from .polling import poll_until_complete

__all__ = [
    "PixAIClient",
    "TaskParameters",
    "LoraSpec",
    "ControlNetSpec",
    "GenerationResult",
    "PixAIError",
    "PixAIAuthError",
    "PixAITimeoutError",
    "PixAITaskFailedError",
    "poll_until_complete",
    "inflight_slot",
    "estimate_credits",
    "media_ids_from_task",
    "test_connection",
]

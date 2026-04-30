"""Generation state machine."""

from enum import Enum


class GenerationState(Enum):
    IDLE = "idle"
    GENERATING = "generating"
    PAUSED = "paused"
    COMPLETING = "completing"

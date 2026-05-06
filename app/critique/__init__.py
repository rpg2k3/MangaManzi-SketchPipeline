"""Critique engine + iteration history + drift learning."""

from .engine import run_critique
from .history import (
    HISTORY_ROOT,
    all_iterations_for_character,
    append_iteration,
    load_iterations,
    recent_iterations,
)
from .learning import (
    DEFAULT_THRESHOLD,
    count_drift_recurrences,
    promote_recurring_drifts,
)
from .regenerate import compose_corrected_prompt

__all__ = [
    "HISTORY_ROOT",
    "DEFAULT_THRESHOLD",
    "all_iterations_for_character",
    "append_iteration",
    "compose_corrected_prompt",
    "count_drift_recurrences",
    "load_iterations",
    "promote_recurring_drifts",
    "recent_iterations",
    "run_critique",
]

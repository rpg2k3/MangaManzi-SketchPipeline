"""Credit cost estimation for PixAI generations.

Numbers are approximate (per the Phase 3 spec): ~7,600/gen with high
priority enabled, ~3,800 standard. Actual billing comes from PixAI's
account dashboard. We log estimates to the cost CSV for budget tracking.
"""

from .defaults import CREDITS_HIGH_PRIORITY, CREDITS_STANDARD


def estimate_credits(high_priority: bool, batch_size: int = 1) -> int:
    per = CREDITS_HIGH_PRIORITY if high_priority else CREDITS_STANDARD
    return per * batch_size

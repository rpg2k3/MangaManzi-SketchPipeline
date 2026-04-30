"""Append-only CSV cost logging — one file per day."""

import csv
from datetime import datetime, date
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs" / "api_costs"

COLUMNS = [
    "timestamp", "provider", "model", "operation",
    "input_tokens", "output_tokens", "images_generated",
    "estimated_cost_usd", "character_id", "pose_id", "status",
]

# Pricing constants (verify against provider docs)
PRICING = {
    "claude_haiku_input": 1.00 / 1_000_000,    # $1/M input tokens
    "claude_haiku_output": 5.00 / 1_000_000,    # $5/M output tokens
    "gemini_batch_image": 0.0195,                # per image (batch)
    "gemini_standard_image": 0.039,              # per image (standard fallback)
}


def _log_path(d: date | None = None) -> Path:
    if d is None:
        d = date.today()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"{d.isoformat()}.csv"


def log_api_call(
    provider: str,
    model: str,
    operation: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images_generated: int = 0,
    estimated_cost_usd: float = 0.0,
    character_id: str = "",
    pose_id: str = "",
    status: str = "success",
):
    path = _log_path()
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(COLUMNS)
        w.writerow([
            datetime.now().isoformat(),
            provider, model, operation,
            input_tokens, output_tokens, images_generated,
            f"{estimated_cost_usd:.6f}",
            character_id, pose_id, status,
        ])


def estimate_claude_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRICING["claude_haiku_input"]
            + output_tokens * PRICING["claude_haiku_output"])


def estimate_gemini_cost(image_count: int, batch: bool = True) -> float:
    rate = PRICING["gemini_batch_image"] if batch else PRICING["gemini_standard_image"]
    return image_count * rate


def get_cumulative_spend() -> dict[str, float]:
    """Read all CSV logs and sum spend by provider."""
    spend = {}
    if not LOGS_DIR.exists():
        return spend
    for csv_path in sorted(LOGS_DIR.glob("*.csv")):
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    provider = row.get("provider", "unknown")
                    cost = float(row.get("estimated_cost_usd", 0))
                    spend[provider] = spend.get(provider, 0) + cost
        except Exception:
            continue
    return spend

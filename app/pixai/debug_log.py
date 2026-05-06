"""Append raw PixAI API responses to a daily debug log.

Hard rule from Phase 3 spec: capture raw responses during dev so we can
diff actual schema against expected. File path: data/debug/pixai/<date>.jsonl
"""

import json
import logging
from datetime import datetime
from pathlib import Path

DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug" / "pixai"
log = logging.getLogger(__name__)


def log_response(operation: str, status_code: int, body) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        if isinstance(body, str):
            body_payload = {"raw": body[:4000]}
        else:
            body_payload = body
        entry = {
            "ts": datetime.now().isoformat(),
            "operation": operation,
            "status_code": status_code,
            "body": body_payload,
        }
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        log.warning("debug_log failed: %s", e)

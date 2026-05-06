"""Locked production defaults + endpoint config for PixAI calls.

Override per-call by passing fields explicitly to TaskParameters.
"""

PIXAI_API_BASE = "https://api.pixai.art"
GRAPHQL_ENDPOINT = PIXAI_API_BASE + "/graphql"

MAX_IN_FLIGHT_TASKS = 10

MIN_POLL_INTERVAL_SEC = 1.5
MAX_POLL_INTERVAL_SEC = 30.0
POLL_BACKOFF_FACTOR = 1.5
DEFAULT_TASK_TIMEOUT_SEC = 180

DEFAULT_BASE_MODEL = "Haruka-v2"
# PixAI's numeric model version id for Haruka-v2. Pinned so we never silently
# drift if the account default changes upstream.
DEFAULT_BASE_MODEL_ID = "1648918127446573124"
DEFAULT_SAMPLING_METHOD = "DPM++ 2M Karras"
# Phase 1B baseline: SDXL-native portrait bucket 832x1216. The previous
# 768x1280 was an off-bucket size for SDXL training data and produced
# softer output. CFG 6.0 / 26 steps is Stage 1's value; Stage 2 and 3
# override these explicitly per the per-stage spec.
DEFAULT_SAMPLING_STEPS = 26
DEFAULT_CFG_SCALE = 6.0
DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 1216
DEFAULT_HIGH_PRIORITY = False
DEFAULT_BATCH_SIZE = 1

CREDITS_HIGH_PRIORITY = 7600
CREDITS_STANDARD = 3800

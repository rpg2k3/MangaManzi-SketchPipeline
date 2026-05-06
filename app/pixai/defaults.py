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
DEFAULT_SAMPLING_STEPS = 28
DEFAULT_CFG_SCALE = 7.1
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 1280
DEFAULT_HIGH_PRIORITY = False
DEFAULT_BATCH_SIZE = 1

CREDITS_HIGH_PRIORITY = 7600
CREDITS_STANDARD = 3800

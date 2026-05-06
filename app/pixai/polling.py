"""Poll a PixAI generation task until it reaches a terminal status."""

import time

from .defaults import (
    DEFAULT_TASK_TIMEOUT_SEC,
    MAX_POLL_INTERVAL_SEC,
    MIN_POLL_INTERVAL_SEC,
    POLL_BACKOFF_FACTOR,
)
from .errors import PixAIError, PixAITaskFailedError, PixAITimeoutError

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
SUCCESS_STATUSES = {"completed"}

# After PixAI accepts a task it can take a couple of seconds to propagate to
# the read API. We tolerate a small number of `task: null` polls as transient
# before declaring the task dead.
NULL_TASK_GRACE_POLLS = 5


def poll_until_complete(
    client,
    task_id: str,
    timeout: float = DEFAULT_TASK_TIMEOUT_SEC,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> dict:
    """Poll getTaskById until status is terminal or timeout.

    Raises PixAIError if PixAI repeatedly returns `task: null` for the
    requested id — typically caused by the worker rejecting the task
    post-validation (e.g. an unsupported `modelId`).

    `sleep_fn`/`monotonic_fn` are injectable for tests.
    """
    start = monotonic_fn()
    interval = MIN_POLL_INTERVAL_SEC
    null_polls = 0
    while True:
        if monotonic_fn() - start > timeout:
            raise PixAITimeoutError(f"Task {task_id} did not complete within {timeout}s")
        sleep_fn(interval)
        task = client.get_task_by_id(task_id)
        if task is None:
            null_polls += 1
            if null_polls >= NULL_TASK_GRACE_POLLS:
                raise PixAIError(
                    f"PixAI returned task=null {null_polls} consecutive polls for "
                    f"id={task_id}. The task was likely rejected post-validation — "
                    "most common cause is an unsupported `modelId` (base checkpoint)."
                )
            interval = min(interval * POLL_BACKOFF_FACTOR, MAX_POLL_INTERVAL_SEC)
            continue
        null_polls = 0
        status = (task.get("status") or "").lower()
        if status in TERMINAL_STATUSES:
            if status not in SUCCESS_STATUSES:
                raise PixAITaskFailedError(
                    f"Task {task_id} ended with status={status}", raw_task=task
                )
            return task
        interval = min(interval * POLL_BACKOFF_FACTOR, MAX_POLL_INTERVAL_SEC)

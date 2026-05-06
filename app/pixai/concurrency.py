"""Process-wide cap on in-flight PixAI tasks (PixAI hard limit: 10)."""

import threading

from .defaults import MAX_IN_FLIGHT_TASKS

_inflight_semaphore = threading.BoundedSemaphore(MAX_IN_FLIGHT_TASKS)


class inflight_slot:
    """Context manager: blocks until a PixAI task slot is free."""

    def __enter__(self):
        _inflight_semaphore.acquire()
        return self

    def __exit__(self, *_):
        _inflight_semaphore.release()

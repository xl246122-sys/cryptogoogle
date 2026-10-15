"""Context-local replay time: never mutate the process clock used by other threads."""
import time
from contextvars import ContextVar
from contextlib import contextmanager

_at = ContextVar('evaluation_time_ms', default=None)

class Clock:
    def time(self):
        value = _at.get()
        return time.time() if value is None else value / 1000

clock = Clock()

@contextmanager
def at_time(timestamp_ms):
    if not isinstance(timestamp_ms, int) or timestamp_ms <= 0:
        raise ValueError('Positive integer evaluation timestamp required')
    token = _at.set(timestamp_ms)
    try:
        yield
    finally:
        _at.reset(token)

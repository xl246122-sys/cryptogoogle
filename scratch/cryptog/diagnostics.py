"""Capture every evaluation's first explicit rejection without global logger state."""
from contextvars import ContextVar
from contextlib import contextmanager

_reasons = ContextVar('rejection_reasons', default=None)

def reject(reason):
    reasons = _reasons.get()
    if reasons is not None:
        reasons.append(reason)

@contextmanager
def capture():
    reasons = []
    token = _reasons.set(reasons)
    try:
        yield reasons
    finally:
        _reasons.reset(token)

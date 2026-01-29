"""Simple startup timing profiler for jobrunner."""

# pylint: disable=global-statement
from contextlib import contextmanager
from functools import wraps
import os
import sys
import time
from typing import List, Optional, Tuple

import jobrunner.logging

LOG = jobrunner.logging.getLogger(__name__)

# Only enable timing if JOBRUNNER_PROFILE environment variable is set
_ENABLED = os.environ.get("JOBRUNNER_PROFILE") == "1"

_start_time: Optional[float] = None
_last_checkpoint: Optional[float] = None
_buffered_checkpoints: List[Tuple[str, float, float]] = []
_logging_ready = False


def start_profiling(start_time: Optional[float] = None) -> None:
    """Initialize the profiling timer."""
    if not _ENABLED:
        return
    global _start_time, _last_checkpoint
    if start_time is not None:
        _start_time = start_time
    else:
        _start_time = time.perf_counter()
    _last_checkpoint = _start_time


def checkpoint(label: str) -> None:
    """Log time since last checkpoint and since start."""
    if not _ENABLED or _start_time is None:
        return

    global _last_checkpoint
    now = time.perf_counter()
    delta = (now - _last_checkpoint) * 1000  # ms
    total = (now - _start_time) * 1000  # ms

    if _logging_ready:
        LOG.debug("TIMING: %s: +%.1fms (total: %.1fms)", label, delta, total)
    else:
        _buffered_checkpoints.append((label, delta, total))
        print(
            f"TIMING: {label}: +{delta:.1f}ms (total: {total:.1f}ms)",
            file=sys.stderr,
        )

    _last_checkpoint = now


def flush_buffered_checkpoints() -> None:
    """Flush buffered checkpoints to the logger once logging is ready."""
    if not _ENABLED:
        return
    global _logging_ready
    _logging_ready = True
    for label, delta, total in _buffered_checkpoints:
        LOG.debug("TIMING: %s: +%.1fms (total: %.1fms)", label, delta, total)


@contextmanager
def timed_section(label: str):
    """Context manager to time a code section."""
    checkpoint(f"{label} - start")
    try:
        yield
    finally:
        checkpoint(f"{label} - end")


def timed_function(func):
    """Decorator to time a function call."""
    if not _ENABLED:
        # When profiling is disabled, return the function unchanged
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract class name if this is a method
        class_name = ""
        if args and hasattr(args[0], "__class__"):
            class_name = f"{args[0].__class__.__name__}."

        label = f"{class_name}{func.__name__}"
        with timed_section(label):
            return func(*args, **kwargs)

    return wrapper

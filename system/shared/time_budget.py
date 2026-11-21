"""Where the 30-minute brief goes.

PR 10 put every model call on one ``OpenRouterClient``. That client's
``DEFAULT_TIME_CAP_SECONDS`` is 1,200 (tested). It is one clock for the whole
run, not a Stage 2 cap stacked on Stage 1. A separate 1,200 second Stage 2
cap was too tight against the brief: Stages 3 and 4 would have had no slack. Sharing the clock leaves 10 minutes for the deterministic
stages after the backstop fires.

The call budget (48 for the run, 12 for one extraction) decides how much
work is attempted. The clock only stops a stuck call.

``arm_run_deadline`` is a second backstop at 25 minutes. It stays disarmed
in unit tests. ``system/run`` arms it.
"""

from __future__ import annotations

import time

RUN_LIMIT_SECONDS = 30 * 60
RUN_DEADLINE_SECONDS = 25 * 60
SHARED_TIME_CAP_SECONDS = 1200.0

_deadline: float | None = None
_deadline_hit = False


def arm_run_deadline(seconds: float = RUN_DEADLINE_SECONDS) -> None:
    global _deadline, _deadline_hit
    _deadline = time.monotonic() + seconds
    _deadline_hit = False


def clear_run_deadline() -> None:
    global _deadline, _deadline_hit
    _deadline = None
    _deadline_hit = False


def run_deadline_hit() -> bool:
    global _deadline_hit
    if _deadline is not None and time.monotonic() >= _deadline:
        _deadline_hit = True
        return True
    return False


def deadline_fired() -> bool:
    return _deadline_hit

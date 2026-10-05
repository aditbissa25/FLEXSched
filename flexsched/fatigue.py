"""Python mirror of the C++ fatigue model (engine/src/fatigue.cpp).

Why duplicate it? The ML model needs ``fatigue_at_start`` for every
historical work session, i.e. "how tired was the user when they began this
task?". Python reconstructs that by replaying the day's sessions through
the same formulas the engine uses. tests/test_parity.py runs both
implementations on the same input and asserts they agree.

    work:  F' = 1 - (1 - F) * exp(-work_rate * (difficulty/5) * minutes)
    rest:  F' = F * exp(-recovery_rate * minutes)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

from .config import DEFAULT_PARAMS, SchedulerParams


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def after_work(fatigue: float, difficulty: int, minutes: float,
               params: SchedulerParams = DEFAULT_PARAMS) -> float:
    if minutes <= 0:
        return _clamp01(fatigue)
    load = min(5, max(1, difficulty)) / 5.0
    decay = math.exp(-params.work_rate * load * minutes)
    return _clamp01(1.0 - (1.0 - _clamp01(fatigue)) * decay)


def after_rest(fatigue: float, minutes: float,
               params: SchedulerParams = DEFAULT_PARAMS) -> float:
    if minutes <= 0:
        return _clamp01(fatigue)
    return _clamp01(_clamp01(fatigue) * math.exp(-params.recovery_rate * minutes))


def replay_day(sessions: Iterable[tuple[datetime, datetime, int]],
               params: SchedulerParams = DEFAULT_PARAMS) -> list[float]:
    """Return fatigue at the start of each (start, end, difficulty) session.

    Sessions must be from the same day and sorted by start time. The day
    starts fresh (F = 0); gaps between sessions count as rest.
    """
    fatigue = 0.0
    previous_end: datetime | None = None
    result: list[float] = []
    for start, end, difficulty in sessions:
        if previous_end is not None:
            gap = (start - previous_end).total_seconds() / 60
            fatigue = after_rest(fatigue, gap, params)
        result.append(fatigue)
        worked = (end - start).total_seconds() / 60
        fatigue = after_work(fatigue, difficulty, worked, params)
        previous_end = end
    return result

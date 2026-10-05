"""Domain objects as dataclasses.

A dataclass is a normal Python class where ``__init__``, ``__repr__`` and
``__eq__`` are generated from the type-annotated fields. They make the rest
of the code read like "task.difficulty" instead of "row[3]".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Task:
    title: str
    category: str
    difficulty: int          # 1..5
    priority: int            # 1..5
    estimate_min: int        # the user's own guess, in minutes
    deadline: Optional[datetime] = None
    status: str = "pending"  # pending | scheduled | done | cancelled
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class WorkSession:
    """One uninterrupted stretch of work on a task (the ML training unit)."""

    task_id: int
    started_at: datetime
    ended_at: datetime
    fatigue_at_start: Optional[float] = None
    id: Optional[int] = None

    @property
    def actual_min(self) -> int:
        return int(round((self.ended_at - self.started_at).total_seconds() / 60))


@dataclass
class PlannedBlock:
    """One row of a generated timetable (a task or a break)."""

    kind: str                       # "task" | "break"
    start: datetime
    end: datetime
    fatigue_start: float
    fatigue_end: float
    task_id: Optional[int] = None
    late: bool = False
    title: str = ""


@dataclass
class PlanResult:
    strategy: str
    blocks: list[PlannedBlock] = field(default_factory=list)
    unscheduled: list[tuple[int, str]] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    run_id: Optional[int] = None

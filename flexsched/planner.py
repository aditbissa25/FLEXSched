"""Planner: the orchestration layer (service layer).

    SQLite (pending tasks)  --->  ML predictor (duration curves)
              |                              |
              +-------> engine request <-----+
                              |
                     C++ engine (schedule)
                              |
            datetimes, titles, persistence  <-+

It also owns ``log_session``: recording real work and reconstructing the
fatigue level at the start of each session (the ML feature).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from . import config
from .config import SchedulerParams
from .engine_bridge import run_engine
from .fatigue import replay_day
from .models import PlanResult, PlannedBlock, Task, WorkSession
from .predictor import DurationPredictor, heuristic_curve
from .repository import ScheduleRepository, SessionRepository, TaskRepository

STRATEGIES = ("fatigue_aware", "edf")
NO_DEADLINE_PADDING = timedelta(days=30)


def minutes_between(origin: datetime, moment: datetime) -> int:
    return int((moment - origin).total_seconds() // 60)


def work_windows(start: date, days: int, day_start: time, day_end: time,
                 skip_weekends: bool = False) -> list[tuple[datetime, datetime]]:
    if day_end <= day_start:
        raise ValueError("day_end must be after day_start")
    windows = []
    for i in range(days):
        day = start + timedelta(days=i)
        if skip_weekends and day.weekday() >= 5:
            continue
        windows.append((datetime.combine(day, day_start), datetime.combine(day, day_end)))
    return windows


def build_request(tasks: list[Task], origin: datetime, horizon_end: datetime,
                  windows: list[tuple[datetime, datetime]],
                  blocked: list[tuple[datetime, datetime]],
                  strategy: str, params: SchedulerParams,
                  predictor: Optional[DurationPredictor]) -> dict:
    """Translate Python objects into the engine's JSON contract (minute offsets)."""
    no_deadline = minutes_between(origin, horizon_end + NO_DEADLINE_PADDING)
    curves = (predictor.duration_curves(tasks, day_of_week=_sqlite_weekday(origin))
              if predictor else [heuristic_curve(t) for t in tasks])
    engine_tasks = []
    for t, curve in zip(tasks, curves):
        engine_tasks.append({
            "id": t.id,
            "difficulty": t.difficulty,
            "priority": t.priority,
            "deadline": minutes_between(origin, t.deadline) if t.deadline else no_deadline,
            "duration_curve": curve,
        })
    return {
        "strategy": strategy,
        "params": params.to_dict(),
        "windows": [{"start": minutes_between(origin, a), "end": minutes_between(origin, b)}
                    for a, b in windows],
        "blocked": [{"start": minutes_between(origin, a), "end": minutes_between(origin, b)}
                    for a, b in blocked],
        "tasks": engine_tasks,
    }


def _sqlite_weekday(d: datetime) -> int:
    """SQLite's strftime('%w'): Sunday=0 .. Saturday=6 (Python: Monday=0)."""
    return (d.weekday() + 1) % 7


def plan(conn: sqlite3.Connection, start: date, days: int = 1,
         strategy: str = "fatigue_aware", day_start: time = time(9, 0),
         day_end: time = time(17, 0), blocked: Iterable[tuple[datetime, datetime]] = (),
         params: SchedulerParams = config.DEFAULT_PARAMS,
         predictor: Optional[DurationPredictor] = None, persist: bool = True,
         skip_weekends: bool = False) -> PlanResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    if days < 1:
        raise ValueError("days must be >= 1")

    task_repo = TaskRepository(conn)
    tasks = task_repo.list(["pending", "scheduled"])
    origin = datetime.combine(start, time(0, 0))
    horizon_end = origin + timedelta(days=days)
    windows = work_windows(start, days, day_start, day_end, skip_weekends)
    blocked = list(blocked)

    request = build_request(tasks, origin, horizon_end, windows, blocked,
                            strategy, params, predictor)
    response = run_engine(request)

    titles = {t.id: t.title for t in tasks}
    result = PlanResult(strategy=strategy, metrics=response["metrics"])
    for b in response["blocks"]:
        result.blocks.append(PlannedBlock(
            kind=b["kind"],
            start=origin + timedelta(minutes=b["start"]),
            end=origin + timedelta(minutes=b["end"]),
            fatigue_start=b["fatigue_start"],
            fatigue_end=b["fatigue_end"],
            task_id=b.get("task_id"),
            late=b.get("late", False),
            title=titles.get(b.get("task_id"), "Break"),
        ))
    result.unscheduled = [(u["task_id"], u["reason"]) for u in response["unscheduled"]]

    if persist:
        ScheduleRepository(conn).save(result, origin, days)
        task_repo.set_status([b.task_id for b in result.blocks if b.kind == "task"],
                             "scheduled")
        task_repo.set_status([tid for tid, _ in result.unscheduled], "pending")
    return result


def compare(conn: sqlite3.Connection, start: date, days: int = 1,
            **kwargs) -> dict[str, PlanResult]:
    """Run every strategy on the same tasks without saving anything."""
    kwargs["persist"] = False
    return {s: plan(conn, start, days, strategy=s, **kwargs) for s in STRATEGIES}


def log_session(conn: sqlite3.Connection, task_id: int, started_at: datetime,
                minutes: int, mark_done: bool = True,
                params: SchedulerParams = config.DEFAULT_PARAMS) -> WorkSession:
    """Record real work and refresh fatigue_at_start for that whole day.

    Recomputing the entire day (not just the new row) keeps the data correct
    even if sessions are logged out of order.
    """
    task_repo = TaskRepository(conn)
    if task_repo.get(task_id) is None:
        raise ValueError(f"task {task_id} does not exist")
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    sessions = SessionRepository(conn)
    session = sessions.add(WorkSession(task_id=task_id, started_at=started_at,
                                       ended_at=started_at + timedelta(minutes=minutes)),
                           commit=False)
    day_rows = sessions.for_day(started_at.date())
    fatigue = replay_day([(s.started_at, s.ended_at, diff) for s, diff in day_rows], params)
    conn.executemany("UPDATE work_sessions SET fatigue_at_start = ? WHERE id = ?",
                     [(round(f, 6), s.id) for (s, _), f in zip(day_rows, fatigue)])
    if mark_done:
        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    conn.commit()
    fatigue_by_id = {s.id: f for (s, _), f in zip(day_rows, fatigue)}
    session.fatigue_at_start = fatigue_by_id[session.id]
    return session

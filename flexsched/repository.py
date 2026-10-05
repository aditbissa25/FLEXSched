"""Repository layer: the ONLY place that contains SQL.

Repository pattern: the rest of the program asks for domain objects
("give me the pending tasks") and never sees SQL or sqlite3 rows. If we
later swap SQLite for PostgreSQL, only this file has to change.

All queries use ``?`` placeholders (parameterised queries). Never build SQL
with f-strings from user input - that is how SQL injection happens.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from . import config
from .db import from_db_time, to_db_time
from .models import PlanResult, Task, WorkSession

VALID_STATUSES = ("pending", "scheduled", "done", "cancelled")


def validate_task(task: Task) -> None:
    """Application-level validation with friendly messages.

    The database CHECK constraints enforce the same rules (defence in depth),
    but their error messages are cryptic, so we check first.
    """
    if not task.title or not task.title.strip():
        raise ValueError("title must not be empty")
    if task.category not in config.CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(config.CATEGORIES)}")
    if not 1 <= task.difficulty <= 5:
        raise ValueError("difficulty must be between 1 and 5")
    if not 1 <= task.priority <= 5:
        raise ValueError("priority must be between 1 and 5")
    if task.estimate_min <= 0:
        raise ValueError("estimate must be a positive number of minutes")
    if task.status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        difficulty=row["difficulty"],
        priority=row["priority"],
        estimate_min=row["estimate_min"],
        deadline=from_db_time(row["deadline"]),
        status=row["status"],
        created_at=from_db_time(row["created_at"]),
    )


class TaskRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, task: Task) -> Task:
        validate_task(task)
        cur = self.conn.execute(
            """INSERT INTO tasks (title, category, difficulty, priority,
                                  estimate_min, deadline, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task.title.strip(), task.category, task.difficulty, task.priority,
             task.estimate_min, to_db_time(task.deadline), task.status),
        )
        self.conn.commit()
        task.id = cur.lastrowid
        return task

    def get(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list(self, statuses: Optional[Iterable[str]] = None) -> list[Task]:
        if statuses is None:
            rows = self.conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        else:
            statuses = list(statuses)
            marks = ",".join("?" for _ in statuses)  # "?,?,?" - still parameterised
            rows = self.conn.execute(
                f"SELECT * FROM tasks WHERE status IN ({marks}) ORDER BY id", statuses
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def set_status(self, task_ids: Iterable[int], status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        self.conn.executemany(
            "UPDATE tasks SET status = ? WHERE id = ?", [(status, i) for i in task_ids]
        )
        self.conn.commit()


class SessionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, session: WorkSession, commit: bool = True) -> WorkSession:
        if session.ended_at <= session.started_at:
            raise ValueError("a session must end after it starts")
        cur = self.conn.execute(
            """INSERT INTO work_sessions (task_id, started_at, ended_at,
                                          actual_min, fatigue_at_start)
               VALUES (?, ?, ?, ?, ?)""",
            (session.task_id, to_db_time(session.started_at), to_db_time(session.ended_at),
             session.actual_min, session.fatigue_at_start),
        )
        if commit:
            self.conn.commit()
        session.id = cur.lastrowid
        return session

    def for_day(self, day: date) -> list[tuple[WorkSession, int]]:
        """Sessions on a calendar day with their task difficulty, in time order."""
        start = datetime.combine(day, datetime.min.time())
        rows = self.conn.execute(
            """SELECT s.*, t.difficulty
               FROM work_sessions s JOIN tasks t ON t.id = s.task_id
               WHERE s.started_at >= ? AND s.started_at < ?
               ORDER BY s.started_at""",
            (to_db_time(start), to_db_time(start + timedelta(days=1))),
        ).fetchall()
        return [
            (WorkSession(id=r["id"], task_id=r["task_id"],
                         started_at=from_db_time(r["started_at"]),
                         ended_at=from_db_time(r["ended_at"]),
                         fatigue_at_start=r["fatigue_at_start"]), r["difficulty"])
            for r in rows
        ]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0]

    # SQL used to build the ML training set: a JOIN plus feature extraction
    # done directly in SQL with strftime().
    TRAINING_SQL = """
        SELECT s.id                                      AS session_id,
               t.category, t.difficulty, t.priority, t.estimate_min,
               s.started_at, s.actual_min, s.fatigue_at_start,
               CAST(strftime('%H', s.started_at) AS INTEGER) AS hour_of_day,
               CAST(strftime('%w', s.started_at) AS INTEGER) AS day_of_week
        FROM work_sessions s
        JOIN tasks t ON t.id = s.task_id
        WHERE s.fatigue_at_start IS NOT NULL
        ORDER BY s.started_at
    """

    # Aggregation query: how wrong are the user's estimates, per category?
    ESTIMATION_BIAS_SQL = """
        SELECT t.category,
               COUNT(*)                                       AS sessions,
               ROUND(AVG(t.estimate_min), 1)                  AS avg_estimate,
               ROUND(AVG(s.actual_min), 1)                    AS avg_actual,
               ROUND(AVG(1.0 * s.actual_min / t.estimate_min), 3) AS avg_ratio
        FROM work_sessions s
        JOIN tasks t ON t.id = s.task_id
        GROUP BY t.category
        HAVING COUNT(*) >= 1
        ORDER BY avg_ratio DESC
    """

    def estimation_bias(self) -> list[sqlite3.Row]:
        return self.conn.execute(self.ESTIMATION_BIAS_SQL).fetchall()


class ScheduleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, plan: PlanResult, horizon_start: datetime, horizon_days: int) -> int:
        """Store a run and all its blocks in ONE transaction (all or nothing)."""
        with self.conn:  # commits on success, rolls back on exception
            cur = self.conn.execute(
                """INSERT INTO schedule_runs (strategy, horizon_start, horizon_days, metrics_json)
                   VALUES (?, ?, ?, ?)""",
                (plan.strategy, to_db_time(horizon_start), horizon_days,
                 json.dumps(plan.metrics)),
            )
            run_id = cur.lastrowid
            self.conn.executemany(
                """INSERT INTO schedule_items (run_id, task_id, kind, start_at, end_at,
                                               fatigue_start, fatigue_end, is_late)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(run_id, b.task_id, b.kind, to_db_time(b.start), to_db_time(b.end),
                  b.fatigue_start, b.fatigue_end, int(b.late)) for b in plan.blocks],
            )
        plan.run_id = run_id
        return run_id

    def runs(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT r.id, r.created_at, r.strategy, r.horizon_start, r.horizon_days,
                      r.metrics_json, COUNT(i.id) AS items
               FROM schedule_runs r LEFT JOIN schedule_items i ON i.run_id = r.id
               GROUP BY r.id
               ORDER BY r.id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

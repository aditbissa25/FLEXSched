import sqlite3
from datetime import datetime, timedelta

import pytest

from flexsched.models import PlanResult, PlannedBlock, Task, WorkSession
from flexsched.repository import ScheduleRepository, SessionRepository, TaskRepository


def make_task(**overrides) -> Task:
    fields = dict(title="Write tests", category="coding", difficulty=3, priority=3,
                  estimate_min=45)
    fields.update(overrides)
    return Task(**fields)


def test_add_and_get_round_trip(conn):
    repo = TaskRepository(conn)
    deadline = datetime(2026, 10, 8, 17, 0)
    task = repo.add(make_task(deadline=deadline))
    assert task.id is not None
    loaded = repo.get(task.id)
    assert loaded.title == "Write tests"
    assert loaded.deadline == deadline
    assert loaded.status == "pending"
    assert loaded.created_at is not None


def test_get_missing_returns_none(conn):
    assert TaskRepository(conn).get(999) is None


@pytest.mark.parametrize("field,value", [
    ("title", "   "), ("category", "gaming"), ("difficulty", 0), ("difficulty", 6),
    ("priority", 9), ("estimate_min", 0), ("status", "archived"),
])
def test_validation_rejects_bad_tasks(conn, field, value):
    with pytest.raises(ValueError):
        TaskRepository(conn).add(make_task(**{field: value}))


def test_database_constraints_are_a_second_line_of_defence(conn):
    # Bypass the Python validation: the CHECK constraint must still refuse it.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (title, category, difficulty, priority, estimate_min)"
                     " VALUES ('x', 'coding', 7, 3, 30)")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work_sessions (task_id, started_at, ended_at, actual_min)"
                     " VALUES (12345, '2026-01-01 09:00:00', '2026-01-01 10:00:00', 60)")


def test_list_filters_by_status(conn):
    repo = TaskRepository(conn)
    a = repo.add(make_task(title="a"))
    b = repo.add(make_task(title="b"))
    repo.set_status([b.id], "done")
    assert [t.title for t in repo.list(["pending"])] == ["a"]
    assert {t.title for t in repo.list()} == {"a", "b"}
    assert repo.list(["cancelled"]) == []
    assert a.id < b.id


def test_session_requires_positive_duration(conn):
    task = TaskRepository(conn).add(make_task())
    start = datetime(2026, 10, 1, 9, 0)
    with pytest.raises(ValueError):
        SessionRepository(conn).add(WorkSession(task.id, start, start))


def test_for_day_returns_only_that_day_in_order(conn):
    task = TaskRepository(conn).add(make_task())
    repo = SessionRepository(conn)
    day = datetime(2026, 10, 1)
    for hour in (14, 9, 11):
        s = day + timedelta(hours=hour)
        repo.add(WorkSession(task.id, s, s + timedelta(minutes=30)))
    other = day + timedelta(days=1, hours=9)
    repo.add(WorkSession(task.id, other, other + timedelta(minutes=30)))

    rows = repo.for_day(day.date())
    assert [s.started_at.hour for s, _ in rows] == [9, 11, 14]
    assert all(diff == 3 for _, diff in rows)


def test_estimation_bias_groups_by_category(conn):
    tasks = TaskRepository(conn)
    sessions = SessionRepository(conn)
    start = datetime(2026, 10, 1, 9, 0)
    coding = tasks.add(make_task(category="coding", estimate_min=60))
    admin = tasks.add(make_task(category="admin", estimate_min=60))
    sessions.add(WorkSession(coding.id, start, start + timedelta(minutes=90)))
    sessions.add(WorkSession(admin.id, start, start + timedelta(minutes=30)))
    rows = {r["category"]: r for r in sessions.estimation_bias()}
    assert rows["coding"]["avg_ratio"] == pytest.approx(1.5)
    assert rows["admin"]["avg_ratio"] == pytest.approx(0.5)


def test_schedule_save_is_atomic_and_complete(conn):
    task = TaskRepository(conn).add(make_task())
    t0 = datetime(2026, 10, 7, 9, 0)
    plan = PlanResult(strategy="edf", metrics={"tasks_scheduled": 1}, blocks=[
        PlannedBlock("task", t0, t0 + timedelta(minutes=45), 0.0, 0.3, task_id=task.id),
        PlannedBlock("break", t0 + timedelta(minutes=45), t0 + timedelta(minutes=60), 0.3, 0.1),
    ])
    run_id = ScheduleRepository(conn).save(plan, t0, 1)
    assert plan.run_id == run_id
    items = conn.execute("SELECT kind, task_id FROM schedule_items WHERE run_id = ?",
                         (run_id,)).fetchall()
    assert [(r["kind"], r["task_id"]) for r in items] == [("task", task.id), ("break", None)]
    runs = ScheduleRepository(conn).runs()
    assert runs[0]["items"] == 2


def test_schedule_save_rolls_back_on_error(conn):
    t0 = datetime(2026, 10, 7, 9, 0)
    bad = PlanResult(strategy="edf", blocks=[
        PlannedBlock("not-a-kind", t0, t0 + timedelta(minutes=5), 0.0, 0.0)])
    with pytest.raises(sqlite3.IntegrityError):
        ScheduleRepository(conn).save(bad, t0, 1)
    # The run row inserted before the failure must have been rolled back too.
    assert conn.execute("SELECT COUNT(*) FROM schedule_runs").fetchone()[0] == 0


def test_schema_version_is_recorded(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

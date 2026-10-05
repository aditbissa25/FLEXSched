"""Tests that talk to the real compiled C++ engine via the JSON bridge."""

from datetime import date, datetime, time, timedelta

import pytest

from conftest import requires_engine
from flexsched.config import DEFAULT_PARAMS
from flexsched.engine_bridge import EngineInputError, run_engine
from flexsched.fatigue import after_rest, after_work
from flexsched.models import Task
from flexsched.planner import build_request, compare, log_session, plan, work_windows
from flexsched.repository import TaskRepository

pytestmark = requires_engine  # skip the whole module if the engine is not built


def test_engine_rejects_invalid_request_with_clear_error():
    with pytest.raises(EngineInputError, match="difficulty"):
        run_engine({"windows": [{"start": 0, "end": 60}],
                    "tasks": [{"id": 1, "difficulty": 9, "priority": 3, "deadline": 50,
                               "duration_curve": [10]}]})


def test_engine_rejects_unknown_strategy():
    with pytest.raises(EngineInputError, match="strategy"):
        run_engine({"strategy": "magic"})


def test_python_and_cpp_fatigue_models_agree():
    """Cross-language parity: replay the engine's blocks with the Python model."""
    origin = datetime(2030, 1, 7)
    tasks = [Task(f"t{i}", "coding", d, 3, est, id=i)
             for i, (d, est) in enumerate([(5, 90), (2, 30), (4, 60), (1, 20), (3, 45)], 1)]
    windows = work_windows(origin.date(), 1, time(9), time(17))
    request = build_request(tasks, origin, origin + timedelta(days=1), windows, [],
                            "fatigue_aware", DEFAULT_PARAMS, predictor=None)
    response = run_engine(request)
    difficulty = {t.id: t.difficulty for t in tasks}

    fatigue, clock = 0.0, response["blocks"][0]["start"]
    for block in response["blocks"]:
        fatigue = after_rest(fatigue, block["start"] - clock)
        assert block["fatigue_start"] == pytest.approx(fatigue, abs=1e-9)
        minutes = block["end"] - block["start"]
        if block["kind"] == "task":
            fatigue = after_work(fatigue, difficulty[block["task_id"]], minutes)
        else:
            fatigue = after_rest(fatigue, minutes)
        assert block["fatigue_end"] == pytest.approx(fatigue, abs=1e-9)
        clock = block["end"]


def _add_tasks(conn, start: date):
    repo = TaskRepository(conn)
    origin = datetime.combine(start, time())
    repo.add(Task("Hard and due", "coding", 5, 5, 90, origin + timedelta(hours=12)))
    repo.add(Task("Easy", "admin", 1, 2, 20))
    repo.add(Task("Medium", "writing", 3, 3, 45, origin + timedelta(days=1, hours=17)))
    repo.add(Task("Too long", "study", 3, 3, 1000))


def test_plan_end_to_end_persists_and_updates_statuses(conn):
    start = date(2030, 1, 7)
    _add_tasks(conn, start)
    blocked = [(datetime(2030, 1, 7, 13), datetime(2030, 1, 7, 14))]
    result = plan(conn, start, days=2, blocked=blocked)

    task_blocks = [b for b in result.blocks if b.kind == "task"]
    assert {b.title for b in task_blocks} == {"Hard and due", "Easy", "Medium"}
    assert [tid for tid, _ in result.unscheduled] == [4]
    assert result.run_id is not None
    for b in result.blocks:  # nothing inside the blocked lunch hour
        assert b.end <= blocked[0][0] or b.start >= blocked[0][1]
        assert time(9) <= b.start.time() and b.end.time() <= time(17)

    statuses = {t.title: t.status for t in TaskRepository(conn).list()}
    assert statuses == {"Hard and due": "scheduled", "Easy": "scheduled",
                        "Medium": "scheduled", "Too long": "pending"}


def test_dry_run_does_not_persist(conn):
    _add_tasks(conn, date(2030, 1, 7))
    plan(conn, date(2030, 1, 7), persist=False)
    assert conn.execute("SELECT COUNT(*) FROM schedule_runs").fetchone()[0] == 0


def test_compare_runs_both_strategies_on_same_input(conn):
    _add_tasks(conn, date(2030, 1, 7))
    results = compare(conn, date(2030, 1, 7), days=2)
    assert set(results) == {"fatigue_aware", "edf"}
    assert results["edf"].metrics["breaks"] == 0


def test_log_session_reconstructs_fatigue_even_out_of_order(conn):
    repo = TaskRepository(conn)
    a = repo.add(Task("a", "coding", 5, 3, 60))
    b = repo.add(Task("b", "admin", 1, 3, 30))
    day = datetime(2030, 1, 8)
    # Log the LATER session first, then the earlier one.
    later = log_session(conn, b.id, day + timedelta(hours=11), 30)
    assert later.fatigue_at_start == 0.0  # alone in the day -> fresh
    log_session(conn, a.id, day + timedelta(hours=9), 60)
    refreshed = conn.execute("SELECT fatigue_at_start FROM work_sessions WHERE task_id = ?",
                             (b.id,)).fetchone()[0]
    expected = after_rest(after_work(0.0, 5, 60), 60)
    assert refreshed == pytest.approx(expected, abs=1e-6)
    assert repo.get(a.id).status == "done"


def test_log_session_validates_input(conn):
    with pytest.raises(ValueError):
        log_session(conn, 999, datetime(2030, 1, 8, 9), 30)

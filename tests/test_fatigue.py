import math
from datetime import datetime, timedelta

import pytest

from flexsched.fatigue import after_rest, after_work, replay_day


def test_work_formula_matches_documentation():
    assert after_work(0.0, 5, 60) == pytest.approx(1 - math.exp(-0.72))


def test_rest_formula_matches_documentation():
    assert after_rest(0.8, 15) == pytest.approx(0.8 * math.exp(-0.75))


def test_values_stay_in_unit_interval():
    assert after_work(0.9, 5, 10_000) <= 1.0
    assert after_rest(1.0, 10_000) >= 0.0
    assert after_work(3.0, 3, 5) <= 1.0
    assert after_rest(-1.0, 5) == 0.0


def test_harder_work_is_more_tiring():
    assert after_work(0.0, 5, 60) > after_work(0.0, 1, 60)


def test_replay_day_starts_fresh_and_accumulates():
    day = datetime(2026, 10, 1, 9, 0)
    sessions = [
        (day, day + timedelta(minutes=60), 5),
        (day + timedelta(minutes=60), day + timedelta(minutes=120), 5),   # no gap
        (day + timedelta(minutes=180), day + timedelta(minutes=200), 1),  # 60 min gap
    ]
    f = replay_day(sessions)
    assert f[0] == 0.0
    assert f[1] == pytest.approx(after_work(0.0, 5, 60))
    expected_third = after_rest(after_work(f[1], 5, 60), 60)
    assert f[2] == pytest.approx(expected_third)


def test_replay_empty_day():
    assert replay_day([]) == []

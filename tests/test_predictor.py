import pytest

from flexsched.db import connect
from flexsched.models import Task
from flexsched.predictor import (DurationPredictor, InsufficientDataError, heuristic_curve,
                                 load_training_frame, train)
from flexsched.synthetic import generate_history


@pytest.fixture(scope="module")
def trained(history_conn):
    return train(history_conn)


def test_training_frame_has_features_and_is_time_ordered(history_conn):
    df = load_training_frame(history_conn)
    assert {"category", "estimate_min", "fatigue_at_start", "hour_of_day",
            "day_of_week", "actual_min"} <= set(df.columns)
    assert df["started_at"].is_monotonic_increasing
    assert df["hour_of_day"].between(0, 23).all()


def test_too_little_data_raises(conn):
    generate_history(conn, days=3, seed=0)
    with pytest.raises(InsufficientDataError):
        train(conn)


def test_learned_model_beats_naive_baselines(trained):
    _, report = trained
    chosen = report.results[report.chosen_model]
    assert report.chosen_model not in ("trust_estimate", "mean_ratio")
    assert chosen["holdout_mae"] < report.results["trust_estimate"]["holdout_mae"]
    assert chosen["holdout_mae"] < report.results["mean_ratio"]["holdout_mae"]


def test_split_is_80_20(trained):
    _, report = trained
    assert report.train_rows + report.holdout_rows == report.rows
    assert report.holdout_rows == pytest.approx(0.2 * report.rows, abs=1)


def test_fatigue_and_difficulty_are_learned_as_important(trained):
    _, report = trained
    imp = report.feature_importance
    assert imp["fatigue_at_start"] > imp["day_of_week"]
    assert imp["difficulty"] > imp["day_of_week"]


def test_duration_curve_is_monotonic_and_positive(trained):
    predictor, _ = trained
    task = Task("x", "coding", 4, 3, 60)
    curve = predictor.duration_curve(task, day_of_week=2)
    assert len(curve) == 5
    assert all(v > 0 for v in curve)
    assert all(a <= b for a, b in zip(curve, curve[1:]))
    assert curve[-1] > curve[0]  # tired takes longer


def test_batch_prediction_matches_single(trained):
    predictor, _ = trained
    tasks = [Task("a", "admin", 1, 2, 20), Task("b", "design", 5, 5, 120)]
    batch = predictor.duration_curves(tasks, day_of_week=3)
    assert batch == [predictor.duration_curve(t, day_of_week=3) for t in tasks]
    assert predictor.duration_curves([], day_of_week=3) == []


def test_model_save_and_load_round_trip(trained, tmp_path):
    predictor, _ = trained
    path = predictor.save(tmp_path / "m.joblib")
    loaded = DurationPredictor.load(path)
    task = Task("x", "study", 3, 3, 45)
    assert loaded.model_name == predictor.model_name
    assert loaded.duration_curve(task, 1) == predictor.duration_curve(task, 1)


def test_loading_missing_model_returns_none(tmp_path):
    assert DurationPredictor.load(tmp_path / "nope.joblib") is None


def test_heuristic_curve_shape():
    assert heuristic_curve(Task("x", "admin", 1, 1, 40)) == [40.0, 45.0, 50.0, 55.0, 60.0]


def test_synthetic_generation_is_reproducible():
    a, b = connect(":memory:"), connect(":memory:")
    generate_history(a, days=10, seed=5, end_day=None)
    generate_history(b, days=10, seed=5, end_day=None)
    q = "SELECT actual_min, fatigue_at_start FROM work_sessions ORDER BY id"
    assert [tuple(r) for r in a.execute(q)] == [tuple(r) for r in b.execute(q)]

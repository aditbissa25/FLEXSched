"""Machine-learning duration prediction with scikit-learn.

Goal: given a task and the user's state, predict how many minutes it will
REALLY take (people are bad at estimating - the "planning fallacy").

Key design decisions (each one is an interview talking point):

1. Target = ratio actual / estimate, not raw minutes.
   The ratio is scale-free ("I take 1.3x my guess for coding"), so a
   pattern learnt on 30-minute tasks transfers to 120-minute tasks. Tree
   models cannot extrapolate beyond the target values they saw; predicting
   a ratio and multiplying back by the estimate side-steps that.

2. Temporal train/test split, not a random one.
   We train on the past and test on the most recent 20% of sessions,
   exactly how the model is used in reality. A random split would leak
   "future" information and give over-optimistic scores.

3. Model selection with TimeSeriesSplit cross-validation on the training
   part only. The hold-out set is touched once, for the final report.

4. Always compare against baselines: "just trust the estimate" and
   "multiply by the average ratio". A model is only useful if it beats them.

5. Fatigue is an input feature, so we can ask "how long at fatigue 0.0,
   0.25, ..., 1.0?" and give the engine a whole duration CURVE.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import config
from .models import Task
from .repository import SessionRepository

CATEGORICAL = ["category"]
NUMERIC = ["estimate_min", "difficulty", "priority", "fatigue_at_start",
           "hour_of_day", "day_of_week"]
FEATURES = CATEGORICAL + NUMERIC
MIN_TRAINING_ROWS = 40
DEFAULT_PLANNING_HOUR = 11  # hour used when the exact start time is not known yet


class InsufficientDataError(RuntimeError):
    pass


# --------------------------------------------------------------- data -----

def load_training_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    """Run the training SQL and return a DataFrame sorted by time."""
    df = pd.read_sql_query(SessionRepository.TRAINING_SQL, conn)
    df["started_at"] = pd.to_datetime(df["started_at"])
    return df.sort_values("started_at").reset_index(drop=True)


def to_ratio(df: pd.DataFrame) -> np.ndarray:
    return (df["actual_min"] / df["estimate_min"]).to_numpy(dtype=float)


# ------------------------------------------------------------- models -----

def _preprocessor(scale_numeric: bool) -> ColumnTransformer:
    numeric = StandardScaler() if scale_numeric else "passthrough"
    return ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("num", numeric, NUMERIC),
    ])


def candidate_models() -> dict[str, Pipeline]:
    """All models we compare. Each is a full Pipeline: preprocessing + regressor."""
    return {
        "trust_estimate": Pipeline([("pre", _preprocessor(False)),
                                    ("reg", DummyRegressor(strategy="constant",
                                                           constant=1.0))]),
        "mean_ratio": Pipeline([("pre", _preprocessor(False)),
                                ("reg", DummyRegressor(strategy="mean"))]),
        "ridge": Pipeline([("pre", _preprocessor(True)),
                           ("reg", Ridge(alpha=1.0))]),
        "random_forest": Pipeline([("pre", _preprocessor(False)),
                                   ("reg", RandomForestRegressor(
                                       n_estimators=200, min_samples_leaf=5,
                                       random_state=42, n_jobs=-1))]),
        "gradient_boosting": Pipeline([("pre", _preprocessor(False)),
                                       ("reg", GradientBoostingRegressor(
                                           n_estimators=300, learning_rate=0.05,
                                           max_depth=3, subsample=0.8,
                                           random_state=42))]),
    }


def _minutes_from_ratio(pipeline: Pipeline, X: pd.DataFrame) -> np.ndarray:
    ratio = np.clip(pipeline.predict(X[FEATURES]), 0.2, 5.0)  # guard against wild outputs
    return ratio * X["estimate_min"].to_numpy(dtype=float)


@dataclass
class TrainingReport:
    rows: int
    train_rows: int
    holdout_rows: int
    chosen_model: str
    results: dict[str, dict[str, float]] = field(default_factory=dict)
    feature_importance: dict[str, float] = field(default_factory=dict)


def train(conn: sqlite3.Connection, holdout_fraction: float = 0.2,
          n_splits: int = 5) -> tuple["DurationPredictor", TrainingReport]:
    df = load_training_frame(conn)
    if len(df) < MIN_TRAINING_ROWS:
        raise InsufficientDataError(
            f"need at least {MIN_TRAINING_ROWS} logged sessions to train, have {len(df)}")

    # 1. Temporal split: oldest 80% for training, newest 20% held out.
    cut = int(len(df) * (1 - holdout_fraction))
    train_df, hold_df = df.iloc[:cut], df.iloc[cut:]

    results: dict[str, dict[str, float]] = {}
    for name, model in candidate_models().items():
        # 2. Cross-validation that respects time order (folds only look backwards).
        fold_mae = []
        for tr_idx, va_idx in TimeSeriesSplit(n_splits=n_splits).split(train_df):
            tr, va = train_df.iloc[tr_idx], train_df.iloc[va_idx]
            model.fit(tr[FEATURES], to_ratio(tr))
            fold_mae.append(mean_absolute_error(va["actual_min"],
                                                _minutes_from_ratio(model, va)))

        # 3. Fit on the full training part, evaluate ONCE on the hold-out.
        model.fit(train_df[FEATURES], to_ratio(train_df))
        pred = _minutes_from_ratio(model, hold_df)
        results[name] = {
            "cv_mae": float(np.mean(fold_mae)),
            "holdout_mae": float(mean_absolute_error(hold_df["actual_min"], pred)),
            "holdout_mape": float(mean_absolute_percentage_error(hold_df["actual_min"], pred)),
            "holdout_r2": float(r2_score(hold_df["actual_min"], pred)),
        }

    # 4. Choose by cross-validation score (NOT by hold-out, which would leak).
    chosen = min(results, key=lambda n: results[n]["cv_mae"])

    # 5. Which features matter? Permutation importance on the hold-out set:
    #    shuffle one column, measure how much the error grows.
    chosen_model = candidate_models()[chosen].fit(train_df[FEATURES], to_ratio(train_df))
    importance: dict[str, float] = {}
    if chosen not in ("trust_estimate", "mean_ratio"):
        perm = permutation_importance(chosen_model, hold_df[FEATURES], to_ratio(hold_df),
                                      scoring="neg_mean_absolute_error",
                                      n_repeats=5, random_state=42)
        importance = {f: float(v) for f, v in zip(FEATURES, perm.importances_mean)}

    # 6. Final model: refit on ALL data so production uses everything we know.
    final = candidate_models()[chosen].fit(df[FEATURES], to_ratio(df))
    report = TrainingReport(rows=len(df), train_rows=len(train_df),
                            holdout_rows=len(hold_df), chosen_model=chosen,
                            results=results, feature_importance=importance)
    predictor = DurationPredictor(final, chosen, datetime.now(), report)
    return predictor, report


# ---------------------------------------------------------- inference -----

class DurationPredictor:
    """A trained pipeline plus the logic to turn it into duration curves."""

    def __init__(self, pipeline: Pipeline, model_name: str,
                 trained_at: datetime, report: Optional[TrainingReport] = None):
        self.pipeline = pipeline
        self.model_name = model_name
        self.trained_at = trained_at
        self.report = report

    def save(self, path: Union[str, Path, None] = None) -> Path:
        path = Path(path or config.MODEL_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "model_name": self.model_name,
                     "trained_at": self.trained_at, "report": self.report,
                     "sklearn_version": sklearn.__version__}, path)
        return path

    @classmethod
    def load(cls, path: Union[str, Path, None] = None) -> Optional["DurationPredictor"]:
        path = Path(path or config.MODEL_PATH)
        if not path.exists():
            return None
        blob = joblib.load(path)
        return cls(blob["pipeline"], blob["model_name"], blob["trained_at"], blob["report"])

    def duration_curves(self, tasks: list[Task], day_of_week: int,
                        hour: int = DEFAULT_PLANNING_HOUR) -> list[list[float]]:
        """Predicted minutes for each task at each level in config.FATIGUE_LEVELS.

        All tasks x all fatigue levels go through the model in ONE predict()
        call (vectorised). Calling predict() once per task would be ~10x slower
        because every call has fixed pandas/scikit-learn overhead.
        """
        if not tasks:
            return []
        levels = config.FATIGUE_LEVELS
        rows = pd.DataFrame([{
            "category": t.category, "estimate_min": t.estimate_min,
            "difficulty": t.difficulty, "priority": t.priority,
            "fatigue_at_start": f, "hour_of_day": hour, "day_of_week": day_of_week,
        } for t in tasks for f in levels])
        minutes = _minutes_from_ratio(self.pipeline, rows).reshape(len(tasks), len(levels))
        # Domain knowledge: being MORE tired never makes you FASTER. Tree models
        # can produce small non-monotonic wiggles, so enforce a rising curve
        # (running maximum along each row).
        minutes = np.maximum(np.maximum.accumulate(minutes, axis=1), 1.0)
        return [[round(float(m), 2) for m in row] for row in minutes]

    def duration_curve(self, task: Task, day_of_week: int,
                       hour: int = DEFAULT_PLANNING_HOUR) -> list[float]:
        return self.duration_curves([task], day_of_week, hour)[0]


def heuristic_curve(task: Task) -> list[float]:
    """Cold-start fallback when no model is trained: +50% at full fatigue."""
    return [round(task.estimate_min * (1.0 + 0.5 * f), 2) for f in config.FATIGUE_LEVELS]

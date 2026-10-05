"""Strategy benchmark: is fatigue-aware scheduling actually better than EDF?

One example proves nothing, so we generate many random-but-realistic
workloads, schedule each with BOTH strategies on identical input, and
compare the averages. Same seed -> same scenarios -> reproducible numbers.

Each scenario: 8-14 tasks, 2 working days (09:00-17:00) with a lunch block,
deadlines spread over the horizon, durations from the duration predictor
(or the heuristic curve if no model is trained).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from . import config
from .engine_bridge import run_engine
from .models import Task
from .planner import STRATEGIES, build_request
from .predictor import DurationPredictor

METRIC_KEYS = ("total_work_minutes", "makespan", "tasks_scheduled", "tasks_late",
               "total_lateness", "breaks", "peak_fatigue", "avg_fatigue_at_start")


@dataclass
class BenchmarkResult:
    scenarios: int
    means: dict[str, dict[str, float]]          # strategy -> metric -> mean
    paired_wins: dict[str, float]               # metric -> share of scenarios FA better


def random_tasks(rng: np.random.Generator, n: int, origin: datetime,
                 horizon_days: int) -> list[Task]:
    tasks = []
    for i in range(n):
        deadline_day = int(rng.integers(0, horizon_days + 1))
        deadline = origin + timedelta(days=deadline_day, hours=int(rng.integers(11, 18)))
        tasks.append(Task(
            id=i + 1,
            title=f"task {i + 1}",
            category=str(rng.choice(config.CATEGORIES)),
            difficulty=int(rng.integers(1, 6)),
            priority=int(rng.integers(1, 6)),
            estimate_min=int(rng.choice([20, 30, 45, 60, 90])),
            deadline=deadline if rng.random() < 0.8 else None,  # 20% have no deadline
        ))
    return tasks


def run_benchmark(scenarios: int = 100, seed: int = 7,
                  predictor: Optional[DurationPredictor] = None) -> BenchmarkResult:
    rng = np.random.default_rng(seed)
    origin = datetime(2030, 1, 7)  # a Monday; any fixed date keeps runs reproducible
    days = 2
    windows = [(origin + timedelta(days=d, hours=9), origin + timedelta(days=d, hours=17))
               for d in range(days)]
    blocked = [(origin + timedelta(days=d, hours=13), origin + timedelta(days=d, hours=13.75))
               for d in range(days)]

    per_strategy: dict[str, list[dict]] = {s: [] for s in STRATEGIES}
    for _ in range(scenarios):
        tasks = random_tasks(rng, int(rng.integers(8, 15)), origin, days)
        for strategy in STRATEGIES:
            request = build_request(tasks, origin, origin + timedelta(days=days), windows,
                                    blocked, strategy, config.DEFAULT_PARAMS, predictor)
            per_strategy[strategy].append(run_engine(request)["metrics"])

    means = {s: {k: float(np.mean([m[k] for m in rows])) for k in METRIC_KEYS}
             for s, rows in per_strategy.items()}

    # Paired comparison: in what share of scenarios is fatigue-aware strictly better?
    lower_is_better = ("total_work_minutes", "total_lateness", "tasks_late",
                       "avg_fatigue_at_start", "peak_fatigue")
    wins = {}
    for k in lower_is_better:
        fa = np.array([m[k] for m in per_strategy["fatigue_aware"]])
        edf = np.array([m[k] for m in per_strategy["edf"]])
        wins[k] = float(np.mean(fa < edf))
    fa_sched = np.array([m["tasks_scheduled"] for m in per_strategy["fatigue_aware"]])
    edf_sched = np.array([m["tasks_scheduled"] for m in per_strategy["edf"]])
    wins["tasks_scheduled"] = float(np.mean(fa_sched > edf_sched))
    return BenchmarkResult(scenarios=scenarios, means=means, paired_wins=wins)

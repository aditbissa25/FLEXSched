"""Synthetic work-history generator.

A brand-new user has no history, and a demo needs data. This module
simulates a person working through tasks for N days and writes the result
into the same tables real usage would fill (tasks + work_sessions).

The simulated person has HIDDEN habits that the ML model has to discover:
    * they underestimate some categories (coding x1.35) more than others (admin x0.9)
    * they underestimate hard tasks more (+8% per difficulty step above 3)
    * fatigue slows them down (up to +55% when exhausted)
    * there is a post-lunch dip (13:00-15:00 is ~10% slower)
    * plus random day-to-day noise (log-normal, ~12%)

Being honest about this matters in an interview: the ML results show the
model CAN recover such patterns; with real data the patterns are whatever
the real user's habits are.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import numpy as np

from . import config
from .db import to_db_time
from .fatigue import after_rest, after_work

CATEGORY_BIAS = {"coding": 1.35, "study": 1.10, "writing": 1.25,
                 "admin": 0.90, "review": 1.00, "design": 1.20}
ESTIMATE_CHOICES = np.array([15, 20, 30, 45, 60, 75, 90, 120])
ESTIMATE_WEIGHTS = np.array([6, 8, 14, 16, 18, 10, 9, 5], dtype=float)

TITLES = {
    "coding": ["Implement feature", "Fix bug", "Refactor module", "Write unit tests"],
    "study": ["Read paper", "Lecture revision", "Practice problems", "Course module"],
    "writing": ["Draft report", "Write documentation", "Blog post", "Edit chapter"],
    "admin": ["Answer emails", "Plan week", "Fill forms", "Expense report"],
    "review": ["Code review", "Review notes", "Proofread", "Check submissions"],
    "design": ["Sketch UI", "System design", "Architecture doc", "Wireframes"],
}


def true_duration(estimate: float, category: str, difficulty: int, priority: int,
                  fatigue: float, hour: int, rng: np.random.Generator) -> int:
    """The hidden 'ground truth' of how long the simulated person takes."""
    factor = CATEGORY_BIAS[category]
    factor *= 1.0 + 0.08 * (difficulty - 3)
    factor *= 1.0 - 0.03 * (priority - 3)          # urgent work gets more focus
    factor *= 1.0 + 0.55 * fatigue
    if 13 <= hour < 15:
        factor *= 1.10                              # post-lunch dip
    elif hour < 11:
        factor *= 0.95                              # fresh morning focus
    factor *= rng.lognormal(mean=0.0, sigma=0.12)
    return max(5, int(round(estimate * factor)))


def generate_history(conn: sqlite3.Connection, days: int = 120, seed: int = 42,
                     end_day: date | None = None) -> int:
    """Simulate `days` days of work ending yesterday. Returns sessions created."""
    rng = np.random.default_rng(seed)  # seeded -> reproducible results
    end_day = end_day or (date.today() - timedelta(days=1))
    start_day = end_day - timedelta(days=days - 1)
    probs = ESTIMATE_WEIGHTS / ESTIMATE_WEIGHTS.sum()

    sessions = 0
    with conn:  # one transaction for everything: fast and atomic
        for offset in range(days):
            day = start_day + timedelta(days=offset)
            weekend = day.weekday() >= 5
            n_tasks = int(rng.integers(0, 3) if weekend else rng.integers(3, 8))

            clock = datetime.combine(day, datetime.min.time()) + timedelta(
                hours=9, minutes=int(rng.integers(0, 46)))
            fatigue = 0.0
            took_lunch = False

            for _ in range(n_tasks):
                category = str(rng.choice(config.CATEGORIES))
                difficulty = int(rng.integers(1, 6))
                priority = int(rng.integers(1, 6))
                estimate = int(rng.choice(ESTIMATE_CHOICES, p=probs))
                title = f"{rng.choice(TITLES[category])} #{int(rng.integers(100, 999))}"

                fatigue_at_start = fatigue
                minutes = true_duration(estimate, category, difficulty, priority,
                                        fatigue, clock.hour, rng)
                start, end = clock, clock + timedelta(minutes=minutes)

                cur = conn.execute(
                    """INSERT INTO tasks (title, category, difficulty, priority,
                                          estimate_min, deadline, status, created_at)
                       VALUES (?, ?, ?, ?, ?, NULL, 'done', ?)""",
                    (title, category, difficulty, priority, estimate,
                     to_db_time(start - timedelta(days=int(rng.integers(0, 4))))),
                )
                conn.execute(
                    """INSERT INTO work_sessions (task_id, started_at, ended_at,
                                                  actual_min, fatigue_at_start)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cur.lastrowid, to_db_time(start), to_db_time(end), minutes,
                     round(fatigue_at_start, 6)),
                )
                sessions += 1

                # Advance the simulated clock and fatigue exactly like the engine would.
                fatigue = after_work(fatigue, difficulty, minutes)
                gap = int(rng.integers(0, 21))
                if not took_lunch and end.hour >= 12:
                    gap += int(rng.integers(40, 61))
                    took_lunch = True
                fatigue = after_rest(fatigue, gap)
                clock = end + timedelta(minutes=gap)
                if clock.hour >= 19:
                    break  # person stops working for the day
    return sessions

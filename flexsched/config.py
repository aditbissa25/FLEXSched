"""Central configuration: file locations and model parameters.

Every tunable number lives here so that there is exactly ONE source of truth.
The Python side sends these values to the C++ engine inside each request,
so the engine's compiled-in defaults are only a fallback.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Locations can be overridden with environment variables (handy for tests/CI).
DB_PATH = Path(os.environ.get("FLEXSCHED_DB", PROJECT_ROOT / "data" / "flexsched.db"))
MODEL_PATH = Path(
    os.environ.get("FLEXSCHED_MODEL", PROJECT_ROOT / "models" / "duration_model.joblib")
)

# Fatigue levels at which the ML model predicts a duration. The engine
# interpolates between these points (see engine/include/flexsched/duration.hpp).
FATIGUE_LEVELS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)

# Allowed task categories (mirrors the CHECK constraint in schema.sql).
CATEGORIES: tuple[str, ...] = ("coding", "study", "writing", "admin", "review", "design")


@dataclass(frozen=True)
class SchedulerParams:
    """Parameters of the fatigue model and the scheduling policy."""

    work_rate: float = 0.012       # fatigue gained per minute at full load
    recovery_rate: float = 0.05    # fraction of fatigue lost per minute of rest
    break_threshold: float = 0.65  # take a break when fatigue reaches this
    break_minutes: int = 15
    w_priority: float = 0.35
    w_urgency: float = 0.45
    w_energy: float = 0.20
    urgency_horizon: float = 480.0

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = SchedulerParams()

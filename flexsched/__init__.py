"""FLEXSched - fatigue-aware task scheduler and planner.

Python side responsibilities:
    * persistence (SQLite) of tasks, work history and generated schedules
    * machine-learning duration prediction (scikit-learn)
    * orchestration: turning database rows into an engine request and back
    * the command-line interface

The scheduling algorithm itself lives in the C++ engine (``engine/``).
"""

__version__ = "1.0.0"

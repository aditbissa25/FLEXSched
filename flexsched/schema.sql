-- FLEXSched database schema (SQLite).
-- Executed by flexsched/db.py; every statement is idempotent (IF NOT EXISTS),
-- so running it on an existing database is safe.

-- Tasks the user wants to get done.
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL CHECK (length(trim(title)) > 0),
    category      TEXT    NOT NULL
                  CHECK (category IN ('coding','study','writing','admin','review','design')),
    difficulty    INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
    priority      INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    estimate_min  INTEGER NOT NULL CHECK (estimate_min > 0),
    deadline      TEXT,                               -- ISO-8601 'YYYY-MM-DD HH:MM:SS' or NULL
    status        TEXT    NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','scheduled','done','cancelled')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- Historical record of actual work: the training data for the ML model.
CREATE TABLE IF NOT EXISTS work_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    started_at        TEXT    NOT NULL,
    ended_at          TEXT    NOT NULL,
    actual_min        INTEGER NOT NULL CHECK (actual_min > 0),
    fatigue_at_start  REAL    CHECK (fatigue_at_start BETWEEN 0 AND 1),
    CHECK (ended_at > started_at)
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON work_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON work_sessions(task_id);

-- Every time the planner runs we store the result, so plans can be compared later.
CREATE TABLE IF NOT EXISTS schedule_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    strategy       TEXT NOT NULL,
    horizon_start  TEXT NOT NULL,
    horizon_days   INTEGER NOT NULL CHECK (horizon_days > 0),
    metrics_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES schedule_runs(id) ON DELETE CASCADE,
    task_id        INTEGER REFERENCES tasks(id) ON DELETE SET NULL,  -- NULL for breaks
    kind           TEXT NOT NULL CHECK (kind IN ('task','break')),
    start_at       TEXT NOT NULL,
    end_at         TEXT NOT NULL,
    fatigue_start  REAL NOT NULL,
    fatigue_end    REAL NOT NULL,
    is_late        INTEGER NOT NULL DEFAULT 0 CHECK (is_late IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_items_run ON schedule_items(run_id);

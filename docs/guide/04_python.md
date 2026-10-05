
# Part 4 — Python package: code walkthrough

The package is **layered**: each module imports only from layers below it (never
upwards), so lower layers can be tested without the upper ones.

| Layer | Modules | Role |
|---|---|---|
| 4. Interface | `cli.py`, `__main__.py` | parse commands, print results |
| 3. Services | `planner.py`, `benchmark.py` (uses `planner.build_request`), `synthetic.py` | orchestrate the use cases |
| 2. ML & integration | `predictor.py`, `engine_bridge.py`, `fatigue.py` | models, C++ bridge, fatigue maths |
| 1. Persistence | `repository.py`, `db.py`, `schema.sql` | all SQL and connections |
| 0. Foundations | `models.py`, `config.py` | dataclasses and settings |

## 4.1 `config.py`: single source of truth

<!-- include: flexsched/config.py -->

**Notes**

* `Path(__file__).resolve().parent.parent` is the repository root, wherever it's cloned.
* `os.environ.get("FLEXSCHED_DB", default)`: environment variables override paths, which
  is useful for tests, CI and deployment (a *12-factor app* habit).
* `SchedulerParams` is **frozen**: parameters can't be mutated during a run. `to_dict()`
  uses `dataclasses.asdict`, and that dict becomes the `"params"` object of the engine
  request, so Python's values always win over the engine's compiled defaults.
* `CATEGORIES` mirrors the SQL `CHECK` constraint (validated in two layers).

## 4.2 `models.py`: domain dataclasses

<!-- include: flexsched/models.py -->

**Notes**

* `Task.id` is `Optional[int]`: `None` until the database assigns one.
* `WorkSession.actual_min` is a `@property` computed from the timestamps, so it can
  never disagree with them.
* `PlanResult.blocks` uses `field(default_factory=list)` (see Part 2.1).

## 4.3 `schema.sql`: the database design

<!-- include: flexsched/schema.sql -->

**Entity–relationship view**

```
tasks (1) ──────< (N) work_sessions        a task can have many sessions
tasks (1) ──────< (N) schedule_items       an item points to a task (or NULL for a break)
schedule_runs (1) ──< (N) schedule_items   a run contains many items
```

**Design choices to defend**

* **Normalised**: task attributes live only in `tasks`; sessions and schedule items
  reference them by id (no duplicated titles that could disagree).
* **Constraints in the database** as well as in Python (defence in depth): even a bug or
  a manual `INSERT` can't store difficulty 7 or a session that ends before it starts
  (`CHECK (ended_at > started_at)` works because ISO text compares chronologically).
* `actual_min` is stored even though it's derivable: it makes training queries simple
  and fast. That's a conscious, small denormalisation.
* `metrics_json` stores a JSON blob: metrics are read whole and never queried by field,
  so a column per metric would add schema churn for no benefit.
* **Indexes** match the queries: `status` (list open tasks), `started_at` (sessions of a
  day, training order), `task_id` (joins), `run_id` (items of a run).

## 4.4 `db.py`: connections and schema initialisation

<!-- include: flexsched/db.py -->

**Notes**

* `":memory:"` creates a private in-RAM database; every test gets a fresh one.
* `conn.row_factory = sqlite3.Row` lets code write `row["title"]` instead of `row[1]`.
* `PRAGMA foreign_keys = ON` **per connection** (SQLite's default is OFF).
* `executescript` runs the whole schema file; `IF NOT EXISTS` makes it idempotent.
* `user_version` records the schema version for future migrations.
* `to_db_time` / `from_db_time` keep one datetime text format in a single place.

## 4.5 `repository.py`: all SQL in one place

<!-- include: flexsched/repository.py -->

**Notes**

* **Repository pattern**: the rest of the code calls `TaskRepository(conn).list(["pending"])`
  and gets `Task` objects. It never sees SQL. Swapping SQLite for PostgreSQL would touch
  this file (and `db.py`) only.
* `validate_task` gives friendly errors; the DB constraints are the safety net.
* Dynamic `IN (?, ?, ?)`: the *number* of placeholders is built dynamically, but values
  are still passed separately, so it stays injection-safe.
* `executemany` runs one statement for many parameter tuples (efficient bulk update).
* `ScheduleRepository.save` uses `with self.conn:` → **atomic** (run row + all item rows,
  or nothing). `test_schedule_save_rolls_back_on_error` proves it.
* `TRAINING_SQL` does feature extraction in SQL (`strftime('%H')`, `strftime('%w')`).
  Note SQLite's `%w` is Sunday=0, while Python's `weekday()` is Monday=0; `planner.py`
  converts with `_sqlite_weekday` so training and prediction agree.
* `ESTIMATION_BIAS_SQL` powers `flexsched stats`: `GROUP BY category` with
  `AVG(actual/estimate)`, the "how wrong am I per category" table.

## 4.6 `fatigue.py`: Python mirror of the engine's model

<!-- include: flexsched/fatigue.py -->

**Notes**

* Same formulas as `fatigue.cpp`. Why duplicate? The ML feature `fatigue_at_start`
  must be computed for **historical** sessions, which never went through the engine.
* Duplication risk is controlled by a **parity test**
  (`test_python_and_cpp_fatigue_models_agree`): Python replays the engine's output block
  by block and must match every `fatigue_start`/`fatigue_end` within 1e-9.
* `replay_day`: start fresh, rest during gaps, work during sessions. Returns the fatigue
  at the start of each session.

## 4.7 `synthetic.py`: the simulated user

<!-- include: flexsched/synthetic.py -->

**Notes**

* `np.random.default_rng(seed)` is NumPy's modern random generator. The same seed gives
  the same data, so results are reproducible (and a test checks it).
* `true_duration` encodes the **hidden habits** (category bias, difficulty, priority
  focus, fatigue slowdown, morning focus, post-lunch dip, log-normal noise). The ML
  model never sees this function; it must rediscover the patterns from data.
* The simulation advances fatigue with the **same** `after_work`/`after_rest`, so stored
  `fatigue_at_start` values are exactly what `replay_day` would compute.
* All inserts happen in **one transaction** (`with conn:`), which is much faster than
  committing after each row.
* Weekends get 0–2 tasks, weekdays 3–7, with a lunch gap once the clock passes noon.

## 4.8 `predictor.py`: training, evaluation, duration curves

<!-- include: flexsched/predictor.py -->

**Notes, in the order `train()` runs**

1. `load_training_frame`: `pd.read_sql_query(TRAINING_SQL, conn)` gives a DataFrame
   sorted by time.
2. Refuse to train on fewer than 40 rows (`InsufficientDataError`): a model trained on 10
   rows is worse than the baseline and gives false confidence.
3. **Temporal split**: `iloc[:cut]` (old 80%) vs `iloc[cut:]` (new 20%).
4. For each of the five candidate pipelines: `TimeSeriesSplit` cross-validation on the
   training part (MAE **in minutes**, computed by converting predicted ratios back),
   then fit on the whole training part and score once on the hold-out.
5. **Choose by CV MAE**, never by hold-out score (that would leak test information into
   the choice).
6. **Permutation importance** on the hold-out set for the chosen model.
7. **Refit the chosen model on all data** for production use: once evaluation is done,
   more data beats a held-back slice.
* `_minutes_from_ratio` clips ratios into `[0.2, 5.0]`, a guard rail against absurd
  predictions on weird inputs.
* `duration_curves` builds one DataFrame with *tasks × 5 fatigue levels* rows and calls
  `predict` **once** (vectorised), then `reshape`s to a matrix. It then applies
  `np.maximum.accumulate(axis=1)` (running maximum along each row) to enforce the domain
  rule that **more fatigue never makes you faster**, since tree models can produce small
  non-monotonic wiggles.
* `heuristic_curve` is the **cold-start** fallback (+50% at full fatigue) used before any
  model exists.
* The saved file includes the scikit-learn version, because pickled models are not
  guaranteed to load across versions.

## 4.9 `engine_bridge.py`: talking to C++

<!-- include: flexsched/engine_bridge.py -->

**Notes**

* `find_engine` searches: env var → `build/` → `build/Release` (MSVC layout) →
  `build/Debug` → `PATH`. If nothing is found it raises a helpful error **with the build
  commands**.
* `subprocess.run([...], input=json, capture_output=True, text=True, timeout=30,
  check=False)`: pass a list (no shell, so no quoting or injection issues), feed stdin,
  capture stdout/stderr as text, never hang forever, and inspect the return code
  ourselves.
* Errors are translated into a small **exception hierarchy**, so callers handle
  "bad input" differently from "engine crashed".
* The docstring records the alternatives considered (pybind11, ctypes) and why
  subprocess + JSON won. That's an important interview topic (Part 7).
* Measured overhead: about 50 ms per call on Windows (mostly process start-up). That's
  negligible for a planner run by a human, and the reason the benchmark takes ~25 s for
  400 engine calls.

## 4.10 `planner.py`: orchestration

<!-- include: flexsched/planner.py -->

**Notes**

* `work_windows` builds one `(start, end)` per day; `skip_weekends` is optional.
* `build_request` is **pure** (no I/O): objects in, dict out. That makes it easy to test
  and to reuse from `benchmark.py`.
* Tasks without a deadline get "horizon end + 30 days": far enough to be non-urgent, but
  still a finite integer for the engine.
* `plan()` maps engine output back to datetimes, saves the run (unless `persist=False`)
  and updates statuses: scheduled tasks become `scheduled`, unscheduled return to
  `pending`.
* `compare()` reuses `plan()` with `persist=False` for every strategy on identical input,
  a fair A/B comparison.
* `log_session` inserts the session **without committing**, re-reads the whole day
  (the same connection sees its own uncommitted rows), replays fatigue for **every**
  session of that day and updates them, then commits once. Logging sessions out of order
  still yields correct fatigue values, and a test logs the later session first to prove it.

## 4.11 `benchmark.py`: is fatigue-aware actually better?

<!-- include: flexsched/benchmark.py -->

**Notes**

* One example proves nothing; 200 seeded random scenarios give stable averages.
* **Paired comparison**: both strategies get the *same* tasks and calendar per scenario,
  so differences come from the policy alone. `paired_wins` reports the share of scenarios
  where fatigue-aware is strictly better per metric.
* A fixed date (`2030-01-07`, a Monday) keeps runs reproducible regardless of today's date.

## 4.12 `cli.py` and `__main__.py`: the user interface

<!-- include: flexsched/cli.py -->
<!-- include: flexsched/__main__.py -->

**Notes**

* `argparse` sub-commands: each `sub.add_parser(...)` gets its own options and a
  `set_defaults(func=cmd_x)`, so `main()` just calls `args.func(args, conn)`. That's a
  simple **command dispatch** table.
* **Custom `type=` converters** (`parse_datetime`, `parse_block`, `int_range(1, 5)`)
  validate input at the boundary and raise `ArgumentTypeError`, so argparse prints a
  clean usage error.
* `int_range` is a **closure**: a function that returns a function remembering `lo`/`hi`.
* `main()` returns an exit code (0/1) and closes the DB in `finally`. Known errors are
  printed to **stderr** without a traceback.
* `table()` is a ~6-line column aligner, so there's no dependency for pretty output.
* `demo` runs everything on a temporary database so your real data is never touched.

## 4.13 pytest suite

### `conftest.py`: shared fixtures

<!-- include: tests/conftest.py -->

### `test_repository.py`

<!-- include: tests/test_repository.py -->

### `test_fatigue.py`

<!-- include: tests/test_fatigue.py -->

### `test_predictor.py`

<!-- include: tests/test_predictor.py -->

### `test_engine_integration.py`

<!-- include: tests/test_engine_integration.py -->

### `test_cli.py`

<!-- include: tests/test_cli.py -->

## 4.14 Project configuration files

### `pyproject.toml`

<!-- include: pyproject.toml -->

Declares the package, its dependencies, the `flexsched` console script
(`pip install -e .` makes `flexsched plan ...` work directly) and pytest settings
(`pythonpath` so tests can import `flexsched` and `conftest`).

### `requirements.txt`

<!-- include: requirements.txt -->

### `.gitignore`

<!-- include: .gitignore -->

Build output, virtual environments, local databases and trained models are **generated
artefacts** and are never committed; anyone can regenerate them with the commands in the
README.

### `.github/workflows/ci.yml`

<!-- include: .github/workflows/ci.yml -->

A **matrix** build: the same steps on Ubuntu (GCC) and Windows (MSVC). `fail-fast: false`
lets both finish so you see every failure at once.

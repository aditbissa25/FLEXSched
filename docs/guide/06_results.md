
# Part 6 — Results, limitations, running the project

## 6.1 Reproducing every number in this guide

```bash
python -m flexsched seed            # 120 days, seed 42 → 445 sessions
python -m flexsched train           # model table + permutation importance
python -m flexsched stats           # estimation bias per category
python -m flexsched benchmark --scenarios 200      # seed 7
ctest --test-dir build              # 39 Catch2 test cases
python -m pytest                    # 49 tests
```

### Duration prediction

```
model              CV MAE (min)  hold-out MAE  MAPE   R^2
-----------------  ------------  ------------  -----  -----
trust_estimate     15.55         17.47         21.5%  0.614
mean_ratio         13.39         14.04         20.3%  0.763
ridge              7.20          6.68          10.0%  0.938  <- chosen
random_forest      8.58          7.08          10.3%  0.932
gradient_boosting  7.93          6.91          11.1%  0.943

Permutation importance:
  category +0.098 | difficulty +0.087 | fatigue_at_start +0.040 | hour_of_day +0.020
  priority +0.016 | estimate_min −0.000 | day_of_week −0.003
```

**How to read it:** error drops from 17.5 to 6.7 minutes (−62%). The importance ranking
matches the simulated habits; `day_of_week` ≈ 0 is correct because the generator has no
weekday effect, so the model isn't inventing patterns. `estimate_min` ≈ 0 is expected
because the target is already *relative* to the estimate.

### Estimation bias (`stats`)

```
category  sessions  avg estimate  avg actual  actual/estimate
coding    72        55.6          80.3        1.433
writing   77        53.2          73.7        1.366
design    70        53.0          66.6        1.29
study     71        50.9          62.2        1.23
review    76        50.8          56.6        1.102
admin     79        59.7          57.6        0.964
```

### Scheduling benchmark (200 scenarios, paired)

```
metric (mean)         fatigue_aware  edf
total_work_minutes    653.920        664.335
makespan              2306.335       2293.180
tasks_scheduled       10.620         10.680
tasks_late            0.425          0.320
total_lateness        90.440         90.855
breaks                2.415          0.000
peak_fatigue          0.783          0.842
avg_fatigue_at_start  0.265          0.321

fatigue_aware strictly better: work minutes 68% | avg fatigue 80% | peak fatigue 82%
```

**Honest reading:**

* **Wins:** −17% average fatigue at task start, −7% peak fatigue, −1.6% total work time
  (tasks done in a better state take less time per the model, which more than pays for
  ~36 minutes of breaks).
* **Ties:** total lateness (90.4 vs 90.9 minutes).
* **Costs:** slightly more late tasks on average (+0.1 per scenario) and a slightly later
  makespan (breaks take time). The guard bounds lateness *minutes*, not the *count*,
  and it's approximate (it ignores future fatigue).

## 6.2 Limitations and assumptions (say these before you're asked)

1. **Synthetic data.** No real-user study; `synthetic.py` defines the "truth". The
   pipeline is real and would work unchanged on logged data, but the numbers describe
   the simulated user.
2. **Fatigue model parameters are assumed**, not fitted. The *form* is plausible
   (saturating growth, exponential recovery) but not validated on people.
3. **Duration depends on fatigue at the start only**; fatigue changes during a long
   task aren't fed back into its duration.
4. **Planning hour fixed at 11:00** when predicting curves (the start time isn't known
   until scheduling). Hour-of-day effects are therefore only approximated at plan time.
5. **No task splitting / pre-emption.** A 2-hour task can't use two 1-hour holes (see the
   unused 12:05–13:00 in Part 5.3).
6. **Blocked time counts as rest**: meetings are treated like breaks.
7. **Greedy + heuristic lookahead**, not an optimal solver.
8. **Single user, local CLI**: no accounts, sync, concurrency control or UI.
9. **Subprocess bridge** costs ~50 ms per call: fine for planning, wasteful for bulk
   simulation.

Each limitation maps to a concrete item in `docs/FUTURE_ROADMAP.md`.

## 6.3 Resume bullets ↔ evidence in the code

| Resume claim | Evidence |
|---|---|
| "fatigue-aware task scheduling system" | `fatigue.hpp/.cpp`, `FatigueAwarePolicy`, breaks in `scheduler.cpp`, duration curves |
| "using historical task data" | `work_sessions` table, `TRAINING_SQL`, `log_session` + `replay_day` |
| "machine-learning-based duration prediction" | `predictor.py`: 5 pipelines, TimeSeriesSplit CV, hold-out, permutation importance |
| "modular scheduling logic" | 6 C++ modules with one responsibility each, Strategy + Factory |
| "task management" | `add`/`list`/`done`/statuses, `TaskRepository`, validation |
| "data persistence with Python, C++ and SQLite" | `schema.sql`, `db.py`, `repository.py`; C++ engine exchanges state via JSON |
| "Catch2 unit tests … scheduling modules and edge cases" | 6 test files, 39 cases, `[edge]`, `[invariant]`, `[determinism]` tags |

**Optional stronger, still-honest versions of your bullets:**

* *Developed a fatigue-aware task scheduler that predicts task durations from historical
  work logs with scikit-learn (time-series CV across 5 models), reducing prediction error
  62% vs. user estimates on held-out data.*
* *Built a modular C++17 scheduling engine (free-slot computation, fatigue simulation,
  pluggable EDF / fatigue-aware policies with a rollout deadline guard) integrated with a
  Python + SQLite planning layer via a JSON contract; lowered simulated fatigue 17% at
  equal lateness over 200 benchmark scenarios.*
* *Wrote 39 Catch2 test cases (340+ assertions) covering scheduling invariants, edge
  cases and determinism, plus 49 pytest tests incl. a Python–C++ parity test; CI on
  Linux and Windows.*

(If you use the numbers, be ready to say "on synthetic data".)

## 6.4 Setup on a new machine

**Windows (what this project was built with):** Python 3.13, CMake, and either
WinLibs GCC (`winget install BrechtSanders.WinLibs.POSIX.UCRT`) with Ninja, or Visual
Studio Build Tools (MSVC).

```bash
cmake -S engine -B build -G Ninja -DCMAKE_BUILD_TYPE=Release   # GCC + Ninja
cmake -S engine -B build                                        # or MSVC (Visual Studio generator)
cmake --build build --config Release
ctest --test-dir build -C Release
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
python -m flexsched demo
```

**Linux / macOS:** same commands; activate with `source .venv/bin/activate`.

## 6.5 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `C++ engine not found` | build it (commands above) or set `FLEXSCHED_ENGINE` to the binary path |
| CMake: `unable to find a build program corresponding to "Ninja"` | Ninja not on PATH; add the compiler's `bin` folder to PATH or pass `-DCMAKE_MAKE_PROGRAM=...` |
| CMake download errors | first configure needs internet (Catch2, nlohmann/json via FetchContent) |
| `need at least 40 logged sessions` | run `seed` (demo data) or log more sessions with `done` |
| integration tests "skipped" | the engine isn't built yet; pytest skips rather than fails |
| `sqlite3.IntegrityError` | a constraint caught invalid data; the message names the column |
| model fails to load after upgrading scikit-learn | retrain: `python -m flexsched train` |

## 6.6 Repository history (commit by commit)

The repository was built in reviewable steps: scaffold → persistence → fatigue model and
synthetic history → ML predictor → C++ engine → Catch2 tests → Python–engine bridge,
planner and CLI → pytest suite and CI → this guide → future roadmap.
`git log --oneline` shows the sequence.

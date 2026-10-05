
# Part 7 — Interview drill

## 7.0 How to use this drill

Interviewers rarely ask one question. They take one line of your resume and **drill**:
*what* → *why* → *what exactly* → *why not something else* → *what breaks* → *how would
you scale it*. Each section below follows one resume line through that ladder, from
**[Basic]** to **[Expert]**. The model answers are deliberately short. Learn the
*reasoning*, not the wording.

Answer shape that works almost everywhere: **claim → reason → evidence → trade-off.**
> "I used a temporal split *(claim)* because the model predicts future sessions from past
> ones *(reason)*; a random split scored better but leaked future habits *(evidence)*;
> the cost is a smaller, more recent test set *(trade-off)*."

Your resume lines:

> **FLEXSched – Intelligent Task Scheduler & Planner** · *Python, C++, scikit-learn, SQLite, Catch2*
> 1. Developed a fatigue-aware task scheduling system using historical task data and
>    machine-learning-based duration prediction.
> 2. Implemented modular scheduling logic, task management and data persistence with
>    Python, C++ and SQLite.
> 3. Wrote Catch2 unit tests to validate scheduling modules and edge cases, improving
>    confidence in core logic.

The drill covers four points: **(A)** the headline, **(B)** bullet 1, **(C)** bullet 2,
**(D)** bullet 3, then **(E)** tech-stack justification, **(F)** cross-cutting and
behavioural questions, **(G)** rapid fire.

---

## A. The headline: "Intelligent Task Scheduler & Planner"

**A1 [Basic] What is FLEXSched in one sentence?**
A planner that learns how long your tasks really take, including how much slower you are
when tired, and builds a timetable that schedules hard work when you're fresh, adds
breaks, and protects deadlines.

**A2 [Basic] Who is it for and what problem does it solve?**
Students and developers who plan their own days. It solves two problems ordinary
calendars ignore: people underestimate tasks (planning fallacy) and slow down as they
get tired.

**A3 [Basic] What does "intelligent" mean here, concretely? Isn't that a buzzword?**
Two concrete things: (1) durations are *learned* from your history with a validated ML
model instead of trusted blindly; (2) the scheduler *simulates* your fatigue and decides
task order and breaks from it. Without those two, it would be an ordinary to-do list.

**A4 [Intermediate] Walk me through the architecture.**
Python CLI → planner (service layer) → SQLite repositories for data, a scikit-learn
pipeline for duration curves, and a C++ engine called as a subprocess with a JSON
request on stdin and a JSON schedule on stdout. The engine has six modules: calendar,
fatigue, duration, policy, scheduler and json_io.

**A5 [Intermediate] What happens end-to-end when the user runs `plan`?**
Load open tasks → predict each task's duration at 5 fatigue levels in one vectorised
call → convert datetimes to minute offsets → engine computes free slots, simulates the
day and picks tasks through the policy → Python maps the result back, saves it in one
transaction, updates statuses and prints it.

**A6 [Intermediate] Why split it into Python and C++ instead of one language?**
Each part plays to its ecosystem: Python has scikit-learn, pandas and sqlite3;
the scheduling core is a tight, deterministic algorithm where C++ gives speed, static
types and Catch2. The JSON boundary keeps them independent, so each can be tested alone.
(Honest add-on: at today's problem sizes Python would also be fast enough. The engine
is built for larger horizons, many simulations, and a clean core that could ship as a library.)

**A7 [Intermediate] How do you know it works?**
Three layers of evidence: 39 Catch2 test cases with invariants and edge cases; 49 pytest
tests including end-to-end and a Python-vs-C++ parity test; and two quantitative
evaluations: hold-out ML error and a 200-scenario paired benchmark against EDF.

**A8 [Advanced] What results did you get, and what's the catch?**
62% lower duration error than trusting estimates (17.5 → 6.7 min MAE) and 17% lower
average fatigue at equal total lateness versus EDF. The catch: the data is synthetic,
and the fatigue model's parameters are assumed. The pipeline would run unchanged on real
logs, but the numbers describe a simulated user.

**A9 [Advanced] If you had to remove one component, which and why?**
The C++ engine could be rewritten in Python with minimal loss at current sizes. I'd keep
it because it enforces a clean contract and is where the algorithmic depth lives. The
ML model is the component I wouldn't remove: it's the main source of accuracy.

**A10 [Expert] How would you turn this into a product with real users?**
Collect real sessions (timer or calendar integration), fit fatigue parameters per user,
add a REST API + web UI, move to PostgreSQL with auth, run the engine as a library or
service, add task splitting and an optimiser, and monitor prediction error per user with
retraining. (Details: `FUTURE_ROADMAP.md`.)

---

## B. Bullet 1: "fatigue-aware scheduling using historical task data and ML-based duration prediction"

### B-I. Fatigue (what → why → what → why)

**B1 [Basic] What does "fatigue-aware" mean?**
The scheduler tracks a fatigue number between 0 (fresh) and 1 (exhausted) as it builds
the plan. Work raises it, rest lowers it, and it influences task order, durations and
breaks.

**B2 [Basic] Why model fatigue at all?**
Because duration and quality depend on it. A plan assuming you're as fast at 4 pm as
at 9 am is wrong in a predictable way, and predictable errors can be corrected.

**B3 [Intermediate] What exactly is your fatigue model?**
Work: `F' = 1 − (1 − F)·e^(−rate·(difficulty/5)·minutes)`, a saturating increase.
Rest: `F' = F·e^(−recovery·minutes)`, exponential recovery. Rate 0.012/min,
recovery 0.05/min.

**B4 [Intermediate] Why those formulas and not, say, linear?**
Linear growth would exceed 1 and needs clamping hacks; the exponential form is bounded,
monotonic and saturating, and harder tasks tire faster through the load factor. Recovery
is fast at first and slows down, which matches how a short break restores much of your
focus. Each formula has one parameter that's easy to explain.

**B5 [Intermediate] Where does fatigue change decisions?**
Three places: (1) **duration**, since the engine reads each task's curve at the current
fatigue; (2) **ordering**, since the energy-match term prefers hard tasks when fresh and easy
ones when tired; (3) **breaks**, inserted when F ≥ 0.65 (unless the slot is ending anyway).

**B6 [Advanced] How do you know the fatigue at the start of past sessions? Users don't log "I'm 0.4 tired".**
I reconstruct it: for each day, replay the logged sessions through the same model
(start fresh, rest during gaps, work during sessions). `log_session` recomputes the
whole day on each insert, so out-of-order logging still gives correct values.

**B7 [Advanced] Isn't it circular to use an assumed fatigue model to create a feature, then learn from it?**
It's a modelling assumption, not circular logic: the feature is a deterministic summary of
"how much work, how recently". If the assumption were useless, the model would learn
that `fatigue_at_start` has ~0 importance. With real data it would be validated the same
way. The next step is to *fit* the rates by maximising predictive accuracy (roadmap).

**B8 [Expert] How would you fit the fatigue parameters from data?**
Treat work_rate and recovery_rate as hyper-parameters: grid-search or Bayesian-optimise
them, recompute `fatigue_at_start` for each candidate, and choose the pair with the best
time-series-CV MAE. Or put the model inside a differentiable pipeline and learn them
jointly. Per-user parameters would need hierarchical pooling to avoid overfitting
sparse users.

### B-II. Historical data

**B9 [Basic] What historical data do you use?**
Work sessions: task id, start, end, actual minutes and reconstructed fatigue at start,
joined with task attributes (category, difficulty, priority, estimate).

**B10 [Basic] Where does it come from in your demo?**
A seeded simulator (`synthetic.py`) that generates 120 days of a person with hidden
habits. Real usage logs through `flexsched done` into the same tables.

**B11 [Intermediate] Why synthetic data? Isn't that cheating?**
There's no public dataset of personal task durations with fatigue context, and a
new user has no history. The simulator gives a controlled ground truth, so I can check
the pipeline *recovers* known patterns: the permutation importances line up with
the hidden habits, and `day_of_week`, which has no effect in the generator, gets ≈ 0. I always
state the numbers are on synthetic data.

**B12 [Intermediate] What hidden habits does the simulator have?**
Category bias (coding ×1.35, admin ×0.9), +8% per difficulty step above 3, −3% per
priority step (focus), up to +55% when exhausted, faster mornings, a 10% post-lunch dip,
and ~12% log-normal noise.

### B-III. ML duration prediction

**B13 [Basic] What exactly does the model predict?**
The ratio actual/estimate; the prediction in minutes is ratio × the user's estimate.

**B14 [Intermediate] Why predict a ratio instead of minutes?**
It's scale-free: "I take 1.4× for coding" holds for 30- and 120-minute tasks. Tree
models can't extrapolate beyond targets they've seen, and the ratio sidesteps that. It also
makes the baseline natural (ratio = 1 means "trust the estimate").

**B15 [Intermediate] Which features, and why each?**
Category (bias differs by kind of work), estimate (anchor), difficulty
(underestimation grows with difficulty), priority (focus), fatigue at start (the core
idea), hour of day (circadian/lunch dip), day of week (tested, turned out irrelevant).

**B16 [Intermediate] Which models did you try and which won?**
Two baselines (trust estimate, mean ratio), Ridge, Random Forest and Gradient Boosting.
Ridge won on cross-validated MAE (7.2 min), with GBR/RF close. Hold-out MAE was 6.7 vs
17.5 for trusting the estimate.

**B17 [Advanced] Why did a linear model beat the ensembles?**
In ratio space the habits are near-multiplicative factors combining almost linearly, so
a regularised linear model captures them with low variance; trees add variance and
approximate smooth effects with steps. I let cross-validation decide instead of
assuming the most complex model wins. On real, messier data the result might differ,
which is why the selection is automatic.

**B18 [Advanced] How did you evaluate without fooling yourself?**
Temporal 80/20 split (past → future); model selection by `TimeSeriesSplit` CV on the
training part only; a single evaluation on the hold-out; comparison against two baselines;
all preprocessing inside a `Pipeline` so scaler/encoder statistics never see validation
data.

**B19 [Advanced] What's data leakage and where could it have happened here?**
Information from the evaluation data influencing training or selection. Here it could
have come from: a random split (future habits in training), picking the model by
hold-out score, fitting the scaler on all data before CV, or features computed from
future sessions. Each is prevented by design.

**B20 [Advanced] MAE vs RMSE vs MAPE: why MAE?**
MAE is in minutes and directly interpretable ("off by 6.7 minutes on average") and is
robust to outliers. RMSE punishes big misses more (useful if over-runs are very costly).
MAPE is scale-free but explodes for tiny actual values. I report MAE (primary), MAPE
and R².

**B21 [Advanced] How does the model plug into the scheduler?**
It predicts minutes at fatigue 0, 0.25, 0.5, 0.75, 1 → a duration **curve** per task.
The engine linearly interpolates at the simulated fatigue and rounds up. I enforce
monotonicity with a running maximum because more fatigue should never make you faster.

**B22 [Expert] Your curve assumes 11:00 as start hour. Isn't that wrong for afternoon tasks?**
Yes, it's an approximation, because the start time is unknown until scheduling. Options:
predict a 2-D grid (fatigue × hour) and interpolate both in the engine; or iterate
(schedule → re-predict with actual start times → reschedule until stable). The
grid is the cleaner fix and is in the roadmap.

**B23 [Expert] How would you get uncertainty, not just a point estimate?**
Quantile regression (e.g. GBR with quantile loss for P50/P80) or conformal prediction
intervals on the time-series CV residuals. The scheduler could then book P80 for
deadline-critical tasks and P50 otherwise, which is a risk-aware schedule.

**B24 [Expert] How would you handle a brand-new user (cold start)?**
Today: a heuristic curve (+50% at full fatigue). Better: a global model trained on
all users as a prior, blended with the user's own data as it accumulates (hierarchical
/ mixed-effects model, or per-user offsets on a shared model).

---

## C. Bullet 2: "modular scheduling logic, task management and data persistence with Python, C++ and SQLite"

### C-I. Modular scheduling logic

**C1 [Basic] What does "modular" mean in your engine?**
Six modules with one job each: calendar (free slots), fatigue (dynamics), duration
(curve interpolation), policy (decision rules), scheduler (the loop), json_io (contract).
Each has its own header, source and test file.

**C2 [Basic] What does the scheduler do, step by step?**
Walk through free slots; rest during gaps; take a break if too tired; find tasks that
fit at the current fatigue; ask the policy which to do; place it; update fatigue and
clock; repeat; explain leftovers.

**C3 [Intermediate] What design pattern is the policy?**
Strategy: an abstract `SelectionPolicy` with `EdfPolicy` and `FatigueAwarePolicy`,
created by a factory from a string. The loop never changes when I add a strategy
(Open/Closed principle).

**C4 [Intermediate] Explain the fatigue-aware score.**
`0.35·priority + 0.45·urgency + 0.20·energy-match`. Priority is normalised 0..1; urgency
is 1 with no slack and decays as `e^(−slack/480)`; energy match is
`1 − |difficulty − energy|`, highest for hard-when-fresh or easy-when-tired.

**C5 [Intermediate] Why EDF as the baseline?**
It's the textbook rule: with fixed durations on one machine, EDF minimises the maximum
lateness (Jackson's rule). It's simple, strong and fatigue-blind, which is exactly the
comparison I want.

**C6 [Advanced] Your first version had worse lateness than EDF. What did you do?**
An ablation showed breaks weren't the cause; ordering was. I added a lookahead: take the
best-scored task only if "this task first, then EDF" produces no more late tasks or
minutes than pure EDF. Two fixes followed: pack the simulation into real slots (it
ignored nights), and include all remaining tasks. Lateness went 143 → 90 minutes (EDF:
91) while keeping the fatigue gains.

**C7 [Advanced] Is your scheduler optimal? Why greedy?**
No. Minimising total tardiness on one machine is NP-hard even with fixed durations, and my
durations depend on order through fatigue. Greedy with a lookahead is fast,
deterministic and explainable; I benchmark it against EDF to show where it wins and where
it costs. An optimiser such as CP-SAT or local search is the upgrade path.

**C8 [Advanced] Complexity of planning?**
Free slots: O(W log W + B log B). Per decision: O(n) durations plus up to k rollouts of
O(n log n + S). Worst case is roughly O(n²·(n log n + S)) per plan, which is milliseconds
for n ≤ 100.

**C9 [Expert] How did you guarantee the loop terminates?**
Every iteration does at least one of: advance time to a later slot, consume a slot,
take a positive-length break, or schedule a task. Slots and tasks are finite, and
`break_minutes > 0` and `0 < threshold ≤ 1` are validated in the constructor.

**C10 [Expert] Any subtle C++ correctness issue you hit?**
Two. (1) My ranking comparator first used an epsilon "equal", which violates strict weak
ordering, and that's undefined behaviour in `std::sort`; I switched to exact comparisons
with deterministic tie-breaks. (2) Duration rounding: the single-point curve path skipped
the floating-point epsilon, caught by a Catch2 test (`61 == 60`).

### C-II. Task management

**C11 [Basic] What can a user do with tasks?**
Add (title, category, difficulty, priority, estimate, deadline), list, plan, log work
(`done`), view stats, past runs and benchmarks, all through the CLI.

**C12 [Intermediate] How is input validated?**
Three layers: argparse types (`int_range(1,5)`, date parsers), `validate_task` in the
repository (friendly messages), and SQL `CHECK`/`NOT NULL`/FK constraints (last line of
defence, tested by bypassing Python).

**C13 [Intermediate] What's the task lifecycle?**
`pending` → `scheduled` (placed by a saved plan) → `done` (work logged); unscheduled
tasks go back to `pending`; `cancelled` is allowed by the schema.

### C-III. Data persistence

**C14 [Basic] What's stored and where?**
SQLite file `data/flexsched.db`: `tasks`, `work_sessions`, `schedule_runs`,
`schedule_items`. The trained model is a joblib file in `models/`.

**C15 [Intermediate] Walk me through the schema decisions.**
Normalised tables with foreign keys (`ON DELETE CASCADE` for sessions, `SET NULL` for
schedule items), `CHECK` constraints for ranges and enums, indexes matching queries
(status, started_at, task_id, run_id), ISO-8601 text dates, metrics as JSON because they're
read whole.

**C16 [Intermediate] How do you prevent SQL injection?**
Only parameterised queries (`?` placeholders), even for dynamic `IN (...)` lists, where
only the placeholder count is generated.

**C17 [Intermediate] How do you keep data consistent when saving a plan?**
A transaction (`with conn:`): the run row and all item rows commit together or roll
back together. A test injects an invalid item and asserts no run row remains.

**C18 [Advanced] Where does C++ fit in "persistence with Python, C++ and SQLite"?**
Precisely: SQLite is accessed from Python; the C++ engine is stateless and exchanges all
state through a versionable JSON contract. Python persists both its inputs and outputs
(runs and items), so every plan is reproducible and comparable later. (Be precise here;
don't claim C++ talks to SQLite.)

**C19 [Advanced] Why the Repository pattern?**
It isolates all SQL in one module: the planner works with `Task` objects, tests can use
`:memory:`, and moving to PostgreSQL changes one layer.

**C20 [Advanced] Why subprocess + JSON instead of pybind11?**
Decoupling and simplicity: no ABI coupling to a specific Python/compiler (painful on
Windows), the engine is testable from the command line, and a crash can't take the
Python process down. The cost (~50 ms per call) is irrelevant for planning; for heavy
simulation I'd switch to pybind11 or batch requests.

**C21 [Expert] What would change with many concurrent users?**
SQLite allows one writer at a time, which is fine for a desktop app. For a multi-user
service: PostgreSQL with connection pooling, row-level ownership (user_id), migrations
(Alembic), and the engine as an in-process library or a stateless service behind a
job queue.

**C22 [Expert] How do you evolve the schema safely?**
`PRAGMA user_version` holds the version; on start-up apply ordered migrations
(`if version < 2: ALTER TABLE ...`) inside a transaction. With PostgreSQL I'd use a
migration tool and make changes backward compatible (expand → migrate → contract).

---

## D. Bullet 3: "Catch2 unit tests to validate scheduling modules and edge cases"

**D1 [Basic] What is Catch2?**
A C++ unit-testing framework: `TEST_CASE`s with tags, `SECTION`s, natural assertions
(`CHECK(a == b)`) that print both sides on failure, and matchers for floating point.

**D2 [Basic] What do your tests cover?**
All six engine modules: 39 test cases, ~340 assertions. Formulas, interpolation, interval
algebra, scoring, the deadline guard, the scheduling loop, JSON parsing and errors.

**D3 [Basic] Give three edge cases you test.**
A task longer than every free slot (reported with a reason); a blocked interval spanning
two working days; an empty or NaN duration curve (rejected). Others: no tasks, no free
time, duplicate ids, out-of-range values, no break squeezed in at slot end.

**D4 [Intermediate] CHECK vs REQUIRE?**
`CHECK` records a failure and continues; `REQUIRE` aborts the test case. I use REQUIRE
before indexing (`REQUIRE(blocks.size()==1)` then `blocks[0]`) so a failure can't turn
into a crash.

**D5 [Intermediate] What's an invariant test? Give yours.**
A property that must hold for *any* valid input: blocks never overlap, always lie
inside free slots, fatigue stays in [0,1], and every task is either scheduled exactly once or
reported unscheduled. I check these for both strategies on a varied 25-task, 3-day
workload with meetings.

**D6 [Intermediate] How do you test floating-point code?**
`CHECK_THAT(x, WithinAbs(expected, 1e-12))` against closed-form values (e.g.
`1 − e^(−0.72)`), plus relational properties (harder > easier, more rest < less rest).

**D7 [Intermediate] Did the tests actually catch bugs?**
Yes: the rounding epsilon bug in single-point curves (`61 == 60`). Writing the
"no break at slot end" test also forced me to reproduce a bug seen in the demo
(3-minute breaks at 16:57) before fixing it.

**D8 [Advanced] How did you make tests deterministic?**
The engine has no randomness and breaks ties by deadline then id; there's a test that
reversed input order yields an identical schedule. Python randomness is seeded.

**D9 [Advanced] How do the C++ tests relate to the Python tests?**
Catch2 = unit level for the engine; pytest = Python units, integration through the real
binary, CLI workflow, and a **cross-language parity test** that replays the engine's
fatigue values in Python to 1e-9. CI runs both on Linux and Windows.

**D10 [Advanced] Why build the engine logic as a library?**
`flexsched_core` is linked into both the executable and the test runner, so the tests
exercise exactly the code that ships; `main.cpp` stays a thin I/O shell.

**D11 [Expert] What would you add to the test strategy?**
Property-based testing with random generators (RapidCheck / Hypothesis); fuzzing
the JSON parser (libFuzzer); sanitizers (ASan/UBSan) in CI; benchmark regression tests
(Catch2 `BENCHMARK`); coverage reports (gcov/lcov) with a threshold; mutation testing to
measure test strength.

**D12 [Expert] "Improving confidence in core logic": how would you quantify that?**
Line/branch coverage of `engine/src`, the number of invariants checked, mutation score,
and defect escape rate (bugs found after merge). Today I can point to the invariant suite,
39 cases across all modules, a parity test and CI on two OS/compiler combos.

---

## E. Tech-stack justification (what → why → why not → advanced)

### Python

* **What for?** Data handling, ML, orchestration, CLI.
* **Why?** scikit-learn, pandas, NumPy and sqlite3 are mature and built-in or one pip away;
  fast to iterate.
* **Why not only Python?** It would work at today's sizes; the C++ core gives a fast,
  strictly typed, separately testable engine with a clean contract.
* **Advanced:** the GIL limits CPU parallelism in threads; heavy work happens in
  NumPy/scikit-learn (C code) or in the engine process.

### C++ (17)

* **What for?** The scheduling engine.
* **Why?** Performance for long horizons and many simulations, deterministic behaviour,
  static typing, RAII, and Catch2 for testing; also a showcase of systems skills.
* **Why C++17?** `std::clamp`, digit separators and guaranteed copy elision (the tests
  return a move-only `Scheduler` by value); universally supported by GCC, Clang and MSVC.
* **Why not Rust/Go/Java?** All viable; C++ matches the resume target roles and has
  mature tooling (CMake, Catch2, nlohmann/json).
* **Advanced:** memory safety via `unique_ptr`, no raw `new/delete`; zero warnings with
  `-Wall -Wextra -Wpedantic`; strict weak ordering in comparators.

### scikit-learn

* **What for?** Duration prediction.
* **Why?** Tabular data, a few hundred rows: classical models are the right tool;
  `Pipeline`, `ColumnTransformer`, `TimeSeriesSplit` and `permutation_importance`
  cover the whole workflow.
* **Why not deep learning (PyTorch)?** Too little data, less interpretable, slower to
  train, and no accuracy benefit on small tabular data.
* **Why not XGBoost/LightGBM?** Possible upgrades; scikit-learn's GBR was within 0.2 min
  of the best model, so an extra dependency wasn't justified.

### SQLite

* **What for?** Tasks, history, plans.
* **Why?** Zero setup, single file, ACID, full SQL (joins, constraints, indexes),
  driver built into Python; ideal for a single-user local app.
* **Why not PostgreSQL/MySQL?** They need a server; their strengths (concurrent writers,
  roles, replication) aren't needed yet. The repository layer makes a switch easy.
* **Why not CSV/JSON files?** No constraints, no transactions, no indexed queries,
  easy to corrupt.
* **Advanced:** foreign keys must be enabled per connection; one writer at a time (WAL
  mode improves concurrency); ISO-8601 text dates.

### Catch2

* **What for?** C++ unit tests.
* **Why?** Natural syntax, expression decomposition in failure messages, sections,
  tags, matchers, CTest integration, easy FetchContent install.
* **Why not GoogleTest?** Equally valid (more popular in big companies, built-in
  mocking); Catch2 is lighter for a small project. I can explain both.

### Supporting choices

* **CMake + FetchContent:** cross-platform builds, dependencies pinned by version.
* **nlohmann/json:** de-facto standard, readable API.
* **pytest:** fixtures, parametrisation, skips. **GitHub Actions:** CI on Ubuntu + Windows.

---

## F. Cross-cutting and behavioural questions

**F1. What was the hardest problem?**
Making fatigue-aware scheduling not hurt deadlines. Benchmarking showed 42% more
lateness than EDF; an ablation ruled out breaks; a rollout guard, made slot-aware and
then given all remaining tasks, brought lateness level with EDF while keeping 17%
lower fatigue.

**F2. What would you do differently?**
Start with the benchmark harness first. It drove every important design decision. And
design the duration prediction as a fatigue × hour grid from the beginning.

**F3. How did you decide the score weights?**
Hand-set to favour urgency (0.45) over priority (0.35) and energy (0.20), then checked
in the benchmark. A proper next step is tuning them by search over the benchmark
objective (e.g. minimise fatigue subject to lateness ≤ EDF).

**F4. How would you scale to 1 million users?**
Stateless API servers; PostgreSQL partitioned by user; the engine as a library inside
workers fed by a queue; nightly or event-driven retraining with a shared global model
plus per-user calibration; caching of curves; monitoring of per-user MAE drift.

**F5. How would you deploy it?**
Package Python with `pyproject.toml` (already there), build the engine in CI per OS,
ship wheels or a Docker image containing both; for a service, a FastAPI container
calling the engine library.

**F6. Is there any ethical or privacy concern?**
Work logs reveal habits. Keep data local by default, encrypt at rest if synced, make
collection opt-in and explainable, allow deletion, and avoid using fatigue data for
employee monitoring.

**F7. How do you know your benchmark isn't biased toward your policy?**
Paired design (same scenarios for both), fixed seeds, the same duration model for both,
and I report metrics where my policy loses (late-task count, makespan).

**F8. How long does it take to run?**
Planning: well under a second (engine ≈ 50 ms incl. process start). Training: ~8 s on
445 rows. Benchmark of 200 scenarios: ~25 s (dominated by 400 process starts).

## G. Rapid-fire (one-liners)

| Question | Answer |
|---|---|
| Half-open interval? | `[start, end)`: touching intervals don't overlap |
| Why minutes as int64? | exact arithmetic, no time zones in the engine |
| Why `unique_ptr`? | single ownership, automatic cleanup |
| Virtual destructor why? | correct destruction through base pointer |
| `const&` parameter? | no copy, no modification |
| What's RAII? | resources released by destructors automatically |
| Exit code 2? | invalid input to the engine |
| One-hot why? | categories have no numeric order |
| Why scale for Ridge? | L2 penalty assumes comparable feature scales |
| `TimeSeriesSplit`? | CV folds that train on the past, validate on the future |
| Permutation importance? | error increase when a feature is shuffled |
| R² = 0.94? | model explains 94% of duration variance (hold-out) |
| `PRAGMA foreign_keys`? | SQLite's FK enforcement is off by default |
| Transaction? | all-or-nothing group of statements |
| Index? | B-tree making lookups/range scans O(log n) |
| Strict weak ordering? | the comparator contract `std::sort` relies on |
| EDF optimal for? | maximum lateness, fixed durations, one machine |
| Total tardiness complexity? | NP-hard (1‖ΣTj) |
| Parity test? | Python and C++ fatigue models give identical numbers |
| Cold start? | heuristic curve until 40 sessions exist |

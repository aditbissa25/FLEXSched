
# Part 3 — C++ engine: code walkthrough

Folder layout:

```
engine/
  CMakeLists.txt
  include/flexsched/   types  fatigue  duration  calendar  policy  scheduler  json_io  (.hpp)
  src/                 fatigue  duration  calendar  policy  scheduler  json_io  main  (.cpp)
  tests/               test_*.cpp (Catch2, one file per module)
  examples/request.json
```

Who includes whom (no cycles; `types` is the foundation):

| Module | Depends on |
|---|---|
| `types` | (only the standard library) |
| `fatigue` | `types` |
| `duration` | `types`, `fatigue` (for `clamp01`) |
| `calendar` | `types` |
| `policy` | `types`, `fatigue` |
| `scheduler` | `types`, `fatigue`, `duration`, `policy` |
| `json_io` | `types`, nlohmann/json |
| `main` | `calendar`, `policy`, `scheduler`, `json_io` |

Reading order: `types` → `fatigue` → `duration` → `calendar` → `policy` →
`scheduler` → `json_io` → `main` → `CMakeLists.txt` → tests.

## 3.1 `types.hpp`: the shared vocabulary

<!-- include: engine/include/flexsched/types.hpp -->

**Notes**

* **Time as integer minutes from the horizon start.** Integers make interval maths exact
  (no floating-point drift), and keeping calendars/time zones in Python keeps the engine
  small. `int64_t` can't realistically overflow.
* **Half-open intervals `[start, end)`.** A block ending at 600 and one starting at 600
  touch but don't overlap. This convention removes off-by-one bugs (Python's `range` uses
  it too).
* `Task::duration_curve` is a `std::vector<double>`: the ML prediction at evenly spaced
  fatigue levels. The engine doesn't care how many points there are (≥ 1).
* `Params` holds every tunable number with a default; Python always sends its own values,
  so the defaults only matter for direct engine use and tests.
* `enum class BlockKind { Task, Break }`: a *scoped* enum. You must write
  `BlockKind::Task`, and it doesn't silently convert to `int`.
* `Metrics` is what the benchmark compares between strategies.

## 3.2 `fatigue.hpp` / `fatigue.cpp`: the fatigue model

<!-- include: engine/include/flexsched/fatigue.hpp -->
<!-- include: engine/src/fatigue.cpp -->

**Notes**

* `explicit` on the constructor prevents accidental conversion from a `double` to a
  `FatigueModel`.
* `: work_rate_(work_rate), ...` is a **member initialiser list**: members are
  initialised directly rather than assigned afterwards. Trailing underscores mark
  private members (a common style).
* The constructor **validates** rates: a negative rate would make fatigue explode.
* `after_work` clamps difficulty into 1..5 and fatigue into [0, 1] *defensively*, so
  invalid inputs can't produce invalid outputs.
* Why these formulas? Work: `F' = 1 − (1 − F)·e^{−r·load·m}`. The "headroom" `1 − F`
  shrinks exponentially, so fatigue rises fast when fresh and saturates near 1, never
  exceeding it. Rest: `F' = F·e^{−k·m}` is exponential recovery (a 15-minute break at
  k = 0.05 removes 53% of fatigue; a 16-hour night removes essentially all of it).
  Both are standard first-order dynamics: simple, bounded, monotonic and explainable in
  one sentence each.

## 3.3 `duration.hpp` / `duration.cpp`: reading the duration curve

<!-- include: engine/include/flexsched/duration.hpp -->
<!-- include: engine/src/duration.cpp -->

**Notes**

* Curve points sit at fatigue `i/(n−1)`. For fatigue `f`: `pos = f·(n−1)`, `lo = ⌊pos⌋`,
  `frac = pos − lo`, `value = curve[lo] + (curve[hi] − curve[lo])·frac`. That's **linear
  interpolation**.
* Validation rejects empty curves and non-positive values. `!(v > 0.0)` also catches
  **NaN**, because every comparison with NaN is false.
* `std::ceil(value − 1e-9)`: always round **up** (never under-book time), but ignore
  floating-point noise like `60.000000000001`. A Catch2 test caught a bug where the
  single-point path skipped this epsilon; both paths now share one rounding line.

## 3.4 `calendar.hpp` / `calendar.cpp`: free-slot computation

<!-- include: engine/include/flexsched/calendar.hpp -->
<!-- include: engine/src/calendar.cpp -->

**Notes**

* `merge_intervals` takes its argument **by value** (`std::vector<Interval> intervals`)
  because it needs its own copy to sort anyway; callers keep their data untouched.
* Erase–remove idiom drops empty intervals first so a zero-length interval can't
  "bridge" two real ones.
* Merging after sorting: if the next interval starts at or before the current end
  (`<=`, so *touching* intervals merge too), extend; otherwise start a new one.
* `free_slots` is a **two-pointer sweep**: `j` only moves forward through the blocked
  list, so the sweep is linear after sorting. Subtle detail: `j` is *not* advanced past
  intervals that might continue into the next window (a block from 16:00 day 1 to
  10:00 day 2 must cut both windows). There's a Catch2 test for exactly that.
* Complexity: O(W log W + B log B) to sort, O(W + B) to sweep.

## 3.5 `policy.hpp` / `policy.cpp`: the decision rules (Strategy pattern)

<!-- include: engine/include/flexsched/policy.hpp -->
<!-- include: engine/src/policy.cpp -->

**Notes**

* `SelectionPolicy` is an **abstract base class** (it has pure virtual functions). The
  scheduler only knows this interface, so adding a new strategy means writing one new
  class and one line in `make_policy`; the scheduler never changes. That's the
  **Open/Closed principle**.
* `make_policy` is a **factory**: it maps a string from JSON to an object and returns
  `std::unique_ptr<SelectionPolicy>`, so ownership is clear and no manual `delete` exists.
* **EDF** (`EdfPolicy::choose`): linear scan for the earliest deadline, with
  deterministic tie-breaks (higher priority, then lower id). Determinism matters:
  same input → same schedule → reproducible tests and benchmarks.
* **Score terms** (`FatigueAwarePolicy`):
    * `priority_term`: `(p − 1)/4` maps 1..5 to 0..1;
    * `urgency_term`: `1` if no slack left, else `e^{−slack/horizon}`. It decays smoothly,
      and with horizon = 480 min a task due a full working day after it would finish has
      urgency ≈ 0.37;
    * `energy_term`: `1 − |difficulty_norm − (1 − F)|`. It's 1 when a hard task meets a
      fresh mind or an easy task meets a tired one.
    * `score = 0.35·priority + 0.45·urgency + 0.20·energy` (weights from `Params`).
* `rank_by_score` scores each candidate **once** (not inside the comparator) and sorts
  indices with an **exact** comparator. `std::sort` requires a strict weak ordering, and
  an epsilon comparison would violate transitivity (undefined behaviour).
* **Rollout deadline guard** (`choose`):
  1. compute the lateness of "do everything in EDF order from now" (the reference);
  2. walk candidates best-score-first; for each, compute the lateness of "do this one
     first, then EDF for the rest";
  3. return the first candidate that is **no worse** than the reference in both late
     tasks and total late minutes;
  4. if none passes (possible when EDF's first task doesn't fit the current slot), fall
     back to EDF among the candidates.
* `rollout_lateness` packs tasks into the real free slots (`ctx.slots`), so a night
  or meeting between tasks is respected. It deliberately ignores future fatigue
  changes and breaks to stay cheap. That's a *heuristic* lookahead, not a proof. Part 5
  tells the story of how this guard evolved, with numbers.
* `EdfPolicy{}.choose(...)`: `EdfPolicy{}` creates a temporary object; it has no state,
  so this is cheap.

## 3.6 `scheduler.hpp` / `scheduler.cpp`: the main loop

<!-- include: engine/include/flexsched/scheduler.hpp -->
<!-- include: engine/src/scheduler.cpp -->

**Notes, following `run()` step by step**

* **Validation first** (`validate`): duplicate ids (detected with an
  `unordered_set`; `insert(...).second` is false if already present), out-of-range
  difficulty/priority, invalid curves. Bad input fails loudly instead of producing a
  quietly wrong schedule.
* **Deterministic order**: tasks are referenced by pointer and sorted by id.
* **Step 1, rest before the slot**: any gap (night, meeting, lunch) reduces fatigue
  via `after_rest`.
* **Step 2, breaks**: only if the policy wants breaks and `F ≥ threshold`. If the slot
  would end before a full break, skip to the next slot instead, because the gap after the
  slot already provides rest. (A real bug found in the demo: pointless 3-minute "breaks"
  at 16:57; fixed and covered by a Catch2 test.) `continue` re-evaluates the loop,
  because one break might not be enough.
* **Step 3, candidates**: compute every remaining task's duration *at the current
  fatigue*; those that fit before the slot ends are candidates; all go into `pending` for
  the lookahead.
* **Step 4, decide and commit**: build a `DecisionContext` (now, fatigue, params, slots,
  current slot, pending), ask the policy, append the block, update fatigue, advance the
  clock, erase the task from `remaining`.
* **Termination**: every iteration either advances time, consumes a slot or schedules
  a task. Slots and tasks are finite, so the loop must end (and `break_minutes > 0` is
  validated so breaks always advance time).
* **Step 5, explanations**: leftovers get a human-readable reason: longer than any free
  slot, or the horizon ran out.
* `compute_metrics` is a free function so it can be tested and reused independently.
* **Complexity**: with *n* tasks and *S* slots, each decision computes *n* durations and
  the guard runs up to *k* rollouts of O(n log n + S). Worst case is roughly
  O(n²·(n log n + S)) per plan. For realistic n (≤ 100) that's milliseconds.

## 3.7 `json_io.hpp` / `json_io.cpp`: the contract with Python

<!-- include: engine/include/flexsched/json_io.hpp -->
<!-- include: engine/src/json_io.cpp -->

**Notes**

* Uses **nlohmann/json**, the de-facto standard header-only JSON library for C++.
  `j.at("key")` throws if missing; `j.value("key", default)` returns a default.
* `parse_params` starts from defaults and overrides only provided keys. This is
  forward-compatible: older clients still work when new parameters are added.
* Every malformed shape becomes `std::invalid_argument` with a readable message
  ("task is missing 'deadline'"), and tests cover those cases.
* `to_json` omits `task_id`/`late` for breaks, so the output is precisely what each
  block kind needs.

## 3.8 `main.cpp`: the executable

<!-- include: engine/src/main.cpp -->

**Notes**

* Reads **all of stdin** into a string with `std::istreambuf_iterator`, parses, runs,
  prints one JSON line.
* **Exit codes are part of the contract**: 0 = success, 2 = bad input, 1 = internal
  error. Errors go to **stderr** so stdout is always valid JSON or empty.
  `engine_bridge.py` maps code 2 to `EngineInputError`.
* `catch` order matters: the most specific exception types come first.

## 3.9 `CMakeLists.txt`

<!-- include: engine/CMakeLists.txt -->

**Notes**

* C++17 required, no compiler extensions (portable code).
* Release is the default build type (optimised).
* Warnings on (`-Wall -Wextra -Wpedantic` / `/W4`). The project compiles with **zero
  warnings** on GCC 16.
* `-static` on MinGW bundles the C++ runtime into the `.exe`, so it runs on Windows
  without MinGW installed.
* `option(FLEXSCHED_BUILD_TESTS ...)` lets packagers skip downloading Catch2.

## 3.10 Catch2 test files

Each module has its own test file. Read them as **executable documentation**: every
`TEST_CASE` name is a sentence describing a behaviour.

### `test_fatigue.cpp`

<!-- include: engine/tests/test_fatigue.cpp -->

Covers: no-op for zero/negative minutes, exact formula values, harder-is-more-tiring,
bounds `[0,1]` under extreme inputs, clamping of out-of-range inputs, exponential rest
and monotonicity, rejection of negative rates.

### `test_duration.cpp`

<!-- include: engine/tests/test_duration.cpp -->

Covers: endpoints, interpolation midpoints, round-up rule and epsilon, single-point
curves, clamping, rejection of empty/zero/negative/NaN curves.

### `test_calendar.cpp`

<!-- include: engine/tests/test_calendar.cpp -->

Covers: overlap/touch/unsorted/contained/empty merging; free slots with nothing blocked,
middle split, edge trims, full cover, outside blocks, overlapping blocks, no windows, and
the tricky **multi-window block**.

### `test_policy.cpp`

<!-- include: engine/tests/test_policy.cpp -->

Covers: each score term, EDF tie-breaking, energy matching when fresh vs tired, urgency
beating energy, the deadline guard (override, no override, already-late task), rollout
simulation including **slot boundaries**, factory errors.

### `test_scheduler.cpp`

<!-- include: engine/tests/test_scheduler.cpp -->

Covers: empty inputs; first-slot placement; **invariants** (no overlap, inside free slots,
every task scheduled exactly once or reported) for both strategies on a 25-task
workload; reasons for unscheduled tasks; lateness accounting; breaks only for
fatigue-aware and their effect on fatigue; no break squeezed in at slot end; fatigue
lengthening later tasks; overnight recovery; **order independence**; every validation
error.

### `test_json_io.cpp`

<!-- include: engine/tests/test_json_io.cpp -->

Covers: defaults, parameter overrides, malformed requests, and the exact output shape.

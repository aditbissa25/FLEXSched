
# Part 5 — Algorithms & design deep dive

## 5.1 The fatigue model, with numbers

Parameters: `work_rate = 0.012`, `recovery_rate = 0.05`, load = difficulty / 5.

| Situation | Formula | Result |
|---|---|---|
| 60 min of difficulty-4 work, fresh | `1 − (1 − 0)·e^(−0.012·0.8·60)` = `1 − e^(−0.576)` | **0.438** |
| 60 min of difficulty-5 work, fresh | `1 − e^(−0.72)` | 0.513 |
| 60 min of difficulty-1 work, fresh | `1 − e^(−0.144)` | 0.134 |
| 15-min break at F = 0.693 | `0.693·e^(−0.75)` | **0.327** |
| 115-min gap (lunch + meeting) at F = 0.327 | `0.327·e^(−5.75)` | **0.001** |
| Night (16 h) at F = 1.0 | `e^(−48)` | ≈ 0 |

Properties worth stating in an interview:

* **Bounded**: F always stays in [0, 1], by construction and by clamping.
* **Monotonic**: more work → more fatigue; more rest → less fatigue.
* **Diminishing**: the same hour adds less fatigue when you're already tired
  (headroom shrinks), which is a realistic saturation.
* **Two parameters**, both interpretable. They're defaults, not fitted to a real
  person (see limitations); the roadmap shows how to fit them from logged data.

## 5.2 Free slots, worked example

Working windows: day 1 09:00–17:00 (540–1020) and day 2 09:00–17:00 (1980–2460).
Blocked: lunch 13:00–14:00 (780–840).

```
windows:   [540 ─────────────────────── 1020]        [1980 ────────── 2460]
blocked:                [780 ── 840]
free:      [540 ──────── 780]  [840 ──── 1020]        [1980 ────────── 2460]
```

## 5.3 A full scheduler trace (`engine/examples/request.json`)

Tasks (durations shown at fatigue 0):

| id | difficulty | priority | deadline | duration @F=0 |
|---|---|---|---|---|
| 1 | 5 | 5 | day 2 17:00 | 120 |
| 2 | 4 | 4 | day 1 15:00 | 60 |
| 3 | 1 | 3 | day 1 12:00 | 20 |
| 4 | 2 | 4 | day 1 17:00 | 30 |
| 5 | 3 | 2 | none (9999) | 45 |

**Decision at 09:00 (F = 0):** all five fit before 13:00. Scores
(`0.35·P + 0.45·U + 0.20·E`):

| id | slack (min) | priority term P | urgency U | energy E | **score** |
|---|---|---|---|---|---|
| 1 | 1800 | 1.00 | 0.024 | 1.00 | 0.561 |
| **2** | 300 | 0.75 | 0.535 | 0.75 | **0.653** |
| 3 | 160 | 0.50 | 0.717 | 0.00 | 0.497 |
| 4 | 450 | 0.75 | 0.392 | 0.25 | 0.489 |
| 5 | 9414 | 0.25 | 0.000 | 0.50 | 0.188 |

Task 2 wins. The rollout guard checks "2 first, then EDF (3, 4, 1, 5)" against
"pure EDF (3, 2, 4, 1, 5)". Neither causes lateness, so task 2 is accepted.

**Resulting timetable (fatigue-aware):**

| time | block | F start → end | why |
|---|---|---|---|
| 09:00–10:00 | task 2 (diff 4) | 0.000 → 0.438 | best score while fresh |
| 10:00–10:22 | task 3 (diff 1) | 0.438 → 0.467 | urgent (due 12:00), easy; duration 22 not 20 because tired |
| 10:22–10:56 | task 4 (diff 2) | 0.467 → 0.547 | |
| 10:56–11:50 | task 5 (diff 3) | 0.547 → 0.693 | the only one left that fits before 13:00 |
| 11:50–12:05 | **break** | 0.693 → 0.327 | F ≥ 0.65 |
| 12:05–13:00 | (free, unused) | | task 1 needs ~136 min at F = 0.33: doesn't fit before 13:00 |
| 13:00–14:00 | (blocked) | | rest: F → 0.001 |
| 14:00–16:01 | task 1 (diff 5) | 0.001 → 0.766 | the hardest task gets a fresh mind |

EDF on the same input does 3, 2, 4, 5, then 1 with no break. The 12:05–13:00 hole shows a
real limitation: tasks can't be split (see the roadmap).

## 5.4 The rollout deadline guard: how it evolved (a good story for interviews)

The first version of the fatigue-aware policy was *score + breaks* only. The benchmark
exposed a problem:

| version | idea | avg total lateness (min) | EDF reference |
|---|---|---|---|
| v1 | score + breaks | 143 *(100 scenarios)* | 101 |
| v2 | one-step guard: don't postpone the single most urgent task | 114 | 91 |
| v3 | rollout: "this task first, then EDF", continuous time | 112 | 91 |
| v4 | rollout packs tasks into real **free slots** (nights, meetings) | 96 | 91 |
| **v5 (final)** | rollout over **all remaining tasks**, not just those fitting now | **90.4** | **90.9** |

Two lessons:

1. **An ablation found the real cause.** I first suspected breaks (they cost time), so I
   ran the policy with breaks disabled. Lateness was unchanged, so breaks weren't the
   culprit; the **ordering decisions** were. That pointed to the lookahead.
2. **The lookahead was blind to nights.** Simulating "back to back" made a large
   due-tomorrow task look safe at 16:00. Packing into real slots fixed most of the gap,
   and giving the rollout every remaining task closed it.

**Mechanism in one sentence:** *pick the highest-scoring task whose "do it first, then
EDF" simulation produces no more late tasks and no more late minutes than plain EDF
would from the same moment.*

**Cost:** for k candidates and n pending tasks, each decision costs
O(k·(n log n + S)), which is milliseconds for realistic sizes.

## 5.5 Why greedy? (scheduling theory you can quote)

* With fixed durations on one machine, **EDF (Jackson's rule) minimises the maximum
  lateness**, so it's the natural baseline.
* Minimising the **number of late jobs** has an exact O(n log n) algorithm
  (Moore–Hodgson).
* Minimising **total tardiness** on one machine is **NP-hard** (Du & Leung, 1990).
* FLEXSched's durations also depend on **the order** (fatigue carries over), which
  makes exact optimisation even harder.

So FLEXSched uses a **greedy simulation with a lookahead guard**: fast, deterministic
and explainable, protected against the main failure mode (deadlines), and benchmarked
against the textbook baseline. The roadmap proposes an exact/metaheuristic optimiser
(OR-Tools CP-SAT or local search) as an upgrade.

## 5.6 ML design decisions (summary)

| Decision | Why | Alternative rejected |
|---|---|---|
| Predict **ratio** actual/estimate | scale-free; trees can't extrapolate raw minutes | raw minutes as target |
| **Temporal** 80/20 split | mirrors real use (past → future), no leakage | random split |
| `TimeSeriesSplit` CV for model selection | honest choice; hold-out touched once | choosing by hold-out score |
| Two **baselines** | proves the model adds value | reporting model scores alone |
| `Pipeline` + `ColumnTransformer` | no preprocessing leakage, one artefact to save | manual preprocessing |
| **Fatigue as a feature** → curve | lets the engine read duration at any fatigue | one fixed prediction per task |
| Monotone curve (running max) | encodes domain knowledge, removes model noise | trusting raw tree output |
| Refit on all data after evaluation | production uses every sample | shipping the 80% model |
| Heuristic fallback | the system works from day one (cold start) | refusing to plan |

## 5.7 Design patterns and principles

| Pattern / principle | Where |
|---|---|
| **Strategy** | `SelectionPolicy` with `EdfPolicy`, `FatigueAwarePolicy` |
| **Factory** | `make_policy(name)` |
| **Repository** | `TaskRepository`, `SessionRepository`, `ScheduleRepository` |
| **Service layer** | `planner.py` coordinates repositories, predictor, engine |
| **Pipeline** | scikit-learn preprocessing + model |
| **Adapter / anti-corruption layer** | `engine_bridge.py` + `build_request` translate between Python objects and the engine contract |
| **Single Responsibility** | one concern per C++ module and per Python module |
| **Open/Closed** | new strategies without touching the scheduler loop |
| **Dependency Inversion** | `Scheduler` depends on the abstract `SelectionPolicy` |
| **RAII** | `std::unique_ptr` ownership; `with conn:` transactions in Python |
| **Fail fast** | validation in engine, repository, CLI and DB constraints |
| **Determinism** | stable tie-breaks, seeded RNGs, fixed benchmark date |

## 5.8 Complexity summary

| Operation | Time |
|---|---|
| `merge_intervals` | O(m log m) |
| `free_slots` | O(W log W + B log B) |
| `effective_duration` | O(1) |
| one scheduling decision | O(n) durations + O(k·(n log n + S)) guard |
| whole plan | ≈ O(n²·(n log n + S)) worst case; ms for n ≤ 100 |
| ML training | dominated by 5 models × 6 fits; ~8 s on 445 rows |
| curve prediction | one vectorised `predict` for all tasks × 5 levels |
| engine call overhead | ~50 ms (process start-up on Windows) |

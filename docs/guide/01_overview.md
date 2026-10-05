# FLEXSched – The Complete Project Guide

*Intelligent, fatigue-aware task scheduler & planner — Python · C++ · scikit-learn · SQLite · Catch2*

**Author:** Adit Bissa

---

## How to use this guide

This document has two jobs:

1. **Teach you the project from zero.** Every technology, every file, every important
   line of code and every algorithm is explained. If you only know Python basics, ML
   basics and SQL basics, read it front to back once; you will then understand every
   design decision well enough to defend it.
2. **Let you present the project.** Part 1 is a self-contained presentation (pitch,
   architecture, results, demo script). Part 7 is an interview drill with model answers.

| Part | What it gives you | When to read it |
|---|---|---|
| 1. Overview | pitch, architecture, data flow, results, demo script | before any presentation |
| 2. Tech-stack primers | Python, C++, CMake, SQLite/SQL, scikit-learn, testing concepts used here | first study pass |
| 3. C++ engine code walkthrough | every engine file, fully listed and explained | second study pass |
| 4. Python code walkthrough | every Python file, fully listed and explained | second study pass |
| 5. Algorithms & design deep dive | worked examples, complexity, design patterns, the story of the deadline guard | before technical interviews |
| 6. Results, limitations, how to run | honest numbers, assumptions, setup and troubleshooting | before demos |
| 7. Interview drill | what → why → how → trade-offs → advanced, for every resume line + tech-stack justification | the night before |

> **Golden rule for interviews:** never claim more than the code does. Everything this
> guide says about FLEXSched is backed by a file you can open, and Part 6 lists the
> limitations so that you can name them before the interviewer does.

---

# Part 1 — The project in ten minutes

## 1.1 Elevator pitches

**30 seconds.** "FLEXSched is a task scheduler that knows you get tired. It learns from
your work history how long tasks *really* take, including how much slower you are when
fatigued, using scikit-learn. A C++ engine then simulates your energy through the day and
builds a timetable that does hard work when you're fresh, easy work when you're tired,
and inserts breaks, while a lookahead guard makes sure it never causes more deadline
misses than the classic Earliest-Deadline-First rule. Data lives in SQLite, and the engine
is covered by Catch2 unit tests."

**2 minutes** (add these to the 30-second version):

* *The problem:* people underestimate tasks (the "planning fallacy") and slow down when
  tired, but calendar tools treat durations as fixed numbers.
* *The key idea:* a task's duration is not a number but a **curve**: minutes as a
  function of fatigue. The ML model produces the curve; the engine reads it at the
  fatigue level it simulates.
* *The architecture:* Python handles data, ML and orchestration. The C++ engine is a
  standalone executable that takes JSON on stdin and writes JSON on stdout, so each half
  can be tested and replaced on its own.
* *The evidence:* on a temporally held-out test set the model cuts duration error by 62%
  versus trusting the user's estimate. Over 200 random scheduling scenarios the
  fatigue-aware policy lowers average fatigue at task start by 17% and peak fatigue by 7%,
  with the same total lateness as EDF.

## 1.2 The problem

Two well-documented human facts:

1. **Planning fallacy.** People systematically underestimate how long tasks take, and the
   error depends on the kind of task (coding is notoriously underestimated; admin often
   overestimated).
2. **Fatigue.** Mental work tires you; tired people are slower and make more mistakes.
   Short breaks restore a lot of capacity; a night's sleep restores nearly all of it.

Ordinary to-do and calendar apps ignore both. A schedule built on raw guesses and a
fixed duration per task falls apart by mid-afternoon.

## 1.3 What FLEXSched does

* Stores tasks (title, category, difficulty 1–5, priority 1–5, your estimate, optional
  deadline) and a **history of real work sessions** in SQLite.
* Reconstructs **how tired you were** at the start of every past session by replaying the
  day through a fatigue model.
* Trains and compares five regression models (two baselines, Ridge, Random Forest,
  Gradient Boosting), picks the best by **time-series cross-validation**, and predicts
  each task's duration at five fatigue levels → a **duration curve**.
* Computes **free time** (working hours minus meetings/lectures) and runs a **greedy,
  fatigue-simulating scheduler** in C++ with two pluggable strategies:
    * `edf`: Earliest Deadline First, the fatigue-blind textbook baseline;
    * `fatigue_aware`: priority + urgency + *energy match*, breaks, and a
      **rollout deadline guard**.
* Saves every generated plan, compares strategies, benchmarks them on hundreds of random
  scenarios, and shows estimation-bias statistics, all from a command-line interface.

## 1.4 Architecture

```
  you --> CLI (python -m flexsched)
               |
               v
  +------------------------------+
  |  planner.py  (orchestration) |
  +------------------------------+
        |              |                 |
        | SQL          | predict()       | JSON request on stdin
        v              v                 v  JSON schedule on stdout
  +----------------+ +---------------+ +-----------------------------------+
  | SQLite         | | scikit-learn  | | C++17 engine (flexsched_engine)   |
  |                | | pipeline      | |                                   |
  | tasks          | |               | |  calendar  -> free slots          |
  | work_sessions  | | Ridge / RF /  | |  fatigue   -> F after work/rest   |
  | schedule_runs  | | GradBoosting  | |  duration  -> curve interpolation |
  | schedule_items | |               | |  policy    -> EDF | fatigue-aware |
  +----------------+ +---------------+ |  scheduler -> greedy simulation   |
                                       |  json_io   -> request/response    |
                                       +-----------------------------------+
                                          tested by Catch2 (39 test cases)
```

**Responsibilities**

| Layer | Language | Files | Owns |
|---|---|---|---|
| Interface | Python | `cli.py` | parsing commands, printing tables |
| Service / orchestration | Python | `planner.py`, `benchmark.py` | DB → ML → engine → DB |
| ML | Python | `predictor.py`, `synthetic.py`, `fatigue.py` | training, evaluation, curves |
| Persistence | Python + SQL | `schema.sql`, `db.py`, `repository.py` | all SQL lives here |
| Scheduling core | C++17 | `engine/` | free time, fatigue, policies, scheduling |

## 1.5 What happens when you run `python -m flexsched plan`

1. `cli.py` parses the arguments (`--start`, `--days`, `--block`, …) and opens SQLite.
2. `planner.plan()` loads all `pending`/`scheduled` tasks through `TaskRepository`.
3. It loads the trained model (`DurationPredictor.load`). For every task it predicts
   minutes at fatigue 0, 0.25, 0.5, 0.75 and 1.0 in **one vectorised call**.
4. It converts real datetimes into **integer minute offsets** from the first planned
   day's midnight (the engine never deals with dates or time zones).
5. It sends one JSON request to `flexsched_engine` through `subprocess.run`.
6. The engine merges the working windows, subtracts blocked intervals (free slots), then
   simulates the day: rest during gaps, breaks when tired, ask the policy what to do
   next, place the task, update fatigue, repeat.
7. The engine prints a JSON response: blocks, unscheduled tasks with reasons, metrics.
8. Python converts offsets back to datetimes, attaches titles, saves the run and its
   items **in one transaction**, updates task statuses and prints the timetable.

## 1.6 Results at a glance

| Claim | Number | Where it comes from |
|---|---|---|
| Duration error vs trusting your estimate | **17.47 → 6.68 min MAE (−62%)** | `flexsched train` on 445 sessions, temporal 80/20 split |
| Variance explained | R² 0.61 → 0.94 | same |
| Avg fatigue at task start, fatigue-aware vs EDF | **0.321 → 0.265 (−17%)** | `flexsched benchmark --scenarios 200` |
| Peak fatigue | 0.842 → 0.783 (−7%) | same |
| Total lateness | 90.9 → 90.4 min (equal) | same |
| Engine tests | 39 Catch2 test cases, ~340 assertions | `ctest` |
| Python tests | 49 pytest tests | `pytest` |

*All data is synthetic (Part 6 explains why, and what that means).*

## 1.7 Demo script (5 minutes)

```bash
python -m flexsched demo
```

What to say while it runs:

1. *"First it simulates 120 days of a person's work history. The simulated person has
   hidden habits: they underestimate coding by about 35%, they slow down when tired, and
   there's a post-lunch dip."*
2. *"Then it trains five models. Note the two baselines: trusting your own estimate gives
   about 17.5 minutes of error; the chosen model gives about 6.7. Model selection uses
   time-series cross-validation, so the hold-out set is never used to choose."*
3. *"It adds ten realistic tasks with deadlines and a couple of meetings, and compares
   strategies on identical input."*
4. *"Here's the fatigue-aware plan. Look at the fatigue column: the 3-hour 'Implement
   auth module' task, the hardest one, starts at 0.01 fatigue right after lunch. Breaks
   appear when fatigue crosses 0.65, and nothing is late."*

Then optionally show the engine standing alone:

```bash
build/flexsched_engine < engine/examples/request.json
```

*"The engine is a plain executable with a JSON contract: I can test, debug and benchmark
it without Python at all."*

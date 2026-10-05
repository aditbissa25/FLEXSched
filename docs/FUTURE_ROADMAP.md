# FLEXSched – Future Roadmap

*From a strong portfolio project to a production-grade, full-stack software product.*

This document is a plan, not a wish list. Every item says **what** to build, **why** it
matters, **how** to do it with concrete technologies, and which **existing code**
changes. Items are grouped into levels; each level is a coherent, demo-able release.

---

## 0. Where the project stands today (v1.0)

| Area | Today | Gap to production |
|---|---|---|
| Users | single user, local CLI | accounts, multi-device, UI |
| Data | SQLite file, synthetic history | real data collection, multi-tenant DB, migrations |
| ML | 5 models, temporal CV, curves at a fixed hour | real-data validation, personalisation, uncertainty, monitoring |
| Scheduling | greedy + rollout guard, no task splitting | splitting, optimisation, re-planning, calendar sync |
| Engineering | Catch2 + pytest, CI on 2 OSes | API, packaging, observability, security, deployment |

The limitations in `PROJECT_GUIDE.md` §6.2 map one-to-one to items below.

---

## Level 1: Make the core smarter (algorithm & ML depth)
*Goal: fix every known modelling limitation. Still a local app. ~2–4 weeks.*

### 1.1 Task splitting (pre-emption) ★ highest impact
* **What:** allow a task to be split into chunks (min chunk, e.g. 25 min, Pomodoro-style).
* **Why:** today a 2-hour task can't use two 1-hour holes (the unused 12:05–13:00 in the
  guide's trace).
* **How:** add `splittable` and `min_chunk_minutes` to `Task` (SQL column + JSON field).
  In `scheduler.cpp`, when no whole task fits, consider placing a chunk of length
  `min(remaining, slot_left)` and keep the remainder in `remaining`. Track remaining
  minutes per task. Add a context-switch penalty to the score.
* **Tests:** invariants still hold; chunks of one task never overlap; a 120-min task fills
  two 60-min slots.

### 1.2 Duration grid: fatigue × hour of day
* **What:** predict a 2-D grid (5 fatigue levels × e.g. 9 start hours) and interpolate
  bilinearly in the engine.
* **Why:** removes the "assume 11:00" approximation, so the post-lunch dip is applied
  where it actually falls.
* **How:** `predictor.duration_curves` → `duration_grid`; JSON `duration_grid` +
  `grid_hours`; `duration.cpp` gains `effective_duration(grid, fatigue, minute_of_day)`.

### 1.3 Learn fatigue parameters from data
* **What:** fit `work_rate` and `recovery_rate` per user.
* **How:** treat them as hyper-parameters: for each candidate pair, recompute
  `fatigue_at_start` via `replay_day`, run time-series CV, keep the pair with the lowest
  MAE (grid search → Optuna). Store per-user params in a `user_params` table.
* **Why:** turns the biggest assumption into a measured quantity.

### 1.4 Uncertainty-aware scheduling
* **What:** predict P50 and P80 durations (quantile Gradient Boosting or conformal
  intervals); book P80 for deadline-critical tasks.
* **Why:** a schedule that's right "on average" still misses deadlines half the time.
* **Metric:** probability of meeting each deadline, shown in the plan.

### 1.5 A real optimiser as a third strategy
* **What:** `strategy: "optimal"` using **Google OR-Tools CP-SAT** (interval variables,
  no-overlap constraint, deadlines as soft constraints, fatigue approximated by
  piecewise-linear costs), or a **local search** (simulated annealing / tabu) over
  the greedy solution.
* **Why:** quantify how far greedy is from optimal; offer "think longer" mode.
* **How:** new `SelectionPolicy` isn't enough here (it's a global method), so add a
  `Planner` interface in C++ (`GreedyPlanner`, `LocalSearchPlanner`) above `Scheduler`.

### 1.6 Tune score weights automatically
* Search `w_priority`, `w_urgency`, `w_energy`, `break_threshold` on the benchmark with
  the objective *minimise fatigue subject to lateness ≤ EDF*. Report a Pareto front
  (fatigue vs lateness) instead of one point.

### 1.7 Smarter context
* Meetings consume energy (load per blocked interval) instead of counting as rest.
* Dependencies between tasks (`depends_on` table → precedence constraints = a DAG; schedule
  in topological order, detect cycles).
* Energy check-ins: the user reports "I feel 3/5" and the scheduler resets F.

---

## Level 2: Real users and real data (product foundation)
*Goal: a usable app that collects real data. ~1–2 months.*

### 2.1 REST API
* **FastAPI** (Python) with Pydantic models generated from the existing dataclasses.
* Endpoints: `/tasks` CRUD, `/sessions` (start/stop timer), `/plans` (create, list,
  get), `/stats`, `/model/train`.
* OpenAPI docs come for free; versioned routes (`/v1/...`).
* `planner.py` stays the service layer; the API is just a new interface next to the CLI.
  That's the payoff of the layered design.

### 2.2 Web frontend
* **React + TypeScript** (Vite), a calendar view (FullCalendar), drag-and-drop to
  override the plan, a fatigue curve chart, a start/stop timer that writes
  `work_sessions` (real data collection).
* Alternative fast path: **Streamlit** dashboard for a demo in a day.

### 2.3 Accounts and multi-tenancy
* Auth via OAuth2/OIDC (Google sign-in) or Auth0/Cognito; JWT access tokens.
* Add `user_id` to every table, enforce ownership in every repository query
  (or PostgreSQL row-level security).

### 2.4 PostgreSQL + migrations
* Move from SQLite to **PostgreSQL** (SQLAlchemy 2.0 Core/ORM + **Alembic** migrations).
* Only `db.py` and `repository.py` change (the Repository pattern pays off).
* Use `TIMESTAMPTZ` and store UTC; convert to the user's time zone at the edges.

### 2.5 Calendar integration
* Import busy times from **Google Calendar / Outlook** (OAuth, read-only scope) as
  blocked intervals; optionally export the plan as events (ICS feed).
* Handle time zones and DST properly (zoneinfo).

### 2.6 Re-planning
* When the user logs that a task over-ran, re-plan the rest of the day automatically
  (warm-start from the current plan; minimise changes ("plan stability") as a soft
  objective).

---

## Level 3: Production engineering
*Goal: deployable, observable, secure, maintainable. Ongoing.*

### 3.1 Engine integration upgrade
* Replace the subprocess bridge with **pybind11** bindings (engine as a Python extension),
  built with **scikit-build-core** into wheels for Linux/macOS/Windows via
  **cibuildwheel**. Keep the CLI executable for debugging.
* Or run the engine as a **gRPC** microservice if other languages need it.
* Benefit: removes ~50 ms per call; enables thousands of simulations per second.

### 3.2 Packaging and deployment
* **Docker** multi-stage build (compile the engine in a builder image, copy the binary
  into a slim Python image).
* **docker-compose** for API + PostgreSQL + worker locally; deploy to a managed platform
  (Render/Fly.io/AWS ECS/Azure Container Apps).
* Background jobs (training, calendar sync) with **Celery/RQ + Redis** or a cloud queue.

### 3.3 MLOps
* **Experiment tracking** (MLflow): parameters, metrics, artefacts per training run.
* **Model registry** and versioned models per user; store the model version on every
  plan for reproducibility.
* **Monitoring**: live MAE per user (predicted vs logged actual), drift detection on
  feature distributions; retrain on schedule or on drift.
* **Global + personal model**: a population model as a prior, per-user calibration
  (hierarchical / mixed-effects or per-user offset), which solves cold start.

### 3.4 Quality gates in CI
* Static analysis: **clang-tidy**, **cppcheck**; **ruff** + **mypy --strict** for Python.
* **Sanitizers** (ASan/UBSan) in a CI job; **coverage** (gcovr / coverage.py) with
  thresholds; **pre-commit** hooks.
* **Property-based tests** (RapidCheck for C++, Hypothesis for Python) for the scheduler
  invariants; **fuzz** the JSON parser (libFuzzer).
* **Benchmark regression**: Catch2 `BENCHMARK` + a stored baseline; fail CI on >10%
  slowdown.
* Contract tests: a JSON Schema for the engine request/response, validated on both sides.

### 3.5 Observability and reliability
* Structured logging (JSON), request IDs, **OpenTelemetry** traces across API → planner
  → engine; Prometheus metrics (plan latency, engine errors, model MAE).
* Timeouts, retries with backoff for calendar APIs, graceful degradation
  (heuristic curves if the model is unavailable, which already exists as the cold start).

### 3.6 Security and privacy
* Secrets in a vault/env, never in the repo; dependency scanning (Dependabot, pip-audit);
  HTTPS only; rate limiting.
* Privacy by design: work-pattern data is sensitive. Make it opt-in, provide export and delete
  (GDPR-style), encrypt at rest, and never expose individual fatigue data to employers.

---

## Level 4: Differentiating features (pick one or two for a standout story)

| Feature | Tech | Interview value |
|---|---|---|
| **Natural-language task entry** ("finish report by Fri, ~2h, hard") | an LLM with structured output → `Task` | modern AI integration with validation |
| **Reinforcement-learning scheduler** (policy learned in the simulator) | gym-style env around the C++ engine, PPO | the simulator becomes a training environment |
| **Team scheduling** (multiple people, shared tasks, meetings) | multi-machine scheduling, CP-SAT | classic hard optimisation problem |
| **Wearable signals** (sleep, HRV) as fatigue inputs | Health APIs, time-series features | personalised, data-rich ML |
| **Mobile app** with notifications ("break now", "start X") | React Native / Flutter | full product loop |
| **What-if simulator** ("what if I add this task?") | engine batch mode | showcases engine speed |

---

## Pivot options (if you want to reposition the project)

1. **"ML systems" pivot:** emphasise Level 1.3–1.4 + 3.3 (personalised models, uncertainty,
   MLOps, monitoring). Pitch: *"a personalised duration-prediction service with
   drift monitoring."*
2. **"Algorithms / optimisation" pivot:** emphasise 1.1, 1.5, 1.6 + team scheduling.
   Pitch: *"a scheduling engine comparing greedy, local search and CP-SAT with a
   reproducible benchmark."*
3. **"Full-stack SWE" pivot:** emphasise Level 2 + 3.1–3.2. Pitch: *"a deployed web app with
   a C++ core, REST API, auth, PostgreSQL and CI/CD."*
4. **Hybrid (recommended):** Level 1.1 + 1.2 + 2.1 + 2.2 + 2.4 + 3.1 + 3.4. That's the smallest
   set that makes it simultaneously an algorithms, ML and full-stack project.

---

## Suggested order of work

| Step | Items | Outcome / demo |
|---|---|---|
| 1 | 1.1 task splitting, 1.2 duration grid | visibly better plans; closes two known limitations |
| 2 | 2.1 FastAPI, 2.2 minimal React UI with timer | real data collection starts |
| 3 | 2.4 PostgreSQL + Alembic, 2.3 auth | multi-user ready |
| 4 | 3.1 pybind11 + wheels, 3.2 Docker deploy | public demo URL |
| 5 | 1.3 fit fatigue params, 1.4 quantiles, 3.3 monitoring | real-data ML results to talk about |
| 6 | 1.5 optimiser + 1.6 tuning | "greedy vs optimal" benchmark chart |
| 7 | one Level-4 feature | the memorable story |

**Definition of "production-grade" for this project:** a deployed web app with
authentication; real user data; migrations; automated tests ≥ 80% coverage on core logic
plus property tests; CI/CD with static analysis and sanitizers; monitoring of both system
health and model accuracy; documented API; reproducible builds for every OS.

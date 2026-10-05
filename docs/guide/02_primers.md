
# Part 2 — Tech-stack primers

Each primer starts from what you already know and stops exactly at the depth this
project uses. The code samples are small and self-contained; Parts 3–4 then show the
real code.

## 2.1 Python features used in this project

### Modules, packages and `python -m`

* A **module** is one `.py` file. A **package** is a folder of modules with an
  `__init__.py` (here: `flexsched/`).
* `from .db import connect`: the leading dot is a **relative import** ("from the module
  `db` in *this* package").
* `python -m flexsched demo` runs the package as a program: Python executes
  `flexsched/__main__.py`, which calls `cli.main()`.

### Type hints and `from __future__ import annotations`

```python
def minutes_between(origin: datetime, moment: datetime) -> int: ...
def load(path: Union[str, Path, None] = None) -> Optional["DurationPredictor"]: ...
```

Type hints document what goes in and out. Python does **not** enforce them at run time;
tools such as mypy and IDEs use them. `from __future__ import annotations` makes all hints
lazy strings, so you can write `list[float]` or `date | None` on older Python versions and
refer to classes defined later in the file.

`Optional[X]` means "X or None". `Union[A, B]` means "A or B". `Iterable[X]` means
"anything you can loop over".

### Dataclasses

```python
@dataclass
class Task:
    title: str
    difficulty: int
    deadline: Optional[datetime] = None
```

`@dataclass` is a **decorator** (a function that takes a class and returns an improved
class). It generates `__init__`, `__repr__` and `__eq__` from the annotated fields.
`@dataclass(frozen=True)` (used for `SchedulerParams`) makes instances immutable, so a
parameter set can't be changed by accident halfway through a run.
`field(default_factory=list)` gives each instance its *own* new list. A plain `= []`
default would be shared by all instances, a classic Python bug.

### Context managers (`with`)

```python
with conn:                      # sqlite3: COMMIT on success, ROLLBACK on exception
    conn.execute(...)
```

`with` guarantees clean-up code runs even if an exception happens. FLEXSched uses it for
database transactions and pytest uses the same idea for `pytest.raises`.

### Comprehensions

```python
marks = ",".join("?" for _ in statuses)                    # generator expression
rows = [_row_to_task(r) for r in rows]                     # list comprehension
fatigue_by_id = {s.id: f for (s, _), f in zip(day_rows, fatigue)}   # dict comprehension
```

`zip(a, b)` walks two sequences in parallel; `(s, _)` **unpacks** a tuple and `_` means
"I don't need this value".

### Exceptions and custom exception classes

```python
class EngineError(RuntimeError): ...
class EngineInputError(EngineError): ...      # a more specific kind of EngineError

raise EngineError("engine timed out") from exc   # keep the original cause attached
```

A hierarchy lets callers catch broadly (`except EngineError`) or precisely
(`except EngineInputError`). `raise ... from exc` chains exceptions so the traceback
shows the root cause.

### `@property`, `@classmethod`, `@staticmethod`

* `@property` turns a method into a computed attribute: `session.actual_min` has no
  parentheses.
* `@classmethod` receives the class (`cls`) instead of an instance, and is used for
  alternative constructors: `DurationPredictor.load(path)`.

### Standard library modules used

| Module | Used for |
|---|---|
| `sqlite3` | the database driver (ships with Python) |
| `subprocess` | starting the C++ engine and piping JSON in/out |
| `json` | encoding requests, decoding responses, storing metrics |
| `argparse` | the command-line interface (sub-commands, typed options) |
| `datetime` | `datetime`, `date`, `time`, `timedelta` arithmetic |
| `pathlib` | `Path` objects instead of string paths (`path.parent.mkdir(...)`) |
| `math` | `exp` for the fatigue formulas |
| `tempfile` | the throw-away folder for `demo` |
| `shutil.which` | finding the engine on `PATH` |

### `*args`, `**kwargs` and keyword forwarding

```python
def compare(conn, start, days=1, **kwargs):
    kwargs["persist"] = False
    return {s: plan(conn, start, days, strategy=s, **kwargs) for s in STRATEGIES}
```

`**kwargs` collects extra keyword arguments into a dict, and `**kwargs` in a call spreads
them out again. That lets `compare` forward every option of `plan` without repeating them.

## 2.2 C++ primer (just what the engine needs)

### How C++ code becomes a program

```
fatigue.hpp ─┐ (declarations: "this function exists")
fatigue.cpp ─┴─► compiler ─► fatigue.o ─┐
scheduler.cpp ─► compiler ─► scheduler.o├─► linker ─► flexsched_engine.exe
main.cpp ─────► compiler ─► main.o ────┘
```

* **Header (`.hpp`)**: declarations, the *interface*. Other files `#include` it.
* **Source (`.cpp`)**: definitions, the *implementation*. Compiled once into an object file.
* **Linker**: stitches object files and libraries into an executable.
* `#pragma once` at the top of a header prevents it being included twice in one file.

Unlike Python, C++ is **compiled ahead of time** and **statically typed**: every type is
known at compile time, so many mistakes are caught before the program runs and the
machine code is fast.

### Namespaces

```cpp
namespace flexsched {
double clamp01(double x);
}
flexsched::clamp01(1.7);   // or: using namespace flexsched; (only inside .cpp/tests)
```

Namespaces prevent name collisions between libraries (like Python modules do).

### Fundamental types used

| Type | Meaning |
|---|---|
| `int` | integer (≥ 32 bits) |
| `std::int64_t` (alias `Minutes`) | exactly 64-bit integer: minute offsets never overflow |
| `double` | 64-bit floating point (fatigue, scores) |
| `bool` | true/false |
| `std::size_t` | unsigned integer used for sizes and indices |
| `std::string` | text |
| `std::vector<T>` | growable array, like a Python list of one type |

`using Minutes = std::int64_t;` creates a **type alias**: the code reads like the domain.

### `struct` vs `class`

Both define types. By convention: `struct` for plain data with public fields
(`Interval`, `Task`, `ScheduledBlock`); `class` for objects with behaviour and private
state (`FatigueModel`, `Scheduler`). Fields can have **default member initialisers**:
`int priority = 3;`.

### References, `const`, pointers

```cpp
double after_rest(double fatigue, Minutes minutes) const;          // by value (cheap types)
ScheduleResult run(const std::vector<Task>& tasks, ...) const;      // by const reference
std::vector<const Task*> remaining;                                 // pointers to tasks
```

* `const std::vector<Task>&` means "a reference to the caller's vector, which I promise
  not to modify". No copy is made, which matters for big objects.
* A `const` **member function** (`... ) const;`) promises not to modify the object.
* `const Task*` is a **pointer** (an address) to a task that cannot be modified through
  it. The scheduler keeps pointers so it can reorder/erase cheaply without copying tasks.
* `*ptr` dereferences; `ptr->field` is shorthand for `(*ptr).field`.

### RAII and `std::unique_ptr`

```cpp
std::unique_ptr<SelectionPolicy> policy = std::make_unique<EdfPolicy>();
```

**RAII** (Resource Acquisition Is Initialisation): an object's destructor frees what it
owns automatically when it goes out of scope. `std::unique_ptr` owns a heap object and
deletes it automatically, so there is no `delete` and no leak. It is **move-only** (can't be
copied; ownership is transferred with `std::move`), which is why `Scheduler` is also
move-only.

### Polymorphism: virtual functions

```cpp
class SelectionPolicy {
public:
    virtual ~SelectionPolicy() = default;
    virtual std::size_t choose(...) const = 0;   // "= 0": pure virtual, must be overridden
};
class EdfPolicy final : public SelectionPolicy {
    std::size_t choose(...) const override;       // compiler checks it really overrides
};
```

Calling `policy_->choose(...)` through a base-class pointer runs the **derived** class's
version, decided at run time (dynamic dispatch via a *vtable*). The base class needs a
**virtual destructor** so deleting through a base pointer destroys the derived object
correctly. `final` forbids further inheritance.

### Lambdas

```cpp
std::sort(v.begin(), v.end(), [&](std::size_t a, std::size_t b) { return scores[a] > scores[b]; });
```

A lambda is an inline anonymous function. `[&]` **captures** surrounding variables by
reference. Python's `lambda` is the same idea, limited to one expression.

### Algorithms from `<algorithm>`

* `std::sort(first, last, comp)`: O(n log n). **Requirement:** `comp` must be a *strict
  weak ordering* (irreflexive, transitive…). An epsilon-based "equal" breaks transitivity
  and is undefined behaviour; that's why FLEXSched compares scores exactly.
* `std::stable_sort`: keeps the original order of equal elements.
* `std::remove_if` + `erase`: the "erase–remove idiom" for deleting matching elements.
* `std::min`, `std::max`, `std::clamp(x, lo, hi)`, `std::any_of`, `std::adjacent_find`.

### Exceptions

```cpp
if (t.difficulty < 1 || t.difficulty > 5) throw std::invalid_argument("difficulty must be 1..5");
try { ... } catch (const std::invalid_argument& e) { std::cerr << e.what(); return 2; }
```

The engine validates input and throws `std::invalid_argument`; `main` catches it and
turns it into exit code 2 plus a message on stderr, which Python turns into
`EngineInputError`.

### Other syntax you will meet

* `static` member function: belongs to the class, not an instance (`FatigueAwarePolicy::score`).
* `constexpr`: a value computed at compile time (`constexpr Minutes kDay = 24 * 60;`).
* `auto`: let the compiler infer the type (`const auto slots = free_slots(...)`).
* Range-for: `for (const Task& t : tasks)`.
* `static_cast<double>(x)`: explicit, checked type conversion.
* `1'000'000`: digit separators for readability.
* Anonymous namespace `namespace { ... }`: helpers visible only inside one `.cpp` file.
* `R"( ... )"`: raw string literal (no escaping), used for JSON in tests.

## 2.3 CMake (the C++ build system)

Compiling many files with the right flags, downloading dependencies and producing test
executables by hand is error-prone. **CMake** describes the build once and generates
build files for any toolchain (Ninja, Make, Visual Studio).

```cmake
add_library(flexsched_core STATIC src/fatigue.cpp ...)        # a target: static library
target_include_directories(flexsched_core PUBLIC include)    # users of it see include/
target_link_libraries(flexsched_core PUBLIC nlohmann_json::nlohmann_json)
add_executable(flexsched_engine src/main.cpp)                 # the CLI program
target_link_libraries(flexsched_engine PRIVATE flexsched_core)
```

* **Targets** are things to build. Properties are attached *per target* ("modern CMake").
* `PUBLIC` = needed by me *and* by whoever links me; `PRIVATE` = only by me.
* **FetchContent** downloads a dependency at configure time and makes its targets
  available (Catch2, nlohmann/json), so no manual installs are needed.
* **CTest**: `enable_testing()` + `catch_discover_tests(flexsched_tests)` registers every
  Catch2 test case, so `ctest` runs them all and reports per case.
* Two-step workflow: `cmake -S engine -B build` (configure) → `cmake --build build` (compile).

Why split into `flexsched_core` (library) + `flexsched_engine` (exe) + `flexsched_tests`
(exe)? The **same compiled logic** is linked into both the program and the tests, so the
tests exercise exactly what ships.

## 2.4 SQLite and SQL

**SQLite** is a full SQL database engine in a library: the whole database is one file,
there is no server, and Python ships the driver (`sqlite3`). It is ACID-compliant and is
the most widely deployed database in the world (phones, browsers, apps).

### Schema concepts used

| Concept | In FLEXSched |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | unique row id, never reused |
| `NOT NULL` | value required |
| `CHECK (difficulty BETWEEN 1 AND 5)` | the DB itself rejects invalid data |
| `DEFAULT 'pending'`, `DEFAULT (datetime('now'))` | automatic values |
| `REFERENCES tasks(id) ON DELETE CASCADE` | foreign key; deleting a task deletes its sessions |
| `ON DELETE SET NULL` | a schedule item survives task deletion with `task_id = NULL` |
| `CREATE INDEX idx_sessions_started ON work_sessions(started_at)` | B-tree index → fast range queries by date |
| `IF NOT EXISTS` | idempotent schema script: safe to run every start-up |

**Gotcha:** SQLite has foreign keys **off by default**. `db.connect()` runs
`PRAGMA foreign_keys = ON` on every connection, and a test proves it works.

**Dates in SQLite:** there's no DATE type; FLEXSched stores ISO-8601 text
`'YYYY-MM-DD HH:MM:SS'`, which sorts correctly as text and works with `strftime()`.

### Queries used

```sql
-- JOIN + feature extraction in SQL
SELECT t.category, t.difficulty, s.actual_min,
       CAST(strftime('%H', s.started_at) AS INTEGER) AS hour_of_day
FROM work_sessions s JOIN tasks t ON t.id = s.task_id
WHERE s.fatigue_at_start IS NOT NULL
ORDER BY s.started_at;

-- Aggregation
SELECT t.category, COUNT(*) AS sessions, AVG(1.0 * s.actual_min / t.estimate_min) AS avg_ratio
FROM work_sessions s JOIN tasks t ON t.id = s.task_id
GROUP BY t.category HAVING COUNT(*) >= 1 ORDER BY avg_ratio DESC;
```

* `JOIN ... ON` combines rows of two tables that match.
* `GROUP BY` makes one output row per group; `COUNT`/`AVG` aggregate within the group;
  `HAVING` filters *groups* (`WHERE` filters *rows*).
* `1.0 * a / b` forces floating-point division (integer / integer truncates in SQLite).
* `LEFT JOIN` (in `runs()`) keeps runs even when they have zero items.

### Transactions and ACID

A **transaction** groups statements so they all happen or none do. Saving a schedule
writes one `schedule_runs` row and N `schedule_items` rows; if item 7 fails, the run row
must disappear too. `with conn:` gives exactly that, and a test forces a failure and
checks the rollback.

ACID = **A**tomic (all or nothing), **C**onsistent (constraints hold), **I**solated
(concurrent transactions don't see half-done work), **D**urable (committed data survives a
crash).

### Parameterised queries (SQL injection)

```python
conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))      # ✅ safe
conn.execute(f"SELECT * FROM tasks WHERE id = {task_id}")          # ❌ never do this
```

With `?` placeholders the driver sends data separately from SQL text, so input like
`1; DROP TABLE tasks` is just a weird value, never code.

### Schema versioning

`PRAGMA user_version` is an integer slot SQLite gives you for free. FLEXSched sets it to
1; a future migration would check `if current < 2: ALTER TABLE ...`.

## 2.5 Machine learning with scikit-learn

### The task: supervised regression

* **Features (X)**: inputs: category, estimate, difficulty, priority, fatigue at start,
  hour of day, day of week.
* **Target (y)**: what we predict. Here it's the **ratio** `actual_min / estimate_min`,
  and the prediction in minutes is `ratio × estimate`.
* **Regression** = predicting a number (vs classification = predicting a label).

### Train / validation / test and leakage

* Fit on **training** data, choose between models with **validation** (cross-validation),
  report once on an untouched **test (hold-out)** set.
* **Leakage** = information from the test set influencing training or model choice;
  results look great and then fail in reality.
* **Temporal data needs temporal splits.** We predict the *future* from the *past*, so
  FLEXSched holds out the most recent 20% of sessions, and cross-validation uses
  `TimeSeriesSplit` (each fold trains on earlier data and validates on later data).
  A random split would let the model "peek" at future habits.

```
TimeSeriesSplit(n_splits=5) on the training part:
fold 1: [train]               [val]
fold 2: [train  train]        [val]
fold 3: [train  train  train] [val]
...                                       (always: train before validation)
```

### Baselines

A model is only interesting if it beats something simple:

* `trust_estimate`: ratio = 1, i.e. believe the user. (`DummyRegressor(strategy="constant", constant=1.0)`)
* `mean_ratio`: multiply every estimate by the average historical ratio. (`DummyRegressor(strategy="mean")`)

### Preprocessing

* **One-hot encoding** turns `category="coding"` into columns
  `[coding=1, study=0, writing=0, ...]`. Models need numbers, and encoding categories as
  1,2,3 would invent a fake order. `handle_unknown="ignore"` keeps prediction working if
  a new category appears.
* **Standard scaling** (`(x − mean) / std`) puts numeric features on one scale. Ridge
  needs it because its penalty treats all coefficients equally; tree models don't.

### `Pipeline` and `ColumnTransformer`

```python
Pipeline([
    ("pre", ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), ["category"]),
                               ("num", StandardScaler(), NUMERIC)])),
    ("reg", Ridge(alpha=1.0)),
])
```

* `ColumnTransformer` applies different preprocessing to different columns.
* `Pipeline` chains preprocessing + model into **one object** with `fit`/`predict`.
* Why it matters: (1) preprocessing statistics (e.g. the scaler's mean) are learned **only
  from the training fold** inside cross-validation, which prevents leakage; (2) the saved
  model file contains everything needed to predict from raw columns.

### The models

| Model | Idea | Strengths / weaknesses |
|---|---|---|
| **Ridge** | linear regression + L2 penalty `α·Σw²` that shrinks coefficients | fast, stable, interpretable; only linear relationships |
| **Random Forest** | average of many decision trees, each trained on a bootstrap sample with random feature subsets (*bagging*) | captures non-linearity and interactions, robust; can't extrapolate, bigger |
| **Gradient Boosting** | trees added one at a time, each fitting the previous ensemble's errors (*boosting*), scaled by a learning rate | often the most accurate on tabular data; more hyper-parameters, can overfit |

Why did **Ridge win here?** In ratio space the simulated habits are close to
multiplicative factors that combine almost linearly, so a regularised linear model fits
them with very little variance. The tree models are close behind (and have slightly
higher R²) but don't beat it on cross-validated MAE. *"I let validation decide rather than
assuming the fanciest model wins"* is a good interview line.

### Metrics

* **MAE**, mean absolute error, in minutes: "on average we're off by 6.7 minutes".
  Easy to explain and robust to outliers.
* **MAPE**, mean absolute percentage error: scale-free ("10% off").
* **R²**: share of variance explained; 1.0 is perfect, 0 is as good as predicting the mean.

### Permutation importance

Shuffle one feature column in the hold-out set and measure how much the error grows. A
big increase means the model relies on that feature. It is model-agnostic and computed on
unseen data. FLEXSched's report shows `category`, `difficulty` and `fatigue_at_start` as
most important and `day_of_week` as ≈ 0, which matches the simulated habits (there is no
weekday effect in the generator). That is a nice sanity check.

### Persistence

`joblib.dump(obj, path)` / `joblib.load(path)` save and load Python objects (efficient for
NumPy arrays). FLEXSched stores the pipeline together with metadata: model name, training
time, report and **scikit-learn version** (models pickled with one version may not load in
another).

## 2.6 Testing concepts

### Kinds of tests here

| Kind | Example |
|---|---|
| **Unit** (one function/class in isolation) | Catch2 `free_slots` cases; pytest `validate_task` cases |
| **Edge-case** | empty curve, zero-length intervals, task longer than every slot, out-of-range input |
| **Invariant/property-style** | "blocks never overlap and always lie inside free slots", checked on a varied 25-task workload for both strategies |
| **Determinism** | reversed input order gives an identical schedule |
| **Integration** | Python → real engine binary → Python, `plan()` end to end with SQLite |
| **Cross-language parity** | Python fatigue model replays the engine's output and must match to 1e-9 |
| **CLI / smoke** | full `seed → train → add → plan → runs` workflow through `main()` |

### Catch2 (C++)

```cpp
TEST_CASE("Late tasks are flagged and lateness is summed", "[scheduler]") {
    const auto r = make("edf").run(tasks, work_days(1));
    REQUIRE(r.blocks.size() == 1);     // stop this test case if false
    CHECK(r.blocks[0].late);           // record failure but keep going
    SECTION("...") { ... }             // each SECTION re-runs the test case from the top
}
```

* `TEST_CASE(name, tags)`: tags like `[edge]` let you run subsets: `flexsched_tests "[edge]"`.
* `REQUIRE` vs `CHECK`: stop vs continue on failure. Use `REQUIRE` when later lines
  would crash (e.g. indexing `blocks[0]`).
* `CHECK_THROWS_AS(expr, std::invalid_argument)`: asserts the right exception type.
* `CHECK_THAT(x, WithinAbs(expected, 1e-12))`: floating-point comparison with tolerance.
* Expression decomposition: on failure Catch2 prints both sides (`61 == 60`).

### pytest (Python)

```python
@pytest.fixture
def conn():
    connection = connect(":memory:")   # setup
    yield connection                   # test runs here
    connection.close()                 # teardown

@pytest.mark.parametrize("field,value", [("difficulty", 0), ("priority", 9)])
def test_validation_rejects_bad_tasks(conn, field, value): ...
```

* **Fixtures** provide fresh resources by argument name; `scope="module"` builds an
  expensive one (90 days of history) once per file.
* `parametrize` runs one test body for many inputs.
* Built-in fixtures: `tmp_path` (a temp folder), `capsys` (captures printed output).
* `pytest.raises(ValueError)`: asserts an exception.
* `skipif` marker: integration tests are skipped (not failed) when the engine isn't built.

### Continuous Integration

`.github/workflows/ci.yml` runs on every push on **Ubuntu (GCC) and Windows (MSVC)**:
configure → build → `ctest` → `pytest`. A green badge means the project builds and passes
on two operating systems and two compilers, not just on my laptop.

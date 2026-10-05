"""Command-line interface (argparse, standard library).

    python -m flexsched <command> [options]

Commands: init, add, list, done, seed, train, stats, plan, compare, runs,
benchmark, demo. Run ``python -m flexsched <command> -h`` for details.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, config
from .benchmark import METRIC_KEYS, run_benchmark
from .db import connect
from .engine_bridge import EngineError
from .models import PlanResult, Task
from .planner import STRATEGIES, compare, log_session, plan
from .predictor import DurationPredictor, InsufficientDataError, train
from .repository import ScheduleRepository, SessionRepository, TaskRepository
from .synthetic import generate_history


# ------------------------------------------------------------ parsing -----

def parse_datetime(text: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"invalid date/time {text!r} (use 'YYYY-MM-DD HH:MM')")


def parse_date(text: str) -> date:
    if text == "today":
        return date.today()
    if text == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_datetime(text).date()


def parse_clock(text: str) -> time:
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid time {text!r} (use HH:MM)") from exc


def parse_block(text: str) -> tuple[datetime, datetime]:
    """'2026-10-07 13:00-14:00' -> (start, end)."""
    try:
        day_part, times = text.rsplit(" ", 1)
        start_s, end_s = times.split("-")
        start = parse_datetime(f"{day_part} {start_s}")
        end = parse_datetime(f"{day_part} {end_s}")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid block {text!r} (use 'YYYY-MM-DD HH:MM-HH:MM')") from exc
    if end <= start:
        raise argparse.ArgumentTypeError("block must end after it starts")
    return start, end


def int_range(lo: int, hi: int):
    def check(text: str) -> int:
        value = int(text)
        if not lo <= value <= hi:
            raise argparse.ArgumentTypeError(f"must be between {lo} and {hi}")
        return value
    return check


# ----------------------------------------------------------- printing -----

def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Render a plain-text table with aligned columns."""
    cells = [[str(h) for h in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def fatigue_bar(f: float, width: int = 10) -> str:
    filled = int(round(f * width))
    return "#" * filled + "." * (width - filled)


def print_plan(result: PlanResult) -> None:
    rows = []
    for b in result.blocks:
        rows.append([
            b.start.strftime("%a %d %b"),
            f"{b.start:%H:%M}-{b.end:%H:%M}",
            "--- break ---" if b.kind == "break" else f"[{b.task_id}] {b.title}"[:40],
            f"{fatigue_bar(b.fatigue_start)} {b.fatigue_start:.2f}",
            "LATE" if b.late else "",
        ])
    print(f"\nStrategy: {result.strategy}"
          + (f"   (saved as run #{result.run_id})" if result.run_id else ""))
    print(table(["Day", "Time", "What", "Fatigue at start", ""], rows) if rows
          else "(nothing scheduled)")
    for task_id, reason in result.unscheduled:
        print(f"  ! task {task_id} not scheduled: {reason}")
    m = result.metrics
    print(f"\n  tasks: {m['tasks_scheduled']} scheduled, {m['tasks_late']} late "
          f"({m['total_lateness']} min total) | work: {m['total_work_minutes']} min | "
          f"breaks: {m['breaks']} | avg fatigue at start: {m['avg_fatigue_at_start']:.2f} | "
          f"peak: {m['peak_fatigue']:.2f}")


def print_comparison(results: dict[str, PlanResult]) -> None:
    rows = [[k] + [_fmt(results[s].metrics[k]) for s in STRATEGIES] for k in METRIC_KEYS]
    print(table(["metric"] + list(STRATEGIES), rows))


def _fmt(v: object) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


# ----------------------------------------------------------- commands -----

def cmd_init(args, conn) -> None:
    print(f"Database ready at {args.db}")


def cmd_add(args, conn) -> None:
    task = TaskRepository(conn).add(Task(
        title=args.title, category=args.category, difficulty=args.difficulty,
        priority=args.priority, estimate_min=args.estimate, deadline=args.deadline))
    print(f"Added task #{task.id}: {task.title}")


def cmd_list(args, conn) -> None:
    statuses = None if args.all else ["pending", "scheduled"]
    tasks = TaskRepository(conn).list(statuses)
    if args.limit:
        tasks = tasks[-args.limit:]
    print(table(["id", "title", "category", "diff", "prio", "est", "deadline", "status"],
                [[t.id, t.title[:36], t.category, t.difficulty, t.priority, t.estimate_min,
                  f"{t.deadline:%Y-%m-%d %H:%M}" if t.deadline else "-", t.status]
                 for t in tasks]))


def cmd_done(args, conn) -> None:
    session = log_session(conn, args.task_id, args.start, args.minutes)
    print(f"Logged {args.minutes} min on task #{args.task_id} "
          f"(fatigue at start reconstructed as {session.fatigue_at_start:.2f})")


def cmd_seed(args, conn) -> None:
    n = generate_history(conn, days=args.days, seed=args.seed)
    print(f"Generated {n} synthetic work sessions over {args.days} days (seed {args.seed})")


def cmd_train(args, conn) -> None:
    predictor, report = train(conn)
    path = predictor.save(args.model)
    print(f"Trained on {report.rows} sessions "
          f"({report.train_rows} train / {report.holdout_rows} hold-out, time-ordered)\n")
    rows = [[name, f"{r['cv_mae']:.2f}", f"{r['holdout_mae']:.2f}",
             f"{100 * r['holdout_mape']:.1f}%", f"{r['holdout_r2']:.3f}",
             "<- chosen" if name == report.chosen_model else ""]
            for name, r in report.results.items()]
    print(table(["model", "CV MAE (min)", "hold-out MAE", "MAPE", "R^2", ""], rows))
    if report.feature_importance:
        print("\nPermutation importance (increase in error when a feature is shuffled):")
        for feat, val in sorted(report.feature_importance.items(), key=lambda kv: -kv[1]):
            print(f"  {feat:18s} {val:+.4f}")
    print(f"\nModel saved to {path}")


def cmd_stats(args, conn) -> None:
    rows = SessionRepository(conn).estimation_bias()
    if not rows:
        print("No work sessions logged yet.")
        return
    print("How long things REALLY take compared with your estimates:\n")
    print(table(["category", "sessions", "avg estimate", "avg actual", "actual/estimate"],
                [[r["category"], r["sessions"], r["avg_estimate"], r["avg_actual"],
                  r["avg_ratio"]] for r in rows]))


def _plan_kwargs(args) -> dict:
    return dict(day_start=args.day_start, day_end=args.day_end, blocked=args.block or [],
                predictor=DurationPredictor.load(args.model),
                skip_weekends=args.skip_weekends)


def cmd_plan(args, conn) -> None:
    kwargs = _plan_kwargs(args)
    if kwargs["predictor"] is None:
        print("(no trained model found - using the heuristic duration curve; "
              "run 'train' for ML predictions)")
    result = plan(conn, args.start, args.days, strategy=args.strategy,
                  persist=not args.dry_run, **kwargs)
    print_plan(result)


def cmd_compare(args, conn) -> None:
    results = compare(conn, args.start, args.days, **_plan_kwargs(args))
    print_comparison(results)


def cmd_runs(args, conn) -> None:
    rows = []
    for r in ScheduleRepository(conn).runs(args.limit):
        m = json.loads(r["metrics_json"])
        rows.append([r["id"], r["created_at"], r["strategy"], r["horizon_start"][:10],
                     r["horizon_days"], m.get("tasks_scheduled"), m.get("tasks_late"),
                     r["items"]])
    print(table(["run", "created", "strategy", "from", "days", "scheduled", "late", "items"],
                rows))


def cmd_benchmark(args, conn) -> None:
    predictor = DurationPredictor.load(args.model)
    print(f"Running {args.scenarios} random scenarios with both strategies "
          f"({'ML model' if predictor else 'heuristic durations'})...")
    result = run_benchmark(args.scenarios, args.seed, predictor)
    rows = [[k] + [f"{result.means[s][k]:.3f}" for s in STRATEGIES] for k in METRIC_KEYS]
    print(table(["metric (mean)"] + list(STRATEGIES), rows))
    print("\nShare of scenarios where fatigue_aware is strictly better than edf:")
    for k, v in result.paired_wins.items():
        print(f"  {k:22s} {100 * v:5.1f}%")


DEMO_TASKS = [
    # title, category, difficulty, priority, estimate, deadline (day offset, hour)
    ("Implement auth module", "coding", 5, 5, 120, (1, 17)),
    ("Fix flaky integration test", "coding", 4, 4, 60, (0, 15)),
    ("Read scheduling paper", "study", 4, 2, 90, (2, 17)),
    ("Reply to project emails", "admin", 1, 3, 20, (0, 12)),
    ("Write sprint report", "writing", 3, 4, 45, (1, 12)),
    ("Review teammate PR", "review", 2, 4, 30, (0, 17)),
    ("Design database schema", "design", 4, 3, 75, (2, 12)),
    ("Update documentation", "writing", 2, 2, 40, None),
    ("Plan next week", "admin", 2, 2, 25, None),
    ("Practice DSA problems", "study", 5, 3, 60, (2, 17)),
]


def cmd_demo(args, _conn) -> None:
    """End-to-end tour on a throw-away database: seed -> train -> plan -> compare."""
    workdir = Path(tempfile.mkdtemp(prefix="flexsched_demo_"))
    conn = connect(workdir / "demo.db")
    model_path = workdir / "model.joblib"
    start = date.today() + timedelta(days=1)

    print("== 1. Generating 120 days of synthetic work history ==")
    print(f"   {generate_history(conn, days=120, seed=42)} sessions")

    print("\n== 2. Training duration models ==")
    predictor, report = train(conn)
    predictor.save(model_path)
    best = report.results[report.chosen_model]
    naive = report.results["trust_estimate"]
    print(f"   chosen: {report.chosen_model} | hold-out MAE {best['holdout_mae']:.1f} min "
          f"vs {naive['holdout_mae']:.1f} min when trusting your own estimate")

    print("\n== 3. Adding this week's tasks ==")
    repo = TaskRepository(conn)
    origin = datetime.combine(start, time(0, 0))
    for title, cat, diff, prio, est, dl in DEMO_TASKS:
        deadline = origin + timedelta(days=dl[0], hours=dl[1]) if dl else None
        repo.add(Task(title, cat, diff, prio, est, deadline))
    print(f"   {len(DEMO_TASKS)} tasks added")

    blocked = [(origin + timedelta(hours=13), origin + timedelta(hours=14)),
               (origin + timedelta(days=1, hours=10), origin + timedelta(days=1, hours=11))]
    print("\n== 4. Comparing strategies (same tasks, same calendar) ==")
    print_comparison(compare(conn, start, 3, blocked=blocked, predictor=predictor))

    print("\n== 5. The fatigue-aware plan ==")
    print_plan(plan(conn, start, 3, blocked=blocked, predictor=predictor))
    print(f"\n(demo files in {workdir})")


# ------------------------------------------------------------- parser -----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flexsched",
                                description="Fatigue-aware task scheduler and planner")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--db", type=Path, default=config.DB_PATH, help="SQLite database file")
    p.add_argument("--model", type=Path, default=config.MODEL_PATH, help="trained model file")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database").set_defaults(func=cmd_init)

    a = sub.add_parser("add", help="add a task")
    a.add_argument("title")
    a.add_argument("--category", "-c", choices=config.CATEGORIES, required=True)
    a.add_argument("--difficulty", "-d", type=int_range(1, 5), default=3)
    a.add_argument("--priority", "-p", type=int_range(1, 5), default=3)
    a.add_argument("--estimate", "-e", type=int_range(1, 24 * 60), required=True,
                   help="your estimate in minutes")
    a.add_argument("--deadline", type=parse_datetime, help="'YYYY-MM-DD HH:MM'")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="list open tasks")
    l.add_argument("--all", action="store_true", help="include done/cancelled tasks")
    l.add_argument("--limit", type=int, default=0, help="show only the last N")
    l.set_defaults(func=cmd_list)

    d = sub.add_parser("done", help="log real work on a task (and mark it done)")
    d.add_argument("task_id", type=int)
    d.add_argument("--start", type=parse_datetime, required=True, help="'YYYY-MM-DD HH:MM'")
    d.add_argument("--minutes", type=int_range(1, 24 * 60), required=True)
    d.set_defaults(func=cmd_done)

    s = sub.add_parser("seed", help="generate synthetic history for demos")
    s.add_argument("--days", type=int_range(1, 3650), default=120)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(func=cmd_seed)

    sub.add_parser("train", help="train the duration model").set_defaults(func=cmd_train)
    sub.add_parser("stats", help="estimation bias per category").set_defaults(func=cmd_stats)

    for name, func, help_text in (("plan", cmd_plan, "build and save a schedule"),
                                  ("compare", cmd_compare, "compare strategies (no save)")):
        q = sub.add_parser(name, help=help_text)
        q.add_argument("--start", type=parse_date, default="tomorrow",
                       help="first day: YYYY-MM-DD, 'today' or 'tomorrow'")
        q.add_argument("--days", type=int_range(1, 60), default=1)
        q.add_argument("--day-start", type=parse_clock, default=time(9, 0))
        q.add_argument("--day-end", type=parse_clock, default=time(17, 0))
        q.add_argument("--block", type=parse_block, action="append",
                       help="busy time, repeatable: 'YYYY-MM-DD HH:MM-HH:MM'")
        q.add_argument("--skip-weekends", action="store_true")
        if name == "plan":
            q.add_argument("--strategy", choices=STRATEGIES, default="fatigue_aware")
            q.add_argument("--dry-run", action="store_true", help="do not save the plan")
        q.set_defaults(func=func)

    r = sub.add_parser("runs", help="show saved schedule runs")
    r.add_argument("--limit", type=int, default=10)
    r.set_defaults(func=cmd_runs)

    b = sub.add_parser("benchmark", help="compare strategies on random scenarios")
    b.add_argument("--scenarios", type=int_range(1, 10000), default=100)
    b.add_argument("--seed", type=int, default=7)
    b.set_defaults(func=cmd_benchmark)

    sub.add_parser("demo", help="end-to-end demo on a temporary database"
                   ).set_defaults(func=cmd_demo)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    conn = None if args.command == "demo" else connect(args.db)
    try:
        args.func(args, conn)
        return 0
    except (ValueError, InsufficientDataError, EngineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

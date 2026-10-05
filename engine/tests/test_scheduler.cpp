#include <algorithm>
#include <stdexcept>

#include <catch2/catch_test_macros.hpp>

#include "flexsched/calendar.hpp"
#include "flexsched/scheduler.hpp"

using namespace flexsched;

namespace {

constexpr Minutes kDay = 24 * 60;
constexpr Minutes kNoDeadline = 1'000'000;

Task make_task(int id, int difficulty, int priority, Minutes deadline,
               std::vector<double> curve) {
    Task t;
    t.id = id;
    t.difficulty = difficulty;
    t.priority = priority;
    t.deadline = deadline;
    t.duration_curve = std::move(curve);
    return t;
}

// Working hours 09:00-17:00 on `days` consecutive days.
std::vector<Interval> work_days(int days) {
    std::vector<Interval> w;
    for (int d = 0; d < days; ++d) w.push_back({d * kDay + 540, d * kDay + 1020});
    return w;
}

Scheduler make(const std::string& strategy, Params p = {}) {
    return Scheduler(p, make_policy(strategy));
}

}  // namespace

TEST_CASE("No tasks -> empty schedule", "[scheduler][edge]") {
    const auto r = make("fatigue_aware").run({}, work_days(1));
    CHECK(r.blocks.empty());
    CHECK(r.unscheduled.empty());
    CHECK(r.metrics.tasks_scheduled == 0);
}

TEST_CASE("No free time -> everything unscheduled", "[scheduler][edge]") {
    const std::vector<Task> tasks{make_task(1, 3, 3, kNoDeadline, {30})};
    const auto r = make("fatigue_aware").run(tasks, {});
    CHECK(r.blocks.empty());
    REQUIRE(r.unscheduled.size() == 1);
    CHECK(r.unscheduled[0].task_id == 1);
}

TEST_CASE("A single task starts at the beginning of the first slot", "[scheduler]") {
    const std::vector<Task> tasks{make_task(7, 3, 3, kNoDeadline, {45})};
    const auto r = make("fatigue_aware").run(tasks, work_days(1));
    REQUIRE(r.blocks.size() == 1);
    CHECK(r.blocks[0].task_id == 7);
    CHECK(r.blocks[0].start == 540);
    CHECK(r.blocks[0].end == 585);
    CHECK(r.blocks[0].fatigue_start == 0.0);
    CHECK(r.blocks[0].fatigue_end > 0.0);
    CHECK_FALSE(r.blocks[0].late);
}

TEST_CASE("Blocks never overlap and always stay inside free slots", "[scheduler][invariant]") {
    std::vector<Task> tasks;
    for (int i = 1; i <= 25; ++i) {
        const double base = 20.0 + (i * 37) % 100;  // varied durations 20..119
        tasks.push_back(make_task(i, 1 + i % 5, 1 + (i * 3) % 5, (i % 4 + 1) * kDay,
                                  {base, base * 1.1, base * 1.2, base * 1.35, base * 1.5}));
    }
    const auto slots = free_slots(work_days(3), {{720, 780}, {kDay + 600, kDay + 660}});

    for (const std::string strategy : {"edf", "fatigue_aware"}) {
        const auto r = make(strategy).run(tasks, slots);
        INFO("strategy = " << strategy);

        // Every task is either scheduled once or reported as unscheduled.
        std::vector<int> seen;
        for (const auto& b : r.blocks)
            if (b.kind == BlockKind::Task) seen.push_back(b.task_id);
        for (const auto& u : r.unscheduled) seen.push_back(u.task_id);
        std::sort(seen.begin(), seen.end());
        REQUIRE(seen.size() == tasks.size());
        CHECK(std::adjacent_find(seen.begin(), seen.end()) == seen.end());

        for (std::size_t i = 0; i < r.blocks.size(); ++i) {
            const auto& b = r.blocks[i];
            CHECK(b.end > b.start);
            if (i > 0) CHECK(b.start >= r.blocks[i - 1].end);  // no overlap, ordered
            const bool inside = std::any_of(slots.begin(), slots.end(), [&](const Interval& s) {
                return b.start >= s.start && b.end <= s.end;
            });
            CHECK(inside);
            CHECK(b.fatigue_start >= 0.0);
            CHECK(b.fatigue_end <= 1.0);
        }
    }
}

TEST_CASE("Task longer than every slot is reported with a reason", "[scheduler][edge]") {
    const std::vector<Task> tasks{make_task(1, 3, 3, kNoDeadline, {600})};  // 10h
    const auto r = make("fatigue_aware").run(tasks, work_days(2));         // 8h days
    CHECK(r.blocks.empty());
    REQUIRE(r.unscheduled.size() == 1);
    CHECK(r.unscheduled[0].reason.find("longest free slot") != std::string::npos);
}

TEST_CASE("Running out of horizon is reported differently", "[scheduler][edge]") {
    std::vector<Task> tasks;
    for (int i = 1; i <= 3; ++i) tasks.push_back(make_task(i, 1, 3, kNoDeadline, {300}));
    const auto r = make("edf").run(tasks, work_days(1));  // only one 300-min task fits
    CHECK(r.metrics.tasks_scheduled == 1);
    REQUIRE(r.unscheduled.size() == 2);
    CHECK(r.unscheduled[0].reason.find("horizon") != std::string::npos);
}

TEST_CASE("Late tasks are flagged and lateness is summed", "[scheduler]") {
    // Deadline 09:30 but the task takes 60 min from 09:00 -> 30 min late.
    const std::vector<Task> tasks{make_task(1, 2, 5, 570, {60})};
    const auto r = make("edf").run(tasks, work_days(1));
    REQUIRE(r.blocks.size() == 1);
    CHECK(r.blocks[0].late);
    CHECK(r.metrics.tasks_late == 1);
    CHECK(r.metrics.total_lateness == 30);
}

TEST_CASE("Fatigue-aware strategy inserts breaks; EDF does not", "[scheduler]") {
    std::vector<Task> tasks;
    for (int i = 1; i <= 6; ++i) tasks.push_back(make_task(i, 5, 3, kNoDeadline, {60}));

    const auto aware = make("fatigue_aware").run(tasks, work_days(1));
    const auto edf = make("edf").run(tasks, work_days(1));

    CHECK(aware.metrics.breaks > 0);
    CHECK(edf.metrics.breaks == 0);
    // Breaks keep fatigue lower at the start of tasks.
    CHECK(aware.metrics.avg_fatigue_at_start < edf.metrics.avg_fatigue_at_start);
    // A break is always followed by lower fatigue than it started with.
    for (const auto& b : aware.blocks) {
        if (b.kind == BlockKind::Break) CHECK(b.fatigue_end < b.fatigue_start);
    }
}

TEST_CASE("No break is squeezed in right before a slot ends", "[scheduler][edge]") {
    // A 470-minute hard task runs 09:00-16:50 and leaves fatigue near 1.0.
    // Only 10 minutes of the day remain (< 15-minute break), so instead of a
    // useless 10-minute break the scheduler should move on to the next day.
    const std::vector<Task> tasks{make_task(1, 5, 3, kNoDeadline, {470}),
                                  make_task(2, 1, 3, kNoDeadline, {60})};
    const auto r = make("fatigue_aware").run(tasks, work_days(2));
    REQUIRE(r.blocks.size() == 2);
    CHECK(r.metrics.breaks == 0);
    CHECK(r.blocks[1].task_id == 2);
    CHECK(r.blocks[1].start == kDay + 540);  // next morning
}

TEST_CASE("Fatigue makes later tasks longer via the duration curve", "[scheduler]") {
    // Same task twice; the second one starts tired so it takes longer.
    const std::vector<Task> tasks{make_task(1, 5, 3, kNoDeadline, {60, 70, 80, 90, 100}),
                                  make_task(2, 5, 3, kNoDeadline, {60, 70, 80, 90, 100})};
    const auto r = make("edf").run(tasks, work_days(1));
    REQUIRE(r.blocks.size() == 2);
    CHECK(r.blocks[0].end - r.blocks[0].start == 60);
    CHECK(r.blocks[1].end - r.blocks[1].start > 60);
}

TEST_CASE("Overnight rest resets fatigue", "[scheduler]") {
    // Two 400-minute tasks: one per day.
    const std::vector<Task> tasks{make_task(1, 5, 3, kNoDeadline, {400}),
                                  make_task(2, 5, 3, kNoDeadline, {400})};
    Params p;
    p.break_threshold = 1.0;  // effectively never take breaks
    const auto r = make("fatigue_aware", p).run(tasks, work_days(2));
    REQUIRE(r.blocks.size() == 2);
    CHECK(r.blocks[1].start == kDay + 540);
    CHECK(r.blocks[1].fatigue_start < 1e-6);
}

TEST_CASE("Output does not depend on input order", "[scheduler][determinism]") {
    std::vector<Task> tasks{make_task(3, 2, 4, 2000, {40}), make_task(1, 5, 2, 3000, {90}),
                            make_task(2, 3, 5, 1500, {55})};
    std::vector<Task> reversed(tasks.rbegin(), tasks.rend());
    const auto a = make("fatigue_aware").run(tasks, work_days(2));
    const auto b = make("fatigue_aware").run(reversed, work_days(2));
    REQUIRE(a.blocks.size() == b.blocks.size());
    for (std::size_t i = 0; i < a.blocks.size(); ++i) {
        CHECK(a.blocks[i].task_id == b.blocks[i].task_id);
        CHECK(a.blocks[i].start == b.blocks[i].start);
    }
}

TEST_CASE("Invalid input is rejected", "[scheduler][edge]") {
    auto sched = make("edf");
    SECTION("duplicate ids") {
        const std::vector<Task> t{make_task(1, 3, 3, 0, {10}), make_task(1, 3, 3, 0, {10})};
        CHECK_THROWS_AS(sched.run(t, work_days(1)), std::invalid_argument);
    }
    SECTION("difficulty out of range") {
        CHECK_THROWS_AS(sched.run({make_task(1, 6, 3, 0, {10})}, work_days(1)),
                        std::invalid_argument);
    }
    SECTION("priority out of range") {
        CHECK_THROWS_AS(sched.run({make_task(1, 3, 0, 0, {10})}, work_days(1)),
                        std::invalid_argument);
    }
    SECTION("empty duration curve") {
        CHECK_THROWS_AS(sched.run({make_task(1, 3, 3, 0, {})}, work_days(1)),
                        std::invalid_argument);
    }
    SECTION("bad parameters") {
        Params p;
        p.break_threshold = 0.0;
        CHECK_THROWS_AS(Scheduler(p, make_policy("edf")), std::invalid_argument);
        p = Params{};
        p.break_minutes = 0;
        CHECK_THROWS_AS(Scheduler(p, make_policy("edf")), std::invalid_argument);
        CHECK_THROWS_AS(Scheduler(Params{}, nullptr), std::invalid_argument);
    }
}

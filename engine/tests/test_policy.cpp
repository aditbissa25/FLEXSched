#include <stdexcept>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include "flexsched/policy.hpp"

using namespace flexsched;
using Catch::Matchers::WithinAbs;

namespace {
Task make_task(int id, int difficulty, int priority, Minutes deadline) {
    Task t;
    t.id = id;
    t.difficulty = difficulty;
    t.priority = priority;
    t.deadline = deadline;
    t.duration_curve = {60};
    return t;
}
}  // namespace

TEST_CASE("Score terms behave as documented", "[policy]") {
    SECTION("priority maps 1..5 onto 0..1") {
        CHECK(FatigueAwarePolicy::priority_term(1) == 0.0);
        CHECK(FatigueAwarePolicy::priority_term(3) == 0.5);
        CHECK(FatigueAwarePolicy::priority_term(5) == 1.0);
    }
    SECTION("urgency is 1 with no slack and decays with more slack") {
        CHECK(FatigueAwarePolicy::urgency_term(0, 480) == 1.0);
        CHECK(FatigueAwarePolicy::urgency_term(-30, 480) == 1.0);
        CHECK_THAT(FatigueAwarePolicy::urgency_term(480, 480), WithinAbs(0.367879, 1e-6));
        CHECK(FatigueAwarePolicy::urgency_term(100, 480) >
              FatigueAwarePolicy::urgency_term(1000, 480));
    }
    SECTION("energy match rewards hard-when-fresh and easy-when-tired") {
        CHECK(FatigueAwarePolicy::energy_term(5, 0.0) == 1.0);
        CHECK(FatigueAwarePolicy::energy_term(1, 1.0) == 1.0);
        CHECK(FatigueAwarePolicy::energy_term(1, 0.0) == 0.0);
        CHECK(FatigueAwarePolicy::energy_term(5, 1.0) == 0.0);
    }
}

TEST_CASE("EDF picks the earliest deadline with deterministic ties", "[policy]") {
    EdfPolicy edf;
    Params p;
    const DecisionContext ctx{0, 0.0, &p};
    const Task a = make_task(1, 3, 1, 500);
    const Task b = make_task(2, 3, 5, 300);
    const Task c = make_task(3, 3, 5, 300);

    CHECK(edf.choose({{&a, 60}, {&b, 60}}, ctx) == 1);           // earlier deadline
    CHECK(edf.choose({{&c, 60}, {&b, 60}}, ctx) == 1);           // tie -> lower id (b)
    const Task d = make_task(4, 3, 2, 300);
    CHECK(edf.choose({{&d, 60}, {&c, 60}}, ctx) == 1);           // tie -> higher priority
    CHECK_FALSE(edf.takes_breaks());
}

TEST_CASE("Fatigue-aware policy matches task difficulty to energy", "[policy]") {
    FatigueAwarePolicy pol;
    Params p;
    const Task hard = make_task(1, 5, 3, 100000);
    const Task easy = make_task(2, 1, 3, 100000);
    const std::vector<Candidate> cands{{&hard, 60}, {&easy, 60}};

    const DecisionContext fresh{0, 0.0, &p};
    const DecisionContext tired{0, 0.9, &p};
    CHECK(pol.choose(cands, fresh) == 0);  // fresh -> hard task
    CHECK(pol.choose(cands, tired) == 1);  // tired -> easy task
    CHECK(pol.takes_breaks());
}

TEST_CASE("Urgency outweighs energy matching", "[policy]") {
    FatigueAwarePolicy pol;
    Params p;
    // We are fresh, so the hard task is the better energy match,
    // but the easy task is due right now.
    const Task hard_later = make_task(1, 5, 3, 100000);
    const Task easy_due = make_task(2, 1, 3, 60);
    const DecisionContext fresh{0, 0.0, &p};
    CHECK(pol.choose({{&hard_later, 60}, {&easy_due, 60}}, fresh) == 1);
}

TEST_CASE("Deadline guard protects the most urgent task", "[policy]") {
    FatigueAwarePolicy pol;
    Params p;
    const DecisionContext fresh{0, 0.0, &p};
    // The hard, high-priority task scores higher (0.55 vs ~0.41)...
    const Task hard = make_task(1, 5, 5, 100000);
    const Task easy_due_100 = make_task(2, 1, 1, 100);
    REQUIRE(FatigueAwarePolicy::best_by_score({{&hard, 60}, {&easy_due_100, 60}}, fresh) == 0);
    // ...but doing it first (0-60) would push the easy task (60-120) past
    // its deadline of 100, while starting the easy task now is on time.
    CHECK(pol.choose({{&hard, 60}, {&easy_due_100, 60}}, fresh) == 1);

    SECTION("no override when postponing is still on time") {
        const Task easy_due_130 = make_task(2, 1, 1, 130);
        CHECK(pol.choose({{&hard, 60}, {&easy_due_130, 60}}, fresh) == 0);
    }
    SECTION("an already-late task is still not postponed further") {
        // Due at 30 but takes 45: 15 min late if started now, 75 min late if
        // postponed. The guard minimises total lateness, so it goes first.
        const Task easy_due_30 = make_task(2, 1, 1, 30);
        CHECK(pol.choose({{&hard, 60}, {&easy_due_30, 45}}, fresh) == 1);
    }
}

TEST_CASE("Rollout lateness simulates back-to-back execution", "[policy]") {
    const Task a = make_task(1, 3, 3, 50);   // takes 60 -> 10 late if first
    const Task b = make_task(2, 3, 3, 200);  // takes 60
    const std::vector<Candidate> c{{&a, 60}, {&b, 60}};

    Params p;
    const DecisionContext ctx{0, 0.0, &p};

    const auto edf = FatigueAwarePolicy::rollout_lateness(c, ctx, c.size());
    CHECK(edf.late_tasks == 1);
    CHECK(edf.total_minutes == 10);

    const auto b_first = FatigueAwarePolicy::rollout_lateness(c, ctx, 1);
    CHECK(b_first.late_tasks == 1);
    CHECK(b_first.total_minutes == 70);  // a finishes at 120, deadline 50

    SECTION("slot boundaries push work to the next slot") {
        // Free 0-90 and 300-400: the second task cannot fit before 90,
        // so it runs 300-360 and misses its deadline of 200 by 160.
        const std::vector<Interval> slots{{0, 90}, {300, 400}};
        const DecisionContext with_slots{0, 0.0, &p, &slots, 0};
        const Task early = make_task(3, 3, 3, 100);
        const std::vector<Candidate> c2{{&early, 60}, {&b, 60}};
        const auto r = FatigueAwarePolicy::rollout_lateness(c2, with_slots, c2.size());
        CHECK(r.late_tasks == 1);
        CHECK(r.total_minutes == 160);
    }
}

TEST_CASE("make_policy builds known strategies and rejects others", "[policy][edge]") {
    CHECK(make_policy("edf")->name() == "edf");
    CHECK(make_policy("fatigue_aware")->name() == "fatigue_aware");
    CHECK_THROWS_AS(make_policy("random"), std::invalid_argument);
    CHECK_THROWS_AS(make_policy(""), std::invalid_argument);
}

#include <cmath>
#include <stdexcept>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include "flexsched/fatigue.hpp"

using flexsched::FatigueModel;
using Catch::Matchers::WithinAbs;

TEST_CASE("Zero or negative minutes leave fatigue unchanged", "[fatigue]") {
    FatigueModel m;
    CHECK(m.after_work(0.3, 3, 0) == 0.3);
    CHECK(m.after_work(0.3, 3, -10) == 0.3);
    CHECK(m.after_rest(0.3, 0) == 0.3);
}

TEST_CASE("Work follows the saturating formula", "[fatigue]") {
    FatigueModel m(0.012, 0.05);
    // 60 minutes at difficulty 5 (load 1.0) from fresh: 1 - exp(-0.72)
    CHECK_THAT(m.after_work(0.0, 5, 60), WithinAbs(1.0 - std::exp(-0.72), 1e-12));
    // From F = 0.5 the remaining "headroom" (0.5) shrinks by the same factor.
    CHECK_THAT(m.after_work(0.5, 5, 60), WithinAbs(1.0 - 0.5 * std::exp(-0.72), 1e-12));
}

TEST_CASE("Harder tasks tire faster than easy ones", "[fatigue]") {
    FatigueModel m;
    const double easy = m.after_work(0.0, 1, 90);
    const double hard = m.after_work(0.0, 5, 90);
    CHECK(hard > easy);
    CHECK(easy > 0.0);
}

TEST_CASE("Fatigue never leaves [0, 1]", "[fatigue][edge]") {
    FatigueModel m;
    CHECK(m.after_work(0.0, 5, 100000) <= 1.0);
    CHECK(m.after_work(0.99, 5, 100000) <= 1.0);
    CHECK(m.after_rest(1.0, 100000) >= 0.0);
    // Out-of-range inputs are clamped rather than propagated.
    CHECK(m.after_work(1.7, 3, 10) <= 1.0);
    CHECK(m.after_rest(-0.4, 10) == 0.0);
    // Out-of-range difficulty is clamped to 1..5.
    CHECK(m.after_work(0.0, 99, 30) == m.after_work(0.0, 5, 30));
    CHECK(m.after_work(0.0, -3, 30) == m.after_work(0.0, 1, 30));
}

TEST_CASE("Rest decays fatigue exponentially", "[fatigue]") {
    FatigueModel m(0.012, 0.05);
    CHECK_THAT(m.after_rest(0.8, 15), WithinAbs(0.8 * std::exp(-0.75), 1e-12));
    // A night (~16h) wipes out practically all fatigue.
    CHECK(m.after_rest(1.0, 16 * 60) < 1e-6);
    // More rest -> less fatigue (monotonic).
    CHECK(m.after_rest(0.8, 30) < m.after_rest(0.8, 10));
}

TEST_CASE("Negative rates are rejected", "[fatigue][edge]") {
    CHECK_THROWS_AS(FatigueModel(-0.1, 0.05), std::invalid_argument);
    CHECK_THROWS_AS(FatigueModel(0.01, -0.05), std::invalid_argument);
}

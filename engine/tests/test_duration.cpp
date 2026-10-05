#include <cmath>
#include <limits>
#include <stdexcept>

#include <catch2/catch_test_macros.hpp>

#include "flexsched/duration.hpp"

using flexsched::effective_duration;

TEST_CASE("Curve endpoints are returned exactly", "[duration]") {
    const std::vector<double> curve{60, 70, 80, 90, 100};
    CHECK(effective_duration(curve, 0.0) == 60);
    CHECK(effective_duration(curve, 1.0) == 100);
    CHECK(effective_duration(curve, 0.5) == 80);
}

TEST_CASE("Values between points are linearly interpolated", "[duration]") {
    const std::vector<double> curve{60, 70, 80, 90, 100};
    // 0.125 is half-way between the points at 0.0 and 0.25.
    CHECK(effective_duration(curve, 0.125) == 65);
    CHECK(effective_duration(curve, 0.875) == 95);
}

TEST_CASE("Durations are rounded up, never down", "[duration]") {
    CHECK(effective_duration({60.2}, 0.3) == 61);
    CHECK(effective_duration({59.0001, 59.0001}, 0.5) == 60);
    // ...but floating point noise just above an integer is ignored.
    CHECK(effective_duration({60.0 + 1e-12}, 0.0) == 60);
}

TEST_CASE("A single-point curve ignores fatigue", "[duration][edge]") {
    CHECK(effective_duration({45}, 0.0) == 45);
    CHECK(effective_duration({45}, 1.0) == 45);
}

TEST_CASE("Fatigue outside [0, 1] is clamped", "[duration][edge]") {
    const std::vector<double> curve{60, 100};
    CHECK(effective_duration(curve, -5.0) == 60);
    CHECK(effective_duration(curve, 7.0) == 100);
}

TEST_CASE("Invalid curves are rejected", "[duration][edge]") {
    CHECK_THROWS_AS(effective_duration({}, 0.0), std::invalid_argument);
    CHECK_THROWS_AS(effective_duration({30, 0}, 0.0), std::invalid_argument);
    CHECK_THROWS_AS(effective_duration({30, -5}, 0.0), std::invalid_argument);
    CHECK_THROWS_AS(effective_duration({std::numeric_limits<double>::quiet_NaN()}, 0.0),
                    std::invalid_argument);
}

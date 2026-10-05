#include <catch2/catch_test_macros.hpp>

#include "flexsched/calendar.hpp"

using flexsched::free_slots;
using flexsched::Interval;
using flexsched::merge_intervals;

namespace {
bool same(const std::vector<Interval>& a, const std::vector<Interval>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (a[i].start != b[i].start || a[i].end != b[i].end) return false;
    }
    return true;
}
}  // namespace

TEST_CASE("merge_intervals sorts and merges", "[calendar]") {
    SECTION("overlapping intervals merge") {
        CHECK(same(merge_intervals({{0, 10}, {5, 20}}), {{0, 20}}));
    }
    SECTION("touching intervals merge") {
        CHECK(same(merge_intervals({{0, 10}, {10, 20}}), {{0, 20}}));
    }
    SECTION("unsorted input is sorted") {
        CHECK(same(merge_intervals({{30, 40}, {0, 10}}), {{0, 10}, {30, 40}}));
    }
    SECTION("contained interval disappears") {
        CHECK(same(merge_intervals({{0, 100}, {20, 30}}), {{0, 100}}));
    }
    SECTION("empty intervals are dropped") {
        CHECK(same(merge_intervals({{5, 5}, {9, 3}}), {}));
        CHECK(merge_intervals({}).empty());
    }
}

TEST_CASE("free_slots subtracts blocked time from windows", "[calendar]") {
    const std::vector<Interval> day{{540, 1020}};  // 09:00-17:00

    SECTION("nothing blocked -> whole window") {
        CHECK(same(free_slots(day, {}), {{540, 1020}}));
    }
    SECTION("meeting in the middle splits the window") {
        CHECK(same(free_slots(day, {{720, 780}}), {{540, 720}, {780, 1020}}));
    }
    SECTION("block at the start or end trims the window") {
        CHECK(same(free_slots(day, {{500, 600}}), {{600, 1020}}));
        CHECK(same(free_slots(day, {{1000, 1100}}), {{540, 1000}}));
    }
    SECTION("block covering the whole window leaves nothing") {
        CHECK(free_slots(day, {{0, 2000}}).empty());
    }
    SECTION("blocks outside the window are ignored") {
        CHECK(same(free_slots(day, {{0, 100}, {1200, 1300}}), {{540, 1020}}));
    }
    SECTION("overlapping blocks are merged first") {
        CHECK(same(free_slots(day, {{600, 700}, {650, 760}}), {{540, 600}, {760, 1020}}));
    }
    SECTION("no windows -> no free time") {
        CHECK(free_slots({}, {{0, 10}}).empty());
    }
}

TEST_CASE("A blocked interval may span two windows", "[calendar][edge]") {
    // Two days 09:00-17:00; something blocks from 16:00 day 1 to 10:00 day 2.
    const std::vector<Interval> windows{{540, 1020}, {1980, 2460}};
    const std::vector<Interval> blocked{{960, 2040}};
    CHECK(same(free_slots(windows, blocked), {{540, 960}, {2040, 2460}}));
}

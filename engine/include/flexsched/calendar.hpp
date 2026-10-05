// calendar.hpp - Computing the free time we are allowed to schedule into.
//
// Input:  working windows (e.g. 09:00-17:00 each day) and blocked intervals
//         (meetings, lectures, gym ...), all as minute offsets.
// Output: a sorted list of non-overlapping FREE slots = windows minus blocked.
//
// This is the classic "interval subtraction" problem:
//   1. sort + merge the windows (they might overlap),
//   2. sort + merge the blocked intervals,
//   3. sweep through both lists once, cutting blocked pieces out.
// Complexity: O(W log W + B log B) for sorting, O(W + B) for the sweep.
#pragma once

#include <vector>

#include "flexsched/types.hpp"

namespace flexsched {

// Sort by start and merge overlapping or touching intervals. Empty
// (end <= start) intervals are dropped.
std::vector<Interval> merge_intervals(std::vector<Interval> intervals);

// Free slots = merged windows minus merged blocked intervals.
std::vector<Interval> free_slots(const std::vector<Interval>& windows,
                                 const std::vector<Interval>& blocked);

}  // namespace flexsched

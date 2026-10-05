#include "flexsched/calendar.hpp"

#include <algorithm>

namespace flexsched {

std::vector<Interval> merge_intervals(std::vector<Interval> intervals) {
    // Drop empty intervals first so they can never "bridge" two real ones.
    intervals.erase(std::remove_if(intervals.begin(), intervals.end(),
                                   [](const Interval& iv) { return iv.empty(); }),
                    intervals.end());

    std::sort(intervals.begin(), intervals.end(),
              [](const Interval& a, const Interval& b) {
                  return a.start < b.start || (a.start == b.start && a.end < b.end);
              });

    std::vector<Interval> merged;
    for (const Interval& iv : intervals) {
        if (!merged.empty() && iv.start <= merged.back().end) {
            merged.back().end = std::max(merged.back().end, iv.end);  // overlap/touch
        } else {
            merged.push_back(iv);
        }
    }
    return merged;
}

std::vector<Interval> free_slots(const std::vector<Interval>& windows,
                                 const std::vector<Interval>& blocked) {
    const std::vector<Interval> w = merge_intervals(windows);
    const std::vector<Interval> b = merge_intervals(blocked);

    std::vector<Interval> result;
    std::size_t j = 0;  // index into blocked; only ever moves forward

    for (const Interval& window : w) {
        Minutes cursor = window.start;

        // Skip blocked intervals that end before this window starts.
        while (j < b.size() && b[j].end <= window.start) ++j;

        // Cut out every blocked interval that overlaps this window.
        std::size_t k = j;
        while (k < b.size() && b[k].start < window.end) {
            if (b[k].start > cursor) {
                result.push_back({cursor, b[k].start});
            }
            cursor = std::max(cursor, b[k].end);
            ++k;
        }
        if (cursor < window.end) {
            result.push_back({cursor, window.end});
        }
        // Do not advance j past k: a long blocked interval may span
        // into the next window as well.
    }
    return result;
}

}  // namespace flexsched

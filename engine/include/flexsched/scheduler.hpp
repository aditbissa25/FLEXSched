// scheduler.hpp - The greedy, fatigue-simulating scheduling loop.
//
// Algorithm (event-driven simulation of one person's work days):
//
//   t = start of first free slot, F = 0 (fresh)
//   while tasks remain and free slots remain:
//       if t is before the current slot: rest until the slot starts
//       if the policy takes breaks and F >= threshold: insert a break
//       candidates = remaining tasks whose duration-at-F fits before slot end
//       if none fit: move on to the next slot
//       else: ask the policy to choose one, place it at t, update F and t
//   anything left over is reported as unscheduled, with a reason
//
// Greedy = we commit to each decision and never revisit it. This is fast
// (O(n^2) for n tasks) and easy to explain, but not guaranteed optimal; the
// general problem (deadlines + variable durations) is NP-hard.
#pragma once

#include <memory>
#include <vector>

#include "flexsched/fatigue.hpp"
#include "flexsched/policy.hpp"
#include "flexsched/types.hpp"

namespace flexsched {

class Scheduler {
public:
    Scheduler(Params params, std::unique_ptr<SelectionPolicy> policy);

    // `slots` must be sorted and non-overlapping (use free_slots()).
    // Throws std::invalid_argument on invalid tasks or parameters.
    ScheduleResult run(const std::vector<Task>& tasks,
                       const std::vector<Interval>& slots) const;

    const SelectionPolicy& policy() const { return *policy_; }

private:
    void validate(const std::vector<Task>& tasks) const;

    Params params_;
    std::unique_ptr<SelectionPolicy> policy_;
    FatigueModel fatigue_;
};

// Computes summary metrics from a finished list of blocks.
Metrics compute_metrics(const std::vector<ScheduledBlock>& blocks,
                        const std::vector<Task>& tasks);

}  // namespace flexsched

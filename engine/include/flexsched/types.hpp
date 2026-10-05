// types.hpp - Plain data types shared by every engine module.
//
// Time convention: all times are integer MINUTES measured from the start of
// the planning horizon (minute 0 = first planned day at 00:00). Python owns
// the conversion between real datetimes and these offsets, so the engine
// never has to deal with time zones or calendars.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace flexsched {

using Minutes = std::int64_t;

// A half-open time interval [start, end).
struct Interval {
    Minutes start = 0;
    Minutes end = 0;

    Minutes length() const { return end - start; }
    bool empty() const { return end <= start; }
};

// A task as the engine sees it. The duration is not a single number but a
// curve: the predicted duration (minutes) at evenly spaced fatigue levels
// 0.0, 0.25, 0.5, 0.75, 1.0 (or any N >= 1 points spread evenly over [0, 1]).
struct Task {
    int id = 0;
    int difficulty = 3;           // 1 (trivial) .. 5 (very demanding)
    int priority = 3;             // 1 (low) .. 5 (critical)
    Minutes deadline = 0;         // minute offset; larger than horizon = "no deadline"
    std::vector<double> duration_curve;
};

// Tunable parameters. Defaults mirror flexsched/config.py on the Python side.
struct Params {
    // Fatigue dynamics (see fatigue.hpp for the formulas).
    double work_rate = 0.012;      // fatigue gained per minute at full load
    double recovery_rate = 0.05;   // fraction of fatigue lost per minute of rest

    // Break policy.
    double break_threshold = 0.65; // insert a break once fatigue reaches this
    Minutes break_minutes = 15;

    // Score weights for the fatigue-aware policy.
    double w_priority = 0.35;
    double w_urgency = 0.45;
    double w_energy = 0.20;
    double urgency_horizon = 480.0; // minutes of slack at which urgency ~ 0.37
};

enum class BlockKind { Task, Break };

// One entry of the final timetable.
struct ScheduledBlock {
    BlockKind kind = BlockKind::Task;
    int task_id = -1;             // -1 for breaks
    Minutes start = 0;
    Minutes end = 0;
    double fatigue_start = 0.0;
    double fatigue_end = 0.0;
    bool late = false;            // finished after its deadline
};

struct Unscheduled {
    int task_id = 0;
    std::string reason;
};

// Aggregate numbers used to compare strategies.
struct Metrics {
    Minutes total_work_minutes = 0;   // sum of task block lengths
    Minutes makespan = 0;             // end of the last block
    int tasks_scheduled = 0;
    int tasks_late = 0;
    Minutes total_lateness = 0;       // sum of (end - deadline) over late tasks
    int breaks = 0;
    double peak_fatigue = 0.0;
    double avg_fatigue_at_start = 0.0;
};

struct ScheduleResult {
    std::vector<ScheduledBlock> blocks;
    std::vector<Unscheduled> unscheduled;
    Metrics metrics;
};

}  // namespace flexsched

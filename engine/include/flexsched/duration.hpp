// duration.hpp - Turning a predicted duration curve into a concrete number.
//
// The ML model (Python) predicts how long a task takes at several fatigue
// levels. The scheduler only knows the fatigue at the moment it wants to
// start the task, so it linearly interpolates between the two nearest
// points of the curve and rounds UP to whole minutes (never under-book).
#pragma once

#include <vector>

#include "flexsched/types.hpp"

namespace flexsched {

// Throws std::invalid_argument if the curve is empty or has a non-positive value.
Minutes effective_duration(const std::vector<double>& curve, double fatigue);

}  // namespace flexsched

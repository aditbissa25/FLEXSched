// fatigue.hpp - The fatigue model: how tiredness builds up and recovers.
//
// Fatigue F is a number in [0, 1]: 0 = fully fresh, 1 = exhausted.
//
//   Working m minutes on a task of difficulty d (load = d / 5):
//       F' = 1 - (1 - F) * exp(-work_rate * load * m)
//     -> saturating growth: F approaches 1 but never exceeds it, and the
//        same work tires a fresh person more (in absolute terms) than an
//        already-tired one. Harder tasks tire faster.
//
//   Resting m minutes (breaks, gaps between work windows, nights):
//       F' = F * exp(-recovery_rate * m)
//     -> exponential decay: a short break removes a big chunk of fatigue,
//        a long night removes almost all of it.
//
// The same two formulas are implemented in flexsched/fatigue.py so that
// Python can reconstruct historic fatigue levels; a test checks they agree.
#pragma once

#include "flexsched/types.hpp"

namespace flexsched {

class FatigueModel {
public:
    explicit FatigueModel(double work_rate = 0.012, double recovery_rate = 0.05);

    // Fatigue after working `minutes` on a task of the given difficulty (1..5).
    double after_work(double fatigue, int difficulty, Minutes minutes) const;

    // Fatigue after resting for `minutes`.
    double after_rest(double fatigue, Minutes minutes) const;

private:
    double work_rate_;
    double recovery_rate_;
};

// Clamp helper used across modules.
double clamp01(double x);

}  // namespace flexsched

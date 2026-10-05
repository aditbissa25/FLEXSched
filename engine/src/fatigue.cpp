#include "flexsched/fatigue.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace flexsched {

double clamp01(double x) { return std::min(1.0, std::max(0.0, x)); }

FatigueModel::FatigueModel(double work_rate, double recovery_rate)
    : work_rate_(work_rate), recovery_rate_(recovery_rate) {
    if (work_rate_ < 0.0 || recovery_rate_ < 0.0) {
        throw std::invalid_argument("fatigue rates must be non-negative");
    }
}

double FatigueModel::after_work(double fatigue, int difficulty, Minutes minutes) const {
    if (minutes <= 0) return clamp01(fatigue);
    const int d = std::clamp(difficulty, 1, 5);
    const double load = d / 5.0;
    const double decay = std::exp(-work_rate_ * load * static_cast<double>(minutes));
    return clamp01(1.0 - (1.0 - clamp01(fatigue)) * decay);
}

double FatigueModel::after_rest(double fatigue, Minutes minutes) const {
    if (minutes <= 0) return clamp01(fatigue);
    return clamp01(clamp01(fatigue) * std::exp(-recovery_rate_ * static_cast<double>(minutes)));
}

}  // namespace flexsched

#include "flexsched/duration.hpp"

#include <cmath>
#include <stdexcept>

#include "flexsched/fatigue.hpp"

namespace flexsched {

Minutes effective_duration(const std::vector<double>& curve, double fatigue) {
    if (curve.empty()) {
        throw std::invalid_argument("duration curve must not be empty");
    }
    for (double v : curve) {
        if (!(v > 0.0)) {  // also rejects NaN
            throw std::invalid_argument("duration curve values must be positive");
        }
    }
    double value = curve.front();
    if (curve.size() > 1) {
        // Curve points sit at fatigue = i / (n - 1) for i = 0..n-1.
        const double f = clamp01(fatigue);
        const double pos = f * static_cast<double>(curve.size() - 1);
        const auto lo = static_cast<std::size_t>(std::floor(pos));
        const std::size_t hi = (lo + 1 < curve.size()) ? lo + 1 : lo;
        const double frac = pos - static_cast<double>(lo);
        value = curve[lo] + (curve[hi] - curve[lo]) * frac;
    }

    // Small epsilon so 60.0000000001 (floating point noise) does not become 61.
    return static_cast<Minutes>(std::ceil(value - 1e-9));
}

}  // namespace flexsched

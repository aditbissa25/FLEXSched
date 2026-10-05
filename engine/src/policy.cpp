#include "flexsched/policy.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

#include "flexsched/fatigue.hpp"

namespace flexsched {

// ---------------------------------------------------------------- EDF ----

std::size_t EdfPolicy::choose(const std::vector<Candidate>& candidates,
                              const DecisionContext& /*ctx*/) const {
    std::size_t best = 0;
    for (std::size_t i = 1; i < candidates.size(); ++i) {
        const Task& a = *candidates[i].task;
        const Task& b = *candidates[best].task;
        // Earlier deadline wins; ties -> higher priority; ties -> lower id.
        if (a.deadline != b.deadline) {
            if (a.deadline < b.deadline) best = i;
        } else if (a.priority != b.priority) {
            if (a.priority > b.priority) best = i;
        } else if (a.id < b.id) {
            best = i;
        }
    }
    return best;
}

// ------------------------------------------------------- Fatigue-aware ----

double FatigueAwarePolicy::priority_term(int priority) {
    // Map 1..5 to 0..1.
    return (std::clamp(priority, 1, 5) - 1) / 4.0;
}

double FatigueAwarePolicy::urgency_term(Minutes slack, double horizon) {
    // slack = minutes left between finishing the task and its deadline.
    // No slack (or already late) -> maximum urgency 1.0.
    // Lots of slack -> urgency decays exponentially towards 0.
    if (slack <= 0) return 1.0;
    if (horizon <= 0.0) return 0.0;
    return std::exp(-static_cast<double>(slack) / horizon);
}

double FatigueAwarePolicy::energy_term(int difficulty, double fatigue) {
    // How well does the task's difficulty match the energy we have left?
    // energy = 1 - fatigue, difficulty normalised to 0..1.
    // Perfect match (hard task when fresh, easy task when tired) -> 1.0.
    const double diff = (std::clamp(difficulty, 1, 5) - 1) / 4.0;
    const double energy = 1.0 - clamp01(fatigue);
    return 1.0 - std::abs(diff - energy);
}

double FatigueAwarePolicy::score(const Candidate& c, const DecisionContext& ctx) {
    const Params& p = *ctx.params;
    const Minutes finish = ctx.now + c.duration;
    const Minutes slack = c.task->deadline - finish;
    return p.w_priority * priority_term(c.task->priority) +
           p.w_urgency * urgency_term(slack, p.urgency_horizon) +
           p.w_energy * energy_term(c.task->difficulty, ctx.fatigue);
}

std::size_t FatigueAwarePolicy::choose(const std::vector<Candidate>& candidates,
                                       const DecisionContext& ctx) const {
    const std::vector<std::size_t> ranked = rank_by_score(candidates, ctx);

    // Rollout deadline guard. Simulate over every unscheduled task if the
    // scheduler gave us the full list, otherwise over the candidates only.
    const std::vector<Candidate>& pool = ctx.pending ? *ctx.pending : candidates;
    auto index_in_pool = [&](std::size_t candidate_idx) {
        for (std::size_t j = 0; j < pool.size(); ++j) {
            if (pool[j].task == candidates[candidate_idx].task) return j;
        }
        return pool.size();
    };

    // What lateness would pure EDF give from here?
    const Lateness edf = rollout_lateness(pool, ctx, pool.size());
    // Take the highest-scored task whose "do it first, then EDF" rollout is
    // no worse than that.
    for (std::size_t idx : ranked) {
        const Lateness with_first = rollout_lateness(pool, ctx, index_in_pool(idx));
        if (with_first.late_tasks <= edf.late_tasks &&
            with_first.total_minutes <= edf.total_minutes) {
            return idx;
        }
    }
    // Nothing passed (possible when EDF's first task does not fit right now):
    // fall back to plain EDF among the candidates.
    return EdfPolicy{}.choose(candidates, ctx);
}

FatigueAwarePolicy::Lateness FatigueAwarePolicy::rollout_lateness(
    const std::vector<Candidate>& candidates, const DecisionContext& ctx, std::size_t first) {
    // Order: optional `first` candidate, then everything else by deadline (EDF).
    std::vector<std::size_t> order;
    order.reserve(candidates.size());
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        if (i != first) order.push_back(i);
    }
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return candidates[a].task->deadline < candidates[b].task->deadline;
    });
    if (first < candidates.size()) order.insert(order.begin(), first);

    // Cheap simulation at today's durations (approximation: it ignores future
    // fatigue changes and breaks). Tasks are packed into the free slots so a
    // night or a meeting in between is taken into account. O(k log k + S).
    Lateness result;
    Minutes t = ctx.now;
    std::size_t s = ctx.slot_index;
    for (std::size_t i : order) {
        const Minutes d = candidates[i].duration;
        if (ctx.slots != nullptr) {
            // Move to the first slot where the task fits; if none is left,
            // pretend it runs right after the last slot (it will be late).
            while (s < ctx.slots->size() &&
                   std::max(t, (*ctx.slots)[s].start) + d > (*ctx.slots)[s].end) {
                ++s;
            }
            if (s < ctx.slots->size()) t = std::max(t, (*ctx.slots)[s].start);
        }
        t += d;
        const Minutes over = t - candidates[i].task->deadline;
        if (over > 0) {
            ++result.late_tasks;
            result.total_minutes += over;
        }
    }
    return result;
}

std::vector<std::size_t> FatigueAwarePolicy::rank_by_score(
    const std::vector<Candidate>& candidates, const DecisionContext& ctx) {
    // Score each candidate once, then sort indices: higher score first;
    // ties -> earlier deadline -> lower id (deterministic output).
    std::vector<double> scores(candidates.size());
    std::vector<std::size_t> ranked(candidates.size());
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        scores[i] = score(candidates[i], ctx);
        ranked[i] = i;
    }
    // Exact comparisons only: std::sort requires a strict weak ordering, and an
    // epsilon-based "equal" would break transitivity (undefined behaviour).
    std::sort(ranked.begin(), ranked.end(), [&](std::size_t a, std::size_t b) {
        if (scores[a] != scores[b]) return scores[a] > scores[b];
        const Task& ta = *candidates[a].task;
        const Task& tb = *candidates[b].task;
        if (ta.deadline != tb.deadline) return ta.deadline < tb.deadline;
        return ta.id < tb.id;
    });
    return ranked;
}

std::size_t FatigueAwarePolicy::best_by_score(const std::vector<Candidate>& candidates,
                                              const DecisionContext& ctx) {
    return rank_by_score(candidates, ctx).front();
}

// ------------------------------------------------------------- Factory ----

std::unique_ptr<SelectionPolicy> make_policy(const std::string& name) {
    if (name == "edf") return std::make_unique<EdfPolicy>();
    if (name == "fatigue_aware") return std::make_unique<FatigueAwarePolicy>();
    throw std::invalid_argument("unknown strategy: '" + name +
                                "' (expected 'edf' or 'fatigue_aware')");
}

}  // namespace flexsched

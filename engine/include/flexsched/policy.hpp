// policy.hpp - "Which task should I do next?" as swappable strategies.
//
// The scheduler loop (scheduler.hpp) is the same for every strategy: walk
// forward through the free slots, track fatigue, and every time we are free
// ask a SelectionPolicy to pick one of the tasks that fits right now.
// This is the Strategy design pattern: the algorithm skeleton is fixed and
// the decision rule is a pluggable object behind a virtual interface.
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "flexsched/types.hpp"

namespace flexsched {

// A task that fits in the current free time, together with how long it
// would take if started right now (given the current fatigue).
struct Candidate {
    const Task* task = nullptr;
    Minutes duration = 0;
};

// Everything a policy may look at when deciding.
struct DecisionContext {
    Minutes now = 0;
    double fatigue = 0.0;
    const Params* params = nullptr;
    // Optional view of the free slots (current one first). When present,
    // lookahead simulations respect slot boundaries such as nights.
    const std::vector<Interval>* slots = nullptr;
    std::size_t slot_index = 0;
    // Optional: ALL unscheduled tasks (a superset of the candidates, which
    // only contain tasks that fit right now). Used by lookahead simulations.
    const std::vector<Candidate>* pending = nullptr;
};

class SelectionPolicy {
public:
    virtual ~SelectionPolicy() = default;

    virtual std::string name() const = 0;

    // Does the scheduler insert recovery breaks when fatigue gets high?
    virtual bool takes_breaks() const = 0;

    // Return the index (into `candidates`) of the task to schedule next.
    // Precondition: candidates is not empty.
    virtual std::size_t choose(const std::vector<Candidate>& candidates,
                               const DecisionContext& ctx) const = 0;
};

// Baseline: Earliest Deadline First, fatigue-blind (no breaks, no energy
// matching). EDF is the textbook optimal rule for minimising maximum
// lateness on a single machine when durations are fixed - a strong,
// well-known baseline to compare against.
class EdfPolicy final : public SelectionPolicy {
public:
    std::string name() const override { return "edf"; }
    bool takes_breaks() const override { return false; }
    std::size_t choose(const std::vector<Candidate>& candidates,
                       const DecisionContext& ctx) const override;
};

// FLEXSched's policy: weighted score of priority, deadline urgency and
// "energy match" (hard tasks when fresh, easy tasks when tired), plus breaks,
// plus a rollout deadline guard: a task may only be picked if
// "do it first, then the rest in EDF order" produces no more late tasks and
// no more lateness than plain EDF would from the same moment.
class FatigueAwarePolicy final : public SelectionPolicy {
public:
    std::string name() const override { return "fatigue_aware"; }
    bool takes_breaks() const override { return true; }
    std::size_t choose(const std::vector<Candidate>& candidates,
                       const DecisionContext& ctx) const override;

    // Exposed so unit tests can check the individual terms.
    static double priority_term(int priority);
    static double urgency_term(Minutes slack, double horizon);
    static double energy_term(int difficulty, double fatigue);
    static double score(const Candidate& c, const DecisionContext& ctx);
    // Candidate indices sorted best-first (ties: earlier deadline, lower id).
    static std::vector<std::size_t> rank_by_score(const std::vector<Candidate>& candidates,
                                                  const DecisionContext& ctx);
    static std::size_t best_by_score(const std::vector<Candidate>& candidates,
                                     const DecisionContext& ctx);

    struct Lateness {
        int late_tasks = 0;
        Minutes total_minutes = 0;
    };
    // Lateness of running candidates one after another from ctx.now: `first`
    // first (pass candidates.size() for "none"), the rest in deadline order.
    // Tasks are packed into the free slots from ctx (or back-to-back if none).
    static Lateness rollout_lateness(const std::vector<Candidate>& candidates,
                                     const DecisionContext& ctx, std::size_t first);
};

// Factory: "edf" or "fatigue_aware". Throws std::invalid_argument otherwise.
std::unique_ptr<SelectionPolicy> make_policy(const std::string& name);

}  // namespace flexsched

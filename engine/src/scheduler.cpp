#include "flexsched/scheduler.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>

#include "flexsched/duration.hpp"

namespace flexsched {

Scheduler::Scheduler(Params params, std::unique_ptr<SelectionPolicy> policy)
    : params_(params),
      policy_(std::move(policy)),
      fatigue_(params.work_rate, params.recovery_rate) {
    if (!policy_) throw std::invalid_argument("policy must not be null");
    if (!(params_.break_threshold > 0.0 && params_.break_threshold <= 1.0)) {
        throw std::invalid_argument("break_threshold must be in (0, 1]");
    }
    if (params_.break_minutes <= 0) {
        throw std::invalid_argument("break_minutes must be positive");
    }
}

void Scheduler::validate(const std::vector<Task>& tasks) const {
    std::unordered_set<int> seen;
    for (const Task& t : tasks) {
        const std::string where = "task " + std::to_string(t.id) + ": ";
        if (!seen.insert(t.id).second) throw std::invalid_argument(where + "duplicate id");
        if (t.difficulty < 1 || t.difficulty > 5)
            throw std::invalid_argument(where + "difficulty must be 1..5");
        if (t.priority < 1 || t.priority > 5)
            throw std::invalid_argument(where + "priority must be 1..5");
        effective_duration(t.duration_curve, 0.0);  // throws if the curve is invalid
    }
}

ScheduleResult Scheduler::run(const std::vector<Task>& tasks,
                              const std::vector<Interval>& slots) const {
    validate(tasks);

    ScheduleResult result;

    // Work on pointers so we never copy task data; sort by id so that the
    // output is deterministic regardless of input order.
    std::vector<const Task*> remaining;
    remaining.reserve(tasks.size());
    for (const Task& t : tasks) remaining.push_back(&t);
    std::sort(remaining.begin(), remaining.end(),
              [](const Task* a, const Task* b) { return a->id < b->id; });

    double fatigue = 0.0;
    std::size_t s = 0;
    Minutes now = slots.empty() ? 0 : slots.front().start;

    while (!remaining.empty() && s < slots.size()) {
        const Interval& slot = slots[s];

        // 1. Idle time before the slot (night, meeting, lunch) counts as rest.
        if (now < slot.start) {
            fatigue = fatigue_.after_rest(fatigue, slot.start - now);
            now = slot.start;
        }
        if (now >= slot.end) {  // slot fully consumed
            ++s;
            continue;
        }

        // 2. Recovery break if we are too tired (only for policies that use breaks).
        if (policy_->takes_breaks() && fatigue >= params_.break_threshold) {
            if (now + params_.break_minutes >= slot.end) {
                // The slot ends before a full break would: the idle gap after
                // the slot (evening, meeting) already provides the rest.
                ++s;
                continue;
            }
            const Minutes break_end = now + params_.break_minutes;
            ScheduledBlock brk;
            brk.kind = BlockKind::Break;
            brk.start = now;
            brk.end = break_end;
            brk.fatigue_start = fatigue;
            fatigue = fatigue_.after_rest(fatigue, break_end - now);
            brk.fatigue_end = fatigue;
            result.blocks.push_back(brk);
            now = break_end;
            continue;  // re-evaluate: slot may be over, or we may need another break
        }

        // 3. Which remaining tasks fit in what is left of this slot right now?
        std::vector<Candidate> candidates;
        std::vector<Candidate> pending;          // every remaining task (for lookahead)
        std::vector<std::size_t> candidate_pos;  // index into `remaining`
        for (std::size_t i = 0; i < remaining.size(); ++i) {
            const Minutes d = effective_duration(remaining[i]->duration_curve, fatigue);
            pending.push_back({remaining[i], d});
            if (now + d <= slot.end) {
                candidates.push_back({remaining[i], d});
                candidate_pos.push_back(i);
            }
        }
        if (candidates.empty()) {
            ++s;  // nothing fits here; the rest of this slot stays free
            continue;
        }

        // 4. Let the policy decide, then commit the decision.
        const DecisionContext ctx{now, fatigue, &params_, &slots, s, &pending};
        const std::size_t pick = policy_->choose(candidates, ctx);
        const Candidate& chosen = candidates.at(pick);

        ScheduledBlock block;
        block.kind = BlockKind::Task;
        block.task_id = chosen.task->id;
        block.start = now;
        block.end = now + chosen.duration;
        block.fatigue_start = fatigue;
        fatigue = fatigue_.after_work(fatigue, chosen.task->difficulty, chosen.duration);
        block.fatigue_end = fatigue;
        block.late = block.end > chosen.task->deadline;
        result.blocks.push_back(block);

        now = block.end;
        remaining.erase(remaining.begin() + static_cast<std::ptrdiff_t>(candidate_pos[pick]));
    }

    // 5. Explain why leftovers could not be placed.
    Minutes longest_slot = 0;
    for (const Interval& iv : slots) longest_slot = std::max(longest_slot, iv.length());
    for (const Task* t : remaining) {
        const Minutes fresh = effective_duration(t->duration_curve, 0.0);
        std::string reason = fresh > longest_slot
                                 ? "needs " + std::to_string(fresh) +
                                       " min but the longest free slot is " +
                                       std::to_string(longest_slot) + " min"
                                 : "not enough free time left in the planning horizon";
        result.unscheduled.push_back({t->id, reason});
    }

    result.metrics = compute_metrics(result.blocks, tasks);
    return result;
}

Metrics compute_metrics(const std::vector<ScheduledBlock>& blocks,
                        const std::vector<Task>& tasks) {
    std::unordered_map<int, const Task*> by_id;
    for (const Task& t : tasks) by_id[t.id] = &t;

    Metrics m;
    double fatigue_sum = 0.0;
    for (const ScheduledBlock& b : blocks) {
        m.makespan = std::max(m.makespan, b.end);
        if (b.kind == BlockKind::Break) {
            ++m.breaks;
            continue;
        }
        ++m.tasks_scheduled;
        m.total_work_minutes += b.end - b.start;
        fatigue_sum += b.fatigue_start;
        m.peak_fatigue = std::max(m.peak_fatigue, b.fatigue_end);
        if (b.late) {
            ++m.tasks_late;
            const auto it = by_id.find(b.task_id);
            if (it != by_id.end()) m.total_lateness += b.end - it->second->deadline;
        }
    }
    if (m.tasks_scheduled > 0) m.avg_fatigue_at_start = fatigue_sum / m.tasks_scheduled;
    return m;
}

}  // namespace flexsched

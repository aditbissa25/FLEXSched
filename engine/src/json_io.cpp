#include "flexsched/json_io.hpp"

#include <stdexcept>

namespace flexsched {

using nlohmann::json;

namespace {

Interval parse_interval(const json& j, const char* field) {
    if (!j.is_object() || !j.contains("start") || !j.contains("end")) {
        throw std::invalid_argument(std::string(field) +
                                    ": each interval needs 'start' and 'end'");
    }
    Interval iv{j.at("start").get<Minutes>(), j.at("end").get<Minutes>()};
    if (iv.end < iv.start) {
        throw std::invalid_argument(std::string(field) + ": interval end before start");
    }
    return iv;
}

std::vector<Interval> parse_intervals(const json& j, const char* field) {
    std::vector<Interval> out;
    if (!j.contains(field)) return out;
    const json& arr = j.at(field);
    if (!arr.is_array()) throw std::invalid_argument(std::string(field) + " must be an array");
    for (const json& item : arr) out.push_back(parse_interval(item, field));
    return out;
}

Params parse_params(const json& j) {
    Params p;  // start from defaults, override whatever is provided
    if (!j.contains("params")) return p;
    const json& q = j.at("params");
    p.work_rate = q.value("work_rate", p.work_rate);
    p.recovery_rate = q.value("recovery_rate", p.recovery_rate);
    p.break_threshold = q.value("break_threshold", p.break_threshold);
    p.break_minutes = q.value("break_minutes", p.break_minutes);
    p.w_priority = q.value("w_priority", p.w_priority);
    p.w_urgency = q.value("w_urgency", p.w_urgency);
    p.w_energy = q.value("w_energy", p.w_energy);
    p.urgency_horizon = q.value("urgency_horizon", p.urgency_horizon);
    return p;
}

Task parse_task(const json& j) {
    for (const char* key : {"id", "difficulty", "priority", "deadline", "duration_curve"}) {
        if (!j.contains(key)) {
            throw std::invalid_argument(std::string("task is missing '") + key + "'");
        }
    }
    Task t;
    t.id = j.at("id").get<int>();
    t.difficulty = j.at("difficulty").get<int>();
    t.priority = j.at("priority").get<int>();
    t.deadline = j.at("deadline").get<Minutes>();
    t.duration_curve = j.at("duration_curve").get<std::vector<double>>();
    return t;
}

const char* kind_name(BlockKind k) { return k == BlockKind::Task ? "task" : "break"; }

}  // namespace

Request parse_request(const json& j) {
    if (!j.is_object()) throw std::invalid_argument("request must be a JSON object");
    Request r;
    r.strategy = j.value("strategy", r.strategy);
    r.params = parse_params(j);
    r.windows = parse_intervals(j, "windows");
    r.blocked = parse_intervals(j, "blocked");
    if (j.contains("tasks")) {
        if (!j.at("tasks").is_array()) throw std::invalid_argument("tasks must be an array");
        for (const json& item : j.at("tasks")) r.tasks.push_back(parse_task(item));
    }
    return r;
}

json to_json(const ScheduleResult& result, const std::string& strategy) {
    json blocks = json::array();
    for (const ScheduledBlock& b : result.blocks) {
        json jb = {{"kind", kind_name(b.kind)},
                   {"start", b.start},
                   {"end", b.end},
                   {"fatigue_start", b.fatigue_start},
                   {"fatigue_end", b.fatigue_end}};
        if (b.kind == BlockKind::Task) {
            jb["task_id"] = b.task_id;
            jb["late"] = b.late;
        }
        blocks.push_back(jb);
    }

    json unscheduled = json::array();
    for (const Unscheduled& u : result.unscheduled) {
        unscheduled.push_back({{"task_id", u.task_id}, {"reason", u.reason}});
    }

    const Metrics& m = result.metrics;
    json metrics = {{"total_work_minutes", m.total_work_minutes},
                    {"makespan", m.makespan},
                    {"tasks_scheduled", m.tasks_scheduled},
                    {"tasks_late", m.tasks_late},
                    {"total_lateness", m.total_lateness},
                    {"breaks", m.breaks},
                    {"peak_fatigue", m.peak_fatigue},
                    {"avg_fatigue_at_start", m.avg_fatigue_at_start}};

    return {{"strategy", strategy},
            {"blocks", blocks},
            {"unscheduled", unscheduled},
            {"metrics", metrics}};
}

}  // namespace flexsched

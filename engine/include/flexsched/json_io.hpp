// json_io.hpp - The contract between Python and the C++ engine.
//
// Python writes ONE JSON request to the engine's stdin, the engine writes
// ONE JSON response to stdout. Keeping the boundary as plain JSON means:
//   * the engine can be tested on its own (pipe a file in, read the output),
//   * either side can be rewritten without touching the other,
//   * there is no fragile binary/ABI coupling between Python and C++.
//
// Request:
// {
//   "strategy": "fatigue_aware" | "edf",
//   "params":   { "work_rate": 0.012, ... }            (optional, all keys optional)
//   "windows":  [ {"start": 540, "end": 1020}, ... ]   (working hours)
//   "blocked":  [ {"start": 720, "end": 780}, ... ]    (optional)
//   "tasks":    [ {"id": 1, "difficulty": 4, "priority": 5,
//                  "deadline": 2000, "duration_curve": [60, 66, 72, 80, 90]} ]
// }
//
// Response: { "strategy", "blocks": [...], "unscheduled": [...], "metrics": {...} }
#pragma once

#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "flexsched/types.hpp"

namespace flexsched {

struct Request {
    std::string strategy = "fatigue_aware";
    Params params;
    std::vector<Interval> windows;
    std::vector<Interval> blocked;
    std::vector<Task> tasks;
};

// Throws std::invalid_argument with a readable message on malformed input.
Request parse_request(const nlohmann::json& j);

nlohmann::json to_json(const ScheduleResult& result, const std::string& strategy);

}  // namespace flexsched

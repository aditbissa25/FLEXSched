#include <stdexcept>

#include <catch2/catch_test_macros.hpp>
#include <nlohmann/json.hpp>

#include "flexsched/json_io.hpp"

using namespace flexsched;
using nlohmann::json;

TEST_CASE("A minimal request uses default parameters", "[json]") {
    const json j = json::parse(R"({
        "windows": [{"start": 540, "end": 1020}],
        "tasks": [{"id": 1, "difficulty": 4, "priority": 2,
                   "deadline": 900, "duration_curve": [30, 40]}]
    })");
    const Request r = parse_request(j);
    CHECK(r.strategy == "fatigue_aware");
    CHECK(r.params.break_minutes == Params{}.break_minutes);
    REQUIRE(r.windows.size() == 1);
    CHECK(r.blocked.empty());
    REQUIRE(r.tasks.size() == 1);
    CHECK(r.tasks[0].duration_curve.size() == 2);
}

TEST_CASE("Provided parameters override defaults", "[json]") {
    const json j = {{"strategy", "edf"},
                    {"params", {{"break_minutes", 20}, {"w_energy", 0.5}}}};
    const Request r = parse_request(j);
    CHECK(r.strategy == "edf");
    CHECK(r.params.break_minutes == 20);
    CHECK(r.params.w_energy == 0.5);
    CHECK(r.params.work_rate == Params{}.work_rate);  // untouched
}

TEST_CASE("Malformed requests are rejected with a clear error", "[json][edge]") {
    CHECK_THROWS_AS(parse_request(json::array()), std::invalid_argument);
    CHECK_THROWS_AS(parse_request({{"windows", {{{"start", 10}}}}}), std::invalid_argument);
    CHECK_THROWS_AS(parse_request({{"windows", {{{"start", 10}, {"end", 5}}}}}),
                    std::invalid_argument);
    CHECK_THROWS_AS(parse_request({{"tasks", {{{"id", 1}}}}}), std::invalid_argument);
    CHECK_THROWS_AS(parse_request({{"tasks", "nope"}}), std::invalid_argument);
}

TEST_CASE("Results serialise to the documented shape", "[json]") {
    ScheduleResult res;
    ScheduledBlock task_block;
    task_block.task_id = 3;
    task_block.start = 540;
    task_block.end = 600;
    task_block.late = true;
    ScheduledBlock break_block;
    break_block.kind = BlockKind::Break;
    break_block.start = 600;
    break_block.end = 615;
    res.blocks = {task_block, break_block};
    res.unscheduled = {{9, "too long"}};
    res.metrics.tasks_scheduled = 1;

    const json out = to_json(res, "fatigue_aware");
    CHECK(out["strategy"] == "fatigue_aware");
    REQUIRE(out["blocks"].size() == 2);
    CHECK(out["blocks"][0]["kind"] == "task");
    CHECK(out["blocks"][0]["task_id"] == 3);
    CHECK(out["blocks"][0]["late"] == true);
    CHECK(out["blocks"][1]["kind"] == "break");
    CHECK_FALSE(out["blocks"][1].contains("task_id"));
    CHECK(out["unscheduled"][0]["reason"] == "too long");
    CHECK(out["metrics"]["tasks_scheduled"] == 1);
}

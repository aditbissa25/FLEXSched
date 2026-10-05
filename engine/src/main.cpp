// main.cpp - Command-line entry point of the scheduling engine.
//
// Usage:
//   flexsched_engine < request.json > response.json
//   flexsched_engine --version
//
// Exit codes: 0 = success, 2 = invalid input, 1 = unexpected internal error.
// Errors are written to stderr so stdout only ever contains valid JSON.
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

#include "flexsched/calendar.hpp"
#include "flexsched/json_io.hpp"
#include "flexsched/policy.hpp"
#include "flexsched/scheduler.hpp"

namespace {
constexpr const char* kVersion = "1.0.0";
}

int main(int argc, char** argv) {
    if (argc > 1) {
        const std::string arg = argv[1];
        if (arg == "--version") {
            std::cout << "flexsched_engine " << kVersion << "\n";
            return 0;
        }
        std::cerr << "usage: flexsched_engine < request.json\n";
        return arg == "--help" ? 0 : 2;
    }

    try {
        const std::string input((std::istreambuf_iterator<char>(std::cin)),
                                std::istreambuf_iterator<char>());
        const nlohmann::json request_json = nlohmann::json::parse(input);
        const flexsched::Request req = flexsched::parse_request(request_json);

        flexsched::Scheduler scheduler(req.params, flexsched::make_policy(req.strategy));
        const auto slots = flexsched::free_slots(req.windows, req.blocked);
        const auto result = scheduler.run(req.tasks, slots);

        std::cout << flexsched::to_json(result, req.strategy).dump() << "\n";
        return 0;
    } catch (const nlohmann::json::exception& e) {
        std::cerr << "invalid JSON: " << e.what() << "\n";
        return 2;
    } catch (const std::invalid_argument& e) {
        std::cerr << "invalid request: " << e.what() << "\n";
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "internal error: " << e.what() << "\n";
        return 1;
    }
}

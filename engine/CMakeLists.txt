cmake_minimum_required(VERSION 3.16)
project(flexsched_engine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(FLEXSCHED_BUILD_TESTS "Build the Catch2 unit tests" ON)

# ---- Third-party dependencies (downloaded at configure time) -------------
include(FetchContent)

FetchContent_Declare(
  nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_MakeAvailable(nlohmann_json)

# ---- Core library: all scheduling logic, no I/O --------------------------
add_library(flexsched_core STATIC
  src/fatigue.cpp
  src/duration.cpp
  src/calendar.cpp
  src/policy.cpp
  src/scheduler.cpp
  src/json_io.cpp)
target_include_directories(flexsched_core PUBLIC include)
target_link_libraries(flexsched_core PUBLIC nlohmann_json::nlohmann_json)

if(MSVC)
  target_compile_options(flexsched_core PRIVATE /W4)
else()
  target_compile_options(flexsched_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

# ---- Command-line executable used by Python ------------------------------
add_executable(flexsched_engine src/main.cpp)
target_link_libraries(flexsched_engine PRIVATE flexsched_core)
if(MINGW)
  # Bundle the C++ runtime so the .exe runs without MinGW on PATH.
  target_link_options(flexsched_engine PRIVATE -static)
endif()

# ---- Unit tests ----------------------------------------------------------
if(FLEXSCHED_BUILD_TESTS)
  FetchContent_Declare(
    Catch2
    URL https://github.com/catchorg/Catch2/archive/refs/tags/v3.7.1.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  FetchContent_MakeAvailable(Catch2)

  add_executable(flexsched_tests
    tests/test_fatigue.cpp
    tests/test_duration.cpp
    tests/test_calendar.cpp
    tests/test_policy.cpp
    tests/test_scheduler.cpp
    tests/test_json_io.cpp)
  target_link_libraries(flexsched_tests PRIVATE flexsched_core Catch2::Catch2WithMain)
  if(MINGW)
    target_link_options(flexsched_tests PRIVATE -static)
  endif()

  enable_testing()
  list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
  include(Catch)
  catch_discover_tests(flexsched_tests)
endif()

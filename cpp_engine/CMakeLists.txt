cmake_minimum_required(VERSION 3.18)
project(cpp_quant_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Optimization & Compiler Flags
if(MSVC)
    add_compile_options(/O2 /W4 /std:c++20)
else()
    add_compile_options(-O3 -Wall -Wextra -pedantic -march=native -ffast-math)
endif()

# Sanitizers
option(ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer" OFF)
option(ENABLE_TSAN "Enable ThreadSanitizer" OFF)
option(BUILD_TESTS "Build GoogleTest test suite" ON)
option(BUILD_BENCHMARKS "Build Performance Benchmarks" ON)

if(ENABLE_ASAN)
    message(STATUS "Enabling AddressSanitizer (ASan)")
    add_compile_options(-fsanitize=address -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address)
endif()

if(ENABLE_UBSAN)
    message(STATUS "Enabling UndefinedBehaviorSanitizer (UBSan)")
    add_compile_options(-fsanitize=undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=undefined)
endif()

if(ENABLE_TSAN)
    message(STATUS "Enabling ThreadSanitizer (TSan)")
    add_compile_options(-fsanitize=thread)
    add_link_options(-fsanitize=thread)
endif()

include_directories(${PROJECT_SOURCE_DIR}/include)

# -------------------------------------------------------------
# Core Engine Static Library
# -------------------------------------------------------------
add_library(quant_engine_core STATIC
    src/core/thread_utils.cpp
    src/protocol/binary_protocol.cpp
    src/protocol/itch50_protocol.cpp
    src/protocol/ouch_protocol.cpp
    src/order_book/order_book.cpp
    src/order_book/matching_engine.cpp
    src/risk/risk_engine.cpp
    src/gateway/io_reactor.cpp
    src/gateway/tcp_order_gateway.cpp
    src/gateway/itch_ouch_simulator.cpp
    src/market_data/gap_recovery.cpp
    src/market_data/udp_multicast_receiver.cpp
    src/engine/replay_engine.cpp
    src/engine/trading_engine.cpp
    src/fast_alpha_engine.cpp
    src/simd_alpha_calculator.cpp
)

target_include_directories(quant_engine_core PUBLIC ${PROJECT_SOURCE_DIR}/include)
find_package(Threads REQUIRED)
target_link_libraries(quant_engine_core PUBLIC Threads::Threads)

# -------------------------------------------------------------
# Standalone Production Gateway Server Executable
# -------------------------------------------------------------
add_executable(quant_gateway src/main_gateway.cpp)
target_link_libraries(quant_gateway PRIVATE quant_engine_core)

# -------------------------------------------------------------
# Performance & Latency Benchmark Suite
# -------------------------------------------------------------
if(BUILD_BENCHMARKS)
    add_executable(benchmark_engine benchmarks/benchmark_main.cpp)
    target_link_libraries(benchmark_engine PRIVATE quant_engine_core)
endif()

# -------------------------------------------------------------
# GoogleTest Integration
# -------------------------------------------------------------
if(BUILD_TESTS)
    include(FetchContent)
    FetchContent_Declare(
        googletest
        URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
    )
    # For Windows: Prevent overriding the parent project's compiler/linker settings
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)

    enable_testing()

    add_executable(engine_tests
        tests/test_lockfree_queues.cpp
        tests/test_object_pool.cpp
        tests/test_binary_protocol.cpp
        tests/test_order_book_matching.cpp
        tests/test_risk_engine.cpp
        tests/test_gap_recovery.cpp
        tests/test_deterministic_replay.cpp
        tests/test_network_gateway.cpp
        tests/test_nasdaq_itch_ouch.cpp
    )

    target_link_libraries(engine_tests PRIVATE quant_engine_core GTest::gtest_main)
    include(GoogleTest)
    gtest_discover_tests(engine_tests)
endif()

# -------------------------------------------------------------
# Pybind11 Python Native Module
# -------------------------------------------------------------
execute_process(
    COMMAND python3 -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
list(APPEND CMAKE_PREFIX_PATH "${pybind11_DIR}")
find_package(pybind11 QUIET)

if(pybind11_FOUND)
    pybind11_add_module(cpp_quant_engine src/bindings.cpp)
    target_link_libraries(cpp_quant_engine PRIVATE quant_engine_core)
    target_include_directories(cpp_quant_engine PRIVATE ${PROJECT_SOURCE_DIR}/include)
endif()

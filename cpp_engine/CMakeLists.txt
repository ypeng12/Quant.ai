cmake_minimum_required(VERSION 3.14)
project(cpp_quant_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Optimization flags
if(MSVC)
    add_compile_options(/O2 /W4)
else()
    add_compile_options(-O3 -Wall -Wextra -pedantic -ffast-math)
endif()

# Pybind11 setup
execute_process(
    COMMAND python3 -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
list(APPEND CMAKE_PREFIX_PATH "${pybind11_DIR}")
find_package(pybind11 REQUIRED)

include_directories(${PROJECT_SOURCE_DIR}/include)

# Build C++ Pybind11 extension module
pybind11_add_module(cpp_quant_engine
    src/fast_alpha_engine.cpp
    src/bindings.cpp
)

target_include_directories(cpp_quant_engine PRIVATE ${PROJECT_SOURCE_DIR}/include)

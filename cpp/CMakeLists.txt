cmake_minimum_required(VERSION 3.14)
project(orderbook_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Optimization flags
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")

# Find pybind11 — try system install, then fetch
find_package(pybind11 QUIET)
if(NOT pybind11_FOUND)
    include(FetchContent)
    FetchContent_Declare(
        pybind11
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG v2.11.1
    )
    FetchContent_MakeAvailable(pybind11)
endif()

# Build the Python module
pybind11_add_module(orderbook_cpp
    orderbook.cpp
    bindings.cpp
)

target_include_directories(orderbook_cpp PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Install to project root so Python can find it
install(TARGETS orderbook_cpp DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/..)

cmake_minimum_required(VERSION 3.16)
project(FluxTrainer CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

enable_testing()

add_subdirectory(core)
add_subdirectory(tools)
add_subdirectory(tests)

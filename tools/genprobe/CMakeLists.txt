add_executable(genprobe main.cpp)
target_link_libraries(genprobe PRIVATE config_json fluxtools_common)

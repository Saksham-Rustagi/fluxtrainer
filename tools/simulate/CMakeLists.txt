add_executable(simulate main.cpp)
target_link_libraries(simulate PRIVATE config_json fluxtools_common)

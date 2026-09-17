add_executable(genbench main.cpp)
find_package(Threads REQUIRED)
target_link_libraries(genbench PRIVATE config_json Threads::Threads)

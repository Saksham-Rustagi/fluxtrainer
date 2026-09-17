add_executable(test_dawg test_dawg.cpp)
target_link_libraries(test_dawg PRIVATE fluxcore dawg_builder)

add_executable(test_solver test_solver.cpp)
target_link_libraries(test_solver PRIVATE fluxcore dawg_builder)

add_executable(test_oracle test_oracle.cpp)
target_link_libraries(test_oracle PRIVATE fluxcore dawg_builder)

find_package(Threads REQUIRED)
add_executable(test_generator test_generator.cpp)
target_link_libraries(test_generator PRIVATE fluxcore dawg_builder Threads::Threads)

enable_testing()
add_test(NAME test_dawg COMMAND test_dawg)
add_test(NAME test_solver COMMAND test_solver)
add_test(NAME test_oracle COMMAND test_oracle)
add_test(NAME test_generator COMMAND test_generator)

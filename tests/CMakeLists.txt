add_executable(test_dawg test_dawg.cpp)
target_link_libraries(test_dawg PRIVATE fluxcore dawg_builder)

add_executable(test_solver test_solver.cpp)
target_link_libraries(test_solver PRIVATE fluxcore dawg_builder)

enable_testing()
add_test(NAME test_dawg COMMAND test_dawg)
add_test(NAME test_solver COMMAND test_solver)

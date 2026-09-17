add_executable(test_dawg test_dawg.cpp)
target_link_libraries(test_dawg PRIVATE fluxcore dawg_builder)

enable_testing()
add_test(NAME test_dawg COMMAND test_dawg)

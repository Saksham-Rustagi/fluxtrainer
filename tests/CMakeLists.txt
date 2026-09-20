add_executable(test_dawg test_dawg.cpp)
target_link_libraries(test_dawg PRIVATE fluxcore dawg_builder)

add_executable(test_solver test_solver.cpp)
target_link_libraries(test_solver PRIVATE fluxcore dawg_builder)

add_executable(test_oracle test_oracle.cpp)
target_link_libraries(test_oracle PRIVATE fluxcore dawg_builder)

find_package(Threads REQUIRED)
add_executable(test_generator test_generator.cpp)
target_link_libraries(test_generator PRIVATE fluxcore dawg_builder Threads::Threads)

add_executable(test_affix test_affix.cpp)
target_link_libraries(test_affix PRIVATE fluxcore dawg_builder lexicon)

# The full-dictionary halves of these suites need CSW21, which is not in the
# repo (licensing, spec 16.1). Point FLUX_WORDLIST at bogwords.txt to run them;
# without it ctest runs only the small synthetic-dictionary checks.
set(FLUX_WORDLIST "" CACHE FILEPATH "CSW21 word list for the full-dictionary tests")
foreach(suite test_dawg test_solver test_oracle test_generator test_affix)
  if(FLUX_WORDLIST)
    add_test(NAME ${suite} COMMAND ${suite} ${FLUX_WORDLIST})
  else()
    add_test(NAME ${suite} COMMAND ${suite})
  endif()
endforeach()

add_executable(test_ruleset test_ruleset.cpp)
target_link_libraries(test_ruleset PRIVATE fluxcore config_json)
target_compile_definitions(test_ruleset PRIVATE FLUX_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
add_test(NAME test_ruleset COMMAND test_ruleset)

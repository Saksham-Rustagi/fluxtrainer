add_executable(measure main.cpp)
target_link_libraries(measure PRIVATE config_json fluxtools_common lexicon)

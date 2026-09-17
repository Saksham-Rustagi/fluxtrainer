# Hand-rolled JSON reader for the versioned ruleset config. Lives under
# tools/ because it touches the filesystem; core/ only ever sees the filled-in
# RulesetConfig struct.
add_library(config_json STATIC
    src/config_json.cpp
)
target_include_directories(config_json PUBLIC include)
target_link_libraries(config_json PUBLIC fluxcore)

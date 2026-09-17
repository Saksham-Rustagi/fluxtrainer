# Offline lexicon indices (spec 7.1, 7.6). Under tools/ rather than core/
# because they are large and only the measurement pipeline reads them; the
# device sees whatever small artifact they produce, not the indices.
add_library(lexicon STATIC
    src/lexicon.cpp
)
target_include_directories(lexicon PUBLIC include)
target_link_libraries(lexicon PUBLIC fluxcore)

# Builds every index against a real dictionary and prints size, build time and
# counts. This is where the D5 numbers come from.
add_executable(lexstat lexstat_main.cpp)
target_link_libraries(lexstat PRIVATE lexicon config_json)

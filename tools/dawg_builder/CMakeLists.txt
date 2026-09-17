# Offline DAWG construction (Daciuk incremental minimization) and
# serialization. Pure in-memory logic, no I/O, but lives under tools/
# because it's build-tooling, not engine code that ships to iOS.
add_library(dawg_builder STATIC
    src/dawg_builder.cpp
)
target_include_directories(dawg_builder PUBLIC include)
target_include_directories(dawg_builder PRIVATE ${CMAKE_SOURCE_DIR}/core/include)

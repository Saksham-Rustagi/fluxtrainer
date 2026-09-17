# Shared tool infrastructure: thread pool, distribution summaries, manifest
# writing, and the git SHA baked in at build time.
set(GIT_VERSION_HEADER ${CMAKE_CURRENT_BINARY_DIR}/git_version.h)

add_custom_target(git_version_header ALL
    COMMAND ${CMAKE_COMMAND}
            -DSOURCE_DIR=${CMAKE_SOURCE_DIR}
            -DIN_FILE=${CMAKE_CURRENT_SOURCE_DIR}/include/git_version.h.in
            -DOUT_FILE=${GIT_VERSION_HEADER}
            -P ${CMAKE_SOURCE_DIR}/cmake/GitVersion.cmake
    BYPRODUCTS ${GIT_VERSION_HEADER}
    COMMENT "Recording git SHA for run manifests"
)

add_library(fluxtools_common STATIC
    src/thread_pool.cpp
    src/stats.cpp
    src/manifest.cpp
)
add_dependencies(fluxtools_common git_version_header)
target_include_directories(fluxtools_common PUBLIC include ${CMAKE_CURRENT_BINARY_DIR})

find_package(Threads REQUIRED)
target_link_libraries(fluxtools_common PUBLIC Threads::Threads)

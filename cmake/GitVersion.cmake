# Regenerates git_version.h. Run as a build step rather than at configure
# time, because a manifest that records a stale SHA is worse than one that
# records none: spec 5.3 says a run that cannot be reproduced from its
# manifest is a bug.
find_package(Git QUIET)

set(GIT_SHA "unknown")
set(GIT_DIRTY "true")

if(GIT_FOUND)
  execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
                  WORKING_DIRECTORY ${SOURCE_DIR}
                  OUTPUT_VARIABLE SHA_OUT OUTPUT_STRIP_TRAILING_WHITESPACE
                  ERROR_QUIET RESULT_VARIABLE SHA_RESULT)
  if(SHA_RESULT EQUAL 0)
    set(GIT_SHA "${SHA_OUT}")
  endif()

  execute_process(COMMAND ${GIT_EXECUTABLE} status --porcelain
                  WORKING_DIRECTORY ${SOURCE_DIR}
                  OUTPUT_VARIABLE STATUS_OUT OUTPUT_STRIP_TRAILING_WHITESPACE
                  ERROR_QUIET RESULT_VARIABLE STATUS_RESULT)
  if(STATUS_RESULT EQUAL 0 AND STATUS_OUT STREQUAL "")
    set(GIT_DIRTY "false")
  endif()
endif()

configure_file(${IN_FILE} ${OUT_FILE} @ONLY)

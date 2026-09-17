# The FluxCore engine. Must stay free of I/O and platform APIs -- it will
# later be compiled as an iOS arm64 static library.
add_library(fluxcore STATIC
    src/dawg.cpp
    src/board.cpp
    src/solver.cpp
    src/generator.cpp
    src/affix.cpp
    src/fluxcore_shim.cpp
)
target_include_directories(fluxcore PUBLIC include)

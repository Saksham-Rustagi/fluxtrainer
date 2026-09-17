#ifndef FLUXCORE_H
#define FLUXCORE_H

#include <stddef.h>
#include <stdint.h>

// C shim for FluxCore. Flat structs and a C ABI so the engine can be
// linked into Swift (or anything else) as a static library later. Nothing
// consumes this yet -- it exists now so the core/ boundary is a formality
// by the time Phase 2 needs it.
//
// FluxCore itself performs no I/O and touches no platform API: every
// function here operates on caller-supplied memory (e.g. an mmap'd file).

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FluxDawgHandle {
    void* impl;
} FluxDawgHandle;

// Wires up `outHandle` over `data`/`size` (e.g. an mmap'd DAWG file, see
// core/include/dawg_format.h for the layout). The caller owns `data` and
// must keep it valid for the handle's lifetime. Returns 1 on success, 0 if
// the buffer is malformed.
int flux_dawg_load(const uint8_t* data, size_t size, FluxDawgHandle* outHandle);

// Releases resources associated with `handle`. Does not free `data`.
void flux_dawg_destroy(FluxDawgHandle* handle);

uint32_t flux_dawg_word_count(const FluxDawgHandle* handle);

// Looks up `word` (uppercase A-Z, `len` bytes, need not be
// NUL-terminated). Returns 1 and writes the dense word ID to `outId` if
// found, else returns 0.
int flux_dawg_find_word_id(const FluxDawgHandle* handle, const char* word, size_t len, uint32_t* outId);

#ifdef __cplusplus
}
#endif

#endif  // FLUXCORE_H

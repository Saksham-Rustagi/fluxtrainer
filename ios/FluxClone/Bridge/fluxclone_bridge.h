#ifndef FLUXCLONE_BRIDGE_H
#define FLUXCLONE_BRIDGE_H

#include <stddef.h>
#include <stdint.h>

// App-side C bridge over FluxCore: one engine holds the DAWG, the ruleset,
// the seed pool, a generator and a solver. Everything crosses as flat
// structs. Not thread-safe for generation (one engine per serial queue);
// the lookups are read-only on the DAWG and safe from any thread.

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FCEngine FCEngine;

// `dawg` must outlive the engine. Returns NULL and writes a message into
// `err` if the ruleset does not parse or pins a different dictionary.
FCEngine* fc_engine_create(const uint8_t* dawg, size_t dawgSize, const char* config,
                           size_t configSize, char* err, size_t errSize);
void fc_engine_destroy(FCEngine* engine);

uint32_t fc_engine_ruleset_version(const FCEngine* engine);
uint64_t fc_engine_config_hash(const FCEngine* engine);
uint64_t fc_engine_dictionary_hash(const FCEngine* engine);
uint32_t fc_engine_dictionary_words(const FCEngine* engine);

// Tier: 0 Casual, 1 GoodCasual, 2 Spam (fluxcore::Tier).
// Draws a tier for `side` from the ruleset's tier shares.
uint8_t fc_engine_draw_tier(FCEngine* engine, uint8_t side, uint64_t rngSeed);

typedef struct FCBoard {
    uint8_t side;
    uint8_t tier;
    char letters[26];  // side*side uppercase letters, NUL-terminated
    uint64_t rootSeed;
    uint64_t boardSeed;
    uint32_t realizedN;
    uint8_t seeded;
    char seedWord[26];  // NUL-terminated, empty when not seeded
    uint64_t potentialPoints;  // each distinct word once (spec 2.3)
    uint32_t potentialWords;
    uint32_t potentialWords5p;
    double generateMs;
    double solveMs;
} FCBoard;

// Best-of-N generation for (side, tier) followed by a count-mode solve of
// the winner. Returns 1 on success.
int fc_engine_generate(FCEngine* engine, uint8_t side, uint8_t tier, uint64_t rootSeed,
                       FCBoard* out);

// Uppercase A-Z. 1 and the dense word ID if `word` is in the dictionary.
int fc_engine_word_id(const FCEngine* engine, const char* word, size_t len, uint32_t* outId);

// 1 if some dictionary word starts with `prefix` (including the word itself).
int fc_engine_is_prefix(const FCEngine* engine, const char* prefix, size_t len);

#ifdef __cplusplus
}
#endif

#endif  // FLUXCLONE_BRIDGE_H

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

// ---------------------------------------------------------------------------
// Phase 3: training boards and full solves.
// ---------------------------------------------------------------------------

// What a constrained generation cost, so the app can show the fallback ladder
// working rather than silently serving a board that misses its target
// (spec 11.1). `exhausted` means the budget ran out before N candidates were
// accepted; a board is still returned if any candidate passed.
typedef struct FCConstrainedStats {
    uint32_t candidatesBuilt;
    uint32_t candidatesAccepted;
    uint32_t solves;
    uint32_t placementFailures;
    uint32_t normRejects;
    uint32_t wordRejects;
    uint8_t exhausted;
    double generateMs;
} FCConstrainedStats;

// A board carrying `target` as a path. [normLow, normHigh] bands total points
// and [minWords, maxWords] bands the distinct word count; 0 / UINT64_MAX and
// 0 / 0 respectively turn each off. Returns 1 if a board was produced -- check
// `outStats->exhausted` for whether it got the tier's full best-of-N.
int fc_engine_generate_hook(FCEngine* engine, uint8_t side, uint8_t tier, const char* target,
                            size_t targetLen, uint64_t rootSeed, uint64_t normLow,
                            uint64_t normHigh, uint32_t minWords, uint32_t maxWords,
                            uint32_t attemptBudget, FCBoard* outBoard,
                            FCConstrainedStats* outStats);

// Solve `letters` (side*side uppercase, as FCBoard::letters) in Full mode and
// keep the result inside the engine. Every word on the board with a path is an
// observed presence with a known outcome, which is what Phase 3 records for
// every board it plays. Returns the distinct word count, or 0 on a bad board.
//
// The result stays valid until the next fc_engine_solve or fc_engine_generate*
// on the same engine, so it is read on the same serial queue that produced it.
typedef struct FCSolveSummary {
    uint32_t words;
    uint64_t totalPoints;
    uint32_t words5p;
    uint8_t pathCapHit;
    double solveMs;
} FCSolveSummary;

uint32_t fc_engine_solve(FCEngine* engine, uint8_t side, const char* letters,
                         FCSolveSummary* outSummary);

// Word `i` of the last solve, NUL-terminated into `out`. Returns its length.
uint32_t fc_engine_solved_word(const FCEngine* engine, uint32_t i, char* out, size_t cap);
// The true number of distinct paths spelling word `i`, and how many were kept.
uint32_t fc_engine_solved_path_count(const FCEngine* engine, uint32_t i);
uint32_t fc_engine_solved_paths_stored(const FCEngine* engine, uint32_t i);
// Path `j` of word `i` as cell indices. Returns the number of cells written.
uint32_t fc_engine_solved_path(const FCEngine* engine, uint32_t i, uint32_t j, uint8_t* out,
                               size_t cap);

#ifdef __cplusplus
}
#endif

#endif  // FLUXCLONE_BRIDGE_H

#pragma once

#include <cstddef>
#include <cstdint>

#include "dawg.h"

// Affix machinery for spec 7.3. There is deliberately no affix list here or
// anywhere else in the engine: affixes are derived, and the three jobs an
// earlier draft conflated into one hand-typed list are three separate
// mechanisms.
//
//   1. Live affixes    walk the DAWG to the stem's node; its subtree
//                      enumerates every valid continuation, exactly and
//                      completely. Front extensions are the same walk over a
//                      reversed DAWG.
//   2. Classification  substring containment. W is additive w.r.t. S iff S
//                      occurs in W as a contiguous substring, which is not an
//                      approximation of the path condition but exactly it.
//   3. Dead affixes    mined from the dictionary (see tools/lexicon), because
//                      "not a word" is only interesting for strings a player
//                      would plausibly try.
//
// The drop-E / Y->I / consonant-doubling rules survive only in
// generateMutations(), which proposes related-but-not-containing words so
// they can be taught as misswipe-prevention items. They decide neither
// validity (a DAWG lookup does) nor class (containment does).

namespace fluxcore {

enum class AffixSide : uint8_t {
    Suffix = 0,  // letters appended:  PRATE -> PRATER
    Prefix = 1,  // letters prepended: PATERS -> EPATERS
    Both = 2,    // letters at both ends
};

enum class AffixClass : uint8_t {
    Additive = 0,  // stem contained contiguously; free points if reachable
    Cellmate = 1,  // same letters, different order (7.6); never produced by affixing
    Mutating = 2,  // a word, but the stem's letters are not preserved
    Dead = 3,      // not a word at all
};

// Which mutation produced a candidate. Reported so a caller can tell why a
// form was proposed; it carries no authority over the form's class.
enum class MutationRule : uint8_t {
    None = 0,
    DropFinalE = 1,
    YToI = 2,
    DoubleFinalConsonant = 3,
};

// The exact path condition (7.3): does `stem` occur in `word` as a
// contiguous substring? If so, *outOffset is where it starts, so the caller
// knows how many cells precede the stem on the board.
bool containsStem(const char* word, uint8_t wordLen, const char* stem, uint8_t stemLen,
                  uint8_t* outOffset);

// Classification by containment. `isWord` is the dictionary's answer, passed
// in rather than looked up so this stays a pure function.
AffixClass classifyForm(const char* form, uint8_t formLen, const char* stem, uint8_t stemLen,
                        bool isWord);

// One live continuation of a stem, discovered by walking the DAWG.
struct LiveAffix {
    char letters[16] = {};
    uint8_t len = 0;
    uint32_t wordId = 0;   // the completed word's dense ID
    uint8_t wordLen = 0;
};

// Every valid continuation of `stem`, enumerated from the stem's DAWG subtree.
// This IS the live suffix set for the stem: complete, and derived rather than
// guessed. Continuations longer than `maxAffixLen` are not explored, and at
// most `maxResults` are written. Returns the number written.
//
// Pass a reversed-dictionary DAWG and a reversed stem to get front extensions
// by the same walk; the caller reverses the reported letters back.
size_t enumerateLiveAffixes(const Dawg& dawg, const char* stem, uint8_t stemLen,
                            uint8_t maxAffixLen, LiveAffix* out, size_t maxResults);

// True when `stem` is a prefix path in the DAWG at all, i.e. some word starts
// with it. Cheap precondition for the walk above.
bool stemIsPrefix(const Dawg& dawg, const char* stem, uint8_t stemLen, uint32_t* outState,
                  uint32_t* outRank);

// A related-but-not-containing candidate, for the misswipe track only.
struct MutationCandidate {
    char form[32] = {};
    uint8_t len = 0;
    MutationRule rule = MutationRule::None;
};

// Applies the three mutation rules to `stem` + `affix` and writes the
// candidates they produce. These are proposals for the misswipe track: the
// caller still asks the DAWG whether each is a word, and still classifies it
// by containment. Returns the number written.
size_t generateMutations(const char* stem, uint8_t stemLen, const char* affix, uint8_t affixLen,
                         MutationCandidate* out, size_t maxResults);

}  // namespace fluxcore

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "dawg.h"

// Offline lexicon indices: the word-to-word relations of spec 7.1 and 7.6,
// precomputed over the whole dictionary.
//
// These live under tools/ and not in core/ on purpose. They are bulky --
// hundreds of megabytes while building, tens when built -- and nothing on the
// device needs them: they feed the measurement tool and, later, the offline
// study-item build. core/ gets whatever small artifact that produces.
//
// Everything is keyed on dense DAWG word IDs, never on strings, so callers can
// count into arrays sized by wordCount(). Strings are produced only at the
// edges, for printing and for hand-checking.
//
// The relations, and which of them need measuring (7.6):
//
//   anagram         SEATERS / SAETERS      same multiset, order differs
//   drop-terminal   CANTERED -> CANTER     contiguous substring, P = 1.0 by
//                                          construction, never measured
//   drop-interior   CANTERED -> CANTRED    one interior letter deleted, needs
//                                          adjacency the long word's own path
//                                          never had, so it must be measured
//   additive ext.   CANTER -> CANTERED     the transpose of drop-terminal,
//                                          annotated with the affix and side

namespace fluxcore {
namespace lex {

struct IndexStats {
    double buildMillis = 0.0;
    size_t bytes = 0;     // heap retained by the finished index
    size_t peakBytes = 0; // heap high-water mark during the build
    size_t entries = 0;   // meaning depends on the index; see each accessor
};

// Convenience for printing and hand-checks. Not used on any hot path.
std::string wordString(const Dawg& dawg, uint32_t wordId);
bool wordId(const Dawg& dawg, const std::string& word, uint32_t* outId);

// ---------------------------------------------------------------------------
// 1. Anagram index (7.6, the strongest cellmate relation)
// ---------------------------------------------------------------------------

class AnagramIndex {
public:
    // False if `dawg` is not loaded. Safe to call twice; the second call
    // rebuilds.
    bool build(const Dawg& dawg);

    // Every word sharing this word's sorted-letter key, including the word
    // itself, so the returned count is >= 1 for any valid ID. Members are in
    // ascending ID order.
    const uint32_t* membersOf(uint32_t wordId, uint32_t* outCount) const;

    // Dense class index for a word, usable as an array key.
    uint32_t classOf(uint32_t wordId) const { return classOf_[wordId]; }

    size_t classCount() const { return offsets_.empty() ? 0 : offsets_.size() - 1; }
    size_t nonTrivialClassCount() const { return nonTrivialClasses_; }  // >= 2 members
    size_t pairCount() const { return pairs_; }                         // ordered pairs
    size_t largestClassSize() const { return largestClass_; }

    const IndexStats& stats() const { return stats_; }

private:
    std::vector<uint32_t> classOf_;
    std::vector<uint32_t> offsets_;  // classCount + 1 entries
    std::vector<uint32_t> members_;
    size_t nonTrivialClasses_ = 0;
    size_t pairs_ = 0;
    size_t largestClass_ = 0;
    IndexStats stats_;
};

// ---------------------------------------------------------------------------
// 2-4. Drop-terminal, drop-interior and additive extensions
// ---------------------------------------------------------------------------

// CANTERED -> CANTER. `trimFront` letters were removed from the front and
// `trimBack` from the back, at least one of them non-zero. Both ends may be
// trimmed at once (CANTERED -> ANTE): the result is still a contiguous
// sub-path of the long word's path, which is the whole reason this class is
// P = 1.0.
struct DropTerminalPair {
    uint32_t word = 0;  // the longer word
    uint32_t sub = 0;   // the shorter word, a proper contiguous substring
    uint8_t trimFront = 0;
    uint8_t trimBack = 0;
};

// CANTERED -> CANTRED. Exactly one letter deleted, at an interior position
// (1 .. len-2). Never a pair that drop-terminal already covers; see the note
// on buildSubwordIndex.
struct DropInteriorPair {
    uint32_t word = 0;
    uint32_t sub = 0;
    uint8_t position = 0;  // index deleted from `word`
};

// The transpose of DropTerminalPair, stored per stem because that is how the
// affix grid asks the question: given this stem, what extends it?
// word == prefix + stem + suffix, with prefixLen + suffixLen > 0.
struct AdditiveExtension {
    uint32_t word = 0;
    uint8_t prefixLen = 0;
    uint8_t suffixLen = 0;

    bool front() const { return prefixLen > 0 && suffixLen == 0; }
    bool back() const { return suffixLen > 0 && prefixLen == 0; }
    bool both() const { return prefixLen > 0 && suffixLen > 0; }
};

struct SubwordOptions {
    // Sub-words below this length are ignored. 3 matches the solver's
    // minWordLen: a 2-letter sub-word is not a scoring word, so it is not a
    // study item either.
    uint8_t minSubwordLen = 3;
};

// All three relations come out of one pass, because they are one enumeration:
// a word W' is an additive extension of S exactly when (W', S) is a
// drop-terminal pair. They are exposed separately because they are read in
// opposite directions.
class SubwordIndex {
public:
    bool build(const Dawg& dawg, const SubwordOptions& options);

    const std::vector<DropTerminalPair>& dropTerminalPairs() const { return terminal_; }
    const std::vector<DropInteriorPair>& dropInteriorPairs() const { return interior_; }

    // Extensions of one stem, in ascending word-ID order. Count is 0 for a
    // stem shorter than minSubwordLen or one nothing extends.
    const AdditiveExtension* extensionsForStem(uint32_t stemId, uint32_t* outCount) const;

    size_t extensionCount() const { return extensions_.size(); }
    size_t stemsWithExtensions() const { return stemsWithExtensions_; }

    const IndexStats& terminalStats() const { return terminalStats_; }
    const IndexStats& interiorStats() const { return interiorStats_; }
    const IndexStats& extensionStats() const { return extensionStats_; }

private:
    std::vector<DropTerminalPair> terminal_;
    std::vector<DropInteriorPair> interior_;
    std::vector<AdditiveExtension> extensions_;
    std::vector<uint32_t> extensionOffsets_;  // wordCount + 1 entries
    size_t stemsWithExtensions_ = 0;
    IndexStats terminalStats_;
    IndexStats interiorStats_;
    IndexStats extensionStats_;
};

// ---------------------------------------------------------------------------
// 4b. Mined affix alphabet (7.3)
// ---------------------------------------------------------------------------

// Spec 7.3: affixes are derived, not enumerated. There is no list anywhere in
// the engine. Live affixes for a given stem come from its DAWG subtree
// (core/affix.h); this is the other half -- the affix ALPHABET, mined by
// counting which continuations are productive across the whole dictionary.
//
// It exists for exactly one job: dead affixes. "Not a word" is only useful
// for strings a player would plausibly try, so the candidate set has to be
// the affixes CSW21 actually uses, ranked by how many stems they extend.
struct MinedAffix {
    char letters[12] = {};
    uint8_t len = 0;
    bool front = false;   // prepended rather than appended
    uint32_t stems = 0;   // distinct stems this affix extends
};

struct MinedAffixOptions {
    uint8_t maxAffixLen = 5;
    size_t keepPerSide = 30;   // "the most productive ~30"
    uint8_t minStemLen = 3;
};

// Ranked most-productive-first, front and back affixes kept separately.
class MinedAffixSet {
public:
    bool build(const Dawg& dawg, const SubwordIndex& subwords, const MinedAffixOptions& options);

    const std::vector<MinedAffix>& back() const { return back_; }
    const std::vector<MinedAffix>& front() const { return front_; }

    // Does `affix` complete `stemId` into a real word? The dead affixes for a
    // stem are the productive ones for which this is false.
    bool completes(const Dawg& dawg, uint32_t stemId, const MinedAffix& affix) const;

    const IndexStats& stats() const { return stats_; }

private:
    std::vector<MinedAffix> back_;
    std::vector<MinedAffix> front_;
    IndexStats stats_;
};

// ---------------------------------------------------------------------------
// 5. Substring-stem families (7.1)
// ---------------------------------------------------------------------------

// The bounds are parameters because the unbounded version does not fit: every
// substring of every word in CSW21 is ~24M (stem, word) entries before
// grouping. Defaults are the band 7.5 says survives, which is also the band
// that fits comfortably in RAM. See the measured costs in the header comment
// of buildStemFamilies in lexicon.cpp.
struct FamilyOptions {
    uint8_t minStemLen = 4;
    uint8_t maxStemLen = 7;  // hard ceiling: stems are packed into 33 bits
    uint32_t minFamilySize = 3;  // 7.2 rule 1's floor; smaller families are dropped
    uint8_t minMemberLen = 3;    // members below the solver's minWordLen are not words in play
};

constexpr uint8_t kMaxStemLen = 7;

class StemFamilyIndex {
public:
    // False with a message in `error` if the options are out of range or the
    // dictionary is too large for the packing (see kMaxPackedWords).
    bool build(const Dawg& dawg, const FamilyOptions& options, std::string* error);

    size_t familyCount() const { return stems_.size(); }

    // Families are in ascending stem order (by length, then alphabetically).
    std::string stem(size_t family) const;
    const uint32_t* members(size_t family, uint32_t* outCount) const;

    // Binary search by stem text; returns familyCount() when absent.
    size_t findFamily(const char* stem, uint8_t len) const;

    size_t memberSlots() const { return members_.size(); }
    const IndexStats& stats() const { return stats_; }

private:
    // Packed stem key: base-26 letter code (33 bits) plus length (3 bits).
    std::vector<uint64_t> stems_;
    std::vector<uint32_t> offsets_;  // familyCount + 1 entries
    std::vector<uint32_t> members_;
    FamilyOptions options_;
    IndexStats stats_;
};

// Word IDs are packed into 20 bits alongside the stem key while sorting, so
// the family builder needs the dictionary to be smaller than this. CSW21 is
// 279,496.
constexpr uint32_t kMaxPackedWords = 1u << 20;

}  // namespace lex
}  // namespace fluxcore

#include "lexicon.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <unordered_map>

namespace fluxcore {
namespace lex {
namespace {

constexpr size_t kWordBuf = 64;  // CSW21's longest word is 15

double millisSince(std::chrono::steady_clock::time_point start) {
    const auto end = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(end - start).count();
}

template <typename T>
size_t vectorBytes(const std::vector<T>& v) {
    return v.capacity() * sizeof(T);
}

// A DAWG walk that carries the dense word ID down with it, so extending a
// prefix by one letter costs one edge scan instead of a fresh findWordId from
// the root. Same trick as the solver's stepEdge; duplicated here rather than
// exported from core, because core's copy is shaped for the board walk and
// this one is shaped for a string walk.
struct Walk {
    const Dawg* dawg = nullptr;
    uint32_t state = 0;
    uint32_t rank = 0;
    bool live = false;

    void reset(const Dawg& d) {
        dawg = &d;
        state = d.rootState();
        rank = 0;
        live = true;
    }

    // Returns true if the prefix so far is itself a word, writing its ID.
    bool step(char letter, uint32_t* outId) {
        if (!live || !dawg->hasEdges(state)) {
            live = false;
            return false;
        }
        const uint8_t target = static_cast<uint8_t>(letter - 'A');
        uint32_t edgeIdx = dawg->state(state).edgeStart;
        uint32_t base = rank;
        for (;;) {
            const DawgEdge& e = dawg->edge(edgeIdx);
            if (e.letter() == target) {
                state = e.childState();
                rank = base + (e.endOfWord() ? 1u : 0u);
                if (e.endOfWord()) {
                    *outId = base;
                    return true;
                }
                return false;
            }
            base += (e.endOfWord() ? 1u : 0u) + dawg->state(e.childState()).wordCount;
            if (e.endOfList()) {
                live = false;
                return false;
            }
            ++edgeIdx;
        }
    }
};

}  // namespace

std::string wordString(const Dawg& dawg, uint32_t id) {
    char buf[kWordBuf];
    const size_t len = dawg.wordForId(id, buf, sizeof(buf));
    return std::string(buf, len);
}

bool wordId(const Dawg& dawg, const std::string& word, uint32_t* outId) {
    return dawg.findWordId(word.data(), word.size(), outId);
}

// ---------------------------------------------------------------------------
// Anagram index
// ---------------------------------------------------------------------------

bool AnagramIndex::build(const Dawg& dawg) {
    if (!dawg.isLoaded()) return false;
    const auto start = std::chrono::steady_clock::now();

    *this = AnagramIndex{};
    const uint32_t words = dawg.wordCount();

    // Sorted letters, held inline rather than as a std::string: 279k tiny
    // heap allocations cost more than the whole rest of this build.
    struct Keyed {
        char key[16];
        uint8_t len;
        uint32_t id;
    };
    std::vector<Keyed> keyed(words);
    char buf[kWordBuf];
    for (uint32_t id = 0; id < words; ++id) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        Keyed& k = keyed[id];
        k.len = static_cast<uint8_t>(len);
        k.id = id;
        std::memset(k.key, 0, sizeof(k.key));
        std::memcpy(k.key, buf, len);
        std::sort(k.key, k.key + len);
    }
    const size_t scratchBytes = vectorBytes(keyed);

    std::sort(keyed.begin(), keyed.end(), [](const Keyed& a, const Keyed& b) {
        const int cmp = std::memcmp(a.key, b.key, sizeof(a.key));
        if (cmp != 0) return cmp < 0;
        return a.id < b.id;
    });

    classOf_.assign(words, 0u);
    members_.resize(words);
    offsets_.reserve(words + 1);
    offsets_.push_back(0);

    size_t i = 0;
    while (i < keyed.size()) {
        size_t j = i + 1;
        while (j < keyed.size() && std::memcmp(keyed[i].key, keyed[j].key, sizeof(keyed[i].key)) == 0) {
            ++j;
        }
        const uint32_t classIndex = static_cast<uint32_t>(offsets_.size() - 1);
        const size_t size = j - i;
        for (size_t k = i; k < j; ++k) {
            members_[k] = keyed[k].id;
            classOf_[keyed[k].id] = classIndex;
        }
        offsets_.push_back(static_cast<uint32_t>(j));
        if (size >= 2) {
            ++nonTrivialClasses_;
            pairs_ += size * (size - 1);  // ordered: 7.6 stores directed trigger pairs
        }
        largestClass_ = std::max(largestClass_, size);
        i = j;
    }

    stats_.buildMillis = millisSince(start);
    stats_.entries = classCount();
    stats_.bytes = vectorBytes(classOf_) + vectorBytes(offsets_) + vectorBytes(members_);
    stats_.peakBytes = stats_.bytes + scratchBytes;
    return true;
}

const uint32_t* AnagramIndex::membersOf(uint32_t id, uint32_t* outCount) const {
    const uint32_t cls = classOf_[id];
    *outCount = offsets_[cls + 1] - offsets_[cls];
    return members_.data() + offsets_[cls];
}

// ---------------------------------------------------------------------------
// Drop-terminal / drop-interior / additive extensions
// ---------------------------------------------------------------------------

bool SubwordIndex::build(const Dawg& dawg, const SubwordOptions& options) {
    if (!dawg.isLoaded()) return false;
    const uint8_t minLen = options.minSubwordLen == 0 ? 1 : options.minSubwordLen;

    const uint32_t words = dawg.wordCount();
    terminal_.clear();
    interior_.clear();
    extensions_.clear();
    extensionOffsets_.clear();
    stemsWithExtensions_ = 0;

    // --- drop-terminal: every proper contiguous substring that is a word.
    const auto terminalStart = std::chrono::steady_clock::now();
    char buf[kWordBuf];
    char cut[kWordBuf];
    for (uint32_t id = 0; id < words; ++id) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        if (len <= minLen) continue;
        for (size_t begin = 0; begin < len; ++begin) {
            Walk walk;
            walk.reset(dawg);
            for (size_t end = begin + 1; end <= len; ++end) {
                uint32_t subId = 0;
                const bool isWord = walk.step(buf[end - 1], &subId);
                if (!walk.live) break;  // no longer a dictionary prefix
                const size_t subLen = end - begin;
                if (!isWord || subLen < minLen) continue;
                if (begin == 0 && end == len) continue;  // the word itself
                DropTerminalPair pair;
                pair.word = id;
                pair.sub = subId;
                pair.trimFront = static_cast<uint8_t>(begin);
                pair.trimBack = static_cast<uint8_t>(len - end);
                terminal_.push_back(pair);
            }
        }
    }
    terminalStats_.buildMillis = millisSince(terminalStart);
    terminalStats_.entries = terminal_.size();
    terminalStats_.bytes = vectorBytes(terminal_);
    terminalStats_.peakBytes = terminalStats_.bytes;

    // --- drop-interior: exactly one letter deleted, not at either end.
    //
    // A pair can be reachable both ways when letters repeat: deleting the
    // interior E of EELS gives ELS, which is also EELS with its first letter
    // trimmed. Drop-terminal wins those, because the pair really is pathable
    // with certainty and recording it as interior would put a guaranteed
    // relation into the measured bucket and drag its measured probability
    // down. The two sets are therefore disjoint by construction.
    const auto interiorStart = std::chrono::steady_clock::now();
    for (uint32_t id = 0; id < words; ++id) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        if (len < 3 || len - 1 < minLen) continue;
        for (size_t pos = 1; pos + 1 < len; ++pos) {
            std::memcpy(cut, buf, pos);
            std::memcpy(cut + pos, buf + pos + 1, len - pos - 1);
            const size_t cutLen = len - 1;
            uint32_t subId = 0;
            if (!dawg.findWordId(cut, cutLen, &subId)) continue;
            if (std::memcmp(cut, buf + 1, cutLen) == 0) continue;  // == trim-front
            if (std::memcmp(cut, buf, cutLen) == 0) continue;      // == trim-back
            DropInteriorPair pair;
            pair.word = id;
            pair.sub = subId;
            pair.position = static_cast<uint8_t>(pos);
            interior_.push_back(pair);
        }
    }
    interiorStats_.buildMillis = millisSince(interiorStart);
    interiorStats_.entries = interior_.size();
    interiorStats_.bytes = vectorBytes(interior_);
    interiorStats_.peakBytes = interiorStats_.bytes;

    // --- additive extensions: the transpose of drop-terminal. A stem that
    // occurs twice in one word (TES in TESTES) yields two entries, because
    // the two splits are two different affix questions.
    const auto extensionStart = std::chrono::steady_clock::now();
    extensionOffsets_.assign(static_cast<size_t>(words) + 1, 0u);
    for (const DropTerminalPair& pair : terminal_) ++extensionOffsets_[pair.sub + 1];
    for (uint32_t id = 0; id < words; ++id) {
        if (extensionOffsets_[id + 1] != 0) ++stemsWithExtensions_;
        extensionOffsets_[id + 1] += extensionOffsets_[id];
    }
    extensions_.resize(terminal_.size());
    {
        std::vector<uint32_t> cursor(extensionOffsets_.begin(), extensionOffsets_.end() - 1);
        // terminal_ is in ascending word order, so each stem's extensions come
        // out ascending too, which is what the header promises.
        for (const DropTerminalPair& pair : terminal_) {
            AdditiveExtension& ext = extensions_[cursor[pair.sub]++];
            ext.word = pair.word;
            ext.prefixLen = pair.trimFront;
            ext.suffixLen = pair.trimBack;
        }
        extensionStats_.peakBytes = vectorBytes(cursor);
    }
    extensionStats_.buildMillis = millisSince(extensionStart);
    extensionStats_.entries = extensions_.size();
    extensionStats_.bytes = vectorBytes(extensions_) + vectorBytes(extensionOffsets_);
    extensionStats_.peakBytes += extensionStats_.bytes;
    return true;
}

const AdditiveExtension* SubwordIndex::extensionsForStem(uint32_t stemId, uint32_t* outCount) const {
    if (extensionOffsets_.empty() || stemId + 1 >= extensionOffsets_.size()) {
        *outCount = 0;
        return nullptr;
    }
    *outCount = extensionOffsets_[stemId + 1] - extensionOffsets_[stemId];
    return extensions_.data() + extensionOffsets_[stemId];
}

// ---------------------------------------------------------------------------
// Substring-stem families
// ---------------------------------------------------------------------------
//
// Measured on CSW21 (279,496 words, 2,544,761 letters), Release, minFamilySize
// 3, on an M-series Mac:
//
//   stems 4..7   5.19M entries  39.6 MB sort buffer  20.8 MB retained  307 ms
//   stems 2..7   9.44M entries  72.0 MB sort buffer  37.0 MB retained  533 ms
//
// Each (stem, word) entry is one packed uint64 during the sort, and that
// buffer is the peak; what survives is the grouped CSR. Unbounded (stems
// 1..15) is 13.76M entries / 105 MB before grouping and is deliberately not
// offered: the bound is the point of this index. Cost is close to linear in
// the entry count, so maxStemLen is the cheap knob and minFamilySize is the
// expensive one -- dropping it to 1 keeps the whole long tail of
// once-occurring stems and roughly quadruples what is retained.

namespace {

// key = length (3 bits) then base-26 letter code (33 bits), so sorting by key
// gives stems ordered by length and then alphabetically.
inline uint64_t stemKey(const char* text, uint8_t len) {
    uint64_t code = 0;
    for (uint8_t i = 0; i < len; ++i) code = code * 26u + static_cast<uint64_t>(text[i] - 'A');
    return (static_cast<uint64_t>(len - 1) << 33) | code;
}

}  // namespace

std::string StemFamilyIndex::stem(size_t family) const {
    const uint64_t key = stems_[family];
    const uint8_t len = static_cast<uint8_t>((key >> 33) + 1);
    uint64_t code = key & ((1ull << 33) - 1);
    std::string out(len, 'A');
    for (uint8_t i = len; i > 0; --i) {
        out[i - 1] = static_cast<char>('A' + code % 26u);
        code /= 26u;
    }
    return out;
}

const uint32_t* StemFamilyIndex::members(size_t family, uint32_t* outCount) const {
    *outCount = offsets_[family + 1] - offsets_[family];
    return members_.data() + offsets_[family];
}

size_t StemFamilyIndex::findFamily(const char* text, uint8_t len) const {
    if (len < options_.minStemLen || len > options_.maxStemLen) return familyCount();
    const uint64_t key = stemKey(text, len);
    const auto it = std::lower_bound(stems_.begin(), stems_.end(), key);
    if (it == stems_.end() || *it != key) return familyCount();
    return static_cast<size_t>(it - stems_.begin());
}

bool StemFamilyIndex::build(const Dawg& dawg, const FamilyOptions& options, std::string* error) {
    const auto setError = [error](const char* message) {
        if (error != nullptr) *error = message;
        return false;
    };
    if (!dawg.isLoaded()) return setError("dictionary is not loaded");
    if (options.minStemLen < 1 || options.minStemLen > options.maxStemLen) {
        return setError("minStemLen must be >= 1 and <= maxStemLen");
    }
    if (options.maxStemLen > kMaxStemLen) return setError("maxStemLen is above kMaxStemLen (7)");
    if (options.minFamilySize < 1) return setError("minFamilySize must be >= 1");
    if (dawg.wordCount() >= kMaxPackedWords) {
        return setError("dictionary has too many words for the 20-bit packed word ID");
    }

    const auto start = std::chrono::steady_clock::now();
    stems_.clear();
    offsets_.clear();
    members_.clear();
    options_ = options;

    const uint32_t words = dawg.wordCount();
    char buf[kWordBuf];

    // Counted first so the entry vector is allocated once: it is the peak.
    size_t total = 0;
    for (uint32_t id = 0; id < words; ++id) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        if (len < options.minMemberLen) continue;
        for (uint8_t stemLen = options.minStemLen; stemLen <= options.maxStemLen; ++stemLen) {
            if (len < stemLen) break;
            total += len - stemLen + 1;
        }
    }

    std::vector<uint64_t> entries;
    entries.reserve(total);
    for (uint32_t id = 0; id < words; ++id) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        if (len < options.minMemberLen) continue;
        for (uint8_t stemLen = options.minStemLen; stemLen <= options.maxStemLen; ++stemLen) {
            if (len < stemLen) break;
            for (size_t begin = 0; begin + stemLen <= len; ++begin) {
                entries.push_back((stemKey(buf + begin, stemLen) << 20) | id);
            }
        }
    }
    const size_t peak = vectorBytes(entries);

    std::sort(entries.begin(), entries.end());
    // A stem occurring twice in one word (ANA in BANANA) packs identically
    // both times, so duplicates are adjacent and dropped here.
    entries.erase(std::unique(entries.begin(), entries.end()), entries.end());

    offsets_.push_back(0);
    size_t i = 0;
    while (i < entries.size()) {
        const uint64_t key = entries[i] >> 20;
        size_t j = i + 1;
        while (j < entries.size() && (entries[j] >> 20) == key) ++j;
        if (j - i >= options.minFamilySize) {
            for (size_t k = i; k < j; ++k) {
                members_.push_back(static_cast<uint32_t>(entries[k] & (kMaxPackedWords - 1)));
            }
            stems_.push_back(key);
            offsets_.push_back(static_cast<uint32_t>(members_.size()));
        }
        i = j;
    }
    stems_.shrink_to_fit();
    members_.shrink_to_fit();
    offsets_.shrink_to_fit();

    stats_.buildMillis = millisSince(start);
    stats_.entries = stems_.size();
    stats_.bytes = vectorBytes(stems_) + vectorBytes(offsets_) + vectorBytes(members_);
    stats_.peakBytes = stats_.bytes + peak;
    return true;
}

// ---------------------------------------------------------------------------
// Mined affix alphabet (7.3)
// ---------------------------------------------------------------------------
//
// Counting is over DISTINCT STEMS rather than raw occurrences, because
// productivity is "how many stems does this affix extend", not "how often
// does this letter sequence appear". -S extending 90k stems is a real affix;
// a sequence that shows up many times inside a handful of long words is not.

bool MinedAffixSet::build(const Dawg& dawg, const SubwordIndex& subwords,
                          const MinedAffixOptions& options) {
    back_.clear();
    front_.clear();
    if (!dawg.isLoaded()) return false;

    const auto start = std::chrono::steady_clock::now();

    std::unordered_map<std::string, uint32_t> backCounts, frontCounts;
    std::string word, stem;

    for (uint32_t stemId = 0; stemId < dawg.wordCount(); ++stemId) {
        uint32_t count = 0;
        const AdditiveExtension* extensions = subwords.extensionsForStem(stemId, &count);
        if (count == 0) continue;
        stem = wordString(dawg, stemId);
        if (stem.size() < options.minStemLen) continue;

        for (uint32_t i = 0; i < count; ++i) {
            const AdditiveExtension& ext = extensions[i];
            word = wordString(dawg, ext.word);
            if (ext.back() && ext.suffixLen <= options.maxAffixLen) {
                ++backCounts[word.substr(word.size() - ext.suffixLen)];
            } else if (ext.front() && ext.prefixLen <= options.maxAffixLen) {
                ++frontCounts[word.substr(0, ext.prefixLen)];
            }
        }
    }

    auto rank = [&](std::unordered_map<std::string, uint32_t>& counts, bool front,
                    std::vector<MinedAffix>* out) {
        std::vector<std::pair<std::string, uint32_t>> all(counts.begin(), counts.end());
        std::sort(all.begin(), all.end(), [](const auto& a, const auto& b) {
            if (a.second != b.second) return a.second > b.second;
            return a.first < b.first;  // deterministic ties
        });
        const size_t keep = std::min(all.size(), options.keepPerSide);
        out->reserve(keep);
        for (size_t i = 0; i < keep; ++i) {
            MinedAffix affix;
            affix.len = static_cast<uint8_t>(std::min<size_t>(all[i].first.size(), 11));
            for (uint8_t c = 0; c < affix.len; ++c) affix.letters[c] = all[i].first[c];
            affix.front = front;
            affix.stems = all[i].second;
            out->push_back(affix);
        }
    };
    rank(backCounts, false, &back_);
    rank(frontCounts, true, &front_);

    stats_.entries = back_.size() + front_.size();
    stats_.bytes = stats_.entries * sizeof(MinedAffix);
    stats_.buildMillis =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    return true;
}

bool MinedAffixSet::completes(const Dawg& dawg, uint32_t stemId, const MinedAffix& affix) const {
    const std::string stem = wordString(dawg, stemId);
    const std::string letters(affix.letters, affix.len);
    const std::string form = affix.front ? letters + stem : stem + letters;
    uint32_t id = 0;
    return dawg.findWordId(form.c_str(), form.size(), &id);
}

}  // namespace lex
}  // namespace fluxcore

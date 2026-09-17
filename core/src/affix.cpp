#include "affix.h"

namespace fluxcore {
namespace {

bool isVowel(char c) { return c == 'A' || c == 'E' || c == 'I' || c == 'O' || c == 'U'; }

// Same edge walk the solver uses, carrying the dense word ID down with us.
struct Step {
    uint32_t childState;
    uint32_t wordRank;
    uint32_t childRank;
    bool isWord;
    bool found;
};

Step stepEdge(const Dawg& dawg, uint32_t state, uint32_t rankBase, uint8_t letter) {
    Step step{};
    uint32_t edgeIdx = dawg.state(state).edgeStart;
    for (;;) {
        const DawgEdge& e = dawg.edge(edgeIdx);
        if (e.letter() == letter) {
            step.found = true;
            step.isWord = e.endOfWord();
            step.wordRank = rankBase;
            step.childRank = rankBase + (e.endOfWord() ? 1u : 0u);
            step.childState = e.childState();
            return step;
        }
        rankBase += (e.endOfWord() ? 1u : 0u) + dawg.state(e.childState()).wordCount;
        if (e.endOfList()) return step;
        ++edgeIdx;
    }
}

struct Walker {
    const Dawg* dawg;
    LiveAffix* out;
    size_t maxResults;
    size_t written;
    uint8_t stemLen;
    uint8_t maxAffixLen;
    char letters[16];
};

void walk(Walker& w, uint32_t state, uint32_t rankBase, uint8_t depth) {
    if (w.written >= w.maxResults || depth >= w.maxAffixLen) return;
    if (!w.dawg->hasEdges(state)) return;

    uint32_t edgeIdx = w.dawg->state(state).edgeStart;
    uint32_t rank = rankBase;
    for (;;) {
        const DawgEdge& e = w.dawg->edge(edgeIdx);
        const uint8_t len = static_cast<uint8_t>(depth + 1);
        w.letters[depth] = static_cast<char>('A' + e.letter());

        uint32_t childRank = rank;
        if (e.endOfWord()) {
            if (w.written < w.maxResults) {
                LiveAffix& affix = w.out[w.written++];
                for (uint8_t i = 0; i < len; ++i) affix.letters[i] = w.letters[i];
                affix.len = len;
                affix.wordId = rank;
                affix.wordLen = static_cast<uint8_t>(w.stemLen + len);
            }
            ++childRank;
        }
        walk(w, e.childState(), childRank, len);

        rank = childRank + w.dawg->state(e.childState()).wordCount;
        if (e.endOfList()) return;
        ++edgeIdx;
    }
}

}  // namespace

bool containsStem(const char* word, uint8_t wordLen, const char* stem, uint8_t stemLen,
                  uint8_t* outOffset) {
    if (stemLen == 0 || stemLen > wordLen) return false;
    for (uint8_t start = 0; start + stemLen <= wordLen; ++start) {
        uint8_t i = 0;
        while (i < stemLen && word[start + i] == stem[i]) ++i;
        if (i == stemLen) {
            if (outOffset) *outOffset = start;
            return true;
        }
    }
    return false;
}

AffixClass classifyForm(const char* form, uint8_t formLen, const char* stem, uint8_t stemLen,
                        bool isWord) {
    if (!isWord) return AffixClass::Dead;
    if (containsStem(form, formLen, stem, stemLen, nullptr)) return AffixClass::Additive;
    return AffixClass::Mutating;
}

bool stemIsPrefix(const Dawg& dawg, const char* stem, uint8_t stemLen, uint32_t* outState,
                  uint32_t* outRank) {
    if (!dawg.isLoaded() || stemLen == 0) return false;
    uint32_t state = dawg.rootState();
    uint32_t rank = 0;
    for (uint8_t i = 0; i < stemLen; ++i) {
        const char c = stem[i];
        if (c < 'A' || c > 'Z') return false;
        if (!dawg.hasEdges(state)) return false;
        const Step step = stepEdge(dawg, state, rank, static_cast<uint8_t>(c - 'A'));
        if (!step.found) return false;
        state = step.childState;
        rank = step.childRank;
    }
    if (outState) *outState = state;
    if (outRank) *outRank = rank;
    return true;
}

size_t enumerateLiveAffixes(const Dawg& dawg, const char* stem, uint8_t stemLen, uint8_t maxAffixLen,
                            LiveAffix* out, size_t maxResults) {
    uint32_t state = 0;
    uint32_t rank = 0;
    if (!stemIsPrefix(dawg, stem, stemLen, &state, &rank)) return 0;
    if (maxAffixLen > 16) maxAffixLen = 16;

    Walker walker{};
    walker.dawg = &dawg;
    walker.out = out;
    walker.maxResults = maxResults;
    walker.written = 0;
    walker.stemLen = stemLen;
    walker.maxAffixLen = maxAffixLen;
    walk(walker, state, rank, 0);
    return walker.written;
}

size_t generateMutations(const char* stem, uint8_t stemLen, const char* affix, uint8_t affixLen,
                         MutationCandidate* out, size_t maxResults) {
    if (stemLen == 0 || affixLen == 0 || maxResults == 0) return 0;
    size_t written = 0;

    auto emit = [&](uint8_t keep, char inserted, MutationRule rule) {
        if (written >= maxResults) return;
        MutationCandidate& candidate = out[written];
        uint8_t n = 0;
        for (uint8_t i = 0; i < keep && n < sizeof(candidate.form) - 1; ++i) {
            candidate.form[n++] = stem[i];
        }
        if (inserted != 0 && n < sizeof(candidate.form) - 1) candidate.form[n++] = inserted;
        for (uint8_t i = 0; i < affixLen && n < sizeof(candidate.form) - 1; ++i) {
            candidate.form[n++] = affix[i];
        }
        candidate.len = n;
        candidate.rule = rule;
        ++written;
    };

    const char last = stem[stemLen - 1];

    // PRATE + ING -> PRATING. The E is consumed, so the result does not
    // contain the stem and is misswipe material rather than points.
    if (last == 'E' && isVowel(affix[0])) {
        emit(static_cast<uint8_t>(stemLen - 1), 0, MutationRule::DropFinalE);
    }

    // SANTY + ER -> SANTIER. Only after a consonant, otherwise PLAY + ED
    // becomes PLAIED and PLAYED is unreachable.
    if (last == 'Y' && stemLen >= 2 && !isVowel(stem[stemLen - 2])) {
        emit(static_cast<uint8_t>(stemLen - 1), 'I', MutationRule::YToI);
    }

    // BAT + ING -> BATTING. Kept as a candidate generator only: the doubled
    // form still CONTAINS the stem, so containment will class it additive,
    // which is correct (7.3). W/X/Y never double, else BOX + ING -> BOXXING
    // and BOXING becomes unreachable.
    if (stemLen >= 3 && isVowel(affix[0]) && !isVowel(last) && last != 'W' && last != 'X' &&
        last != 'Y' && isVowel(stem[stemLen - 2]) && !isVowel(stem[stemLen - 3])) {
        emit(stemLen, last, MutationRule::DoubleFinalConsonant);
    }

    return written;
}

}  // namespace fluxcore

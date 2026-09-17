#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace fluxtools {

// What a run has to record to be reproducible (spec 5.3). A run that cannot
// be reproduced from its manifest is a bug, so every input that can change a
// number is in here: the config hash, the dictionary hash (word IDs are only
// meaningful against the dictionary that produced them, per spec 5.1), the
// git SHA with a dirty flag, and the root seed.
struct Manifest {
    std::string tool;
    std::string outputDir;

    std::string configPath;
    uint64_t configHash = 0;
    uint32_t rulesetVersion = 0;
    std::vector<std::string> provisional;

    std::string dictionaryPath;
    uint64_t dictionaryHash = 0;
    uint32_t dictionaryWords = 0;

    std::string gitSha;
    bool gitDirty = true;

    uint64_t rootSeed = 0;
    unsigned threads = 0;
    double wallSeconds = 0;
    std::string startedUtc;

    // (cell name, boards) in the order the cells were run.
    std::vector<std::pair<std::string, uint64_t>> boardsPerCell;

    // Free-form extras a specific tool wants recorded, written as strings.
    std::vector<std::pair<std::string, std::string>> extra;
};

bool writeManifest(const Manifest& manifest, const std::string& path, std::string* error);

// Current UTC time as ISO-8601, for the `startedUtc` field.
std::string utcTimestamp();

}  // namespace fluxtools

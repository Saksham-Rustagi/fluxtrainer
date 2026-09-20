#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "ruleset.h"

// Config loading for the generator. Lives under tools/ because it does file
// I/O and string work; core/ receives a filled-in RulesetConfig and nothing
// else.
//
// Every field is required. A missing or misspelled key is an error rather
// than a default, because a silently defaulted generation parameter would
// change every simulated statistic while the config hash stayed put.

namespace fluxcore {
namespace config {

struct LoadResult {
    RulesetConfig config;


    // The `provisional` list from the file (spec 2.4). Carried as text for
    // the loading tool to print; core does not see it.
    std::vector<std::string> provisional;
};

// FNV-1a over the raw file bytes, stamped into config.configHash.
uint64_t hashConfigBytes(const char* data, size_t size);

// `origin` is used only in error messages.
bool parseRulesetConfig(const char* data, size_t size, const std::string& origin, LoadResult* out,
                        std::string* error);

bool loadRulesetConfig(const std::string& path, LoadResult* out, std::string* error);

// From this ruleset version on, the file carries `generation` and
// `dictionary` blocks; before it, both are forbidden (see parseTop).
constexpr uint32_t kFirstGenerationBlockVersion = 3;

// Hard gate for every tool that loads a DAWG next to a ruleset: a pinned
// ruleset (v3+) refuses any dictionary but its own, because word IDs and
// every stats, family and solution table keyed on them change with it
// (spec 5.1). Unpinned (v1/v2) rulesets pass; the caller should warn.
bool checkDictionary(const RulesetConfig& config, uint64_t sourceHash, uint32_t words,
                     std::string* error);

// checkDictionary for a command-line tool: prints the mismatch as an error
// and returns false, or prints a warning when the ruleset pins nothing.
bool enforceDictionary(const RulesetConfig& config, uint64_t sourceHash, uint32_t words,
                       const char* tool);

}  // namespace config
}  // namespace fluxcore

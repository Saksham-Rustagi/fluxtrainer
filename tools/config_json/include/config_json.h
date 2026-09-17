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

}  // namespace config
}  // namespace fluxcore

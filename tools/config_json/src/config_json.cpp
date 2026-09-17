#include "config_json.h"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace fluxcore {
namespace config {
namespace {

struct ParseError {
    std::string message;
};

[[noreturn]] void fail(const std::string& where, const std::string& what) {
    throw ParseError{where + ": " + what};
}

struct JsonValue {
    enum class Type { Null, Bool, Number, String, Array, Object };

    Type type = Type::Null;
    bool boolean = false;
    double number = 0.0;
    std::string text;
    std::vector<JsonValue> items;
    std::vector<std::pair<std::string, JsonValue>> members;

    const JsonValue* find(const std::string& key) const {
        for (const auto& member : members) {
            if (member.first == key) return &member.second;
        }
        return nullptr;
    }
};

class JsonParser {
public:
    JsonParser(const char* data, size_t size, std::string origin)
        : data_(data), size_(size), origin_(std::move(origin)) {}

    JsonValue parse() {
        skipSpace();
        JsonValue value = parseValue();
        skipSpace();
        if (pos_ != size_) fail(where(), "trailing content after the top-level value");
        return value;
    }

private:
    std::string where() const {
        size_t line = 1;
        for (size_t i = 0; i < pos_ && i < size_; ++i) {
            if (data_[i] == '\n') ++line;
        }
        return origin_ + ":" + std::to_string(line);
    }

    bool atEnd() const { return pos_ >= size_; }
    char peek() const { return data_[pos_]; }

    void skipSpace() {
        while (pos_ < size_) {
            const char c = data_[pos_];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                ++pos_;
            } else {
                break;
            }
        }
    }

    void expect(char c) {
        if (atEnd() || data_[pos_] != c) {
            fail(where(), std::string("expected '") + c + "'");
        }
        ++pos_;
    }

    bool literal(const char* text) {
        const size_t len = std::char_traits<char>::length(text);
        if (pos_ + len > size_) return false;
        for (size_t i = 0; i < len; ++i) {
            if (data_[pos_ + i] != text[i]) return false;
        }
        pos_ += len;
        return true;
    }

    JsonValue parseValue() {
        if (atEnd()) fail(where(), "unexpected end of input");
        switch (peek()) {
            case '{': return parseObject();
            case '[': return parseArray();
            case '"': {
                JsonValue value;
                value.type = JsonValue::Type::String;
                value.text = parseString();
                return value;
            }
            case 't':
            case 'f': {
                JsonValue value;
                value.type = JsonValue::Type::Bool;
                if (literal("true")) {
                    value.boolean = true;
                } else if (literal("false")) {
                    value.boolean = false;
                } else {
                    fail(where(), "malformed literal");
                }
                return value;
            }
            case 'n': {
                if (!literal("null")) fail(where(), "malformed literal");
                return JsonValue{};
            }
            default: return parseNumber();
        }
    }

    JsonValue parseObject() {
        JsonValue value;
        value.type = JsonValue::Type::Object;
        expect('{');
        skipSpace();
        if (!atEnd() && peek() == '}') {
            ++pos_;
            return value;
        }
        for (;;) {
            skipSpace();
            std::string key = parseString();
            skipSpace();
            expect(':');
            skipSpace();
            value.members.emplace_back(std::move(key), parseValue());
            skipSpace();
            if (atEnd()) fail(where(), "unterminated object");
            if (peek() == ',') {
                ++pos_;
                continue;
            }
            expect('}');
            return value;
        }
    }

    JsonValue parseArray() {
        JsonValue value;
        value.type = JsonValue::Type::Array;
        expect('[');
        skipSpace();
        if (!atEnd() && peek() == ']') {
            ++pos_;
            return value;
        }
        for (;;) {
            skipSpace();
            value.items.push_back(parseValue());
            skipSpace();
            if (atEnd()) fail(where(), "unterminated array");
            if (peek() == ',') {
                ++pos_;
                continue;
            }
            expect(']');
            return value;
        }
    }

    std::string parseString() {
        expect('"');
        std::string out;
        while (!atEnd()) {
            const char c = data_[pos_++];
            if (c == '"') return out;
            if (c != '\\') {
                out.push_back(c);
                continue;
            }
            if (atEnd()) break;
            const char esc = data_[pos_++];
            switch (esc) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                // \u is not supported: config keys and values are ASCII, and
                // accepting a form we do not decode would be worse.
                default: fail(where(), "unsupported string escape");
            }
        }
        fail(where(), "unterminated string");
    }

    JsonValue parseNumber() {
        const size_t start = pos_;
        if (!atEnd() && (peek() == '-' || peek() == '+')) ++pos_;
        bool digits = false;
        while (!atEnd()) {
            const char c = data_[pos_];
            if ((c >= '0' && c <= '9')) {
                digits = true;
                ++pos_;
            } else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                ++pos_;
            } else {
                break;
            }
        }
        if (!digits) fail(where(), "expected a value");

        const std::string text(data_ + start, pos_ - start);
        char* end = nullptr;
        const double parsed = std::strtod(text.c_str(), &end);
        if (end == nullptr || *end != '\0') fail(where(), "malformed number '" + text + "'");

        JsonValue value;
        value.type = JsonValue::Type::Number;
        value.number = parsed;
        return value;
    }

    const char* data_;
    size_t size_;
    std::string origin_;
    size_t pos_ = 0;
};

const JsonValue& requireMember(const JsonValue& object, const std::string& key,
                               const std::string& path) {
    const JsonValue* found = object.find(key);
    if (found == nullptr) fail(path + "." + key, "required field is missing");
    return *found;
}

const JsonValue& requireObject(const JsonValue& value, const std::string& path) {
    if (value.type != JsonValue::Type::Object) fail(path, "expected an object");
    return value;
}

const JsonValue& requireArray(const JsonValue& value, const std::string& path) {
    if (value.type != JsonValue::Type::Array) fail(path, "expected an array");
    return value;
}

bool requireBool(const JsonValue& value, const std::string& path) {
    if (value.type != JsonValue::Type::Bool) fail(path, "expected true or false");
    return value.boolean;
}

const std::string& requireString(const JsonValue& value, const std::string& path) {
    if (value.type != JsonValue::Type::String) fail(path, "expected a string");
    return value.text;
}

uint64_t requireUInt(const JsonValue& value, const std::string& path, uint64_t low, uint64_t high) {
    if (value.type != JsonValue::Type::Number) fail(path, "expected a number");
    const double n = value.number;
    if (n < 0.0 || std::floor(n) != n) fail(path, "expected a non-negative whole number");
    const uint64_t parsed = static_cast<uint64_t>(n);
    if (parsed < low || parsed > high) {
        fail(path, "must be between " + std::to_string(low) + " and " + std::to_string(high));
    }
    return parsed;
}

// An unknown key is nearly always a typo, and a typo that parses is a
// silently defaulted parameter. Keys starting with '_' are comments.
void requireKnownKeys(const JsonValue& object, const std::string& path,
                      const std::vector<std::string>& known) {
    for (const auto& member : object.members) {
        if (!member.first.empty() && member.first[0] == '_') continue;
        bool recognized = false;
        for (const std::string& key : known) {
            if (member.first == key) {
                recognized = true;
                break;
            }
        }
        if (!recognized) fail(path + "." + member.first, "unknown field");
    }
}

void parseLetterWeights(const JsonValue& value, const std::string& path, RulesetConfig* config) {
    requireObject(value, path);
    std::vector<std::string> known;
    for (char c = 'A'; c <= 'Z'; ++c) known.push_back(std::string(1, c));
    requireKnownKeys(value, path, known);

    uint64_t total = 0;
    for (uint8_t i = 0; i < 26; ++i) {
        const std::string key(1, static_cast<char>('A' + i));
        const uint64_t weight = requireUInt(requireMember(value, key, path), path + "." + key, 0,
                                            0xFFFFFFFFull);
        config->letterWeights[i] = static_cast<uint32_t>(weight);
        total += weight;
    }
    if (total == 0) fail(path, "letter weights must not all be zero");
    if (total > 0xFFFFFFFFull) fail(path, "letter weights sum to more than 2^32");
}

void parseScoreTable(const JsonValue& value, const std::string& path, uint8_t minWordLen,
                     RulesetConfig* config) {
    requireObject(value, path);

    std::vector<std::string> known;
    for (uint8_t len = minWordLen; len <= kMaxCells; ++len) known.push_back(std::to_string(len));
    requireKnownKeys(value, path, known);

    for (uint8_t len = minWordLen; len <= kMaxCells; ++len) {
        const std::string key = std::to_string(len);
        config->scores.pointsByLength[len] = static_cast<uint32_t>(
            requireUInt(requireMember(value, key, path), path + "." + key, 0, 0xFFFFFFFFull));
    }
}

void parseTier(const JsonValue& value, const std::string& path, Tier tier, GridConfig* grid) {
    requireObject(value, path);
    requireKnownKeys(value, path, {"share", "minCandidates", "maxCandidates"});

    const uint8_t index = static_cast<uint8_t>(tier);
    grid->tierShare[index] = static_cast<uint32_t>(
        requireUInt(requireMember(value, "share", path), path + ".share", 0, 1000000));
    grid->candidates[index].minN = static_cast<uint32_t>(requireUInt(
        requireMember(value, "minCandidates", path), path + ".minCandidates", 1, 1000000));
    grid->candidates[index].maxN = static_cast<uint32_t>(requireUInt(
        requireMember(value, "maxCandidates", path), path + ".maxCandidates", 1, 1000000));
    if (grid->candidates[index].maxN < grid->candidates[index].minN) {
        fail(path, "maxCandidates is below minCandidates");
    }
}

void parseGrid(const JsonValue& value, const std::string& path, GridConfig* grid) {
    requireObject(value, path);
    requireKnownKeys(value, path, {"side", "share", "tiers", "seedLengths"});

    grid->side = static_cast<uint8_t>(
        requireUInt(requireMember(value, "side", path), path + ".side", 2, kMaxSide));
    grid->share = static_cast<uint32_t>(
        requireUInt(requireMember(value, "share", path), path + ".share", 0, 1000000));

    const JsonValue& tiers = requireObject(requireMember(value, "tiers", path), path + ".tiers");
    requireKnownKeys(tiers, path + ".tiers", {"spam", "goodCasual", "casual"});
    parseTier(requireMember(tiers, "spam", path + ".tiers"), path + ".tiers.spam", Tier::Spam, grid);
    parseTier(requireMember(tiers, "goodCasual", path + ".tiers"), path + ".tiers.goodCasual",
              Tier::GoodCasual, grid);
    parseTier(requireMember(tiers, "casual", path + ".tiers"), path + ".tiers.casual", Tier::Casual,
              grid);
    if (grid->tierShareTotal() == 0) fail(path + ".tiers", "tier shares must not all be zero");

    const JsonValue& lengths =
        requireArray(requireMember(value, "seedLengths", path), path + ".seedLengths");
    if (lengths.items.empty()) fail(path + ".seedLengths", "must list at least one seed length");
    if (lengths.items.size() > kMaxSeedLengths) {
        fail(path + ".seedLengths",
             "at most " + std::to_string(kMaxSeedLengths) + " seed lengths are supported");
    }

    const uint64_t cells = static_cast<uint64_t>(grid->side) * grid->side;
    bool anyGeneral = false;
    for (size_t i = 0; i < lengths.items.size(); ++i) {
        const std::string itemPath = path + ".seedLengths[" + std::to_string(i) + "]";
        const JsonValue& item = requireObject(lengths.items[i], itemPath);
        requireKnownKeys(item, itemPath, {"length", "weight", "spamOnly"});

        SeedLengthOption& option = grid->seedLengths[i];
        option.length = static_cast<uint8_t>(
            requireUInt(requireMember(item, "length", itemPath), itemPath + ".length", 1, cells));
        option.weight = static_cast<uint32_t>(requireUInt(
            requireMember(item, "weight", itemPath), itemPath + ".weight", 1, 1000000));
        option.spamOnly = requireBool(requireMember(item, "spamOnly", itemPath),
                                      itemPath + ".spamOnly");
        if (!option.spamOnly) anyGeneral = true;
    }
    grid->seedLengthCount = static_cast<uint8_t>(lengths.items.size());
    if (!anyGeneral) {
        fail(path + ".seedLengths",
             "every seed length is spamOnly, so no Casual or Good Casual board could ever carry a seed");
    }
}

void parseTop(const JsonValue& root, const std::string& origin, LoadResult* out) {
    requireObject(root, origin);
    requireKnownKeys(root, origin,
                     {"version", "provisional", "letterWeights", "scoreTable", "solver", "seeding",
                      "cheapScoring", "grids"});

    RulesetConfig& config = out->config;
    config.version = static_cast<uint32_t>(
        requireUInt(requireMember(root, "version", origin), origin + ".version", 1, 0xFFFFFFFFull));

    const JsonValue& provisional =
        requireArray(requireMember(root, "provisional", origin), origin + ".provisional");
    for (size_t i = 0; i < provisional.items.size(); ++i) {
        out->provisional.push_back(requireString(
            provisional.items[i], origin + ".provisional[" + std::to_string(i) + "]"));
    }

    const JsonValue& solver =
        requireObject(requireMember(root, "solver", origin), origin + ".solver");
    requireKnownKeys(solver, origin + ".solver", {"maxPathsPerWord", "minWordLen"});
    config.solver.maxPathsPerWord = static_cast<uint32_t>(
        requireUInt(requireMember(solver, "maxPathsPerWord", origin + ".solver"),
                    origin + ".solver.maxPathsPerWord", 1, 0xFFFFFFFFull));
    config.solver.minWordLen = static_cast<uint8_t>(
        requireUInt(requireMember(solver, "minWordLen", origin + ".solver"),
                    origin + ".solver.minWordLen", 1, kMaxCells));

    parseLetterWeights(requireMember(root, "letterWeights", origin), origin + ".letterWeights",
                       &config);
    parseScoreTable(requireMember(root, "scoreTable", origin), origin + ".scoreTable",
                    config.solver.minWordLen, &config);

    const JsonValue& seeding =
        requireObject(requireMember(root, "seeding", origin), origin + ".seeding");
    requireKnownKeys(seeding, origin + ".seeding",
                     {"probabilityPerMille", "extraSeedCount", "allowSeedOverlap", "pathAttempts",
                      "placementAttempts"});
    config.seedProbabilityPerMille = static_cast<uint32_t>(
        requireUInt(requireMember(seeding, "probabilityPerMille", origin + ".seeding"),
                    origin + ".seeding.probabilityPerMille", 0, 1000));
    config.extraSeedCount = static_cast<uint32_t>(
        requireUInt(requireMember(seeding, "extraSeedCount", origin + ".seeding"),
                    origin + ".seeding.extraSeedCount", 0, 8));
    config.allowSeedOverlap = requireBool(
        requireMember(seeding, "allowSeedOverlap", origin + ".seeding"),
        origin + ".seeding.allowSeedOverlap");
    config.seedPathAttempts = static_cast<uint32_t>(
        requireUInt(requireMember(seeding, "pathAttempts", origin + ".seeding"),
                    origin + ".seeding.pathAttempts", 1, 100000));
    config.seedPlacementAttempts = static_cast<uint32_t>(
        requireUInt(requireMember(seeding, "placementAttempts", origin + ".seeding"),
                    origin + ".seeding.placementAttempts", 1, 100000));
    if (config.extraSeedCount > 0 && !config.allowSeedOverlap) {
        fail(origin + ".seeding",
             "extraSeedCount > 0 without allowSeedOverlap: extra seeds would only ever land on "
             "untouched cells");
    }

    const JsonValue& cheap =
        requireObject(requireMember(root, "cheapScoring", origin), origin + ".cheapScoring");
    requireKnownKeys(cheap, origin + ".cheapScoring", {"enabled", "minStartCells", "marginPerMille"});
    config.cheapScoringEnabled =
        requireBool(requireMember(cheap, "enabled", origin + ".cheapScoring"),
                    origin + ".cheapScoring.enabled");
    config.cheapScoringMinStartCells = static_cast<uint32_t>(
        requireUInt(requireMember(cheap, "minStartCells", origin + ".cheapScoring"),
                    origin + ".cheapScoring.minStartCells", 1, kMaxCells));
    config.cheapScoringMarginPerMille = static_cast<uint32_t>(
        requireUInt(requireMember(cheap, "marginPerMille", origin + ".cheapScoring"),
                    origin + ".cheapScoring.marginPerMille", 1000, 1000000));

    const JsonValue& grids = requireArray(requireMember(root, "grids", origin), origin + ".grids");
    if (grids.items.empty()) fail(origin + ".grids", "must list at least one grid");
    if (grids.items.size() > kMaxGrids) {
        fail(origin + ".grids", "at most " + std::to_string(kMaxGrids) + " grids are supported");
    }
    for (size_t i = 0; i < grids.items.size(); ++i) {
        parseGrid(grids.items[i], origin + ".grids[" + std::to_string(i) + "]",
                  &config.grids[i]);
    }
    config.gridCount = static_cast<uint8_t>(grids.items.size());
    for (uint8_t i = 0; i < config.gridCount; ++i) {
        for (uint8_t j = static_cast<uint8_t>(i + 1); j < config.gridCount; ++j) {
            if (config.grids[i].side == config.grids[j].side) {
                fail(origin + ".grids", "two grids declare the same side");
            }
        }
    }
    if (config.gridShareTotal() == 0) fail(origin + ".grids", "grid shares must not all be zero");
}

}  // namespace

uint64_t hashConfigBytes(const char* data, size_t size) {
    uint64_t h = 1469598103934665603ull;  // FNV-1a 64-bit offset basis
    constexpr uint64_t prime = 1099511628211ull;
    for (size_t i = 0; i < size; ++i) {
        h ^= static_cast<unsigned char>(data[i]);
        h *= prime;
    }
    return h;
}

bool parseRulesetConfig(const char* data, size_t size, const std::string& origin, LoadResult* out,
                        std::string* error) {
    *out = LoadResult{};
    try {
        JsonParser parser(data, size, origin);
        const JsonValue root = parser.parse();
        parseTop(root, origin, out);
    } catch (const ParseError& e) {
        if (error != nullptr) *error = e.message;
        *out = LoadResult{};
        return false;
    }
    out->config.configHash = hashConfigBytes(data, size);
    return true;
}

bool loadRulesetConfig(const std::string& path, LoadResult* out, std::string* error) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        if (error != nullptr) *error = path + ": cannot open config file";
        return false;
    }
    std::ostringstream buffer;
    buffer << in.rdbuf();
    const std::string bytes = buffer.str();
    if (bytes.empty()) {
        if (error != nullptr) *error = path + ": config file is empty";
        return false;
    }
    return parseRulesetConfig(bytes.data(), bytes.size(), path, out, error);
}

}  // namespace config
}  // namespace fluxcore

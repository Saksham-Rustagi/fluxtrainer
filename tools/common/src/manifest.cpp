#include "manifest.h"

#include <cstdio>
#include <ctime>
#include <fstream>

namespace fluxtools {
namespace {

std::string escape(const std::string& in) {
    std::string out;
    out.reserve(in.size() + 8);
    for (char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\t': out += "\\t"; break;
            default: out.push_back(c);
        }
    }
    return out;
}

std::string hex64(uint64_t value) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "0x%016llx", static_cast<unsigned long long>(value));
    return buf;
}

}  // namespace

std::string utcTimestamp() {
    const std::time_t now = std::time(nullptr);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &now);
#else
    gmtime_r(&now, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return buf;
}

bool writeManifest(const Manifest& manifest, const std::string& path, std::string* error) {
    std::ofstream out(path);
    if (!out) {
        if (error) *error = "cannot write manifest: " + path;
        return false;
    }

    out << "{\n";
    out << "  \"tool\": \"" << escape(manifest.tool) << "\",\n";
    out << "  \"startedUtc\": \"" << escape(manifest.startedUtc) << "\",\n";
    out << "  \"wallSeconds\": " << manifest.wallSeconds << ",\n";
    out << "  \"threads\": " << manifest.threads << ",\n";
    out << "  \"rootSeed\": " << manifest.rootSeed << ",\n";
    out << "  \"outputDir\": \"" << escape(manifest.outputDir) << "\",\n";

    out << "  \"config\": {\n";
    out << "    \"path\": \"" << escape(manifest.configPath) << "\",\n";
    out << "    \"hash\": \"" << hex64(manifest.configHash) << "\",\n";
    out << "    \"rulesetVersion\": " << manifest.rulesetVersion << ",\n";
    out << "    \"provisional\": [";
    for (size_t i = 0; i < manifest.provisional.size(); ++i) {
        out << (i ? ", " : "") << "\"" << escape(manifest.provisional[i]) << "\"";
    }
    out << "]\n  },\n";

    out << "  \"dictionary\": {\n";
    out << "    \"path\": \"" << escape(manifest.dictionaryPath) << "\",\n";
    out << "    \"hash\": \"" << hex64(manifest.dictionaryHash) << "\",\n";
    out << "    \"words\": " << manifest.dictionaryWords << "\n  },\n";

    out << "  \"build\": {\n";
    out << "    \"gitSha\": \"" << escape(manifest.gitSha) << "\",\n";
    out << "    \"gitDirty\": " << (manifest.gitDirty ? "true" : "false") << "\n  },\n";

    out << "  \"boardsPerCell\": {\n";
    for (size_t i = 0; i < manifest.boardsPerCell.size(); ++i) {
        out << "    \"" << escape(manifest.boardsPerCell[i].first)
            << "\": " << manifest.boardsPerCell[i].second
            << (i + 1 < manifest.boardsPerCell.size() ? ",\n" : "\n");
    }
    out << "  }";

    if (!manifest.extra.empty()) {
        out << ",\n  \"extra\": {\n";
        for (size_t i = 0; i < manifest.extra.size(); ++i) {
            out << "    \"" << escape(manifest.extra[i].first) << "\": \""
                << escape(manifest.extra[i].second) << "\""
                << (i + 1 < manifest.extra.size() ? ",\n" : "\n");
        }
        out << "  }";
    }
    out << "\n}\n";

    return out.good();
}

}  // namespace fluxtools

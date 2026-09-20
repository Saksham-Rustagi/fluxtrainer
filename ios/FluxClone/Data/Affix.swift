import Foundation

/// Classifies an invalid attempt by the affix pattern it most plausibly over-applied
/// (SPEC 3.6, 8.4): the attempt is STEM + SUFFIX (or PREFIX + STEM) where STEM is a real
/// word. Longest affix wins. Stems are also tried with a dropped E restored (BAKING ->
/// BAKE) and a Y restored from I (HAPPIER -> HAPPY), since those are the forms players
/// over-apply.
enum AffixClassifier {
    static let suffixes = [
        "NESSES", "INGS", "IEST", "IERS", "NESS", "LESS", "MENT", "ABLE", "IER", "IES", "ING",
        "ERS", "EST", "ISH", "FUL", "OUS", "IVE", "ITY", "IZE", "ISE", "ED", "ER", "EN", "ES",
        "LY", "AL", "Y", "S",
    ]
    static let prefixes = ["OVER", "UNDER", "OUT", "PRE", "DIS", "MIS", "NON", "RE", "UN", "DE", "IN"]

    struct Result {
        let affix: String  // "-IER", "RE-"
        let stem: String
    }

    static func classify(_ word: String, isWord: (String) -> Bool) -> Result? {
        // `suffixes` is ordered longest first, so the first match is the longest.
        for suffix in suffixes where word.count > suffix.count + 1 && word.hasSuffix(suffix) {
            let base = String(word.dropLast(suffix.count))
            var candidates = [base]
            if suffix.first.map({ "AEIOUY".contains($0) }) == true { candidates.append(base + "E") }
            if suffix.hasPrefix("I") { candidates.append(base + "Y") }
            if base.hasSuffix("I") { candidates.append(String(base.dropLast()) + "Y") }
            if base.count >= 2, base.last == base.dropLast().last { candidates.append(String(base.dropLast())) }
            if let stem = candidates.first(where: { $0.count >= 2 && isWord($0) }) {
                return Result(affix: "-" + suffix, stem: stem)
            }
        }
        for prefix in prefixes where word.count > prefix.count + 2 && word.hasPrefix(prefix) {
            let stem = String(word.dropFirst(prefix.count))
            if isWord(stem) { return Result(affix: prefix + "-", stem: stem) }
        }
        return nil
    }
}

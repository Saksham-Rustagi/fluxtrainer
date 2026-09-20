import Foundation

/// Every family on the board, not just the ones the queue happens to rank.
///
/// `FamilyIndex` answers "which of the 1,336 shipped hooks is this word a branch of",
/// which is the right question for ranking -- those are the families Phase 2 priced. It is
/// the wrong question for browsing. A board carries hundreds of families the queue has no
/// opinion about, including the big obvious ones, and "show me everything that was here
/// and what I took of it" has to mean everything.
///
/// So these are read off the board itself, using SPEC 7.3's definition and nothing else: a
/// word W belongs to family S when **S is a contiguous substring of W**. Enumerate every
/// substring of every solved word, keep the ones two or more words share, and that is the
/// board's family structure with no list involved.
struct BoardFamily: Identifiable {
    let stem: String
    let members: [SolvedWord]
    let found: [SolvedWord]
    let missed: [SolvedWord]
    /// What the queue knows about the members it knows, by word. Empty for a family the
    /// shipped record has never priced, which is most of them.
    let branches: [String: Branch]

    var id: String { stem }
    var pointsMissed: Int { missed.reduce(0) { $0 + $1.points } }
    var pointsPresent: Int { members.reduce(0) { $0 + $1.points } }
    /// Points a game the queue expects from the missed members it can price. Zero is not
    /// "worthless" here -- it usually means the queue has never seen these words.
    var gainMissed: Double { missed.reduce(0) { $0 + (branches[$1.word]?.expectedGain ?? 0) } }
    var ranked: Bool { !branches.isEmpty }
    /// Members the field almost never takes: real vocabulary rather than a seeing problem.
    var alphaMissed: [SolvedWord] { missed.filter { branches[$0.word]?.isAlpha == true } }
    /// Narrower stems inside this one whose members are all members of this family:
    /// AMPE- and AMPER- under AMP-. SPEC 12.2's containment chain, folded into the widest
    /// level so the list is families rather than levels of one family.
    var narrower: [String] = []

    var share: Double { members.isEmpty ? 0 : Double(found.count) / Double(members.count) }
    /// Small enough to hunt for (SPEC 7.5's band, on this board).
    var isCue: Bool { BoardFamilies.cueBand.contains(members.count) }
}

enum BoardFamilies {
    /// Shorter than three letters is not a cue, it is a coincidence: two-letter substrings
    /// group half the board together and mean nothing to hunt for.
    static let minStem = 3
    /// A family of one is a word.
    static let minMembers = 2
    /// How many make it to the screen. The count of the rest is shown rather than the rest.
    static let listCap = 80
    /// SPEC 7.5's enumerability band, applied to a family's size on this board. A stem
    /// with 89 members is not a cue -- it is "every word with -ING in it" -- and a stem
    /// with one is a word. Between two and six, "what else hangs off this" is a question
    /// with an answer you can hold in your head while the clock runs.
    static let cueBand = 2...6

    /// Every family with two or more members on this board, best first.
    ///
    /// Sorted by the points left on the table, because that is the question a browse
    /// answers: what was here, and how much of it did I take. Expected gain per game is
    /// the better ranker for *teaching* and it is what the review items above use, but
    /// most families here have never been priced, so ranking by it would sort the whole
    /// list by whether Phase 2 had an opinion.
    static func all(on solved: SolvedBoard, found: Set<String>, index: FamilyIndex?)
        -> [BoardFamily] {
        var members: [String: [Int]] = [:]           // stem -> indices into solved.words
        members.reserveCapacity(solved.count * 6)
        for (i, word) in solved.words.enumerated() {
            let chars = Array(word.word)
            guard chars.count >= minStem else { continue }
            // Every contiguous substring from `minStem` up to the whole word. The whole
            // word is included on purpose: TOR is a member of the TOR- family, and SPEC
            // 7.4's "found the base, missed two extensions" needs the base to be in it.
            for length in minStem...chars.count {
                for start in 0...(chars.count - length) {
                    members[String(chars[start..<(start + length)]), default: []].append(i)
                }
            }
        }

        var out: [BoardFamily] = []
        // Two stems covering exactly the same words are one family described twice --
        // TOR- and TORE- on a board where every TOR word is a TORE word. The longer stem
        // is the more specific description of it and is the one kept.
        var seen: [Set<Int>: String] = [:]
        for (stem, indices) in members where indices.count >= minMembers {
            let key = Set(indices)
            if let other = seen[key] {
                // Longest wins, alphabetical on a tie, so the list does not reshuffle
                // between two runs over the same board.
                if other.count > stem.count || (other.count == stem.count && other < stem) {
                    continue
                }
            }
            seen[key] = stem
        }
        for (key, stem) in seen {
            let words = key.sorted().map { solved.words[$0] }
            var priced: [String: Branch] = [:]
            if let index {
                for word in words {
                    if let branch = index.families(of: word.word)
                        .first(where: { $0.stem == stem })?.branch {
                        priced[word.word] = branch
                    }
                }
            }
            out.append(BoardFamily(
                stem: stem, members: words,
                found: words.filter { found.contains($0.word) },
                missed: words.filter { !found.contains($0.word) },
                branches: priced))
        }
        let ordered = out.sorted {
            $0.pointsMissed != $1.pointsMissed ? $0.pointsMissed > $1.pointsMissed
                : $0.members.count > $1.members.count
        }
        return fold(ordered)
    }

    /// SPEC 12.2: "the breadcrumb shows where the stem sits in the containment chain
    /// (-LLERS under -ERS under -RS)".
    ///
    /// A board produces the whole chain, and listed flat it is four rows saying nearly the
    /// same thing: AMP- with 26 members, then AMPE- with 10, AMBE- with 10 and AMPER- with
    /// 9, all of them inside AMP-, crowding out the other families entirely. One row per
    /// chain, at the widest level, with the narrower stems carried on it -- which keeps
    /// the big obvious families in the list, which is the point of the list.
    ///
    /// The fold is total on a chain, and that is a theorem rather than a heuristic: if S
    /// is a substring of T then every word containing T also contains S, so members(T) is
    /// always a subset of members(S). A narrower level can never reach a word its parent
    /// lacks.
    ///
    /// Two rules that look opposed and are not. Equal member sets keep the **longer**
    /// stem, because that is the more specific name for exactly those words. A strict
    /// subset keeps the **shorter** one, because that is a narrower level of a bigger
    /// family and the list is a list of families.
    ///
    /// The input is sorted by points missed, and a superset always has at least the points
    /// of its subsets, so the widest level is always seen first.
    static func fold(_ families: [BoardFamily]) -> [BoardFamily] {
        var kept: [BoardFamily] = []
        var keptWords: [Set<String>] = []
        for family in families {
            let words = Set(family.members.map(\.word))
            var folded = false
            for i in kept.indices {
                // The cheap test first: only a stem that contains this one, or is
                // contained by it, can be on the same chain.
                guard kept[i].stem.contains(family.stem) || family.stem.contains(kept[i].stem)
                else { continue }
                if words.isSubset(of: keptWords[i]) {
                    kept[i].narrower.append(family.stem)
                    folded = true
                    break
                }
            }
            if !folded {
                kept.append(family)
                keptWords.append(words)
            }
        }
        return kept
    }
}

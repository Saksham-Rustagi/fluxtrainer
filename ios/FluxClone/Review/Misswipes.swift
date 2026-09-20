import Foundation

/// The four causes of an invalid swipe, and the reason only two of them teach anything.
///
/// This is `tools/queue/misswipe.py` reimplemented on the device, against the same
/// precedence and the same definitions, so a string classified here and the same string
/// classified in the Phase 2 report land in the same bucket. It runs on the board the
/// attempt was made on, which is the only place the two motor causes can be told apart
/// from the two vocabulary ones: both of those are questions about paths.
///
/// SPEC 16.6 and Phase 2's brief both warn that some invalid attempts are how the player
/// searches -- tracing a path to see what connects. Nothing here is scored or fed back as
/// pressure to swipe less. The two motor causes are shown as diagnostics and produce no
/// study items, which is the whole point of separating them.
enum MisswipeCause: String {
    /// A real stem plus an affix that does not take: HOLERS, NILER, CUER. Vocabulary, and
    /// exactly what the dead half of the affix grid is for.
    case affixError
    /// The attempt is a proper prefix of a word that was still reachable from the last
    /// cell entered. Motor: he lifted early. Diagnostic only.
    case earlyLift
    /// A valid word sits one substitution, transposition or interior insertion away, on a
    /// path that exists on this board. Motor: he took the wrong tile. Diagnostic only.
    case pathError
    /// Nothing valid nearby. He believed it was a word. The most valuable kind here.
    case trueNonWord

    var isLearnable: Bool { self == .affixError || self == .trueNonWord }

    var label: String {
        switch self {
        case .affixError: return "affix that does not take"
        case .earlyLift: return "lifted early"
        case .pathError: return "wrong tile"
        case .trueNonWord: return "not a word"
        }
    }
}

struct MisswipeFinding: Identifiable {
    let word: String
    let cause: MisswipeCause
    /// Across every game ever logged, including this one. A first-time miss is noise; the
    /// fourth time he swipes RALL it is a fact about him.
    let lifetimeCount: Int
    let secondsThisBoard: Double
    /// For an affix error: the stem and the affix over-applied. For an early lift: the
    /// word he was one or two cells short of. For a path error: the word one edit away.
    let stem: String?
    let affix: String?
    let nearest: [String]
    var id: String { word }

    var sentence: String {
        switch cause {
        case .affixError:
            let s = stem ?? ""
            return "\(s) does not take \(affix ?? "that")."
                + (nearest.isEmpty ? "" : " \(nearest.prefix(2).joined(separator: ", ")) do.")
        case .earlyLift:
            return nearest.isEmpty ? "One cell short." : "One cell short of \(nearest[0])."
        case .pathError:
            return nearest.isEmpty ? "A tile out." : "\(nearest[0]) was the path."
        case .trueNonWord:
            return "Nothing close. This one is a belief, not a slip."
        }
    }
}

enum MisswipeClassifier {
    static let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    /// The shortest attempt worth classifying. Below this, "not a word" is almost always
    /// a two-cell brush rather than an attempt.
    static let minLength = 3
    /// How many extra cells count as an early lift. Three or more is a different word, not
    /// a lift, and calling it one would flatter the motor bucket.
    static let liftReach = 2

    /// Precedence is affixError > earlyLift > pathError > trueNonWord, and the ordering is
    /// load-bearing. Appending the missing last letter is itself an insertion, so a
    /// generic edit-one test run first would swallow every early lift into pathError.
    static func classify(attempt: InvalidAttempt, letters: [Character], side: Int,
                         isWord: (String) -> Bool) -> MisswipeFinding? {
        guard attempt.word.count >= minLength else { return nil }
        let geometry = BoardWalk(letters: letters, side: side)

        if let affix = AffixClassifier.classify(attempt.word, isWord: isWord) {
            let alternatives = liveAffixes(stem: affix.stem, isWord: isWord)
            return MisswipeFinding(word: attempt.word, cause: .affixError, lifetimeCount: 0,
                                   secondsThisBoard: attempt.seconds, stem: affix.stem,
                                   affix: affix.affix, nearest: alternatives)
        }
        let lifts = geometry.continuations(of: attempt.word, from: attempt.cells,
                                           upTo: liftReach, isWord: isWord)
        if !lifts.isEmpty {
            return MisswipeFinding(word: attempt.word, cause: .earlyLift, lifetimeCount: 0,
                                   secondsThisBoard: attempt.seconds, stem: nil, affix: nil,
                                   nearest: Array(lifts.prefix(4)))
        }
        let nearby = editOne(attempt.word).filter { isWord($0) && geometry.hasPath($0) }
        if !nearby.isEmpty {
            return MisswipeFinding(word: attempt.word, cause: .pathError, lifetimeCount: 0,
                                   secondsThisBoard: attempt.seconds, stem: nil, affix: nil,
                                   nearest: Array(nearby.sorted().prefix(4)))
        }
        return MisswipeFinding(word: attempt.word, cause: .trueNonWord, lifetimeCount: 0,
                               secondsThisBoard: attempt.seconds, stem: nil, affix: nil,
                               nearest: [])
    }

    /// Which affixes the stem *does* take, from the same curated list the over-application
    /// was detected against. "HOLE takes -S and -D" is the correction; "HOLERS is not a
    /// word" is not, because it does not say what to do instead.
    static func liveAffixes(stem: String, isWord: (String) -> Bool) -> [String] {
        AffixClassifier.suffixes.filter { isWord(stem + $0) }.map { stem + $0 }
    }

    /// Substitutions, adjacent transpositions and *interior* insertions. A terminal append
    /// is the early-lift case and is excluded here by construction.
    static func editOne(_ s: String) -> Set<String> {
        var out = Set<String>()
        let chars = Array(s)
        for i in chars.indices {
            for c in alphabet where c != chars[i] {
                var copy = chars
                copy[i] = c
                out.insert(String(copy))
            }
        }
        for i in 0..<max(0, chars.count - 1) where chars[i] != chars[i + 1] {
            var copy = chars
            copy.swapAt(i, i + 1)
            out.insert(String(copy))
        }
        for i in chars.indices {          // 0..<count: insertions before each cell, never after
            for c in alphabet {
                var copy = chars
                copy.insert(c, at: i)
                out.insert(String(copy))
            }
        }
        out.remove(s)
        return out
    }

    /// Lifetime repeat counts for a set of strings, from the whole attempt log. This is
    /// what makes a misswipe worth showing: one RALL is a slip, five is a habit.
    static func lifetimeCounts(_ words: [String]) -> [String: Int] {
        guard !words.isEmpty else { return [:] }
        let list = words.map { "'" + $0.replacingOccurrences(of: "'", with: "''") + "'" }
            .joined(separator: ",")
        var out: [String: Int] = [:]
        Database.shared.query("""
            SELECT letters, COUNT(*) FROM attempt
            WHERE result = 'invalid' AND reason = 'not_word' AND letters IN (\(list))
            GROUP BY letters
            """) { out[$0.text(0)] = $0.int(1) }
        return out
    }
}

/// Path questions on one board. The solver answers them for dictionary words; these are
/// about strings that are not words, which is why this exists separately.
struct BoardWalk {
    let letters: [Character]
    let side: Int

    func neighbours(_ cell: Int) -> [Int] {
        let row = cell / side, col = cell % side
        var out: [Int] = []
        out.reserveCapacity(8)
        for dr in -1...1 {
            for dc in -1...1 where !(dr == 0 && dc == 0) {
                let r = row + dr, c = col + dc
                if r >= 0, r < side, c >= 0, c < side { out.append(r * side + c) }
            }
        }
        return out
    }

    /// Is there any legal path for `word` on this board?
    func hasPath(_ word: String) -> Bool {
        let target = Array(word)
        guard !target.isEmpty, target.count <= letters.count else { return false }
        var used = [Bool](repeating: false, count: letters.count)
        func walk(_ cell: Int, _ depth: Int) -> Bool {
            if depth == target.count - 1 { return true }
            used[cell] = true
            defer { used[cell] = false }
            for next in neighbours(cell) where !used[next] && letters[next] == target[depth + 1] {
                if walk(next, depth + 1) { return true }
            }
            return false
        }
        for cell in letters.indices where letters[cell] == target[0] {
            if walk(cell, 0) { return true }
        }
        return false
    }

    /// Words reachable by carrying on from the last cell of `cells`, one or two cells
    /// further, without reusing a tile. This is the early-lift test, and it is a walk
    /// rather than a dictionary sweep because the question is about the board, not the
    /// lexicon: the same two extra letters are a lift on one board and not on another.
    func continuations(of word: String, from cells: [Int], upTo extra: Int,
                       isWord: (String) -> Bool) -> [String] {
        guard let last = cells.last, !cells.isEmpty else { return [] }
        var used = Set(cells)
        var out: [String] = []
        func walk(_ cell: Int, _ prefix: String, _ depth: Int) {
            guard depth <= extra else { return }
            for next in neighbours(cell) where !used.contains(next) {
                let grown = prefix + String(letters[next])
                used.insert(next)
                if isWord(grown) { out.append(grown) }
                if depth < extra { walk(next, grown, depth + 1) }
                used.remove(next)
            }
        }
        walk(last, word, 1)
        return out
    }
}

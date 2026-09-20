import Foundation

/// SPEC 9, finally built. Review after every board, and the engine of the app.
///
/// The tension this has to hold, and the reason it is not a solver with a nicer skin:
/// **what gets missed on any one board is mostly board luck.** A review driven by "what
/// did you miss today" teaches board-specific trivia and chases whatever was fumbled. The
/// Phase 2 queue's expected-value ranking is a far better selector than one game's misses.
///
/// So: **review is the interface, the queue is the ranker.** Forty words missed, three
/// shown, and the three are chosen by what they are worth across all boards -- Phase 2's
/// `expectedGain`, which is `presences per game x points x (achievable rate - my rate)` --
/// never by what was missed most here.
struct BoardReview {
    let gameId: String
    let purpose: String
    let side: Int
    let tier: Tier
    let score: Int
    let words: Int
    let boardWords: Int
    let elapsed: Double
    /// The board itself, kept so the review can draw paths on it and so the full solution
    /// is one tap away (SPEC 12.3) without solving it a second time.
    let letters: [Character]
    let solved: SolvedBoard
    let found: Set<String>

    /// Against his own completed games on the same grid and tier. Nil until there are
    /// enough of them to mean anything.
    let percentile: Double?
    let comparedWith: Int
    let leak: Leak?

    /// SPEC 9.1's hard cap. Everything past it is behind one tap into the full solution,
    /// deliberately out of the default flow.
    static let itemCap = 6
    let items: [Item]
    let overflow: Int
    /// Every missed word the queue can price, by what it is worth a game. The `items`
    /// above are the six things to act on; this is the list to read down.
    let rankedWords: [WordGap]
    /// Every family with two or more members on the board, priced or not. Read off the
    /// solve rather than out of the shipped record, so the big obvious ones are in it.
    let families: [BoardFamily]

    let misswipes: [MisswipeFinding]
    let misswipeSeconds: Double
    let duplicates: [DuplicateAttempt]
    let duplicateSeconds: Double
    let transitions: [Progression.Transition]
    /// The board was thin enough that skipping short words was not the right call, which
    /// is the condition SPEC 7.4 attaches to suppressing 3- and 4-letter families.
    let sparse: Bool
    /// Mixed practice only: the seeded families, scored. Empty on every other board.
    let mixed: [MixedResult]

    /// What a seeded family did on a mixed-practice board. The explicit version of Phase
    /// 4's unannounced re-injection: the board said nothing, and this is the breakdown
    /// afterwards.
    struct MixedResult: Identifiable {
        enum Outcome: String { case completed, part, missed, absent }
        let stem: String
        let present: Int
        let found: Int
        var id: String { stem }

        var outcome: Outcome {
            if present == 0 { return .absent }
            if found == present { return .completed }
            return found == 0 ? .missed : .part
        }

        var label: String {
            switch outcome {
            case .completed: return "all \(present)"
            case .part: return "\(found) of \(present)"
            case .missed: return "none of \(present)"
            // The generator could not place it. Said rather than hidden, the same as a
            // drill board that misses its target count.
            case .absent: return "not on the board"
            }
        }
    }

    enum Item: Identifiable {
        case family(FamilyGap)
        case word(WordGap)

        var id: String {
            switch self {
            case .family(let g): return "f:" + g.stem
            case .word(let g): return "w:" + g.word
            }
        }

        var value: Double {
            switch self {
            case .family(let g): return g.rankingValue
            case .word(let g): return g.branch.expectedGain
            }
        }

        var stem: String {
            switch self {
            case .family(let g): return g.stem
            case .word(let g): return g.stem
            }
        }
    }

    /// The single biggest thing that went wrong, in points, so four different kinds of
    /// waste can be compared at all. Seconds are converted at the board's own points rate,
    /// which is the only rate that is his and current.
    struct Leak {
        enum Kind: String {
            case freePoints      // extensions of stems he demonstrably swiped
            case misswipes
            case duplicates
        }
        let kind: Kind
        let points: Int
        let detail: String

        var sentence: String {
            switch kind {
            case .freePoints:
                return "\(points.formatted()) points in extensions of stems you already swiped."
            case .misswipes:
                return "\(points.formatted()) points of clock on strings that are not words."
            case .duplicates:
                return "\(points.formatted()) points of clock re-swiping words you had."
            }
        }
    }
}

/// SPEC 7.4's family gap. The four cases are not equally interesting and the ordering is
/// the point of the section.
struct FamilyGap {
    /// 1: found 2+ members and missed a 5+ member. You were on the stem and did not
    ///    finish. Cheapest possible points and the strongest signal in review.
    /// 2: missed a high-strength family entirely, in a region you demonstrably worked.
    /// 3: found the base and missed two or more extensions. Ending-set blindness.
    /// 4: missed a family entirely in a region you never touched. A coverage problem, and
    ///    shown as one -- SPEC 9.4 is explicit that coverage misses generate no study item.
    let priority: Int
    let stem: String
    let hook: Hook
    let meeting: FamilyMeeting
    /// The stem's own path on this board, for lighting it under the replay.
    let stemPath: [Int]?
    /// The missed members, best first, with the path each one takes.
    let missed: [(word: String, points: Int, path: [Int])]
    let covered: Bool

    /// How realizable the advice is, not how big the miss is. A family he was standing on
    /// is nearly free to finish; one in a corner he never visited is a scanning problem,
    /// and SPEC 9.4 says a scanning problem does not become a word list.
    static let realizability: [Int: Double] = [1: 1.0, 2: 0.6, 3: 0.8, 4: 0.25]

    /// Expected gain from the queue, discounted by realizability. Not points on this
    /// board: a word he takes 42% of the time is only 58% of a miss, and the queue already
    /// knows that number for every branch.
    var rankingValue: Double {
        meeting.missedExpectedGain * (Self.realizability[priority] ?? 0.5)
    }

    var reason: String {
        switch priority {
        case 1: return "You found \(meeting.found.count) of these and stopped."
        case 2: return "You worked this corner and took none of them."
        case 3: return "You had \(stem) and missed \(meeting.missed.count) endings."
        default: return "You never went here."
        }
    }
}

/// One word, ranked by what it is worth across every board, with the sentence that says
/// why it is on screen at all.
struct WordGap: Identifiable {
    var id: String { word }
    let word: String
    let stem: String
    let branch: Branch
    let path: [Int]
    let points: Int
    /// "ERASE was on 243 of your boards. You found it twice. The top 25% find it 28% of
    /// the time." Nil when the branch has too few ranked presences to say anything.
    let gap: SightGap?

    var sentence: String {
        gap?.sentence
            ?? "\(word) is worth \(String(format: "%.1f", branch.expectedGain)) points a game."
    }
}

enum ReviewBuilder {
    /// A family whose missed members are worth less than this a game is not worth a card.
    /// 1.0 is the median expected gain of a live branch across the whole shipped queue, so
    /// the line reads "at least one median-value branch's worth".
    static let familyGainFloor = 1.0
    /// A word's own bar for the "worth it" section, same units and same reasoning.
    static let wordGainFloor = 1.0
    /// Share of a family's cells that have to have been under the finger for the region to
    /// count as worked. Half: enough that "you were there" is not a claim about one tile.
    static let coveredShare = 0.5
    /// Misswipes shown. The rest are in the log, and the section is a diagnostic, not a
    /// leaderboard.
    static let misswipeCap = 3
    static let duplicateCap = 4
    /// How many games on the same grid and tier before a percentile is worth printing.
    static let minGamesForPercentile = 8

    /// Everything here is synchronous and belongs on a background queue: it solves nothing
    /// (the solve is passed in) but it walks paths and reads the log.
    static func build(result: GameResult, solved: SolvedBoard, purpose: String,
                      index: FamilyIndex, isWord: (String) -> Bool,
                      meetings: [String: FamilyMeeting]? = nil,
                      drilledStem: String? = nil,
                      mixedStems: [String] = []) -> BoardReview {
        let found = Set(result.found.map(\.word))
        let letters = result.board.letters
        let side = result.board.side
        let elapsed = max(1, result.elapsed)
        let sparse = isSparse(words: solved.count, side: side)

        let meetings = meetings ?? index.meetings(on: solved, found: found)
        let gaps = familyGaps(meetings: meetings, solved: solved, letters: letters, side: side,
                              touched: result.touchedCells, sparse: sparse, index: index)
        // Two lists, same ranking, different jobs. `everyWord` is the whole readable
        // list; `wordGaps` is the slice that competes for one of the six item slots, and
        // it drops families already on screen so an item is not spent twice.
        let everyWord = wordGaps(solved: solved, found: found, index: index, skipping: [],
                                 onePerFamily: false)
        let wordGaps = wordGaps(solved: solved, found: found, index: index,
                                skipping: Set(gaps.map(\.stem)))

        var items: [BoardReview.Item] = gaps.map { .family($0) } + wordGaps.map { .word($0) }
        items.sort { $0.value > $1.value }
        let total = items.count
        items = distinct(items)
        let overflow = max(0, total - items.count)

        let misswipes = classifyMisswipes(result: result, letters: letters, side: side,
                                          isWord: isWord)
        let duplicates = result.duplicateAttempts
            .sorted { $0.seconds > $1.seconds }
            .prefix(duplicateCap)
        let duplicateSeconds = result.duplicateAttempts.reduce(0) { $0 + $1.seconds }
        let misswipeSeconds = result.invalidAttempts.reduce(0) { $0 + $1.seconds }

        let (rank, compared) = scorePercentile(score: result.score, gameId: result.gameId,
                                               side: side, tier: result.board.tier,
                                               purpose: purpose)
        let leak = biggestLeak(result: result, solved: solved, meetings: meetings,
                               elapsed: elapsed, misswipeSeconds: misswipeSeconds,
                               duplicateSeconds: duplicateSeconds)
        let transitions = Progression.pendingTransitions(
            words: Set(solved.words.map(\.word)))
        record(items: items, gameId: result.gameId)

        return BoardReview(
            gameId: result.gameId, purpose: purpose, side: side, tier: result.board.tier,
            score: result.score, words: result.words, boardWords: solved.count,
            elapsed: elapsed, letters: letters, solved: solved, found: found,
            percentile: rank, comparedWith: compared, leak: leak,
            items: items, overflow: overflow, rankedWords: everyWord,
            families: BoardFamilies.all(on: solved, found: found, index: index),
            misswipes: misswipes, misswipeSeconds: misswipeSeconds,
            duplicates: Array(duplicates), duplicateSeconds: duplicateSeconds,
            transitions: transitions, sparse: sparse,
            mixed: mixedStems.sorted().map { stem in
                let m = meetings[stem]
                return BoardReview.MixedResult(stem: stem, present: m?.present.count ?? 0,
                                               found: m?.found.count ?? 0)
            })
    }

    /// Containment is not exclusive, so neither are families, and the first draft of this
    /// screen showed OATS-, MOA- and ATOM- one after another with ATMOS, ATOMS and MOATS
    /// in all three. Three cards, one fact. A family whose missed members are mostly
    /// already on screen under another stem is dropped: the cap is six items and an item
    /// spent twice is an item wasted.
    static let overlapCeiling = 0.6

    static func distinct(_ items: [BoardReview.Item]) -> [BoardReview.Item] {
        var shown: Set<String> = []
        var stems: [String] = []
        var out: [BoardReview.Item] = []
        for item in items where out.count < BoardReview.itemCap {
            let words: Set<String>
            switch item {
            case .family(let gap): words = Set(gap.missed.map(\.word))
            case .word(let gap): words = [gap.word]
            }
            guard !words.isEmpty else { continue }
            // A stem inside a stem already on screen is the same family at a different
            // level of SPEC 12.2's containment chain -- IDL- under IDLE-, NOT- under
            // NOTE-. The app's job is to say which level to hunt for, not to show three.
            // The word-set test alone misses this whenever a hook's branch list is capped
            // and the two lists end up only partly overlapping.
            let nested = stems.contains { $0.contains(item.stem) || item.stem.contains($0) }
            if nested, !words.isDisjoint(with: shown) { continue }
            // A card whose headline word is already on screen opens by telling him
            // something he has just read. ERA-, RASE- and SEA- are three different
            // families -- not nested, not 60% overlapping -- and all three led with ERASE.
            if let lead = headline(item), shown.contains(lead) { continue }
            let repeated = Double(words.intersection(shown).count) / Double(words.count)
            guard repeated <= overlapCeiling else { continue }
            shown.formUnion(words)
            stems.append(item.stem)
            out.append(item)
        }
        return out
    }

    /// The word a card opens with: the most expensive miss in the family, which is what
    /// `FamilyGap.missed` is sorted by.
    static func headline(_ item: BoardReview.Item) -> String? {
        switch item {
        case .family(let gap): return gap.missed.first?.word
        case .word(let gap): return gap.word
        }
    }

    /// What went on screen, in the order it went there. The gate is a question about
    /// whether these items were worth reading, and that question cannot be asked against
    /// an export unless the items are in it.
    static func record(items: [BoardReview.Item], gameId: String) {
        let wall = TrainingLog.now()
        Database.shared.writeMany("review_item", items.enumerated().map { rank, item in
            switch item {
            case .family(let gap):
                return ["game_id": gameId, "rank": rank, "kind": "family", "stem": gap.stem,
                        "word": nil, "priority": gap.priority, "value": gap.rankingValue,
                        "covered": gap.covered ? 1 : 0, "missed": gap.missed.count,
                        "wall": wall]
            case .word(let gap):
                return ["game_id": gameId, "rank": rank, "kind": "word", "stem": gap.stem,
                        "word": gap.word, "priority": nil,
                        "value": gap.branch.expectedGain, "covered": nil, "missed": 1,
                        "wall": wall]
            }
        })
    }

    /// Below the measured p10 of his own boards for that grid, filler was the right call
    /// and short families stop being something to nag about. The band comes from the hook
    /// record, which took it from 2,865 of his own boards.
    static func isSparse(words: Int, side: Int) -> Bool {
        guard let band = HookBundle.shared?.density[side] else { return false }
        return words <= band.minWords
    }

    // MARK: Families

    static func familyGaps(meetings: [String: FamilyMeeting], solved: SolvedBoard,
                           letters: [Character], side: Int, touched: Set<Int>,
                           sparse: Bool, index: FamilyIndex) -> [FamilyGap] {
        var out: [FamilyGap] = []
        for (stem, meeting) in meetings {
            guard !meeting.missed.isEmpty, let hook = index.hook(stem) else { continue }
            guard meeting.missedExpectedGain >= familyGainFloor else { continue }
            // SPEC 7.4's last row: do not nag about missed 3s and 4s on a board where
            // skipping them was correct play. Conditional on the board, not absolute.
            if !sparse, meeting.missed.allSatisfy({ $0.word.count <= 4 }) { continue }

            // By what the word is worth a game first, points second. A card's first word
            // is the one it opens with and the one whose path is drawn, so it has to be
            // the one that matters, not merely the longest.
            let missed = meeting.missed
                .sorted {
                    let a = meeting.branches[$0.word]?.expectedGain ?? 0
                    let b = meeting.branches[$1.word]?.expectedGain ?? 0
                    if a != b { return a > b }
                    return $0.points != $1.points ? $0.points > $1.points : $0.word < $1.word
                }
                .compactMap { w -> (word: String, points: Int, path: [Int])? in
                    guard let path = w.paths.first else { return nil }
                    return (w.word, w.points, path)
                }
            guard !missed.isEmpty else { continue }

            let cells = Set(missed.flatMap(\.path))
            let covered = !cells.isEmpty
                && Double(cells.intersection(touched).count) / Double(cells.count) >= coveredShare
            let stemPath = BoardGeometryUtil.paths(of: stem, letters: letters, side: side,
                                                   cap: 1).first

            let priority: Int
            if meeting.found.count >= 2 && missed.contains(where: { $0.word.count >= 5 }) {
                priority = 1
            } else if meeting.baseWasFound() && meeting.missed.count >= 2 {
                priority = 3
            } else if meeting.found.isEmpty && covered {
                priority = 2
            } else if meeting.found.isEmpty {
                priority = 4
            } else {
                // Found one, missed some, none of them long. Real but the weakest of the
                // four; treated as the ending-set case without the base.
                priority = 3
            }
            out.append(FamilyGap(priority: priority, stem: stem, hook: hook, meeting: meeting,
                                 stemPath: stemPath, missed: missed, covered: covered))
        }
        return out.sorted { $0.rankingValue > $1.rankingValue }
    }

    // MARK: Words

    /// Top words by expected gain from the queue, not by anything local to this board.
    /// Families already on screen are skipped, because a card saying "you missed STORED"
    /// under a card saying "you missed three TORE- endings" is one item spent twice.
    static func wordGaps(solved: SolvedBoard, found: Set<String>, index: FamilyIndex,
                         skipping: Set<String>, onePerFamily: Bool = true) -> [WordGap] {
        var out: [WordGap] = []
        for word in solved.words where !found.contains(word.word) {
            guard let membership = index.bestMembership(of: word.word),
                  !skipping.contains(membership.stem),
                  membership.branch.expectedGain >= wordGainFloor,
                  let path = word.paths.first else { continue }
            out.append(WordGap(word: word.word, stem: membership.stem, branch: membership.branch,
                               path: path, points: word.points,
                               gap: SightGap(branch: membership.branch)))
        }
        let ranked = out.sorted { $0.branch.expectedGain > $1.branch.expectedGain }
        guard onePerFamily else { return ranked }
        return ranked.reduce(into: [WordGap]()) { acc, gap in
            // One per family, so a single stem cannot take the whole section.
            if !acc.contains(where: { $0.stem == gap.stem }) { acc.append(gap) }
        }
    }

    // MARK: Misswipes

    static func classifyMisswipes(result: GameResult, letters: [Character], side: Int,
                                  isWord: (String) -> Bool) -> [MisswipeFinding] {
        var byWord: [String: InvalidAttempt] = [:]
        var seconds: [String: Double] = [:]
        for attempt in result.invalidAttempts {
            seconds[attempt.word, default: 0] += attempt.seconds
            if byWord[attempt.word] == nil { byWord[attempt.word] = attempt }
        }
        guard !byWord.isEmpty else { return [] }
        let lifetime = MisswipeClassifier.lifetimeCounts(Array(byWord.keys))

        let findings = byWord.values.compactMap { attempt -> MisswipeFinding? in
            guard let f = MisswipeClassifier.classify(attempt: attempt, letters: letters,
                                                      side: side, isWord: isWord)
            else { return nil }
            return MisswipeFinding(word: f.word, cause: f.cause,
                                   lifetimeCount: lifetime[f.word] ?? 1,
                                   secondsThisBoard: seconds[f.word] ?? f.secondsThisBoard,
                                   stem: f.stem, affix: f.affix, nearest: f.nearest)
        }
        // Learnable first, then by how often he has done it. A first-time miss is noise;
        // the fourth time he swipes RALL it is a fact about him.
        return Array(findings
            .sorted {
                if $0.cause.isLearnable != $1.cause.isLearnable { return $0.cause.isLearnable }
                if $0.lifetimeCount != $1.lifetimeCount { return $0.lifetimeCount > $1.lifetimeCount }
                return $0.secondsThisBoard > $1.secondsThisBoard
            }
            .prefix(misswipeCap))
    }

    // MARK: Verdict

    /// Against his own completed games on the same grid and tier. Same-tier only: a Spam
    /// board and a Casual board are not the same test, and a percentile across both would
    /// mostly measure which tier came up.
    static func scorePercentile(score: Int, gameId: String, side: Int, tier: Tier,
                                purpose: String) -> (Double?, Int) {
        var below = 0, total = 0
        // The board just played is excluded. Leaving it in counts it as one it did not
        // beat, which drags every percentile down by 1/n and is wrong for the same reason
        // a rank against yourself always is.
        Database.shared.query("""
            SELECT COUNT(*), SUM(CASE WHEN score < ? THEN 1 ELSE 0 END)
            FROM game
            WHERE t_end IS NOT NULL AND grid = ? AND tier = ? AND game_id != ?
              AND COALESCE(purpose, 'ranked') = ?
            """, [score, side, tier.name, gameId, purpose]) { row in
            total = row.int(0)
            below = row.int(1)
        }
        guard total >= minGamesForPercentile else { return (nil, total) }
        return (Double(below) / Double(total), total)
    }

    /// The four kinds of waste, priced in points so they can be compared. Clock is
    /// converted at the board's own rate, which is the only rate that is both his and
    /// current; a historical tier rate would flatter a bad board and punish a good one.
    static func biggestLeak(result: GameResult, solved: SolvedBoard,
                            meetings: [String: FamilyMeeting], elapsed: Double,
                            misswipeSeconds: Double, duplicateSeconds: Double)
        -> BoardReview.Leak? {
        let rate = Double(result.score) / elapsed     // points a second, this board
        var candidates: [BoardReview.Leak] = []

        // Distinct words, because a word on nine stems is one missed word and not nine.
        // Counting per family made a 369-word board report a quarter of a million points
        // of leak, which is arithmetic rather than information.
        var freeWords: Set<String> = []
        var families = 0
        for meeting in meetings.values where !meeting.found.isEmpty {
            families += 1
            for missed in meeting.missed { freeWords.insert(missed.word) }
        }
        let free = freeWords.reduce(0) { $0 + fluxPoints(forLength: $1.count) }
        if free > 0 {
            candidates.append(.init(
                kind: .freePoints, points: free,
                detail: "\(freeWords.count) words across \(families) families you opened"))
        }
        // No coverage bucket here on purpose. Everything not found is "coverage" by
        // default, so it wins every comparison and says nothing; SPEC 9.4 is explicit that
        // a coverage miss produces no study item. It is still a *card*, where it is framed
        // as the scanning problem it is -- it is just not the headline.
        if misswipeSeconds > 0 {
            candidates.append(.init(
                kind: .misswipes, points: Int(misswipeSeconds * rate),
                detail: String(format: "%d attempts, %.1f s", result.invalid, misswipeSeconds)))
        }
        if duplicateSeconds > 0 {
            candidates.append(.init(
                kind: .duplicates, points: Int(duplicateSeconds * rate),
                detail: String(format: "%d re-swipes, %.1f s", result.duplicates,
                               duplicateSeconds)))
        }
        return candidates.max { $0.points < $1.points }
    }
}

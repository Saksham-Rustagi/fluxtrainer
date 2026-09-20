import XCTest
@testable import FluxClone

/// Fixtures shared by the review tests. Branches carry seventeen fields and only three or
/// four matter to any one test, so the defaults here are a plausible mid-queue branch and
/// each test overrides what it is actually about.
enum Fixture {
    static func branch(_ word: String, cls: HookClass = .additive, points: Int? = nil,
                       gain: Double = 2.0, status: String = "learning",
                       myRate: Double? = 0.2, topQ: Double? = 0.5, fieldRate: Double? = 0.4,
                       presences: Int = 200,
                       finds: Int = 40, earns: Bool = true, misswiped: Int = 0) -> Branch {
        Branch(word: word, cls: cls, ext: "", points: points ?? fluxPoints(forLength: word.count),
               reachability: 0.3, reachSource: "observed", myRate: myRate,
               topQuartileRate: topQ, nTopQuartile: 90, fieldRate: fieldRate,
               presences: presences, finds: finds,
               opportunity: 120, presencesPerGame: 0.08, belief: 0.4, status: status,
               expectedGain: gain, earns: earns, misswiped: misswiped)
    }

    static func hook(_ stem: String, _ branches: [Branch]) -> Hook {
        Hook(stem: stem, stemLen: stem.count, isWord: true, rank: 1, track: "par", score: 5,
             expectedGain: branches.reduce(0) { $0 + $1.expectedGain }, residual: 100,
             enumerability: 3, enumerabilitySource: "observed", cueable: true, owned: 2,
             learning: 2, unknown: 2, studyItems: 3, familySize: branches.count,
             branchCount: branches.count, presentShare: 0.1, presentGames: 200,
             presenceByTierGrid: [:], deadBranches: 4, deadPoints: 0.5, why: "",
             branches: branches)
    }

    /// A solved board holding exactly these words, each on one made-up path. The paths do
    /// not have to be legal for the review logic -- nothing here re-walks them -- but they
    /// have to be distinct, because coverage is measured on cells.
    static func solved(_ words: [(String, [Int])]) -> SolvedBoard {
        SolvedBoard(words: words.map { SolvedWord(word: $0.0, paths: [$0.1], pathCount: 1) },
                    totalPoints: 0, words5p: 0, solveMs: 0)
    }

    static func index(_ hooks: [Hook]) -> FamilyIndex {
        FamilyIndex(bundle: HookBundle(
            schema: 1, generated: "test", player: "test", queueTotal: hooks.count,
            hooks: hooks, density: [:], minedAffixes: [], opportunityRef: [:],
            beliefPriors: [:], misswipes: [:]))
    }
}

/// The reverse index, against the record as it actually ships. A board asks "which of
/// these 428 words are branches, of what" for every word, so this is the hot path of every
/// review and the thing most likely to be quietly wrong.
final class FamilyIndexTests: XCTestCase {
    private static let bundle: HookBundle? = try? HookBundle.parse()

    func testEveryLiveBranchIsFindableFromItsWord() throws {
        let bundle = try XCTUnwrap(Self.bundle)
        let index = FamilyIndex(bundle: bundle)
        for hook in bundle.hooks.prefix(50) {
            for branch in hook.branches where branch.cls.earnsPoints {
                let families = index.families(of: branch.word)
                XCTAssertTrue(families.contains { $0.stem == hook.stem },
                              "\(branch.word) is on \(hook.stem) and the index does not say so")
            }
        }
    }

    /// Containment is not exclusive, so neither is membership. A word on nine stems has to
    /// come back on all nine, or review would credit one family and silently drop eight.
    func testAWordCanBelongToSeveralFamilies() throws {
        let bundle = try XCTUnwrap(Self.bundle)
        let index = FamilyIndex(bundle: bundle)
        let shared = bundle.hooks
            .flatMap { h in h.branches.filter(\.cls.earnsPoints).map { ($0.word, h.stem) } }
            .reduce(into: [String: Set<String>]()) { $0[$1.0, default: []].insert($1.1) }
            .first { $0.value.count >= 3 }
        let (word, stems) = try XCTUnwrap(shared)
        XCTAssertEqual(Set(index.families(of: word).map(\.stem)), stems)
    }

    /// Dead branches never enter the index. A board carrying no live member of a family is
    /// not a meeting with that family, and counting it as one would put stems in My Stems
    /// that the player could not have taken anything from.
    func testDeadBranchesAreNotMemberships() {
        let hook = Fixture.hook("TORE", [Fixture.branch("STORE"),
                                         Fixture.branch("TOREER", cls: .dead, earns: false)])
        let index = Fixture.index([hook])
        XCTAssertEqual(index.families(of: "STORE").count, 1)
        XCTAssertTrue(index.families(of: "TOREER").isEmpty)
    }

    func testMeetingsSplitFoundFromMissed() {
        let index = Fixture.index([Fixture.hook("TORE", [
            Fixture.branch("STORE"), Fixture.branch("STORED"), Fixture.branch("TORES"),
        ])])
        let board = Fixture.solved([("STORE", [0, 1, 2, 3, 4]), ("STORED", [0, 1, 2, 3, 4, 5]),
                                    ("TORES", [1, 2, 3, 4, 6])])
        let meetings = index.meetings(on: board, found: ["STORE"])
        let tore = try? XCTUnwrap(meetings["TORE"])
        XCTAssertEqual(tore?.present.count, 3)
        XCTAssertEqual(tore?.found.map(\.word), ["STORE"])
        XCTAssertEqual(Set(tore?.missed.map(\.word) ?? []), ["STORED", "TORES"])
        XCTAssertEqual(tore?.pointsMissed, fluxPoints(forLength: 6) + fluxPoints(forLength: 5))
    }
}

/// SPEC 7.4's four cases. They are not equally interesting, and getting the case wrong
/// means telling the player "you were there and did not finish" about a corner he never
/// visited -- which is worse than saying nothing.
final class FamilyGapTests: XCTestCase {
    private func gaps(hooks: [Hook], board: SolvedBoard, found: Set<String>,
                      touched: Set<Int>, sparse: Bool = false) -> [FamilyGap] {
        let index = Fixture.index(hooks)
        return ReviewBuilder.familyGaps(meetings: index.meetings(on: board, found: found),
                                        solved: board, letters: Array("XXXXXXXXXXXXXXXX"),
                                        side: 4, touched: touched, sparse: sparse, index: index)
    }

    /// Priority 1: two members found and a long one missed. The cheapest possible points
    /// and the strongest signal in review.
    func testFoundTwoAndMissedALongOneIsTheTopCase() {
        let hook = Fixture.hook("TORE", [Fixture.branch("TORE"), Fixture.branch("TORES"),
                                         Fixture.branch("STORED", gain: 4)])
        let board = Fixture.solved([("TORE", [0, 1, 2, 3]), ("TORES", [0, 1, 2, 3, 4]),
                                    ("STORED", [5, 0, 1, 2, 3, 4])])
        let gap = gaps(hooks: [hook], board: board, found: ["TORE", "TORES"], touched: [0, 1, 2, 3])
        XCTAssertEqual(gap.first?.priority, 1)
    }

    /// Priority 3: the base was taken and the endings were not. Ending-set blindness, and
    /// very trainable.
    func testBaseFoundAndTwoEndingsMissedIsTheEndingSetCase() {
        let hook = Fixture.hook("HOLE", [Fixture.branch("HOLE"), Fixture.branch("HOLES"),
                                         Fixture.branch("HOLED")])
        let board = Fixture.solved([("HOLE", [0, 1, 2, 3]), ("HOLES", [0, 1, 2, 3, 4]),
                                    ("HOLED", [0, 1, 2, 3, 5])])
        let gap = gaps(hooks: [hook], board: board, found: ["HOLE"], touched: [0, 1, 2, 3])
        XCTAssertEqual(gap.first?.priority, 3)
    }

    /// Priorities 2 and 4 differ only in coverage, and that is exactly the distinction
    /// worth making: one is a vision leak on a pattern, the other is a scanning problem,
    /// and SPEC 9.4 says a scanning problem does not become a word list.
    func testCoverageSeparatesTheTwoWholeFamilyMisses() {
        let hook = Fixture.hook("SANT", [Fixture.branch("SANTERA", gain: 3),
                                         Fixture.branch("SANTERO", gain: 3)])
        let board = Fixture.solved([("SANTERA", [0, 1, 2, 3, 4, 5, 6]),
                                    ("SANTERO", [0, 1, 2, 3, 4, 5, 7])])
        let worked = gaps(hooks: [hook], board: board, found: [],
                          touched: [0, 1, 2, 3, 4, 5, 6, 7])
        XCTAssertEqual(worked.first?.priority, 2)
        XCTAssertTrue(worked.first?.covered == true)

        let untouched = gaps(hooks: [hook], board: board, found: [], touched: [12, 13])
        XCTAssertEqual(untouched.first?.priority, 4)
        XCTAssertFalse(untouched.first?.covered == true)
    }

    /// SPEC 7.4's last row. Do not nag about missed 3s and 4s on a board where skipping
    /// them was correct play -- and do show them when it was not.
    func testShortOnlyFamiliesAreSuppressedExceptOnASparseBoard() {
        let hook = Fixture.hook("TOR", [Fixture.branch("TORE", gain: 2),
                                        Fixture.branch("TORS", gain: 2)])
        let board = Fixture.solved([("TORE", [0, 1, 2, 3]), ("TORS", [0, 1, 2, 4])])
        XCTAssertTrue(gaps(hooks: [hook], board: board, found: [], touched: []).isEmpty)
        XCTAssertFalse(gaps(hooks: [hook], board: board, found: [], touched: [],
                            sparse: true).isEmpty)
    }

    /// The ordering rule the whole phase turns on: expected value from the queue, never
    /// what was missed most here. The cheap family is worth more a game and wins even
    /// though the other one lost more points on this particular board.
    func testRankingIsExpectedValueNotPointsOnThisBoard() {
        let cheap = Fixture.hook("ERAS", [Fixture.branch("ERASE", gain: 18.3)])
        let dear = Fixture.hook("PRAT", [Fixture.branch("PRATERS", gain: 0.6),
                                         Fixture.branch("EPATERS", gain: 0.6)])
        let board = Fixture.solved([("ERASE", [0, 1, 2, 3, 4]),
                                    ("PRATERS", [5, 6, 7, 8, 9, 10, 11]),
                                    ("EPATERS", [5, 6, 7, 8, 9, 10, 12])])
        let ranked = gaps(hooks: [cheap, dear], board: board, found: [],
                          touched: Set(0...12))
        XCTAssertEqual(ranked.first?.stem, "ERAS")
        // PRAT- lost 3,400 points on this board against ERASE's 800, and still comes second.
        XCTAssertEqual(ranked.last?.stem, "PRAT")
    }

    /// Realizability, not size. A family he was standing on is nearly free to finish; one
    /// in a corner he never visited is a scanning problem worth a quarter of the same gain.
    func testACoverageMissIsDiscountedAgainstAnEqualGapHeWasStandingOn() {
        let standing = FamilyGap.realizability[1] ?? 0
        let corner = FamilyGap.realizability[4] ?? 0
        XCTAssertGreaterThan(standing, corner * 3)
    }
}

/// The word section: ranked by what a word is worth across every board, never by what it
/// cost here.
final class WordGapTests: XCTestCase {
    func testTopByExpectedGainAndOnePerFamily() {
        let index = Fixture.index([
            Fixture.hook("ERAS", [Fixture.branch("ERASE", gain: 18.3),
                                  Fixture.branch("ERASED", gain: 9.0)]),
            Fixture.hook("TORE", [Fixture.branch("STORE", gain: 10.7)]),
        ])
        let board = Fixture.solved([("ERASE", [0, 1, 2, 3, 4]), ("ERASED", [0, 1, 2, 3, 4, 5]),
                                    ("STORE", [6, 7, 8, 9, 10])])
        let gaps = ReviewBuilder.wordGaps(solved: board, found: [], index: index, skipping: [])
        XCTAssertEqual(gaps.map(\.word), ["ERASE", "STORE"],
                       "one word per family, best first")
    }

    /// A family already on screen does not get a second card. One item spent twice is one
    /// item wasted, and the cap is six.
    func testFamiliesAlreadyShownAreSkipped() {
        let index = Fixture.index([Fixture.hook("ERAS", [Fixture.branch("ERASE", gain: 18.3)])])
        let board = Fixture.solved([("ERASE", [0, 1, 2, 3, 4])])
        XCTAssertTrue(ReviewBuilder.wordGaps(solved: board, found: [], index: index,
                                             skipping: ["ERAS"]).isEmpty)
    }

    func testWordsBelowTheGainFloorAreNotWorthACard() {
        let index = Fixture.index([Fixture.hook("TUT", [Fixture.branch("TUTORED", gain: 0.2)])])
        let board = Fixture.solved([("TUTORED", [0, 1, 2, 3, 4, 5, 6])])
        XCTAssertTrue(ReviewBuilder.wordGaps(solved: board, found: [], index: index,
                                             skipping: []).isEmpty)
    }
}

/// `tools/queue/misswipe.py`, on the device. Only two of the four causes teach anything,
/// and the precedence is what keeps them apart.
final class MisswipeTests: XCTestCase {
    /// H O L E
    /// D A S R
    /// I N T C
    /// P E R S
    ///
    /// Laid out so the strings under test are walkable: HOLERS runs 0-1-2-3-7-6 and HOLES
    /// runs 0-1-2-3-6, which is what makes "is a real word one edit away *on this board*"
    /// a question with an answer here.
    private let letters = Array("HOLEDASRINTCPERS")
    private var isWord: (String) -> Bool { { FluxEngine.shared.wordId($0) != nil } }

    private func classify(_ word: String, cells: [Int]) -> MisswipeFinding? {
        MisswipeClassifier.classify(
            attempt: InvalidAttempt(word: word, cells: cells, seconds: 1),
            letters: letters, side: 4, isWord: isWord)
    }

    /// HOLE is a word, HOLERS is not, and -ERS is the affix over-applied. Vocabulary, and
    /// the one cause the dead half of the affix grid is built for.
    func testARealStemPlusAnAffixThatDoesNotTakeIsAnAffixError() throws {
        let finding = try XCTUnwrap(classify("HOLERS", cells: [0, 1, 2, 3, 7, 6]))
        XCTAssertEqual(finding.cause, .affixError)
        XCTAssertEqual(finding.stem, "HOLE")
        XCTAssertEqual(finding.affix, "-ERS")
        XCTAssertTrue(finding.cause.isLearnable)
    }

    /// The precedence that matters. Appending the missing last letter is itself an
    /// insertion, so an edit-one test run first would swallow every early lift into
    /// pathError and the motor bucket would swell for no reason.
    func testEarlyLiftIsTestedBeforeTheGenericEditTest() throws {
        // HOL, lifted at cell 2, with E sitting next door at cell 3: HOLE was one cell on.
        let finding = try XCTUnwrap(classify("HOL", cells: [0, 1, 2]))
        XCTAssertEqual(finding.cause, .earlyLift)
        XCTAssertTrue(finding.nearest.contains("HOLE"))
        XCTAssertFalse(finding.cause.isLearnable, "a lift is motor, and teaches nothing")
    }

    /// A terminal append is the early-lift case by construction, so it must not also be an
    /// edit-one candidate.
    func testEditOneExcludesTerminalAppends() {
        let edits = MisswipeClassifier.editOne("HOL")
        XCTAssertFalse(edits.contains("HOLE"), "HOLE is an append, which is a lift not a slip")
        XCTAssertFalse(edits.contains("HOLD"), "so is HOLD")
        XCTAssertTrue(edits.contains("HOT"), "a substitution is an edit")
        XCTAssertTrue(edits.contains("HOEL"), "an interior insertion is an edit")
        XCTAssertFalse(edits.contains("HOL"))
    }

    /// Nothing valid nearby: he believed it was a word. The most valuable kind in the
    /// track, and a study item.
    func testAStringWithNothingNearIsABelief() throws {
        let finding = try XCTUnwrap(classify("HOLERSDAINT", cells: Array(0..<11)))
        XCTAssertEqual(finding.cause, .trueNonWord)
        XCTAssertTrue(finding.cause.isLearnable)
    }

    func testTwoCellBrushesAreNotClassifiedAtAll() {
        XCTAssertNil(classify("HO", cells: [0, 1]))
    }

    func testBoardWalkOnlyWalksLegalPaths() {
        let walk = BoardWalk(letters: letters, side: 4)
        XCTAssertTrue(walk.hasPath("HOLE"))      // 0-1-2-3, the top row
        XCTAssertTrue(walk.hasPath("HOLES"))     // 0-1-2-3-6, down to the S
        XCTAssertFalse(walk.hasPath("HOLED"), "D sits at 4 and is not adjacent to E at 3")
        XCTAssertFalse(walk.hasPath("ZZZZ"))
    }
}

/// Learning has to be visible and has to change something -- including downwards. The
/// player's own history says decay is the normal case, not the exception.
final class SlippingTests: XCTestCase {
    private func recent(_ finds: Int, of presences: Int) -> Progression.Recent {
        Progression.Recent(finds: finds, presences: presences)
    }

    func testAnEstablishedWordNowBeingMissedIsSlipping() {
        // Taken 60% of the time over 2,865 ranked boards, taken once in the last six here.
        XCTAssertTrue(Progression.isSlipping(established: 0.6, recent: recent(1, of: 6)))
    }

    func testAWordStillBeingTakenIsNot() {
        XCTAssertFalse(Progression.isSlipping(established: 0.6, recent: recent(4, of: 6)))
    }

    /// Three presences is not evidence. Firing on a thin window would put half the queue
    /// in the slipping state after one bad board.
    func testAThinWindowCannotTriggerIt() {
        XCTAssertFalse(Progression.isSlipping(established: 0.6, recent: recent(0, of: 3)))
    }

    /// A word that was never being taken cannot stop being taken. Without this floor,
    /// "slipping" would just be another name for "unknown".
    func testAWordThatWasNeverTakenCannotSlip() {
        XCTAssertFalse(Progression.isSlipping(established: 0.08, recent: recent(0, of: 6)))
    }

    func testNoRankedBaselineMeansNoVerdict() {
        XCTAssertFalse(Progression.isSlipping(established: nil, recent: recent(0, of: 6)))
    }
}

/// The family page's one job: "have I got the ones that matter?"
final class FamilyPageTests: XCTestCase {
    private func page(_ rows: [FamilyPage.Row]) -> FamilyPage {
        FamilyPage(hook: Fixture.hook("TORE", rows.map(\.branch)), live: rows, dead: [],
                   trend: Progression.Trend(beforeFinds: 0, beforePresences: 0, afterFinds: 0,
                                            afterPresences: 0, firstDrilled: nil,
                                            lastMet: nil, meetings: 0))
    }

    private func row(_ word: String, gain: Double, status: String) -> FamilyPage.Row {
        let branch = Fixture.branch(word, gain: gain, status: status)
        return FamilyPage.Row(branch: branch, status: status, myRate: branch.myRate,
                              inAppPresences: 0, inAppFinds: 0,
                              worthKnowing: branch.earns
                                  && gain >= FamilyPage.worthKnowingFloor)
    }

    /// STORED and RESTORE above the line, TUTORED below it, and the headline counts only
    /// what is above.
    func testTheHeadlineCountsOnlyWhatIsWorthKnowing() {
        let p = page([row("STORED", gain: 6, status: "known"),
                      row("RESTORE", gain: 4, status: "unknown"),
                      row("TUTORED", gain: 0.1, status: "unknown")])
        XCTAssertEqual(p.worthKnowing.count, 2)
        XCTAssertEqual(p.headline, "You have 1 of the 2 branches worth knowing.")
    }

    func testOneBranchReadsAsASingular() {
        let p = page([row("STORED", gain: 6, status: "known"),
                      row("TUTORED", gain: 0.1, status: "unknown")])
        XCTAssertEqual(p.headline, "You have 1 of the 1 branch worth knowing.")
    }

    /// A slipping branch is not owned, whatever belief says about it. That is the point of
    /// the state: it exists to contradict a stale "owned".
    func testASlippingBranchIsNotCountedAsOwned() {
        let p = page([row("STORED", gain: 6, status: "slipping")])
        XCTAssertEqual(p.ownedWorthKnowing, 0)
        XCTAssertEqual(p.slipping.map(\.word), ["STORED"])
    }
}

/// Mixed practice, scored per family afterwards. The board says nothing while it is being
/// played, which is the whole point of it.
final class MixedPracticeTests: XCTestCase {
    private func result(present: Int, found: Int) -> BoardReview.MixedResult.Outcome {
        BoardReview.MixedResult(stem: "TORE", present: present, found: found).outcome
    }

    func testTheFourOutcomes() {
        XCTAssertEqual(result(present: 3, found: 3), .completed)
        XCTAssertEqual(result(present: 3, found: 1), .part)
        XCTAssertEqual(result(present: 3, found: 0), .missed)
        // The generator could not place it. Said rather than hidden.
        XCTAssertEqual(result(present: 0, found: 0), .absent)
        XCTAssertEqual(BoardReview.MixedResult(stem: "TORE", present: 0, found: 0).label,
                       "not on the board")
    }
}

/// The two defects the first screenshot found. Both looked fine in code.
final class ReviewCompositionTests: XCTestCase {
    private func familyItem(_ stem: String, missed: [String], gain: Double) -> BoardReview.Item {
        let branches = missed.map { Fixture.branch($0, gain: gain / Double(missed.count)) }
        var meeting = FamilyMeeting(stem: stem)
        for (i, branch) in branches.enumerated() {
            meeting.add(word: SolvedWord(word: branch.word, paths: [[i]], pathCount: 1),
                        branch: branch, found: false)
        }
        // Sorted the way `familyGaps` sorts it -- most expensive first -- because the
        // word a card opens with is the first of these, and a hand-ordered fixture would
        // be testing an order the app never produces.
        let ordered = missed
            .map { (word: $0, points: fluxPoints(forLength: $0.count), path: [0]) }
            .sorted { $0.points != $1.points ? $0.points > $1.points : $0.word < $1.word }
        return .family(FamilyGap(
            priority: 2, stem: stem, hook: Fixture.hook(stem, branches), meeting: meeting,
            stemPath: nil, missed: ordered, covered: true))
    }

    /// OATS-, MOA- and ATOM- all led with ATMOS, ATOMS and MOATS. Three cards, one fact.
    /// Containment is not exclusive, so neither are families.
    func testFamiliesSharingTheirMissedWordsAreNotShownTwice() {
        let items = [
            familyItem("OATS", missed: ["ATMOS", "ATOMS", "MOATS", "COATS"], gain: 8),
            familyItem("MOA", missed: ["ATMOS", "ATOMS", "MOATS"], gain: 6),
            familyItem("ERAS", missed: ["ERASE", "ERASED"], gain: 5),
        ]
        let shown = ReviewBuilder.distinct(items).map(\.stem)
        XCTAssertEqual(shown, ["OATS", "ERAS"], "MOA- is OATS- again under another name")
    }

    /// Overlap has to be partial before it counts as the same item: two families sharing
    /// one member out of four are two different facts.
    func testAPartialOverlapIsStillItsOwnItem() {
        let items = [
            familyItem("OATS", missed: ["ATMOS", "ATOMS", "MOATS", "COATS"], gain: 8),
            familyItem("COAT", missed: ["COATS", "COATED", "COATER", "COATIS"], gain: 6),
        ]
        XCTAssertEqual(ReviewBuilder.distinct(items).count, 2)
    }

    func testTheCapIsSix() {
        let items = (0..<10).map { familyItem("S\($0)", missed: ["WORD\($0)"], gain: 3) }
        XCTAssertEqual(ReviewBuilder.distinct(items).count, BoardReview.itemCap)
    }
}

/// The headline leak. It read 244,600 points on a 369-word board, which is arithmetic
/// rather than information.
final class LeakTests: XCTestCase {
    private func meeting(_ stem: String, found: [String], missed: [String]) -> FamilyMeeting {
        var m = FamilyMeeting(stem: stem)
        for (i, word) in (found + missed).enumerated() {
            m.add(word: SolvedWord(word: word, paths: [[i]], pathCount: 1),
                  branch: Fixture.branch(word), found: found.contains(word))
        }
        return m
    }

    private func result(score: Int, found: [String]) -> GameResult {
        let board = GeneratedBoard(
            side: 4, tier: .goodCasual, letters: Array("ABCDEFGHIJKLMNOP"), rootSeed: 1,
            boardSeed: 1, realizedN: 1, seedWord: nil, potentialPoints: 0, potentialWords: 0,
            potentialWords5p: 0, generateMs: 0, solveMs: 0, gridSource: "drawn",
            tierSource: "drawn")
        return GameResult(
            gameId: "t", board: board, score: score, words: found.count, invalid: 0,
            duplicates: 0, abandoned: false,
            found: found.enumerated().map { FoundWord(word: $1, t: Double($0), cells: [$0]) },
            tBoardShown: 0, elapsed: 80)
    }

    /// STORED is on TORE-, TOR- and ORE-. It is one missed word, not three, and counting
    /// it per family is what produced the quarter-million.
    func testAWordOnSeveralStemsIsCountedOnce() {
        let meetings = ["TORE": meeting("TORE", found: ["STORE"], missed: ["STORED"]),
                        "TOR": meeting("TOR", found: ["STORE"], missed: ["STORED"]),
                        "ORE": meeting("ORE", found: ["STORE"], missed: ["STORED"])]
        let leak = ReviewBuilder.biggestLeak(
            result: result(score: 800, found: ["STORE"]),
            solved: Fixture.solved([("STORE", [0]), ("STORED", [1])]),
            meetings: meetings, elapsed: 80, misswipeSeconds: 0, duplicateSeconds: 0)
        XCTAssertEqual(leak?.kind, .freePoints)
        XCTAssertEqual(leak?.points, fluxPoints(forLength: 6), "STORED, once")
    }

    /// A family he never opened is a scanning problem. It is a card, framed as one, and
    /// never the headline -- everything not found is "coverage" by default, so it would
    /// win every comparison while saying nothing.
    func testAFamilyHeNeverOpenedIsNotTheHeadline() {
        let meetings = ["SANT": meeting("SANT", found: [], missed: ["SANTERA", "SANTERO"])]
        let leak = ReviewBuilder.biggestLeak(
            result: result(score: 800, found: []),
            solved: Fixture.solved([("SANTERA", [0]), ("SANTERO", [1])]),
            meetings: meetings, elapsed: 80, misswipeSeconds: 4, duplicateSeconds: 0)
        XCTAssertEqual(leak?.kind, .misswipes,
                       "with nothing opened, the only real leak on this board is the clock")
    }
}

/// The containment chain, which the word-set test alone does not catch. Real boards put
/// IDL- and IDLE-, NOT- and NOTE- on screen together: the same family at two levels.
extension ReviewCompositionTests {
    func testAStemInsideAStemAlreadyShownIsOneLevelTooMany() {
        let items = [
            familyItem("IDL", missed: ["IDLES", "IDLER", "IDLY", "IDLEST"], gain: 9),
            familyItem("IDLE", missed: ["IDLES", "IDLER", "IDLEST", "IDLENESS"], gain: 6),
            familyItem("ROST", missed: ["ROSTER", "ROSTED"], gain: 4),
        ]
        XCTAssertEqual(ReviewBuilder.distinct(items).map(\.stem), ["IDL", "ROST"])
    }

    /// Nesting alone is not enough. Two stems can be nested and still be about different
    /// words on this board, and dropping one then would lose a real item.
    func testNestedStemsWithNoSharedMissIsStillTwoItems() {
        let items = [
            familyItem("TOR", missed: ["TORS", "TORI"], gain: 5),
            familyItem("TORE", missed: ["STORED", "RESTORE"], gain: 4),
        ]
        XCTAssertEqual(ReviewBuilder.distinct(items).count, 2)
    }
}

extension ReviewCompositionTests {
    /// Three unrelated stems all leading with ERASE. Not nested, not 60% overlapping, and
    /// still three cards that open by telling him the same thing.
    func testTwoFamiliesCannotOpenWithTheSameWord() {
        let items = [
            familyItem("ERA", missed: ["ERASE", "SERAL", "TERAS", "ARES"], gain: 42),
            familyItem("RASE", missed: ["ERASE", "RASES", "SEARE"], gain: 22),
            familyItem("SEA", missed: ["SEARE", "SEAT"], gain: 20),
        ]
        // ERA- keeps ERASE. RASE- would open with it again. SEA- opens with SEARE, which
        // nothing has shown, so it stays.
        XCTAssertEqual(ReviewBuilder.distinct(items).map(\.stem), ["ERA", "SEA"])
    }
}

/// The first row the app writes for a word is not a transition. It arrived owned, out of
/// 2,865 ranked boards, and the app is simply seeing it for the first time.
final class TransitionSeedTests: XCTestCase {
    func testTheUpsertSeedsAnnouncedStatusAndThenLeavesItAlone() {
        let sql = TrainingQueue.beliefUpsert
        XCTAssertTrue(sql.contains("announced_status"),
                      "the insert has to seed it, or every first sighting announces")
        let update = sql.components(separatedBy: "DO UPDATE SET").last ?? ""
        // Seeded on update only when it is still NULL -- a row written by Phase 3 has
        // none, and would otherwise announce every observed word at once on the first
        // recompute after the upgrade.
        XCTAssertTrue(update.contains(
            "announced_status = COALESCE(word_belief.announced_status, excluded.status)"),
            "the update must seed it once and never overwrite it")
        XCTAssertFalse(update.contains("announced_status = excluded.status"),
                       "an unconditional overwrite repeats every announcement for ever")
        // And the row must not go through INSERT OR REPLACE, which would null the column.
        XCTAssertTrue(sql.contains("ON CONFLICT(word) DO UPDATE"))
    }
}

/// Families read off the board, using SPEC 7.3's definition and nothing else: a word W is
/// in family S when S is a contiguous substring of W. No list involved, so the big obvious
/// families are in it too.
final class BoardFamiliesTests: XCTestCase {
    private func families(_ words: [String], found: Set<String> = []) -> [BoardFamily] {
        let solved = Fixture.solved(words.enumerated().map { ($1, [$0]) })
        return BoardFamilies.all(on: solved, found: found, index: nil)
    }

    func testAFamilyNeedsTwoMembers() {
        XCTAssertTrue(families(["STORE", "PLANK"]).isEmpty,
                      "two unrelated words share no substring of three or more")
    }

    /// SPEC 7.4's "found the base, missed two extensions" needs the base to be a member of
    /// its own family, so the whole word counts as a stem.
    func testTheBaseWordIsAMemberOfItsOwnFamily() {
        let tore = families(["TORE", "TORES", "STORE"]).first { $0.stem == "TORE" }
        XCTAssertEqual(Set(tore?.members.map(\.word) ?? []), ["TORE", "TORES", "STORE"])
    }

    /// TOR- and TORE- over the same three words are one family described twice. The longer
    /// stem is the more specific description and is the one kept.
    func testTwoStemsOverTheSameWordsCollapseToTheLonger() {
        let stems = families(["TORE", "TORES", "STORE"]).map(\.stem)
        XCTAssertTrue(stems.contains("TORE"))
        XCTAssertFalse(stems.contains("TOR"), "TOR- covers exactly the same three words")
    }

    /// TOR- reaches TORI and TORE- does not, so they are different sets -- but TORE- is
    /// still a level *inside* TOR-, so the list shows TOR- and carries TORE- on it.
    func testANarrowerLevelIsCarriedNotListed() {
        let all = families(["TORE", "TORES", "TORI"])
        XCTAssertEqual(all.first?.stem, "TOR", "TOR- has all three and leads")
        XCTAssertFalse(all.map(\.stem).contains("TORE"))
        XCTAssertTrue(all[0].narrower.contains("TORE"))
    }

    func testFoundAndMissedSplitAndPriceOut() {
        let f = families(["HOLE", "HOLES", "HOLED"], found: ["HOLE"])
            .first { $0.stem == "HOLE" }
        XCTAssertEqual(f?.found.map(\.word), ["HOLE"])
        XCTAssertEqual(Set(f?.missed.map(\.word) ?? []), ["HOLES", "HOLED"])
        XCTAssertEqual(f?.pointsMissed, 2 * fluxPoints(forLength: 5))
        XCTAssertFalse(f?.ranked ?? true, "no index, so nothing here is priced")
    }

    /// Sorted by what is still on the table, which is the question a browse answers.
    func testSortedByPointsLeftOnTheBoard() {
        let all = families(["HOLE", "HOLES", "HOLED", "CAT", "CATS"], found: [])
        let points = all.map(\.pointsMissed)
        XCTAssertEqual(points, points.sorted(by: >))
    }

    /// A 5x5 board is 800 words and every substring of every one of them. It has to stay
    /// cheap enough to run on the way into review.
    func testStaysCheapOnAFullSizedBoard() {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        var words: [(String, [Int])] = []
        for i in 0..<800 {
            var w = ""
            var n = i
            for _ in 0..<(4 + i % 4) { w.append(alphabet[n % 26]); n /= 26 }
            words.append((w, [i % 25]))
        }
        let solved = Fixture.solved(words)
        let started = Date()
        _ = BoardFamilies.all(on: solved, found: [], index: nil)
        XCTAssertLessThan(Date().timeIntervalSince(started), 2.0)
    }
}

/// rank.py's split, on the device. Below 10% the field almost never takes the word, so
/// finding it at all is the win; at or above it, he is expected to take it and is not.
final class AlphaTrackTests: XCTestCase {
    func testTheFieldRateIsTheLine() {
        XCTAssertTrue(Fixture.branch("SIREES", fieldRate: 0.04).isAlpha)
        XCTAssertFalse(Fixture.branch("STORE", fieldRate: 0.47).isAlpha)
        XCTAssertFalse(Fixture.branch("EDGE", fieldRate: Branch.alphaBelow).isAlpha,
                       "the line is strictly below 10%, as rank.py has it")
    }

    /// A branch the ranked import could not price is not alpha by default. Unpriced is
    /// unknown, and calling it vocabulary would fill the alpha list with noise.
    func testAnUnpricedBranchIsNotAlpha() {
        XCTAssertFalse(Fixture.branch("XYZZY", fieldRate: nil).isAlpha)
    }

    /// The record has to carry the rate, or the whole split is unavailable on device.
    func testTheShippedRecordCarriesTheFieldRate() throws {
        let bundle = try XCTUnwrap(try? HookBundle.parse())
        XCTAssertEqual(bundle.schema, 2)
        let priced = bundle.hooks.prefix(20)
            .flatMap(\.branches)
            .filter { $0.cls.earnsPoints && $0.fieldRate != nil }
        XCTAssertGreaterThan(priced.count, 50, "schema 2 ships fieldRate per branch")
        XCTAssertTrue(priced.contains(where: \.isAlpha), "and some of them are alpha")
    }
}

/// SPEC 12.2's containment chain. A board produces every level of it, and listed flat the
/// biggest cluster crowds out every other family on the board.
extension BoardFamiliesTests {
    func testTheContainmentChainFoldsToItsWidestLevel() {
        // AMP- has all three; AMPE-, AMPER- and AMPERE- all have the same two, so the
        // identical-set rule names that set after the longest of them, and the chain rule
        // then folds it into AMP-.
        let solved = Fixture.solved([("AMPERE", [0]), ("AMPERES", [1]), ("AMPLE", [2])])
        let all = BoardFamilies.all(on: solved, found: [], index: nil)
        XCTAssertEqual(all.first?.stem, "AMP", "the widest level leads")
        XCTAssertFalse(all.map(\.stem).contains("AMPERE"), "AMPERE- is inside AMP-")
        XCTAssertTrue(all[0].narrower.contains("AMPERE"), "and is carried on it")
    }

    /// Folding is about the chain, not about size. Two unrelated families of very
    /// different sizes both stay.
    func testAnUnrelatedFamilyIsNotFolded() {
        let solved = Fixture.solved([("AMPERE", [0]), ("AMPERES", [1]), ("AMPLE", [2]),
                                     ("HOLES", [3]), ("HOLED", [4])])
        let stems = BoardFamilies.all(on: solved, found: [], index: nil).map(\.stem)
        XCTAssertTrue(stems.contains("AMP"))
        XCTAssertTrue(stems.contains("HOLE"))
    }

    /// The fold is total on a chain, and that is a theorem rather than a heuristic: if S
    /// is a substring of T then every word containing T contains S, so a longer stem's
    /// members are always a subset of a shorter one's. A narrower level can therefore
    /// never carry a word its parent lacks, and the whole chain always collapses to one
    /// row. The rule that keeps the *longer* stem applies only to sets that are equal.
    func testALongerStemCanNeverReachAWordItsParentLacks() {
        let solved = Fixture.solved([("AMPERE", [0]), ("AMPLE", [1]), ("RAMP", [2]),
                                     ("CAMP", [3])])
        let all = BoardFamilies.all(on: solved, found: [], index: nil)
        let amp = try? XCTUnwrap(all.first { $0.stem == "AMP" })
        XCTAssertEqual(amp?.members.count, 4)
        for family in all where family.stem != "AMP" {
            XCTAssertFalse(family.stem.contains("AMP"),
                           "\(family.stem)- is inside AMP- and should have folded")
        }
    }
}

extension BoardFamiliesTests {
    /// SPEC 7.5's band, on this board. A stem with 89 members is "every word with -ING in
    /// it", not something to hunt for; a stem with one is a word.
    func testTheCueBandIsTheEnumerableOne() {
        let two = families(["HOLE", "HOLES"]).first { $0.stem == "HOLE" }
        XCTAssertTrue(two?.isCue ?? false)

        var many: [String] = []
        for i in 0..<9 { many.append("HOLE" + String(Array("ABCDEFGHI")[i])) }
        let big = families(many).first { $0.stem == "HOLE" }
        XCTAssertEqual(big?.members.count, 9)
        XCTAssertFalse(big?.isCue ?? true, "nine members is a list, not a cue")
    }
}

/// Mixed practice: what goes in and what comes back.
final class MixedSelectionTests: XCTestCase {
    private func ranked(_ stems: [String]) -> [TrainingQueue.Ranked] {
        stems.enumerated().map { i, stem in
            TrainingQueue.Ranked(
                hook: Fixture.hook(stem, [Fixture.branch(stem + "S", gain: Double(10 - i))]),
                owned: 2, learning: 1, unknown: 1, expectedGain: Double(10 - i),
                effort: 1, score: Double(10 - i), eligible: true)
        }
    }

    /// The bug behind "they are the same every time": `queue.ranked` is sorted
    /// deterministically, so taking the top N off it is the same N for ever.
    func testTheDefaultSelectionVaries() {
        let candidates = ranked((0..<12).map { "ST\($0)" }).map {
            MixedCandidate(hook: $0.hook, reason: .queued, lastMet: nil, owned: 2,
                           worthKnowing: 3)
        }
        var seen: Set<Set<String>> = []
        for _ in 0..<40 { seen.insert(MixedCandidates.defaultSelection(from: candidates)) }
        XCTAssertGreaterThan(seen.count, 1, "the same families every time is not practice")
    }

    func testTheDefaultSelectionIsTheRightSize() {
        let candidates = ranked((0..<12).map { "ST\($0)" }).map {
            MixedCandidate(hook: $0.hook, reason: .queued, lastMet: nil, owned: 2,
                           worthKnowing: 3)
        }
        let chosen = MixedCandidates.defaultSelection(from: candidates)
        XCTAssertTrue(MixedCandidates.range.contains(chosen.count))
    }

    /// A short list still produces a playable mix rather than an empty one.
    func testAThinCandidateListStillFills() {
        let candidates = ranked(["ERAS", "TORE"]).map {
            MixedCandidate(hook: $0.hook, reason: .drilled, lastMet: nil, owned: 2,
                           worthKnowing: 3)
        }
        XCTAssertEqual(MixedCandidates.defaultSelection(from: candidates).count, 2)
    }

    /// Every family asked for is reported, including one the generator could not place.
    /// The old code dropped those silently, which is why review looked unrelated.
    func testAFamilyThatCouldNotBePlacedIsStillReported() {
        let absent = BoardReview.MixedResult(stem: "SIREE", present: 0, found: 0)
        XCTAssertEqual(absent.outcome, .absent)
        XCTAssertEqual(absent.label, "not on the board")
    }
}

extension MixedSelectionTests {
    /// "7 of 5 worth knowing" was on screen: owned counted every branch the recompute
    /// calls known, and the denominator counted only the branches above the value floor.
    func testOwnedAndWorthKnowingShareADenominator() {
        let hook = Fixture.hook("TORE", [
            Fixture.branch("STORED", gain: 6),     // worth knowing
            Fixture.branch("RESTORE", gain: 4),    // worth knowing
            Fixture.branch("TUTORED", gain: 0.1),  // below the floor
        ])
        let worth = hook.liveBranches.filter {
            $0.earns && $0.expectedGain >= FamilyPage.worthKnowingFloor
        }
        XCTAssertEqual(worth.count, 2)
        // Whatever the owned count is, it is drawn from `worth` and so cannot exceed it.
        let candidate = MixedCandidate(hook: hook, reason: .drilled, lastMet: nil,
                                       owned: worth.count, worthKnowing: worth.count)
        XCTAssertLessThanOrEqual(candidate.owned, candidate.worthKnowing)
        XCTAssertTrue(candidate.detail.hasPrefix("2 of 2 worth knowing"))
    }
}

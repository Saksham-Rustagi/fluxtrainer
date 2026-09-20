import XCTest
@testable import FluxClone

/// The hook record as it is actually shipped. These run against the bundled file, not a
/// fixture, because the thing most likely to break is the contract between
/// `tools/queue/hookrecord.py` and `HookRecord.swift`, and a fixture would agree with
/// whichever side wrote it.
final class HookRecordTests: XCTestCase {
    private static let bundle: HookBundle? = try? HookBundle.parse()

    private func loaded() throws -> HookBundle {
        try XCTUnwrap(Self.bundle, "training_hooks.json did not parse: \(HookBundle.loadError ?? "")")
    }

    func testBundleParsesAndCarriesWhatTheSessionNeeds() throws {
        let bundle = try loaded()
        XCTAssertEqual(bundle.schema, HookBundle.expectedSchema)
        XCTAssertGreaterThan(bundle.hooks.count, 100)
        XCTAssertEqual(bundle.queueTotal, 10594, "the Phase 2 queue is 10,594 hooks")

        // The density band, per grid, measured from the player's own boards.
        for side in [4, 5] {
            let band = try XCTUnwrap(bundle.density[side])
            XCTAssertLessThan(band.minWords, band.medianWords)
            XCTAssertLessThan(band.medianWords, band.maxWords)
        }
        // 5x5 boards are denser than 4x4 ones; a band that said otherwise would be wired
        // to the wrong grid. The bands themselves overlap -- a dense 4x4 and a sparse 5x5
        // meet around 500 words -- so it is the centres that have to separate.
        XCTAssertGreaterThan(bundle.density[5]!.medianWords, bundle.density[4]!.medianWords)
        XCTAssertGreaterThan(bundle.density[5]!.minWords, bundle.density[4]!.minWords)

        // SPEC 7.3 mechanism 3: the affix alphabet, both directions.
        XCTAssertEqual(bundle.minedAffixes.count, 60)
        XCTAssertTrue(bundle.minedAffixes.contains { $0.side == "back" && $0.letters == "ERS" })
        XCTAssertTrue(bundle.minedAffixes.contains { $0.side == "front" && $0.letters == "RE" })

        // The belief constants, needed before an in-app presence can be added to a ranked
        // one on the same scale.
        XCTAssertFalse(bundle.opportunityRef.isEmpty)
        for lc in 3...7 { XCTAssertNotNil(bundle.beliefPriors[lc]) }
    }

    func testEveryHookIsUsableAsATeachingUnit() throws {
        let bundle = try loaded()
        for hook in bundle.hooks {
            XCTAssertFalse(hook.stem.isEmpty)
            XCTAssertEqual(hook.stemLen, hook.stem.count)
            // The bundle is the session's pool, so everything in it must pass SPEC 7.5's
            // cue band -- the filter the session applies.
            XCTAssertTrue((2.0...6.0).contains(hook.enumerability), "\(hook.stem)")
            XCTAssertFalse(hook.branches.isEmpty, "\(hook.stem)")
            // Every additive branch really does contain the stem: that is SPEC 7.3's
            // classification rule, and the app relies on it to read branches off a board.
            for branch in hook.branches where branch.cls == .additive {
                XCTAssertTrue(branch.word.contains(hook.stem),
                              "\(branch.word) is additive on \(hook.stem) but does not contain it")
            }
            for branch in hook.branches where branch.cls == .dead {
                XCTAssertEqual(branch.myRate, nil)
                XCTAssertFalse(branch.earns)
            }
        }
    }

    /// The live half must be the residual, in value order. The bug this replaces sorted
    /// alphabetically, which buried STORE and STORED under PRESTORED and PROTORES and
    /// turned a three-word problem into a 73-card deck.
    func testDeckLeadsWithWhatTheQueueIsTeaching() throws {
        let bundle = try loaded()
        for hook in bundle.hooks.prefix(40) {
            let live = AffixGridBuilder.live(for: hook)
            XCTAssertLessThanOrEqual(live.count, AffixGridBuilder.liveCap)
            XCTAssertTrue(live.allSatisfy { $0.isLive })
            // Nothing already owned is on a card: SPEC 7.5.1's residual, not the family.
            for item in live {
                XCTAssertNotEqual(hook.branch(item.word)?.status, "known", "\(item.word)")
            }
            // The study items come first, in expected-gain order.
            let study = live.compactMap { hook.branch($0.word) }
                .filter { $0.earns && $0.expectedGain > 0 }
            XCTAssertEqual(study.map(\.expectedGain), study.map(\.expectedGain).sorted(by: >),
                           "\(hook.stem) is not in value order")
        }

        // TORE- is the worked example: four words carry gain and they must lead.
        if let tore = bundle.hooks.first(where: { $0.stem == "TORE" }) {
            let words = AffixGridBuilder.live(for: tore).map(\.word)
            XCTAssertEqual(Array(words.prefix(4)), ["STORE", "STORES", "STORED", "STORER"])
            XCTAssertFalse(words.contains("PROTORES"))
        }
    }

    /// The dead half comes from strings the player has actually swiped, from the shipped
    /// log and from the app's own attempts, and from nowhere else.
    func testDeadHalfIsOnlyRealMisswipes() throws {
        let bundle = try loaded()
        XCTAssertGreaterThan(bundle.misswipes.count, 300, "the invalid-attempt log is shipped")

        let tore = try XCTUnwrap(bundle.hooks.first { $0.stem == "TORE" })
        // The dictionary-mined junk must not come back.
        let shipped = AffixGridBuilder.dead(for: tore, shipped: bundle.misswipes, inApp: [:])
        XCTAssertFalse(shipped.contains { $0.word == "TOREER" })
        XCTAssertFalse(shipped.contains { $0.word == "GTORE" })
        XCTAssertTrue(shipped.allSatisfy { $0.fromMisswipe && !$0.isLive })

        // An attempt made in the app feeds the set, ordered by how often it was tried, and
        // the stem's own misswipes come first however rare they are: NOTRELATED was tried
        // nine times and still ranks below TOREE, tried once, because TOREE is about TORE.
        let withInApp = AffixGridBuilder.dead(for: tore, shipped: ["TOREE": 1],
                                              inApp: ["TORER": 4, "NOTRELATED": 9])
        XCTAssertEqual(withInApp.prefix(2).map(\.word), ["TORER", "TOREE"])
        XCTAssertEqual(withInApp.first?.ext, "-R")
        XCTAssertEqual(withInApp.last?.word, "NOTRELATED", "borrowed to meet the floor")
        XCTAssertEqual(withInApp.last?.ext, "your own misswipe")

        // A stem with nothing logged against it still gets a few cards, borrowed from the
        // rest of his own log: a deck whose answer is always "Word" trains pressing Word,
        // and a fast reflexive Word reads as `known` and corrupts the sort.
        let borrowed = AffixGridBuilder.dead(for: tore, shipped: ["RALL": 5, "SOLT": 3, "REA": 2],
                                             inApp: [:])
        XCTAssertEqual(borrowed.count, AffixGridBuilder.deadFloor)
        XCTAssertTrue(borrowed.allSatisfy { $0.fromMisswipe && !$0.isLive })
        XCTAssertEqual(borrowed.first?.word, "RALL")          // most-attempted first
        XCTAssertEqual(borrowed.first?.ext, "your own misswipe")

        // With nothing logged at all there is nothing to borrow, and that is honest.
        XCTAssertTrue(AffixGridBuilder.dead(for: tore, shipped: [:], inApp: [:]).isEmpty)
    }

    func testExtensionDisplayReadsAgainstTheStem() {
        XCTAssertEqual(AffixGridBuilder.extDisplay("TORER", stem: "TORE"), "-R")
        XCTAssertEqual(AffixGridBuilder.extDisplay("STORE", stem: "TORE"), "S-")
        XCTAssertEqual(AffixGridBuilder.extDisplay("STORED", stem: "TORE"), "S--D")
        XCTAssertEqual(AffixGridBuilder.extDisplay("TORE", stem: "TORE"), "TORE")
    }

}

/// Board geometry and the branch derivation the whole drill rests on.
final class TrainingBoardGeometryTests: XCTestCase {
    // A 4x4 board whose letters are laid out so RAI has exactly one path.
    //   R A I N
    //   S T O P
    //   E D U C
    //   K L M F
    let letters: [Character] = Array("RAINSTOPEDUCKLMF")

    func testStemPathsFindEveryPathAndOnlyRealOnes() {
        let paths = BoardGeometryUtil.paths(of: "RAI", letters: letters, side: 4)
        XCTAssertEqual(paths, [[0, 1, 2]])

        // A path may not reuse a cell (spec 2.1).
        XCTAssertTrue(BoardGeometryUtil.paths(of: "RAR", letters: letters, side: 4).isEmpty)
        // Non-adjacent letters have no path.
        XCTAssertTrue(BoardGeometryUtil.paths(of: "RN", letters: letters, side: 4).isEmpty)
        // Diagonals count.
        XCTAssertEqual(BoardGeometryUtil.paths(of: "RT", letters: letters, side: 4), [[0, 5]])

        // Every returned path spells the word along real adjacencies.
        let geo = GridGeometry(side: 4, tileSize: 10, spacing: 0)
        for path in BoardGeometryUtil.paths(of: "STOP", letters: letters, side: 4) {
            XCTAssertEqual(String(path.map { letters[$0] }), "STOP")
            for (a, b) in zip(path, path.dropFirst()) { XCTAssertTrue(geo.adjacent(a, b)) }
        }
    }

    func testContiguousSubpathIsExactlyThePathCondition() {
        XCTAssertTrue([3, 4, 5, 6].contains(subpath: [4, 5]))
        XCTAssertTrue([3, 4, 5, 6].contains(subpath: [3, 4, 5, 6]))
        // Same cells, not contiguous in order: the stem's path is not inside it.
        XCTAssertFalse([3, 4, 5, 6].contains(subpath: [4, 6]))
        // Order matters -- a reversed stem is a different path.
        XCTAssertFalse([3, 4, 5, 6].contains(subpath: [5, 4]))
        XCTAssertFalse([3, 4].contains(subpath: [3, 4, 5]))
        XCTAssertFalse([3, 4].contains(subpath: []))
    }
}

/// The engine's Phase 3 entry points, against the real DAWG and ruleset.
final class TrainingEngineTests: XCTestCase {
    let engine = FluxEngine.shared

    func testSolveReturnsRealPathsForEveryWord() {
        guard let board = engine.generateRanked(side: 4, tier: .goodCasual, rootSeed: 4242)
        else { return XCTFail("no board") }
        let solved = engine.solve(side: board.side, letters: board.letters)
        XCTAssertGreaterThan(solved.count, 50)
        XCTAssertEqual(solved.totalPoints, board.potentialPoints)
        XCTAssertEqual(solved.count, board.potentialWords)

        let geo = GridGeometry(side: board.side, tileSize: 10, spacing: 0)
        for word in solved.words {
            XCTAssertFalse(word.paths.isEmpty, word.word)
            XCTAssertLessThanOrEqual(word.paths.count, min(word.pathCount, 8))
            for path in word.paths {
                XCTAssertEqual(String(path.map { board.letters[$0] }), word.word)
                XCTAssertEqual(Set(path).count, path.count, "a path may not reuse a cell")
                for (a, b) in zip(path, path.dropFirst()) { XCTAssertTrue(geo.adjacent(a, b)) }
            }
            XCTAssertNotNil(engine.wordId(word.word))
        }
    }

    func testDrillBoardCarriesTheHookAndThreeToSixReachableBranches() throws {
        let bundle = try XCTUnwrap(try? HookBundle.parse())
        // A few hooks from the top of the queue: the ones the session will actually serve.
        for hook in bundle.hooks.prefix(5) {
            guard let board = TrainingBoards.drill(hook: hook, engine: engine) else {
                XCTFail("no drill board for \(hook.stem)")
                continue
            }
            let lit = try XCTUnwrap(board.litPath)
            XCTAssertEqual(String(lit.map { board.letters[$0] }), hook.stem)
            XCTAssertFalse(board.targets.isEmpty)
            if !board.degraded {
                XCTAssertTrue(TrainingBoards.targetRange.contains(board.targets.count),
                              "\(hook.stem): \(board.targets.count) targets")
            }
            for word in board.targets {
                // Additive by containment, present on the board, and reachable by
                // extending the path that is lit. All three, or the drill is a lie.
                XCTAssertTrue(word.contains(hook.stem))
                let solvedWord = try XCTUnwrap(board.solved.word(word))
                XCTAssertTrue(solvedWord.paths.contains { $0.contains(subpath: lit) },
                              "\(word) does not extend the lit \(hook.stem)")
            }
        }
    }

    func testAcquisitionBoardSitsInsideTheMeasuredDensityBand() throws {
        let bundle = try XCTUnwrap(try? HookBundle.parse())
        for hook in bundle.hooks.prefix(4) {
            guard let board = TrainingBoards.acquisition(hook: hook, engine: engine,
                                                         density: bundle.density) else {
                XCTFail("no acquisition board for \(hook.stem)")
                continue
            }
            XCTAssertNil(board.litPath, "a sweep board lights nothing")
            XCTAssertFalse(BoardGeometryUtil.paths(of: hook.stem, letters: board.letters,
                                                   side: board.side).isEmpty)
            XCTAssertNotEqual(board.board.tier, .spam, "acquisition boards are never Spam")
            if !board.degraded, let band = bundle.density[board.side] {
                XCTAssertGreaterThanOrEqual(board.solved.count, band.minWords)
                XCTAssertLessThanOrEqual(board.solved.count, band.maxWords)
            }
        }
    }

    /// The board must not be identifiable as a training board. The one measurable part of
    /// that is density: a board that came out at twice the ranked median would announce
    /// itself before the first swipe.
    func testAcquisitionBoardsLookLikeRankedBoards() throws {
        let bundle = try XCTUnwrap(try? HookBundle.parse())
        let hook = bundle.hooks[0]
        var counts: [Int] = []
        for _ in 0..<6 {
            guard let board = TrainingBoards.acquisition(hook: hook, engine: engine,
                                                         density: bundle.density),
                  let band = bundle.density[board.side] else { continue }
            counts.append(board.solved.count)
            XCTAssertLessThanOrEqual(board.solved.count, band.maxWords)
        }
        XCTAssertFalse(counts.isEmpty)
    }
}

/// The know-against-see sort: SPEC 8.1's calibration, done per hook with the exercise the
/// app already has.
final class WordKnowledgeTests: XCTestCase {
    func testLatencySeparatesRecognitionFromDerivation() {
        // A fast correct call is recognition: you know the word.
        XCTAssertEqual(WordKnowledge.classify(correct: true, latency: 0.4), .known)
        XCTAssertEqual(WordKnowledge.classify(correct: true, latency: 1.2), .known)
        // A slow correct call means you worked it out, which is not the same thing.
        XCTAssertEqual(WordKnowledge.classify(correct: true, latency: 2.6), .shaky)
        // Wrong is wrong however fast.
        XCTAssertEqual(WordKnowledge.classify(correct: false, latency: 0.3), .unknown)
        XCTAssertEqual(WordKnowledge.classify(correct: false, latency: 9.0), .unknown)
    }

    func testOnlyTheVocabularyVerdictsCountAsVocabulary() {
        XCTAssertFalse(WordKnowledge.Verdict.known.isVocabulary)
        XCTAssertTrue(WordKnowledge.Verdict.shaky.isVocabulary)
        XCTAssertTrue(WordKnowledge.Verdict.unknown.isVocabulary)
        XCTAssertFalse(WordKnowledge.Verdict.unjudged.isVocabulary)
    }

    /// The line the app never showed, in the player's own numbers.
    func testSightGapReadsAsASentence() throws {
        let bundle = try XCTUnwrap(try? HookBundle.parse())
        let eras = try XCTUnwrap(bundle.hooks.first { $0.stem == "ERAS" })
        let erase = try XCTUnwrap(eras.branch("ERASE"))
        let gap = try XCTUnwrap(SightGap(branch: erase))
        XCTAssertEqual(gap.sentence,
                       "ERASE was on 243 of your boards. You found it twice. "
                       + "The top 25% find it 28% of the time.")

        // Worst first, by points a game rather than by raw rate difference: ERASES has a
        // marginally wider rate gap and is on a third as many boards.
        let gaps = SightGap.forHook(eras)
        XCTAssertEqual(gaps.first?.word, "ERASE")
        XCTAssertGreaterThan(gaps[0].expectedGain, gaps[1].expectedGain)

        // A word with too little evidence gets no sentence rather than a made-up one.
        let thin = Branch(word: "XYZZY", cls: .additive, ext: "", points: 800,
                          reachability: 0.5, reachSource: "fitted", myRate: 0,
                          topQuartileRate: 0.4, nTopQuartile: 40, fieldRate: 0.2,
                          presences: 3, finds: 0,
                          opportunity: 1, presencesPerGame: 0.01, belief: 0.1,
                          status: "unknown", expectedGain: 0, earns: true, misswiped: 0)
        XCTAssertNil(SightGap(branch: thin))
    }
}

/// SPEC 8.1 as Phase 3 continues it.
final class BeliefTests: XCTestCase {
    let priors: [Int: (a: Double, b: Double)] = [5: (0.53, 1.35)]

    func testOpportunityFallsAsTheBoardGetsDenser() {
        let reference = ["4x4_5": 0.34, "5x5_5": 0.21]
        // A sparse board where he took a third of the 5s: full opportunity.
        let sparse = Belief.opportunity(foundOfClass: 20, presentOfClass: 50, side: 4,
                                        length: 5, reference: reference)
        // A dense board where he took the same number: far less.
        let dense = Belief.opportunity(foundOfClass: 20, presentOfClass: 400, side: 4,
                                       length: 5, reference: reference)
        XCTAssertEqual(sparse, 1.0, accuracy: 1e-9, "capped at 1")
        XCTAssertLessThan(dense, 0.2)
        XCTAssertEqual(Belief.opportunity(foundOfClass: 0, presentOfClass: 0, side: 4,
                                          length: 5, reference: reference), 0)
    }

    func testMissOnADenseBoardBarelyMovesBelief() {
        let base = Belief.belief(length: 5, rankedFinds: 2, rankedOpportunity: 10,
                                 inAppFinds: 0, inAppOpportunity: 0, priors: priors)
        let afterDenseMiss = Belief.belief(length: 5, rankedFinds: 2, rankedOpportunity: 10,
                                           inAppFinds: 0, inAppOpportunity: 0.05, priors: priors)
        let afterSparseMiss = Belief.belief(length: 5, rankedFinds: 2, rankedOpportunity: 10,
                                            inAppFinds: 0, inAppOpportunity: 1, priors: priors)
        XCTAssertLessThan(afterDenseMiss, base)
        XCTAssertLessThan(afterSparseMiss, afterDenseMiss)
        XCTAssertEqual(afterDenseMiss, base, accuracy: 0.01)
    }

    /// The rule the brief is emphatic about: drilling a hook must not make it look
    /// learned. A find with the stem lit has to move belief much less than the same find
    /// unprompted, or the hook leaves the queue having taught nothing transferable.
    func testALitFindCountsForFarLessThanAnUnpromptedOne() {
        func after(_ evidence: Belief.Evidence) -> Double {
            let c = Belief.contribution(found: true, opportunity: 0.8, evidence: evidence)
            return Belief.belief(length: 5, rankedFinds: 0, rankedOpportunity: 12,
                                 inAppFinds: c.finds, inAppOpportunity: c.opportunity,
                                 priors: priors)
        }
        let unprompted = after(.unpromptedBoard)
        let sweep = after(.familySweep)
        let lit = after(.litDrill)
        let grid = after(.affixGrid)
        XCTAssertGreaterThan(unprompted, sweep)
        XCTAssertGreaterThan(sweep, lit)
        XCTAssertGreaterThan(lit, grid)
        // Four lit finds are still worth less than one unprompted one.
        let fourLit = Belief.belief(length: 5, rankedFinds: 0, rankedOpportunity: 12,
                                    inAppFinds: 4 * Belief.Evidence.litDrill.weight,
                                    inAppOpportunity: 4 * Belief.Evidence.litDrill.weight * 0.8,
                                    priors: priors)
        XCTAssertLessThanOrEqual(fourLit, unprompted + 1e-9)
    }

    func testStatusUsesTheSpecThresholds() {
        XCTAssertEqual(Belief.status(0.9), "known")
        XCTAssertEqual(Belief.status(0.5), "learning")
        XCTAssertEqual(Belief.status(0.1), "unknown")
    }
}

/// A board is worth drilling when either half is open -- the word is unlearned, or there
/// is room between how often he takes it and how often someone who sees it does.
final class WorthDrillingTests: XCTestCase {
    private func branch(_ word: String, status: String, gain: Double) -> Branch {
        Branch(word: word, cls: .additive, ext: "", points: 800, reachability: 0.4,
               reachSource: "observed", myRate: 0.4, topQuartileRate: 0.6, nTopQuartile: 90,
               fieldRate: 0.5, presences: 200, finds: 80, opportunity: 120,
               presencesPerGame: 0.08,
               belief: 0.7, status: status, expectedGain: gain, earns: true, misswiped: 0)
    }

    private func hook(_ branches: [Branch]) -> Hook {
        Hook(stem: "TORE", stemLen: 4, isWord: true, rank: 2, track: "par", score: 8,
             expectedGain: 33, residual: 830, enumerability: 2.4,
             enumerabilitySource: "observed", cueable: true, owned: 8, learning: 24,
             unknown: 87, studyItems: 4, familySize: 60, branchCount: 140,
             presentShare: 0.13, presentGames: 384, presenceByTierGrid: [:],
             deadBranches: 56, deadPoints: 0.9, why: "", branches: branches)
    }

    func testAKnownWordWithARealSightGapIsStillWorthDrilling() {
        // STORE: he knows it and takes it 42% of the time against the top quartile's 58%.
        // The old test rejected this board. That was the bug behind "I already know these".
        let h = hook([branch("STORE", status: "known", gain: 10.7)])
        XCTAssertTrue(TrainingBoards.worthDrilling(hook: h, targets: ["STORE"]))
    }

    func testAKnownWordWithNoGapLeftIsNot() {
        let h = hook([branch("TORES", status: "known", gain: 0)])
        XCTAssertFalse(TrainingBoards.worthDrilling(hook: h, targets: ["TORES"]))
    }

    func testAnUnlearnedWordIsWorthDrillingWithOrWithoutAGap() {
        let h = hook([branch("STOREY", status: "unknown", gain: 0)])
        XCTAssertTrue(TrainingBoards.worthDrilling(hook: h, targets: ["STOREY"]))
    }

    func testAWordNotOnTheHookAtAllCountsAsUnseen() {
        XCTAssertTrue(TrainingBoards.worthDrilling(hook: hook([]), targets: ["ANYTHING"]))
    }
}

/// The session's shape, which is the part a user notices when it is wrong.
@MainActor
final class SessionPlanTests: XCTestCase {
    private func hook(_ stem: String) -> Hook {
        Hook(stem: stem, stemLen: stem.count, isWord: true, rank: 1, track: "par", score: 1,
             expectedGain: 1, residual: 1, enumerability: 3, enumerabilitySource: "observed",
             cueable: true, owned: 3, learning: 1, unknown: 2, studyItems: 2, familySize: 10,
             branchCount: 12, presentShare: 0.1, presentGames: 100, presenceByTierGrid: [:],
             deadBranches: 10, deadPoints: 1, why: "", branches: [])
    }

    /// The grid comes before the board, because it is a sorting step: its answers and
    /// latencies decide whether the drill that follows is about seeing or about knowing.
    func testFullDaySortsBeforeItDrills() {
        let plan = TrainingSession.buildPlan(newHook: hook("RAI"), due: [], shortDay: false)
        XCTAssertEqual(plan, [.warmup,
                              .affixGrid(stem: "RAI"),
                              .drill(stem: "RAI", attempt: 1),
                              .drill(stem: "RAI", attempt: 2),
                              .summary])
    }

    /// A short day is one board plus one grid, graded normally. Grading it at reduced
    /// weight would penalise having a life and make the schedule drift on exactly the
    /// days it should not.
    func testShortDayIsOneBoardAndOneGrid() {
        let plan = TrainingSession.buildPlan(newHook: hook("RAI"), due: [hook("TORE")],
                                             shortDay: true)
        XCTAssertEqual(plan, [.affixGrid(stem: "RAI"),
                              .drill(stem: "RAI", attempt: 1),
                              .summary])
    }

    func testDueHooksGetTwoAcquisitionBoardsBetweenThem() {
        let one = TrainingSession.buildPlan(newHook: nil, due: [hook("TORE")], shortDay: false)
        XCTAssertEqual(one, [.warmup, .sweep(stem: "TORE", attempt: 1),
                             .sweep(stem: "TORE", attempt: 2), .summary])

        let two = TrainingSession.buildPlan(newHook: nil, due: [hook("TORE"), hook("TANE")],
                                            shortDay: false)
        XCTAssertEqual(two, [.warmup, .sweep(stem: "TORE", attempt: 1),
                             .sweep(stem: "TANE", attempt: 1), .summary])
    }

    /// Nothing to teach is still a session: the warm-up is worth about 1,633 points on
    /// game 1 and costs one board.
    func testNothingDueStillGivesAWarmUp() {
        XCTAssertEqual(TrainingSession.buildPlan(newHook: nil, due: [], shortDay: false),
                       [.warmup, .summary])
    }
}

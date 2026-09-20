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

    func testAffixDeckIsHalfDeadAndLeadsWithMisswipes() throws {
        let bundle = try loaded()
        let hook = try XCTUnwrap(bundle.hooks.first { $0.branches.contains { $0.cls == .dead } })
        let deck = AffixGridBuilder.deck(for: hook, size: 40)
        XCTAssertFalse(deck.isEmpty)
        let dead = deck.filter { !$0.isLive }
        // Dead branches carry equal weight: knowing a branch is dead is worth as much as
        // knowing one is live.
        XCTAssertGreaterThan(dead.count, deck.count / 3)
        XCTAssertLessThan(dead.count, deck.count * 2 / 3 + 1)
        // Nothing in the deck is a cellmate: an anagram is not an affix judgement.
        XCTAssertFalse(deck.contains { $0.cls == .cellmate })

        // A stem with misswiped strings puts them in the deck before dictionary-derived
        // ones. Checked on a hook that actually has some.
        if let withMisswipe = bundle.hooks.first(where: {
            $0.branches.contains { $0.cls == .dead && $0.misswiped > 0 }
        }) {
            let d = AffixGridBuilder.deck(for: withMisswipe, size: 40)
            XCTAssertTrue(d.contains { $0.fromMisswipe })
        }
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

    func testFullDayIsWarmUpThenTwoDrillsThenTheGrid() {
        let plan = TrainingSession.buildPlan(newHook: hook("RAI"), due: [], shortDay: false)
        XCTAssertEqual(plan, [.warmup,
                              .drill(stem: "RAI", attempt: 1),
                              .drill(stem: "RAI", attempt: 2),
                              .affixGrid(stem: "RAI"),
                              .summary])
    }

    /// A short day is one board plus one grid, graded normally. Grading it at reduced
    /// weight would penalise having a life and make the schedule drift on exactly the
    /// days it should not.
    func testShortDayIsOneBoardAndOneGrid() {
        let plan = TrainingSession.buildPlan(newHook: hook("RAI"), due: [hook("TORE")],
                                             shortDay: true)
        XCTAssertEqual(plan, [.drill(stem: "RAI", attempt: 1),
                              .affixGrid(stem: "RAI"),
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

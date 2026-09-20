import XCTest
@testable import FluxClone

/// The port's rules against Flux's (docs/CLONE_RECON.md d): 8-way adjacency, retrace is a
/// no-op, non-adjacent tiles are ignored, off-grid does not cancel, first tile by rect,
/// later tiles by the 0.43 circle, no interpolation.
final class RecognizerTests: XCTestCase {
    // 4x4, 72 pt tiles, no spacing: centres at 36, 108, 180, 252.
    let geo = GridGeometry(side: 4, tileSize: 72, spacing: 0)

    func c(_ cell: Int) -> CGPoint { geo.center(cell) }

    func testFirstTileUsesFullRectLaterTilesUseCircle() {
        let r = Recognizer(geometry: geo, config: .flux)
        // A cell corner is outside the circle but inside the rect.
        XCTAssertEqual(r.begin(at: CGPoint(x: 2, y: 2)), [0])
        // Corner of cell 5, adjacent to 0: rect yes, circle no.
        XCTAssertEqual(r.move(to: CGPoint(x: 74, y: 74)), [])
        XCTAssertEqual(r.move(to: c(5)), [5])
        XCTAssertEqual(r.path, [0, 5])
    }

    func testCircleRadiusIs043OfTile() {
        let r = Recognizer(geometry: geo, config: .flux)
        r.begin(at: c(0))
        // 0.43 * 72 = 30.96 pt from cell 1's centre.
        XCTAssertEqual(r.move(to: CGPoint(x: 108 - 30.9, y: 36)), [1])
        let r2 = Recognizer(geometry: geo, config: .flux)
        r2.begin(at: c(0))
        XCTAssertEqual(r2.move(to: CGPoint(x: 108 - 31.1, y: 36)), [])
    }

    func testRetraceIsNoOpAndDoesNotUndo() {
        let r = Recognizer(geometry: geo, config: .flux)
        r.begin(at: c(0))
        r.move(to: c(1))
        r.move(to: c(2))
        XCTAssertEqual(r.move(to: c(1)), [])  // back onto the previous tile
        XCTAssertEqual(r.move(to: c(0)), [])
        XCTAssertEqual(r.path, [0, 1, 2])
    }

    func testNonAdjacentIgnoredPathContinuesFromLast() {
        let r = Recognizer(geometry: geo, config: .flux)
        r.begin(at: c(0))
        XCTAssertEqual(r.move(to: c(2)), [])   // skipped over 1
        XCTAssertEqual(r.move(to: c(1)), [1])  // adjacent to 0 again
        XCTAssertEqual(r.move(to: c(2)), [2])
    }

    func testDiagonalThroughCornerDoesNotGrabNeighbours() {
        let r = Recognizer(geometry: geo, config: .flux)
        r.begin(at: c(0))
        // Straight line from centre of 0 to centre of 5 through the shared corner (72, 72).
        for i in 1...36 {
            let t = CGFloat(i) / 36
            r.move(to: CGPoint(x: 36 + 72 * t, y: 36 + 72 * t))
        }
        XCTAssertEqual(r.path, [0, 5])
    }

    func testOffGridDoesNotCancel() {
        let r = Recognizer(geometry: geo, config: .flux)
        r.begin(at: c(0))
        XCTAssertEqual(r.move(to: CGPoint(x: -40, y: -40)), [])
        XCTAssertEqual(r.move(to: CGPoint(x: 500, y: 36)), [])
        XCTAssertEqual(r.move(to: c(1)), [1])
        XCTAssertEqual(r.path, [0, 1])
    }

    func testStartOffGridThenEnterSelectsFirstCircle() {
        let r = Recognizer(geometry: geo, config: .flux)
        XCTAssertEqual(r.begin(at: CGPoint(x: -20, y: -60)), [])
        XCTAssertEqual(r.move(to: c(10)), [10])  // any tile can be first
        XCTAssertEqual(r.move(to: c(15)), [15])
    }

    func testNoInterpolationSkipsCrossedTileSegmentDoesNot() {
        // One sample jump from the centre of 0 to the centre of 2 crosses tile 1.
        let flux = Recognizer(geometry: geo, config: .flux)
        flux.begin(at: c(0))
        flux.move(to: c(2))
        XCTAssertEqual(flux.path, [0])

        let seg = Recognizer(geometry: geo, config: .shadow)
        seg.begin(at: c(0))
        XCTAssertEqual(seg.move(to: c(2)), [1, 2])
    }

    func testSpacingGapIsOutsideRect() {
        let spaced = GridGeometry(side: 4, tileSize: 70, spacing: 4)
        XCTAssertNil(spaced.cellInRect(CGPoint(x: 72, y: 10)))  // in the gap
        XCTAssertEqual(spaced.cellInRect(CGPoint(x: 75, y: 10)), 1)
    }

    func testTileSizeFormula() {
        // iPhone 16 Pro, 402 pt: 72 on both grids.
        XCTAssertEqual(BoardSettings.flux.tileSize(side: 4, screenWidth: 402), 72)
        XCTAssertEqual(BoardSettings.flux.tileSize(side: 5, screenWidth: 402), 72)
        // 393 pt: 5x5 capped by (393 - 40) / 5.
        XCTAssertEqual(BoardSettings.flux.tileSize(side: 5, screenWidth: 393), 70.6, accuracy: 0.001)
    }

    func testScoring() {
        XCTAssertEqual([3, 4, 5, 6, 7, 8, 9].map(fluxPoints), [100, 400, 800, 1400, 1800, 2200, 2600])
        XCTAssertEqual(fluxPoints(forLength: 2), 0)
    }
}

final class AffixTests: XCTestCase {
    let words: Set<String> = ["HAPPY", "BAKE", "RUN", "STEM", "DO", "TIE", "TIES"]

    func classify(_ w: String) -> String? {
        AffixClassifier.classify(w) { self.words.contains($0) }.map { "\($0.affix) \($0.stem)" }
    }

    func testAffixes() {
        XCTAssertEqual(classify("HAPPIER"), "-IER HAPPY")
        XCTAssertEqual(classify("BAKING"), "-ING BAKE")
        XCTAssertEqual(classify("RUNNER"), "-ER RUN")
        XCTAssertEqual(classify("STEMS"), "-S STEM")
        XCTAssertEqual(classify("REDO"), nil)  // too short for a prefix stem of 2
        XCTAssertEqual(classify("RESTEM"), "RE- STEM")
        XCTAssertNil(classify("QXZT"))
    }
}

final class EngineTests: XCTestCase {
    func testLoadsPinnedV3() {
        let e = FluxEngine.shared
        XCTAssertEqual(e.rulesetVersion, 3)
        XCTAssertEqual(e.dictionaryWords, 223_493)
        XCTAssertNotNil(e.wordId("QUA"))
        XCTAssertNil(e.wordId("LES"))  // one of the 419 Flux removals
        XCTAssertTrue(e.isPrefix("QUIC"))
        XCTAssertFalse(e.isPrefix("QXZ"))
    }

    func testGenerationIsFastAndSolved() {
        for (side, tier) in [(4, Tier.spam), (5, Tier.spam), (4, Tier.casual)] {
            let done = expectation(description: "gen \(side) \(tier)")
            FluxEngine.shared.generate(sideOverride: side, tierOverride: tier) { board in
                XCTAssertNotNil(board)
                if let board {
                    XCTAssertEqual(board.letters.count, side * side)
                    XCTAssertGreaterThan(board.potentialPoints, 0)
                    XCTAssertLessThan(board.generateMs + board.solveMs, 1000, "board must show in under a second")
                    print("gen \(side)x\(side) \(tier.name): N=\(board.realizedN) \(board.generateMs) ms")
                }
                done.fulfill()
            }
            wait(for: [done], timeout: 10)
        }
    }
}

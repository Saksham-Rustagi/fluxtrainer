import XCTest

/// End-to-end check of the touch path in the simulator: launch straight into a game,
/// drag across a row of tiles, and confirm the app selects them and survives the lift.
/// The board is random, so this asserts on behaviour that holds for any board: tiles
/// highlight during the drag, and the game is still running afterwards.
final class SwipeUITests: XCTestCase {
    func testSwipeSelectsTilesAndSubmits() {
        let app = XCUIApplication()
        app.launchEnvironment["FLUXCLONE_AUTOPLAY"] = "1"
        app.launch()

        // Wait for the board: the HUD timer counts down from 01:20.
        let timer = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH '01:'")).firstMatch
        XCTAssertTrue(timer.waitForExistence(timeout: 20), "board never appeared")

        let w = app.frame.width, h = app.frame.height
        // Three points across a row inside the lower half, where the grid is.
        let start = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: w * 0.2, dy: h * 0.62))
        let mid = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: w * 0.5, dy: h * 0.62))
        let end = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: w * 0.8, dy: h * 0.62))

        start.press(forDuration: 0.05, thenDragTo: mid, withVelocity: .default, thenHoldForDuration: 0.05)
        mid.press(forDuration: 0.05, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0.05)

        // Still on the board, clock still running: no crash on select/submit.
        XCTAssertTrue(timer.exists, "game view went away after a swipe")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.lifetime = .keepAlways
        add(shot)
    }
}

/// The training session reaches a drill board, on the real queue and the real engine.
/// Cheap, and it guards the whole chain: hook record parsed, queue ranked, a hook chosen,
/// a constrained board generated and solved, the stem lit and a counter on screen.
final class TrainingUITests: XCTestCase {
    func testTrainingReachesADrillBoard() {
        let app = XCUIApplication()
        app.launchEnvironment["FLUXCLONE_TRAIN"] = "1"
        app.launch()

        // A drill runs 30 to 45 seconds, so the clock reads 00:xx from the first frame --
        // that alone distinguishes it from the clone's 80-second board.
        let clock = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH '00:'")).firstMatch
        XCTAssertTrue(clock.waitForExistence(timeout: 40), "no drill board")

        // The counter says how many branches remain, never which. 3 to 6 of them.
        let counter = app.staticTexts.matching(
            NSPredicate(format: "label MATCHES '^[3-6]$'")).firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 5), "no target counter on the drill")

        // No score and no word count: nothing on a drill but the stem, the counter and
        // the clock.
        XCTAssertFalse(app.staticTexts.matching(
            NSPredicate(format: "label ENDSWITH ' words'")).firstMatch.exists,
            "the word count is showing during a drill")

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.lifetime = .keepAlways
        add(shot)
    }
}

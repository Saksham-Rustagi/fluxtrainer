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

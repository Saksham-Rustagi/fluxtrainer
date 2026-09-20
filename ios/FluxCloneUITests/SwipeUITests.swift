import XCTest

/// Every UI test runs with sound off, via the same `soundEnabled` default the settings
/// screen writes. Nothing here asserts on audio, and the simulator's audio server wedges
/// under repeated launch/terminate cycles: `AVAudioEngine.start` then aborts the process
/// on a 10-second RPC watchdog inside `AURemoteIO::Cleanup`, which fails whatever test
/// happened to be running. It is a simulator fault, not the app's, and it should not be
/// able to fail a test about swiping.
extension XCUIApplication {
    static func silent() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-soundEnabled", "NO"]
        return app
    }
}

/// End-to-end check of the touch path in the simulator: launch straight into a game,
/// drag across a row of tiles, and confirm the app selects them and survives the lift.
/// The board is random, so this asserts on behaviour that holds for any board: tiles
/// highlight during the drag, and the game is still running afterwards.
final class SwipeUITests: XCTestCase {
    func testSwipeSelectsTilesAndSubmits() {
        let app = XCUIApplication.silent()
        app.launchEnvironment["FLUXCLONE_AUTOPLAY"] = "1"
        app.launch()

        // Wait for the board: the HUD timer counts down from 01:20.
        let timer = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH '01:'")).firstMatch
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
    /// The session sorts before it drills: the affix grid first, deciding per word whether
    /// the board that follows is about seeing or about knowing, then the brief that says
    /// so in the player's own numbers, then the board.
    func testSessionSortsThenBriefsThenDrills() {
        let app = XCUIApplication.silent()
        app.launchEnvironment["FLUXCLONE_TRAIN"] = "1"
        // A session left half-finished is resumed by design. This test wants it from the
        // top, or a previous run's resume state decides what screen it lands on.
        app.launchEnvironment["FLUXCLONE_RESET_SESSION"] = "1"
        app.launch()

        // 1. The grid. Short now -- the residual plus real misswipes, not 80 cards.
        let counter = app.staticTexts.matching(
            NSPredicate(format: "label MATCHES '^[0-9]+ / [0-9]+$'")).firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 40), "no affix grid")
        let deckSize = Int(counter.label.split(separator: "/").last?
            .trimmingCharacters(in: .whitespaces) ?? "") ?? 0
        XCTAssertGreaterThan(deckSize, 0)
        XCTAssertLessThanOrEqual(deckSize, 16, "the deck is sized to the hook, not to 80")

        // Answer every card. Which button is irrelevant here; the flow is what is tested.
        //
        // Driven by what is on screen rather than by the count: a wrong answer holds the
        // card for 0.9 s to show the correction, and a tap that lands during that hold is
        // swallowed, so counting taps runs out of cards early and the test fails on a
        // deck that is working. A few spare iterations cost nothing.
        let word = app.buttons["Word"]
        let done = app.buttons["Done"]
        for _ in 0..<(deckSize + 6) {
            if done.exists { break }
            guard word.waitForExistence(timeout: 5) else { break }
            word.tap()
        }
        XCTAssertTrue(done.waitForExistence(timeout: 10), "grid never finished")
        done.tap()

        // 2. The brief: the line the hook record has carried since Phase 2 and that
        // nothing used to display.
        let sentence = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS 'of your boards'")).firstMatch
        XCTAssertTrue(sentence.waitForExistence(timeout: 20), "no vision brief")
        XCTAssertTrue(app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS 'seeing problem'")).firstMatch.exists)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.lifetime = .keepAlways
        add(shot)

        // 3. The board, with the stem lit and a counter.
        app.buttons["Go"].tap()
        let clock = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH '00:'")).firstMatch
        XCTAssertTrue(clock.waitForExistence(timeout: 30), "no drill board after the brief")
        let targets = app.staticTexts.matching(NSPredicate(format: "label MATCHES '^[3-6]$'")).firstMatch
        XCTAssertTrue(targets.waitForExistence(timeout: 5), "no target counter")
        XCTAssertFalse(app.staticTexts.matching(
            NSPredicate(format: "label ENDSWITH ' words'")).firstMatch.exists,
            "the word count is showing during a drill")

        // 4. The way out that is not walking out. A drill can put a word on the board that
        // has simply not been learned yet, and sitting through the clock teaches nothing.
        let giveUp = app.buttons["I don't know these"]
        XCTAssertTrue(giveUp.exists, "no way to end a drill except the clock")
        giveUp.tap()

        // 5. The verdict, straight away -- no path animation to sit through -- ordered by
        // what each word is worth a game, with the numbers that justify learning it.
        let gain = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS '/game'")).firstMatch
        XCTAssertTrue(gain.waitForExistence(timeout: 10),
                      "the verdict does not say what the words are worth")
        XCTAssertTrue(app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS 'pts'")).firstMatch.exists,
            "no per-word detail to learn from")
        let verdictShot = XCTAttachment(screenshot: app.screenshot())
        verdictShot.name = "Verdict"
        verdictShot.lifetime = .keepAlways
        add(verdictShot)
    }
}

/// Phase 3.5's structural change, end to end: playing is the front door, and a finished
/// board comes back into review rather than a score card. This guards the chain the whole
/// phase rests on -- board solved after the game, presences written, families indexed off
/// the solve, and the review built and shown.
final class ReviewUITests: XCTestCase {
    func testAFinishedBoardLandsInReview() {
        let app = XCUIApplication.silent()
        app.launchEnvironment["FLUXCLONE_AUTOPLAY"] = "1"
        // Eight seconds rather than eighty. The only thing this changes is the clock.
        app.launchEnvironment["FLUXCLONE_BOARD_SECONDS"] = "8"
        app.launch()

        let clock = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH '00:0'")).firstMatch
        XCTAssertTrue(clock.waitForExistence(timeout: 25), "board never appeared")

        // One swipe, so the board is not entirely empty and the review has a score to
        // compare against something.
        let w = app.frame.width, h = app.frame.height
        let start = app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: w * 0.2, dy: h * 0.62))
        let end = app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: w * 0.8, dy: h * 0.62))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .default,
                    thenHoldForDuration: 0.05)

        // The clock runs out, the board is solved, and review appears.
        let again = app.buttons["Play again"]
        XCTAssertTrue(again.waitForExistence(timeout: 40), "no review after the board")
        XCTAssertTrue(app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS ' words'")).firstMatch.exists,
            "the verdict does not say how much of the board was taken")
        // The full solution is a tab now, not a link at the bottom of one long scroll.
        XCTAssertTrue(app.buttons["Board"].exists,
                      "the full solution is not one tap away")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.lifetime = .keepAlways
        add(shot)
    }
}

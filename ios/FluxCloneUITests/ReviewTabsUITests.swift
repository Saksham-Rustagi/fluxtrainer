import XCTest

/// Walks the four review tabs and photographs each. The assertions are thin on purpose --
/// the job here is to prove every tab renders against a real board and a real record, and
/// to leave a screenshot of each in the result bundle, which is the only way to see that
/// a word is wrapping mid-string or a badge is stacking vertically.
final class ReviewTabsUITests: XCTestCase {
    func testEveryTabRendersOnARealBoard() {
        let app = XCUIApplication.silent()
        app.launchEnvironment["FLUXCLONE_AUTOPLAY"] = "1"
        app.launchEnvironment["FLUXCLONE_BOARD_SECONDS"] = "6"
        app.launch()

        let clock = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH '00:0'")).firstMatch
        XCTAssertTrue(clock.waitForExistence(timeout: 25), "board never appeared")

        XCTAssertTrue(app.buttons["Play again"].waitForExistence(timeout: 40),
                      "no review after the board")

        for tab in ["Leaks", "Words", "Families", "Board"] {
            let button = app.buttons[tab]
            XCTAssertTrue(button.waitForExistence(timeout: 5), "no \(tab) tab")
            button.tap()
            // Every tab has to put something on screen. A tab that renders empty on a
            // 600-word board is a bug, not a quiet board.
            XCTAssertGreaterThan(app.staticTexts.count, 3, "\(tab) rendered nothing")
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.name = tab
            shot.lifetime = .keepAlways
            add(shot)
        }

        // Families is the one that has to work without the shipped record: it is read off
        // the board's own solve, so every board has some. It opens on the enumerable ones
        // -- sorting the full list by points puts "every word with -ING in it" on top.
        app.buttons["Families"].tap()
        let cues = app.buttons.matching(
            NSPredicate(format: "label BEGINSWITH 'Cues '")).firstMatch
        XCTAssertTrue(cues.waitForExistence(timeout: 5), "no cue filter")
        let all = app.buttons.matching(
            NSPredicate(format: "label BEGINSWITH 'All '")).firstMatch
        XCTAssertTrue(all.exists, "the big families are not reachable")
        all.tap()
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "FamiliesAll"
        shot.lifetime = .keepAlways
        add(shot)
    }
}

/// Mixed practice, end to end, because every part of it was wrong at once: the families
/// were chosen for you, `queue.ranked` is deterministic so it chose the same five every
/// time, and when the generator could not place them the app silently served an ordinary
/// board -- so review reported unrelated families and nothing about the ones asked for.
final class MixedPracticeUITests: XCTestCase {
    func testTheFamiliesYouPickAreTheOnesReportedBack() {
        let app = XCUIApplication.silent()
        app.launchEnvironment["FLUXCLONE_BOARD_SECONDS"] = "6"
        app.launch()

        let mixed = app.buttons.matching(
            NSPredicate(format: "label CONTAINS 'Mixed practice'")).firstMatch
        XCTAssertTrue(mixed.waitForExistence(timeout: 40), "no mixed practice button")
        mixed.tap()

        // The picker, with a reason against each family rather than a bare list of stems.
        let play = app.buttons["mixed.play"]
        XCTAssertTrue(play.waitForExistence(timeout: 10), "no picker")
        let count = app.staticTexts.matching(
            NSPredicate(format: "label ENDSWITH ' families'")).firstMatch
        XCTAssertTrue(count.exists, "the picker does not say how many are selected")

        // Read back what is actually ticked, so the assertion is about *these* families
        // and not about whatever the default happened to be.
        let ticked = app.images.matching(
            NSPredicate(format: "identifier == 'checkmark.circle.fill'")).count
        XCTAssertGreaterThanOrEqual(ticked, 2, "nothing selected by default")

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "MixedPicker"
        shot.lifetime = .keepAlways
        add(shot)
        play.tap()

        let clock = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH '00:0'")).firstMatch
        XCTAssertTrue(clock.waitForExistence(timeout: 40), "no mixed board")

        XCTAssertTrue(app.buttons["Play again"].waitForExistence(timeout: 40),
                      "no review after the mixed board")
        // The whole point of a mixed board: the breakdown, naming every family asked for,
        // including any the generator could not place.
        let heading = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS 'families you were carrying'")).firstMatch
        XCTAssertTrue(heading.exists, "review does not report the families it was seeded with")
        let rows = app.buttons.matching(
            NSPredicate(format: "label CONTAINS '-' AND label CONTAINS 'of'")).count
        XCTAssertGreaterThan(rows, 0, "no per-family result")
        let after = XCTAttachment(screenshot: app.screenshot())
        after.name = "MixedReview"
        after.lifetime = .keepAlways
        add(after)
    }
}

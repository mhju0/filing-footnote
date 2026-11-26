import XCTest

/// Roadmap P3: the walkthrough video's script, on the app's own development bundle (real
/// filings, approved summaries only). It runs only when `FOOTNOTE_WALKTHROUGH` is `1`
/// (`TEST_RUNNER_FOOTNOTE_WALKTHROUGH=1` on `xcodebuild test`), because it waits between steps
/// for the viewer and needs the git-ignored bundle. `ios/scripts/walkthrough.sh` records it.
///
/// Korean first, from a fresh install: Samsung Electronics → a buyback filing and its
/// summary → the annual report → revenue and its earlier years → compare with last year and
/// the calculation → compare with Apple (an amount comparison is refused, then growth with
/// its caveat) → the quarter report → one tap to English.
final class WalkthroughUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let buyback = "dart:20260821000616"
    private static let annual = "dart:20260310002820"
    private static let quarter = "dart:20261116001482"

    @MainActor func testWalkthrough() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["FOOTNOTE_WALKTHROUGH"] == "1",
                          "set TEST_RUNNER_FOOTNOTE_WALKTHROUGH=1 to record the walkthrough")
        continueAfterFailure = false
        XCUIDevice.shared.appearance = .light
        let app = XCUIApplication()
        // Without this argument the first-run guide opens first (D104).
        app.launchArguments = ["-FootnoteSkipGuideAndTips"]
        app.launch()
        hold(3)

        let company = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label BEGINSWITH %@", "삼성전자")).firstMatch
        XCTAssertTrue(company.waitForExistence(timeout: 10))
        company.tap()
        hold(3)

        // A filing and the summary the owner approved.
        let filing = identified(Self.buyback, in: app)
        reveal(filing, in: app)
        hold(1)
        filing.tap()
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 5))
        hold(4)
        app.swipeUp()
        hold(3)
        goBack(from: "filing-page", in: app)

        // The annual report, then revenue.
        let annual = identified(Self.annual, in: app)
        revealUpward(annual, in: app)
        annual.tap()
        XCTAssertTrue(identified("annual-page", in: app).waitForExistence(timeout: 5))
        hold(3)
        let revenue = app.buttons["figure-revenue"]
        reveal(revenue, in: app)
        hold(1)
        revenue.tap()
        XCTAssertTrue(identified("figure-page", in: app).waitForExistence(timeout: 5))
        hold(3)
        app.swipeUp()
        hold(2)

        // Compare with last year, and how it was calculated.
        tapRevealed(app.buttons["compare-last-year"], in: app)
        XCTAssertTrue(identified("year-compare-page", in: app).waitForExistence(timeout: 5))
        hold(3)
        tapRevealed(app.buttons["see-calculation"], in: app)
        XCTAssertTrue(identified("calculation-page", in: app).waitForExistence(timeout: 5))
        hold(4)
        goBack(from: "calculation-page", in: app)
        goBack(from: "year-compare-page", in: app)

        // Compare with Apple: nothing is compared until a rate is chosen; amounts never are.
        tapRevealed(app.buttons["compare-company"], in: app)
        XCTAssertTrue(identified("peer-picker", in: app).waitForExistence(timeout: 5))
        hold(2)
        tapRevealed(identified("peer-\(Self.apple)", in: app), in: app)
        XCTAssertTrue(identified("company-compare-page", in: app).waitForExistence(timeout: 5))
        hold(4)
        let amount = app.buttons["금액"]
        XCTAssertTrue(amount.waitForExistence(timeout: 5))
        amount.tap()
        let refusal = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "refusal-")).firstMatch
        XCTAssertTrue(refusal.waitForExistence(timeout: 5))
        hold(4)
        let growth = app.buttons["증가율"]
        XCTAssertTrue(growth.waitForExistence(timeout: 5))
        growth.tap()
        XCTAssertTrue(identified("rate-\(Self.samsung)", in: app).waitForExistence(timeout: 5))
        hold(3)
        let caveat = identified("caveat", in: app)
        reveal(caveat, in: app)
        hold(4)
        goBack(from: "company-compare-page", in: app)
        goBack(from: "figure-page", in: app)
        goBack(from: "annual-page", in: app)

        // The quarter report against the same quarter a year earlier.
        let quarter = identified(Self.quarter, in: app)
        revealUpward(quarter, in: app)
        quarter.tap()
        XCTAssertTrue(identified("quarter-page", in: app).waitForExistence(timeout: 5))
        hold(4)

        // One tap to English, on the same screen, then back through the company.
        let toEnglish = app.buttons["Switch to English"]
        XCTAssertTrue(toEnglish.waitForExistence(timeout: 5))
        toEnglish.tap()
        XCTAssertTrue(app.buttons["한국어로 보기"].waitForExistence(timeout: 5))
        hold(4)
        goBack(from: "quarter-page", in: app)
        hold(2)
        let filingAgain = identified(Self.buyback, in: app)
        reveal(filingAgain, in: app)
        filingAgain.tap()
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 5))
        hold(5)
        // Leave the stored language as it was for the next recording.
        app.buttons["한국어로 보기"].tap()
        hold(1)
    }

    // MARK: - Helpers

    private func hold(_ seconds: TimeInterval) { Thread.sleep(forTimeInterval: seconds) }

    @MainActor private func identified(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            app.swipeUp()
            tries += 1
        }
    }

    @MainActor private func revealUpward(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            app.swipeDown()
            tries += 1
        }
    }

    @MainActor private func tapRevealed(_ element: XCUIElement, in app: XCUIApplication) {
        reveal(element, in: app)
        XCTAssertTrue(element.isHittable, element.debugDescription)
        element.tap()
    }

    @MainActor private func goBack(from page: String, in app: XCUIApplication) {
        let back = app.navigationBars.buttons.matching(identifier: "BackButton").firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), app.debugDescription)
        back.tap()
        XCTAssertTrue(identified(page, in: app).waitForNonExistence(timeout: 5), page)
    }
}

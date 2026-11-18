import XCTest

/// Roadmap I7: the filing page, the annual page and the source action, on the FootnoteKit
/// fixture. The fixture's summary rows are test data, so the summary layout is checked here
/// and never with the real bundle.
final class FilingPagesUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let disposal = "dart:20261029000539"
    private static let purchase = "dart:20260821000616"
    private static let annual = "dart:20260310000123"

    @MainActor private func launch(_ route: String, language: String = "ko") throws -> XCUIApplication {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", fixture, "-FootnoteOpen", route, "-language", language]
        app.launch()
        return app
    }

    /// An element whose accessibility label contains `text` (a row reads as one element).
    @MainActor private func element(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    /// Scrolls the page up until `element` exists and is on screen, at most eight times.
    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            app.swipeUp()
            tries += 1
        }
    }

    @MainActor func testEventFilingShowsNumbersInReviewStateAndOpensTheOriginal() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.disposal)")
        XCTAssertTrue(app.descendants(matching: .any)["filing-page"].waitForExistence(timeout: 10))
        // No approved summary for this filing: board 19's in-review state.
        XCTAssertTrue(element("요약을 확인하고 있어요", in: app).exists)
        XCTAssertTrue(element("공시의 숫자", in: app).exists)
        XCTAssertTrue(element("처분 주식 수, 4,690주", in: app).exists)

        let original = app.buttons["open-original"]
        reveal(original, in: app)
        XCTAssertTrue(original.isHittable)
        XCTAssertGreaterThanOrEqual(original.frame.height, 44)
        original.tap()
        // The in-app Safari view (SFSafariViewController) covers the page.
        let safari = app.otherElements["TopBrowserBar"].firstMatch
        let done = app.buttons["Done"].firstMatch
        let shown = safari.waitForExistence(timeout: 10) || done.waitForExistence(timeout: 5)
        XCTAssertTrue(shown, "the original did not open in the in-app Safari view")
    }

    @MainActor func testApprovedSummaryShowsWithTheHowWrittenNote() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.purchase)")
        XCTAssertTrue(app.descendants(matching: .any)["filing-page"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["회사는 이 공시를 제출했다고 밝혔어요"].exists)
        XCTAssertFalse(element("요약을 확인하고 있어요", in: app).exists)
        XCTAssertTrue(app.staticTexts["공시를 바탕으로 미리 써 두고, 게시 전에 확인한 문장이에요."].exists)
    }

    @MainActor func testAnnualPageShowsTwoYearsAndOpensAFigure() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.annual)", language: "en")
        XCTAssertTrue(app.descendants(matching: .any)["annual-page"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["The company said it filed this report."].exists)
        let revenue = app.buttons["figure-revenue"]
        reveal(revenue, in: app)
        XCTAssertTrue(revenue.label.contains("up 16.20 percent from the year before"), revenue.label)
        revenue.tap()
        XCTAssertTrue(app.descendants(matching: .any)["figure-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(element("+16.20%, up", in: app).exists)
    }
}

import XCTest

/// Roadmap I8 and I9: the figure screen, compare with last year and its calculation, and
/// compare with another company, on the FootnoteKit fixture. In the fixture Samsung has two
/// years of figures and Apple one, so Apple's year compare and a growth compare with Apple
/// are refused for a missing period.
final class FigureCompareUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let annual = "dart:20260310000123"

    @MainActor private func launch(_ route: String, language: String = "ko") throws -> XCUIApplication {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", fixture, "-FootnoteOpen", route, "-language", language]
        app.launch()
        return app
    }

    @MainActor private func element(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

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

    /// Annual page → figure → years → compare with last year → calculation; then a refusal.
    @MainActor func testFigureYearsCompareAndCalculation() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.annual)")
        XCTAssertTrue(identified("annual-page", in: app).waitForExistence(timeout: 10))
        let revenue = app.buttons["figure-revenue"]
        reveal(revenue, in: app)
        revenue.tap()

        XCTAssertTrue(identified("figure-page", in: app).waitForExistence(timeout: 5))
        // The header reads the exact value and the direction in words.
        XCTAssertTrue(element("300조 8,709억 300만원", in: app).exists)
        XCTAssertTrue(element("16.20퍼센트 늘었어요", in: app).exists)
        // Earlier years as a list, each value exact.
        let prior = element("2024 회계연도, 258조 9,354억 9,400만원", in: app)
        reveal(prior, in: app)
        XCTAssertTrue(prior.exists)

        let compare = app.buttons["compare-last-year"]
        reveal(compare, in: app)
        XCTAssertGreaterThanOrEqual(compare.frame.height, 44)
        compare.tap()
        XCTAssertTrue(identified("year-compare-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("year-change", in: app).label.contains("16.20퍼센트 늘었어요"))

        let calculation = app.buttons["see-calculation"]
        reveal(calculation, in: app)
        calculation.tap()
        XCTAssertTrue(identified("calculation-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("equation", in: app).exists)
        XCTAssertTrue(element("300,870,903,000,000", in: app).exists)

        // Apple has one year in the fixture: compare with last year is refused.
        app.terminate()
        let refused = try launch("yearcompare=\(Self.apple)|revenue|2025")
        let refusal = identified("refusal-missing_period", in: refused)
        XCTAssertTrue(refusal.waitForExistence(timeout: 10))
        XCTAssertTrue(element("2024 회계연도 매출", in: refused).exists)
        XCTAssertTrue(identified("instead-0", in: refused).exists)
    }

    /// Picker → Apple → growth refused for a missing period → operating margin with the caveat.
    @MainActor func testCompareWithAnotherCompany() throws {
        let app = try launch("picker=\(Self.samsung)|revenue|2025", language: "en")
        XCTAssertTrue(identified("peer-picker", in: app).waitForExistence(timeout: 10))
        let peer = identified("peer-\(Self.apple)", in: app)
        reveal(peer, in: app)
        peer.tap()

        XCTAssertTrue(identified("company-compare-page", in: app).waitForExistence(timeout: 5))
        // Growth needs Apple's FY2024 revenue, which the fixture lacks.
        XCTAssertTrue(identified("refusal-missing_period", in: app).waitForExistence(timeout: 5))
        let margin = identified("instead-0", in: app)
        reveal(margin, in: app)
        margin.tap()

        let samsungRate = identified("rate-\(Self.samsung)", in: app)
        XCTAssertTrue(samsungRate.waitForExistence(timeout: 5))
        XCTAssertTrue(identified("rate-\(Self.apple)", in: app).exists)
        XCTAssertTrue(identified("rate-difference", in: app).label.contains("21.09"))
        let caveat = identified("caveat", in: app)
        reveal(caveat, in: app)
        XCTAssertTrue(caveat.label.contains("K-IFRS, US GAAP"), caveat.label)
        // No ranking words anywhere on the screen.
        for word in ["better", "worse", "outperform", "higher than", "lower than"] {
            XCTAssertFalse(element(word, in: app).exists, word)
        }
    }
}

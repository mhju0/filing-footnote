import XCTest

/// Roadmap I11: the quarter report on the FootnoteKit fixture. From the company page's
/// quarterly row to the three figures, each against the same quarter a year earlier, the
/// related preliminary results, and a figure's screen.
final class QuarterReportUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let samsungQuarter = "dart:20261116000111"
    private static let appleQuarter = "sec:0000320193-26-000020"
    private static let preliminary = "dart:20261029800099"

    @MainActor private func launch(_ route: String, language: String) throws -> XCUIApplication {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", fixture, "-FootnoteOpen", route, "-language", language,
                               "-FootnoteSkipGuideAndTips"]
        app.launch()
        return app
    }

    @MainActor private func identified(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    @MainActor private func formula(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .other)
            .matching(NSPredicate(format: "label BEGINSWITH %@", label + ", "))
            .firstMatch
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            app.swipeUp()
            tries += 1
        }
    }

    @MainActor func testCompanyRowOpensTheQuarterReportAndAFigure() throws {
        let app = try launch("company=\(Self.samsung)", language: "ko")
        XCTAssertTrue(identified("summary-quarter", in: app).waitForExistence(timeout: 10))
        // The summary card and the questions come first (D106); the report row is below them.
        let row = identified(Self.samsungQuarter, in: app)
        reveal(row, in: app)
        XCTAssertTrue(row.exists)
        // Board 14: the title, then revenue against the same quarter a year earlier.
        XCTAssertTrue(row.label.hasPrefix("2026년 3분기 보고서"), row.label)
        XCTAssertTrue(row.label.contains("전년보다 8.80퍼센트 증가"), row.label)
        row.tap()

        XCTAssertTrue(identified("quarter-page", in: app).waitForExistence(timeout: 5))
        let revenue = identified("quarter-revenue", in: app)
        XCTAssertTrue(revenue.waitForExistence(timeout: 5))
        // VoiceOver reads the exact value and the change in words.
        XCTAssertTrue(revenue.label.hasPrefix("매출, 86조 617억 4,700만원"), revenue.label)
        XCTAssertTrue(revenue.label.contains("8.80퍼센트 증가"), revenue.label)
        // A loss a year earlier: board 9's line instead of a percentage.
        let operating = identified("quarter-operating_income", in: app)
        XCTAssertTrue(operating.label.contains("작년 숫자가 0 이하라 증가율을 계산하지 않아요"), operating.label)
        XCTAssertTrue(identified("quarter-net_income_attributable", in: app).exists)

        let preliminary = identified(Self.preliminary, in: app)
        reveal(preliminary, in: app)
        XCTAssertTrue(preliminary.label.contains("이 보고서보다 먼저 냈어요"), preliminary.label)
        XCTAssertTrue(identified("investor-event", in: app).exists)

        // The detail keeps the quarter’s figure and comparison.
        let figure = identified("quarter-revenue", in: app)
        if !figure.isHittable { app.swipeDown() }
        let revenueLabel = figure.label
        figure.tap()
        XCTAssertTrue(identified("quarter-figure-page", in: app).waitForExistence(timeout: 5))
        XCTAssertEqual(identified("quarter-figure-change", in: app).label, revenueLabel)
    }

    @MainActor func testQuarterDetailRetainsRefusalForLossBaseline() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.samsungQuarter)", language: "ko")
        let operating = identified("quarter-operating_income", in: app)
        XCTAssertTrue(operating.waitForExistence(timeout: 10))
        let comparison = operating.label
        XCTAssertTrue(comparison.contains("작년 숫자가 0 이하라 증가율을 계산하지 않아요"))
        operating.tap()
        XCTAssertTrue(identified("quarter-figure-page", in: app).waitForExistence(timeout: 5))
        XCTAssertEqual(identified("quarter-figure-change", in: app).label, comparison)
        let details = identified("quarter-calculation-details", in: app)
        reveal(details, in: app)
        XCTAssertTrue(details.isHittable)
        details.tap()
        XCTAssertFalse(formula("식", in: app).exists)
    }

    @MainActor func testUSQuarterInEnglish() throws {
        let app = try launch("filing=\(Self.apple)|\(Self.appleQuarter)", language: "en")
        XCTAssertTrue(identified("quarter-page", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Q3 FY2026 report (10-Q)"].exists)
        let revenue = identified("quarter-revenue", in: app)
        XCTAssertTrue(revenue.label.contains("increased 11.76 percent from the year before"), revenue.label)
        // No preliminary results or investor event in the fixture: the section is removed.
        XCTAssertFalse(identified("investor-event", in: app).exists)
        let comparison = revenue.label
        revenue.tap()
        XCTAssertTrue(identified("quarter-figure-page", in: app).waitForExistence(timeout: 5))
        let headline = identified("quarter-figure-change", in: app)
        XCTAssertEqual(headline.label, comparison)
        XCTAssertTrue(headline.label.contains("Comparison period Q3 FY2025"), headline.label)
        let details = identified("quarter-calculation-details", in: app)
        reveal(details, in: app)
        XCTAssertTrue(details.isHittable)
        let result = formula("Formula", in: app)
        XCTAssertFalse(result.exists)
        details.tap()
        reveal(result, in: app)
        XCTAssertTrue(result.exists)
        XCTAssertTrue(result.label.contains("11.76%"), result.label)
        XCTAssertTrue(result.label.contains("same quarter last year"), result.label)
    }
}

import XCTest

/// D99: "Ask about this company" on the FootnoteKit fixture. A question on the company page
/// opens its answer; the answer's figures carry exact amounts and open their filing; the buy
/// and next-quarter questions are deflected to what the filings say.
final class AskQuestionsUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let samsungQuarter = "dart:20261116000111"
    private static let samsungAnnual = "dart:20260310000123"

    @MainActor private func launch(_ route: String, language: String) throws -> XCUIApplication {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", fixture, "-FootnoteOpen", route, "-language", language]
        app.launch()
        return app
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

    @MainActor func testQuestionOpensItsAnswerAndTheSourceFiling() throws {
        let app = try launch("company=\(Self.samsung)", language: "ko")
        let question = identified("ask-revenue", in: app)
        XCTAssertTrue(question.waitForExistence(timeout: 10))
        reveal(question, in: app)
        XCTAssertEqual(question.label, "매출은 어때요?")
        // Every question is a full-size target.
        for intent in ["should_buy", "fundamentals", "recent_trend", "profit_or_loss", "revenue", "next_quarter_revenue"] {
            let frame = identified("ask-\(intent)", in: app).frame
            XCTAssertGreaterThanOrEqual(frame.height, 44, intent)
            XCTAssertGreaterThanOrEqual(frame.width, 44, intent)
        }
        question.tap()

        XCTAssertTrue(identified("answer-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["회사는 최근 분기 매출이 작년 같은 분기보다 늘었다고 보고했어요."].exists)
        let revenue = identified("answer-quarter-revenue", in: app)
        XCTAssertTrue(revenue.exists)
        // VoiceOver reads the exact amount and the change in words.
        XCTAssertTrue(revenue.label.hasPrefix("매출, 86조 617억 4,700만원"), revenue.label)
        XCTAssertTrue(revenue.label.contains("8.80퍼센트 증가"), revenue.label)
        XCTAssertTrue(identified("answer-year-revenue", in: app).exists)

        let source = identified("answer-source-\(Self.samsungQuarter)", in: app)
        reveal(source, in: app)
        source.tap()
        XCTAssertTrue(identified("quarter-page", in: app).waitForExistence(timeout: 5))
    }

    @MainActor func testBuyingIsDeflectedToQuestionsTheFilingsAnswer() throws {
        let app = try launch("company=\(Self.samsung)", language: "en")
        let question = identified("ask-should_buy", in: app)
        XCTAssertTrue(question.waitForExistence(timeout: 10))
        reveal(question, in: app)
        question.tap()

        XCTAssertTrue(identified("answer-page", in: app).waitForExistence(timeout: 5))
        let statements = identified("answer-statements", in: app)
        XCTAssertTrue(statements.label.contains("This app doesn't tell you to buy or sell shares."), statements.label)
        // No figure answers the buy question.
        XCTAssertFalse(identified("answer-quarter-revenue", in: app).exists)

        let related = identified("related-fundamentals", in: app)
        reveal(related, in: app)
        XCTAssertEqual(related.label, "What are the fundamentals?")
        related.tap()
        XCTAssertTrue(app.staticTexts["The business, in the company's words"].waitForExistence(timeout: 5))
        XCTAssertTrue(identified("answer-source-\(Self.samsungAnnual)", in: app).exists)
    }

    @MainActor func testNextQuarterPointsToTheCompanysOutlook() throws {
        let app = try launch("ask=\(Self.samsung)|next_quarter_revenue", language: "ko")
        XCTAssertTrue(identified("answer-page", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(identified("answer-statements", in: app).label.contains("앞으로의 매출은 추정하지 않아요"))
        let outlook = identified("answer-outlook", in: app)
        XCTAssertTrue(outlook.exists)
        outlook.tap()
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 5))
    }

    @MainActor func testMissingDataIsSaidNotShownAsZero() throws {
        // Apple's fixture has no annual summary and one annual year.
        let app = try launch("ask=\(Self.apple)|fundamentals", language: "en")
        XCTAssertTrue(identified("answer-page", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(identified("answer-statements", in: app).label
            .contains("The app doesn't have the company's own description of its business yet."))

        let trend = try launch("ask=\(Self.apple)|recent_trend", language: "en")
        XCTAssertTrue(identified("answer-page", in: trend).waitForExistence(timeout: 10))
        let year = identified("answer-year-revenue", in: trend)
        reveal(year, in: trend)
        XCTAssertTrue(year.label.contains("A year is missing"), year.label)
        XCTAssertTrue(trend.staticTexts[
            "The latest fiscal year's revenue can't be compared with the year before."].exists)
    }
}

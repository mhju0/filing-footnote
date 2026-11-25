import SQLite3
import XCTest

/// Roadmap I10: the 소식 feed and the 용어 glossary on the FootnoteKit fixture. The fixture's
/// glossary rows predate the `metric_` keys (D81), so the glossary tests open an edited copy
/// with the D81 keys; the text in it is test data, never shipped wording.
final class NewsGlossaryUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let dividend = "dart:20261029800101"

    @MainActor private func launch(
        _ route: String, language: String = "ko", bundle: String? = nil
    ) throws -> XCUIApplication {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", bundle ?? fixture, "-FootnoteOpen", route, "-language", language]
        app.launch()
        return app
    }

    /// A temporary copy of the fixture after `sql`.
    private func editedFixture(_ sql: String) throws -> String {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        let path = NSTemporaryDirectory() + "footnote-\(UUID().uuidString).sqlite"
        try FileManager.default.copyItem(atPath: fixture, toPath: path)
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK, String(cString: sqlite3_errmsg(db)))
        addTeardownBlock { try? FileManager.default.removeItem(atPath: path) }
        return path
    }

    /// The D81 keys: `metric_revenue`, and an entry for the dividend category.
    private func glossaryFixture() throws -> String {
        try editedFixture("""
            UPDATE glossary SET term_key = 'metric_' || term_key;
            INSERT INTO glossary (term_key, lang, term, plain, formal) VALUES
              ('category_dividend', 'ko', '배당', '시험용 배당 설명이에요.', NULL),
              ('category_dividend', 'en', 'Dividend', 'A test entry about dividends.', NULL);
            """)
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

    /// Newest first, under day headings; a row names its company and opens the filing page.
    @MainActor func testNewsListsFilingsByDayAndOpensOne() throws {
        let app = try launch("news")
        XCTAssertTrue(identified("news-page", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["11월 2일"].exists)
        XCTAssertTrue(app.staticTexts["10월 29일"].exists)
        let first = element("애플, 실적", in: app)
        XCTAssertTrue(first.exists)
        XCTAssertLessThan(app.staticTexts["11월 2일"].frame.minY, app.staticTexts["10월 29일"].frame.minY)
        // No filing is within seven days of the fixture's data date (November 17).
        XCTAssertFalse(element("새 공시", in: app).exists)
        XCTAssertGreaterThanOrEqual(first.frame.height, 44)
        first.tap()
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 5))
    }

    /// 새 공시: the data date and the six days before it (the owner's rule).
    @MainActor func testNewsTagsFilingsFromTheLastSevenDays() throws {
        let app = try launch("news", language: "en",
                             bundle: try editedFixture("UPDATE build_meta SET data_as_of = '2026-11-08'"))
        XCTAssertTrue(identified("news-page", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(element("Apple, Earnings, New", in: app).exists)
        XCTAssertFalse(element("Samsung Electronics, Buyback, New", in: app).exists)
    }

    @MainActor func testNewsEmptyState() throws {
        let app = try launch("news", bundle: try editedFixture("UPDATE build_meta SET data_as_of = '2030-01-01'"))
        XCTAssertTrue(identified("news-empty", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(element("최근 1년 동안 낸 공시가 없어요.", in: app).exists)
        XCTAssertFalse(app.buttons["news-type"].exists)
    }

    @MainActor func testNewsFiltersByFilingTypeAndRestoresAll() throws {
        let app = try launch("news", language: "en")
        let filter = app.buttons["news-type"]
        let earnings = element("Apple, Earnings", in: app)
        let dividend = element("Samsung Electronics, Dividend", in: app)
        XCTAssertTrue(filter.waitForExistence(timeout: 10))
        XCTAssertEqual(filter.value as? String, "All filings")
        XCTAssertGreaterThanOrEqual(filter.frame.height, 44)
        XCTAssertTrue(earnings.exists)

        filter.tap()
        app.buttons["Dividend"].tap()
        XCTAssertTrue(dividend.waitForExistence(timeout: 5))
        XCTAssertFalse(earnings.exists)
        XCTAssertEqual(filter.value as? String, "Dividend")

        filter.tap()
        app.buttons["All filings"].tap()
        XCTAssertTrue(earnings.waitForExistence(timeout: 5))
        XCTAssertEqual(filter.value as? String, "All filings")
    }

    /// The tab shows key terms first, then the rest by initial. A tap discloses the meaning and formal term.
    @MainActor func testGlossaryTabShowsPlainWordAndFormalTerm() throws {
        let app = try launch("news", language: "en", bundle: try glossaryFixture())
        XCTAssertTrue(identified("news-page", in: app).waitForExistence(timeout: 10))
        app.tabBars.buttons["Glossary"].tap()
        XCTAssertTrue(identified("glossary-page", in: app).waitForExistence(timeout: 5))
        let margin = identified("glossary-metric_operating_margin", in: app)
        XCTAssertTrue(margin.exists)
        XCTAssertTrue(margin.label.hasPrefix("Operating margin"), margin.label)
        // Key terms first in their fixed order (revenue before operating margin), then the
        // other terms by initial, so Dividend comes after both (2026-11-26 review, issue 12).
        let dividend = identified("glossary-category_dividend", in: app)
        let revenue = identified("glossary-metric_revenue", in: app)
        XCTAssertLessThan(revenue.frame.minY, margin.frame.minY)
        XCTAssertLessThan(margin.frame.minY, dividend.frame.minY)

        let definition = identified("glossary-definition-metric_operating_margin", in: app)
        XCTAssertFalse(definition.exists)
        XCTAssertGreaterThanOrEqual(margin.frame.height, 44)
        margin.tap()
        XCTAssertTrue(definition.waitForExistence(timeout: 5))
        XCTAssertTrue(definition.label.contains("Formal term: Operating income divided by revenue"), definition.label)
        margin.tap()
        XCTAssertTrue(definition.waitForNonExistence(timeout: 5))
    }

    @MainActor func testGlossarySearchMatchesOtherLanguageAndClears() throws {
        let app = try launch("glossary", bundle: try glossaryFixture())
        let search = app.textFields["glossary-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText("unmatched")
        XCTAssertTrue(identified("glossary-empty", in: app).waitForExistence(timeout: 5))
        let clear = app.buttons["glossary-search-clear"]
        clear.tap()
        XCTAssertTrue(identified("glossary-metric_revenue", in: app).waitForExistence(timeout: 5))

        search.tap()
        search.typeText("Dividend\n")
        let dividend = identified("glossary-category_dividend", in: app)
        XCTAssertTrue(dividend.waitForExistence(timeout: 5))
        XCTAssertEqual(dividend.label, "배당")
        XCTAssertFalse(identified("glossary-metric_revenue", in: app).exists)
        dividend.tap()
        XCTAssertTrue(identified("glossary-definition-category_dividend", in: app).waitForExistence(timeout: 5))
    }

    /// The figure screen's "용어 풀이 더 보기" opens the glossary at the metric's entry.
    @MainActor func testFigureLinkOpensItsEntry() throws {
        let app = try launch("figure=\(Self.samsung)|revenue|2025", bundle: try glossaryFixture())
        XCTAssertTrue(identified("figure-page", in: app).waitForExistence(timeout: 10))
        let more = app.buttons["more-in-glossary"]
        reveal(more, in: app)
        more.tap()
        XCTAssertTrue(identified("glossary-page", in: app).waitForExistence(timeout: 5))
        let entry = identified("glossary-metric_revenue", in: app)
        XCTAssertTrue(entry.waitForExistence(timeout: 2))
        XCTAssertTrue(entry.isSelected)
        XCTAssertTrue(identified("glossary-definition-metric_revenue", in: app).exists)
        XCTAssertFalse(identified("glossary-metric_operating_margin", in: app).isSelected)
    }

    /// A filing page links to the entry for its category.
    @MainActor func testFilingPageLinksToItsCategoryEntry() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.dividend)", bundle: try glossaryFixture())
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 10))
        let link = app.buttons["glossary-link"]
        reveal(link, in: app)
        XCTAssertTrue(link.label.contains("용어 풀이: 배당"), link.label)
        link.tap()
        XCTAssertTrue(identified("glossary-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("glossary-category_dividend", in: app).isSelected)
    }

    /// No glossary rows in the bundle: no tab and no link (R-24).
    @MainActor func testNoGlossaryRowsHidesTheTabAndLinks() throws {
        let app = try launch("filing=\(Self.samsung)|\(Self.dividend)",
                             bundle: try editedFixture("DELETE FROM glossary"))
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 10))
        XCTAssertFalse(app.tabBars.buttons["용어"].exists)
        XCTAssertFalse(app.buttons["glossary-link"].exists)
    }
}

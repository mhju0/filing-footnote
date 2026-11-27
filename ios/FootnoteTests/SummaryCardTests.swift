import Foundation
import FootnoteKit
import SQLite3
import Testing
@testable import Footnote

private final class TestBundle {}

private let fixtureURL = Bundle(for: TestBundle.self).url(forResource: "footnote", withExtension: "sqlite")!

/// The company page's summary card, the quarter's fiscal label and the category symbols
/// (D106).
@Suite("Summary card")
struct SummaryCardTests {
    static let samsung = "dart:00126380"
    static let apple = "sec:0000320193"

    let store: BundleStore

    init() throws {
        store = try BundleStore(contentsOf: fixtureURL)
    }

    @Test func selectionIDsRoundTripAndStayApartFromFilings() {
        for part in [SummarySelection.year, .quarter] {
            #expect(SummarySelection(part.id) == part)
            #expect(store.filing(id: part.id) == nil)
            #expect(AskSelection.intent(part.id) == nil)
        }
        #expect(SummarySelection(nil) == nil)
        #expect(SummarySelection("dart:20261116000111") == nil)
        #expect(SummarySelection(AskSelection.id(.revenue)) == nil)
    }

    /// The hero opens the annual revenue figure; the quarter opens its report.
    @Test func rowsOpenTheFigureAndTheQuarterReport() throws {
        let summary = try #require(CompanyAnswerer.summary(store: store, companyID: Self.samsung))
        #expect(SummarySelection.year.route(summary, companyID: Self.samsung) == .figure(Self.samsung, "revenue", 2025))
        #expect(SummarySelection.quarter.route(summary, companyID: Self.samsung) == .filing("dart:20261116000111"))
    }

    /// t2 sits on the year figure when the card links it (D107); a card that says the year
    /// is missing has no year link, and t2 stays on the report row.
    @Test func theFigureTipGoesWhereTheCardLinksTheYear() throws {
        let summary = try #require(CompanyAnswerer.summary(store: store, companyID: Self.samsung))
        #expect(CompanySummaryCard.linksYear(summary, companyID: Self.samsung))

        let path = NSTemporaryDirectory() + "footnote-\(UUID().uuidString).sqlite"
        try FileManager.default.copyItem(at: fixtureURL, to: URL(fileURLWithPath: path))
        defer { try? FileManager.default.removeItem(atPath: path) }
        var db: OpaquePointer?
        #expect(sqlite3_open(path, &db) == SQLITE_OK)
        let sql = "UPDATE filings SET period_label = NULL WHERE id = 'dart:20260310000123'"
        #expect(sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK)
        sqlite3_close(db)
        let edited = try BundleStore(contentsOf: URL(fileURLWithPath: path))
        let missing = try #require(CompanyAnswerer.summary(store: edited, companyID: Self.samsung))
        #expect(missing.year == .statement(.yearMissing))
        #expect(!CompanySummaryCard.linksYear(missing, companyID: Self.samsung))
    }

    @Test func quarterLabelsNameTheirCalendarMonths() throws {
        let samsung = try #require(QuarterPage(store: store, filingID: "dart:20261116000111")?.rows.first?.current)
        #expect(PageCopy.quarterLabelWithMonths(samsung, .ko) == "2026 회계연도 3분기" + Copy.dot + "7–9월")
        #expect(PageCopy.quarterLabelWithMonths(samsung, .en) == "Q3 FY2026" + Copy.dot + "Jul–Sep")
        let apple = try #require(QuarterPage(store: store, filingID: "sec:0000320193-26-000020")?.rows.first?.current)
        let months = PageCopy.months(start: apple.periodStart, end: apple.periodEnd, .en)
        #expect(months == Formatting.monthDay(apple.periodStart, language: .en) + "–"
            + Formatting.monthDay(apple.periodEnd, language: .en))
        #expect(PageCopy.quarterLabelWithMonths(apple, .en).hasPrefix("Q\(apple.fiscalQuarter) FY\(apple.fiscalYear)"))
    }

    /// At the accessibility sizes a source part wider than the line wraps between two halves
    /// that leave no word alone: the Korean date after its year, never inside `11월 16일`,
    /// a title before its last two words or after its comma, and `10-K` never at its hyphen.
    /// The date reads the same as `Copy.filedOn`.
    @Test @MainActor func sourcePartsWrapWithoutOrphans() throws {
        let date = try #require(CivilDate(iso: "2026-11-16"))
        let korean = SummarySource.filedOn(date, .ko)
        #expect(korean.spokenSeparators == Copy.filedOn(date, .ko).spokenSeparators)
        #expect(AskCopy.halves(korean) == ["2026년", "11월" + Copy.noBreak + "16일 공시"])
        #expect(SummarySource.filedOn(date, .en) == Copy.filedOn(date, .en))
        #expect(AskCopy.halves(SummarySource.filedOn(date, .en)) == ["Filed", Copy.unbroken("Nov 16, 2026")])

        let parts = SummarySource.phrases(["출처", "2026년 3분기 보고서", korean])
        #expect(BalancedText.halves(parts[1], atComma: true) == ["2026년", "3분기 보고서" + Copy.noBreak + "·"])
        let english = SummarySource.phrases(["Source", "Annual report, FY2025", "Filed"])
        #expect(BalancedText.halves(english[1], atComma: true) == ["Annual report,", "FY2025" + Copy.noBreak + "·"])
        #expect(BalancedText.joiningHyphens("(10-K)") == "(10-\u{2060}K)")
    }

    /// Design direction 7 B: one symbol per category, none shared.
    @Test func everyCategoryHasItsOwnSymbol() {
        let symbols = FilingCategory.allCases.map(\.symbol)
        #expect(Set(symbols).count == symbols.count)
        #expect(!symbols.contains(""))
    }
}

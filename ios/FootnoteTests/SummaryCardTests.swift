import Foundation
import FootnoteKit
import Testing
@testable import Footnote

private final class TestBundle {}

private let fixtureURL = Bundle(for: TestBundle.self).url(forResource: "footnote", withExtension: "sqlite")!

/// The company page's summary card, the quarter's fiscal label and the category symbols
/// (D100).
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

    /// Design direction 7 B: one symbol per category, none shared.
    @Test func everyCategoryHasItsOwnSymbol() {
        let symbols = FilingCategory.allCases.map(\.symbol)
        #expect(Set(symbols).count == symbols.count)
        #expect(!symbols.contains(""))
    }
}

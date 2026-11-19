import Foundation
import Testing
@testable import FootnoteKit

/// The quarter report (I11, board 15) over the fixture: Samsung's 3분기보고서, whose operating
/// income a year earlier is a loss, and Apple's 10-Q, whose quarters are 13 weeks long.
@Suite struct QuarterPageTests {
    let store = try! BundleStore(contentsOf: Support.fixtureURL)

    private func page(_ id: String) throws -> QuarterPage {
        try #require(QuarterPage(store: store, filingID: id))
    }

    private func percent(_ row: QuarterFigureRow) -> Decimal? {
        if case .result(let change) = row.comparison { return change.percentChange }
        return nil
    }

    @Test func threeFiguresEachAgainstTheSameQuarterAYearEarlier() throws {
        let page = try page(BundleStoreTests.samsungQuarter)
        #expect(page.filing.kind == .quarterly)
        #expect(page.filing.category == .quarterly)
        #expect(page.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncomeAttributable])
        let revenue = page.rows[0]
        #expect(revenue.current.value == Support.decimal("86061747000000"))
        #expect(revenue.prior?.value == Support.decimal("79098718000000"))
        #expect(revenue.comparison == .result(QuarterChange(
            priorValue: Support.decimal("79098718000000"), currentValue: Support.decimal("86061747000000"),
            delta: Support.decimal("6963029000000"), percentChange: Support.decimal("8.80"))))
        #expect(percent(page.rows[2]) == Support.decimal("22.77"))
        #expect(page.period?.start == Support.date("2026-07-01"))
        #expect(page.period?.end == Support.date("2026-09-30"))
        #expect(page.priorPeriod?.start == Support.date("2025-07-01"))
        #expect(page.currency == "KRW")
    }

    @Test func aLossAYearEarlierGivesNoPercentage() throws {
        let operating = try page(BundleStoreTests.samsungQuarter).rows[1]
        #expect(operating.prior?.value == Support.decimal("-1200000000000"))
        #expect(operating.comparison == .refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline)))
    }

    @Test func thirteenWeekQuartersEndingADayApartCompare() throws {
        let page = try page(BundleStoreTests.appleQuarter)
        #expect(page.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncomeAttributable])
        #expect(page.rows.map(percent) == ["11.76", "12.00", "9.52"].map(Support.decimal))
        #expect(page.currency == "USD")
    }

    @Test func netIncomeStandsInWhenNoAttributableFigureIsStated() throws {
        let store = try Support.editedFixture(
            "DELETE FROM quarter_figures WHERE metric = 'net_income_attributable'")
        let page = try #require(QuarterPage(store: store, filingID: BundleStoreTests.samsungQuarter))
        #expect(page.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncome])
        // Apple states no net income apart from the attributable figure: two rows.
        let apple = try #require(QuarterPage(store: store, filingID: BundleStoreTests.appleQuarter))
        #expect(apple.rows.map(\.metric) == [.revenue, .operatingIncome])
    }

    @Test func aMissingPriorQuarterIsAMissingPeriod() throws {
        let store = try Support.editedFixture(
            "DELETE FROM quarter_figures WHERE metric = 'revenue' AND fiscal_year = 2025")
        let row = try #require(QuarterPage(store: store, filingID: BundleStoreTests.samsungQuarter)?.rows.first)
        #expect(row.prior == nil)
        #expect(row.comparison == .refusal(Refusal(.missingPeriod, .missingFact)))
    }

    @Test func theRelatedPreliminaryResultsAndInvestorEvent() throws {
        let page = try page(BundleStoreTests.samsungQuarter)
        // Both earnings filings of 29 October fall between the quarter end and the report;
        // the newest, the corrected one, is shown.
        #expect(page.preliminary?.id == "dart:20261029800099")
        #expect(page.investorEvent?.id == "dart:20261113801115")
        let apple = try self.page(BundleStoreTests.appleQuarter)
        #expect(apple.preliminary == nil)
        #expect(apple.investorEvent == nil)
    }

    @Test func otherFilingsHaveNoQuarterPage() {
        #expect(QuarterPage(store: store, filingID: BundleStoreTests.samsungAnnual) == nil)
        #expect(AnnualPage(store: store, filingID: BundleStoreTests.samsungQuarter) == nil)
    }

    @Test func comparisonRefusesFiguresThatAreNotAlike() throws {
        let rows = try page(BundleStoreTests.samsungQuarter).rows
        let current = rows[0].current, prior = try #require(rows[0].prior)
        func edited(_ figure: QuarterFigure, start: String? = nil, end: String? = nil, currency: String? = nil)
            -> QuarterFigure {
            QuarterFigure(
                id: figure.id, companyID: figure.companyID, filingID: figure.filingID, metric: figure.metric,
                fiscalYear: figure.fiscalYear, fiscalQuarter: figure.fiscalQuarter,
                periodStart: start.map(Support.date) ?? figure.periodStart,
                periodEnd: end.map(Support.date) ?? figure.periodEnd, value: figure.value, unit: figure.unit,
                currency: currency ?? figure.currency, basis: figure.basis, regulatorTag: figure.regulatorTag)
        }
        // The year to date is not a quarter.
        #expect(QuarterComparison.compare(prior: edited(prior, start: "2025-01-01"), current: current)
            == .refusal(Refusal(.incompatibleComparison, .periodLengthMismatch)))
        // The quarter before is never compared.
        #expect(QuarterComparison.compare(
            prior: edited(prior, start: "2026-04-01", end: "2026-06-30"), current: current)
            == .refusal(Refusal(.incompatibleComparison, .periodEndMismatch)))
        #expect(QuarterComparison.compare(prior: edited(prior, currency: "USD"), current: current)
            == .refusal(Refusal(.incompatibleCurrency, .currencyMismatch)))
        // A quarter is 12 to 14 weeks counting both ends, as the backend's `_QUARTER_DAYS`:
        // 84 days (Costco's 12-week quarters) and 98 days compare; 83 and 99 do not.
        func lasting(_ start2026: String, _ start2025: String) -> Comparison<QuarterChange> {
            QuarterComparison.compare(prior: edited(prior, start: start2025), current: edited(current, start: start2026))
        }
        if case .refusal = lasting("2026-07-09", "2025-07-09") { Issue.record("84 days is a quarter") }
        if case .refusal = lasting("2026-06-25", "2025-06-25") { Issue.record("98 days is a quarter") }
        #expect(lasting("2026-07-10", "2025-07-09") == .refusal(Refusal(.incompatibleComparison, .periodLengthMismatch)))
        #expect(lasting("2026-06-24", "2025-06-25") == .refusal(Refusal(.incompatibleComparison, .periodLengthMismatch)))
    }

    @Test func companyPageShowsTheQuarterAboveOneAnnualReport() throws {
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(page.quarterReport?.filing.id == BundleStoreTests.samsungQuarter)
        #expect(page.quarterReport?.change?.percentChange == Support.decimal("8.80"))
        #expect(page.periodicReports.count == CompanyPage.maxPeriodicReports - 1)
        // The quarterly report is not an event filing.
        #expect(!page.filings.contains { $0.kind == .quarterly })
    }

    @Test func titles() throws {
        let samsung = try #require(store.filing(id: BundleStoreTests.samsungQuarter))
        #expect(Titles.title(for: samsung, language: .ko) == "2026년 3분기 보고서")
        #expect(Titles.title(for: samsung, language: .en) == "Q3 2026 report")
        let apple = try #require(store.filing(id: BundleStoreTests.appleQuarter))
        #expect(Titles.title(for: apple, language: .ko) == "2026 회계연도 3분기 보고서 (10-Q)")
        #expect(Titles.title(for: apple, language: .en) == "Q3 FY2026 report (10-Q)")
    }

    /// A 반기보고서 (report code 11012, FY2026-Q2) keeps DART's name.
    @Test func halfYearReportTitles() throws {
        let q3 = try #require(store.filing(id: BundleStoreTests.samsungQuarter))
        func filing(form: String, title: String, label: String?) -> Filing {
            Filing(id: q3.id, companyID: q3.companyID, kind: .quarterly, category: .quarterly, form: form,
                   secItems: nil, titleOriginal: title, filedOn: q3.filedOn, periodLabel: label,
                   sourceURL: q3.sourceURL, isCorrected: false, sourceTextSHA256: q3.sourceTextSHA256)
        }
        let half = filing(form: "반기보고서", title: "반기보고서 (2026.06)", label: "FY2026-Q2")
        #expect(Titles.title(for: half, language: .ko) == "2026년 반기보고서")
        #expect(Titles.title(for: half, language: .en) == "H1 2026 report")
        let unlabelled = filing(form: "반기보고서", title: "반기보고서 (2026.06)", label: nil)
        #expect(Titles.title(for: unlabelled, language: .ko) == "반기보고서")
        #expect(Titles.title(for: unlabelled, language: .en) == "Half-year report")
        let first = filing(form: "분기보고서", title: "분기보고서 (2026.03)", label: "FY2026-Q1")
        #expect(Titles.title(for: first, language: .ko) == "2026년 1분기 보고서")
        #expect(Titles.title(for: first, language: .en) == "Q1 2026 report")
    }
}

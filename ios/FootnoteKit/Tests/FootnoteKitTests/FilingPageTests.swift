import Foundation
import Testing
@testable import FootnoteKit

/// The filing page and annual page models (board 12A, board 4) over the fixture, with SQL
/// edits for tables the fixture does not hold. Summary rows inserted here are test data only.
@Suite("Filing page")
struct FilingPageTests {
    static let earnings = "dart:20261029800087"
    static let correctedEarnings = "dart:20261029800099"
    static let disposal = "dart:20261029000539"
    static let purchase = "dart:20260821000616"
    static let dividend = "dart:20261029800101"
    static let outlookPlan = "dart:20261029800102"
    static let appleEarnings = "sec:0000320193-26-000024"

    static func fact(_ filing: String, _ position: Int, _ key: String, _ kind: String,
                     _ value: String, _ unit: String?, _ origin: String) -> String {
        let unitSQL = unit.map { "'\($0)'" } ?? "NULL"
        return "INSERT INTO filing_facts VALUES ('\(filing)', \(position), '\(key)', '\(kind)', "
            + "'\(value)', \(unitSQL), '\(origin)');"
    }

    /// Hyundai's Q3 2026 preliminary results, as the dev bundle holds them.
    static let resultsSQL = [
        fact(earnings, 1, "results_period_start", "date", "2026-07-01", nil, "dartdoc:results.results_period_start"),
        fact(earnings, 2, "results_period_end", "date", "2026-09-30", nil, "dartdoc:results.results_period_end"),
        fact(earnings, 3, "results_year_ago_start", "date", "2025-07-01", nil, "dartdoc:results.results_year_ago_start"),
        fact(earnings, 4, "results_year_ago_end", "date", "2025-09-30", nil, "dartdoc:results.results_year_ago_end"),
        fact(earnings, 5, "results_revenue_current", "amount", "45110247", "백만원", "dartdoc:results.results_revenue_current"),
        fact(earnings, 6, "results_revenue_prior_period", "amount", "49215328", "백만원", "dartdoc:results.results_revenue_prior_period"),
        fact(earnings, 7, "results_revenue_year_ago", "amount", "46721448", "백만원", "dartdoc:results.results_revenue_year_ago"),
        fact(earnings, 8, "results_operating_income_current", "amount", "2677232", "백만원", "dartdoc:results.results_operating_income_current"),
        fact(earnings, 9, "results_operating_income_year_ago", "amount", "2537266", "백만원", "dartdoc:results.results_operating_income_year_ago"),
        fact(earnings, 10, "results_net_income_current", "amount", "-5", "백만원", "dartdoc:results.results_net_income_current"),
        fact(earnings, 11, "results_net_income_year_ago", "amount", "-3", "백만원", "dartdoc:results.results_net_income_year_ago"),
        fact(earnings, 12, "results_net_income_attributable_current", "amount", "1704370", "백만원", "dartdoc:results.results_net_income_attributable_current"),
    ].joined(separator: "\n")

    @Test func resultsCompareWithTheSamePeriodAYearEarlier() throws {
        let store = try Support.editedFixture(Self.resultsSQL)
        let page = try #require(FilingPage(store: store, filingID: Self.earnings))
        guard case .comparison(let block) = try #require(page.blocks.first) else {
            Issue.record("no comparison block")
            return
        }
        #expect(block.kind == .results)
        #expect(block.basis == .consolidated)
        #expect(block.period == DatePeriod(start: Support.date("2026-07-01"), end: Support.date("2026-09-30")))
        #expect(block.basePeriod?.start == Support.date("2025-07-01"))
        #expect(block.rows.map(\.name.ko) == ["매출", "영업이익", "순이익", "지배주주 순이익"])
        let revenue = block.rows[0]
        // (45110247 - 46721448) / 46721448 * 100 = -3.4485...
        #expect(revenue.change == Support.decimal("-3.45"))
        #expect(block.rows[1].change == Support.decimal("5.52"))
        // A negative base gives no rate; a missing base gives none either.
        #expect(block.rows[2].change == nil)
        #expect(block.rows[2].baseNotPositive)
        #expect(block.rows[3].base == nil)
        #expect(!block.rows[3].baseNotPositive)
        // The previous quarter is never compared (DESIGN.md: no quarter-on-quarter change).
        #expect(revenue.base == Support.decimal("46721448"))
    }

    @Test func disposalRowsFollowBoardTwelveA() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.disposal))
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        #expect(rows.map(\.name?.ko) == ["처분 주식 수", "주당 가격", "처분 금액", "처분 예정일", "이사회 결정일"])
        #expect(rows.map(\.name?.en) == ["Shares", "Price per share", "Amount", "Disposal date", "Board decision"])
        #expect(rows[3].value == .date(Support.date("2026-10-30")))
        // Free text (the stated purpose) is not a number row.
        #expect(!rows.contains { $0.origin.hasSuffix("dp_pp") })
    }

    @Test func aPeriodOverSeveralDaysIsOneRow() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.purchase))
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        let period = try #require(rows.first { $0.name?.ko == "취득 기간" })
        #expect(period.value == .dateRange(Support.date("2026-08-24"), Support.date("2026-11-21")))
        #expect(!rows.contains { $0.origin.hasSuffix("aqexpd_edd") })
    }

    @Test func sixNumbersAtMost() throws {
        let sql = [
            Self.fact(Self.dividend, 1, "dividend_per_share_common", "amount", "2500", "원", "dartdoc:dividend.dividend_per_share_common"),
            Self.fact(Self.dividend, 2, "dividend_per_share_preferred", "amount", "2500", "원", "dartdoc:dividend.dividend_per_share_preferred"),
            Self.fact(Self.dividend, 3, "dividend_yield_common", "ratio", "0.8", "%", "dartdoc:dividend.dividend_yield_common"),
            Self.fact(Self.dividend, 4, "dividend_yield_preferred", "ratio", "1.6", "%", "dartdoc:dividend.dividend_yield_preferred"),
            Self.fact(Self.dividend, 5, "dividend_total", "amount", "656885882500", "원", "dartdoc:dividend.dividend_total"),
            Self.fact(Self.dividend, 6, "dividend_record_date", "date", "2026-11-30", nil, "dartdoc:dividend.dividend_record_date"),
            Self.fact(Self.dividend, 7, "dividend_payment_date", "date", "2026-12-30", nil, "dartdoc:dividend.dividend_payment_date"),
            Self.fact(Self.dividend, 8, "dividend_decision_date", "date", "2026-10-29", nil, "dartdoc:dividend.dividend_decision_date"),
        ].joined(separator: "\n")
        let page = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: Self.dividend))
        #expect(page.numberCount == FilingPage.maxNumbers)
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        #expect(rows.last?.name?.ko == "지급 예정일")
    }

    @Test func correctedOutlookKeepsTheValueBeforeTheCorrection() throws {
        let filing = Self.outlookPlan
        let sql = [
            "UPDATE filings SET title_original = '[기재정정]영업실적등에대한전망(공정공시)', is_corrected = 1 WHERE id = '\(filing)';",
            Self.fact(filing, 1, "outlook_year_y1", "text", "2026", nil, "dartdoc:outlook.outlook_year_y1"),
            Self.fact(filing, 2, "outlook_item1_label", "text", "2026년 판매목표(대수)", nil, "dartdoc:outlook.outlook_item1_label"),
            Self.fact(filing, 3, "outlook_item1_y1", "amount", "4000000", "대수", "dartdoc:outlook.outlook_item1_y1"),
            Self.fact(filing, 4, "outlook_item2_label", "text", "2026년 판매목표(대수)-국내", nil, "dartdoc:outlook.outlook_item2_label"),
            Self.fact(filing, 5, "outlook_item2_y1", "amount", "664000", "대수", "dartdoc:outlook.outlook_item2_y1"),
            Self.fact(filing, 6, "outlook_change1_label", "text", "2026년 판매목표(대수)", nil, "dartdoc:outlook.outlook_change1_label"),
            Self.fact(filing, 7, "outlook_change1_before", "amount", "4158300", "대수", "dartdoc:outlook.outlook_change1_before"),
            Self.fact(filing, 8, "outlook_change1_after", "amount", "4000000", "대수", "dartdoc:outlook.outlook_change1_after"),
            Self.fact(filing, 9, "outlook_revenue_y1", "amount", "54684", "억원", "dartdoc:outlook.outlook_revenue_y1"),
            Self.fact(filing, 10, "outlook_change2_label", "text", "1. 연결 영업실적 전망 내용 - 매출액", nil, "dartdoc:outlook.outlook_change2_label"),
            Self.fact(filing, 11, "outlook_change2_before", "amount", "53200", "억원", "dartdoc:outlook.outlook_change2_before"),
            Self.fact(filing, 12, "outlook_change2_after", "amount", "54684", "억원", "dartdoc:outlook.outlook_change2_after"),
        ].joined(separator: "\n")
        let page = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: filing))
        #expect(page.isOutlook)
        #expect(!page.outlookHasNoFigures)
        guard case .outlook(let block) = try #require(page.blocks.first) else {
            Issue.record("no outlook block")
            return
        }
        #expect(block.year == "2026")
        #expect(block.items.map { $0.name(.ko, blockYear: block.year) } == ["매출", "전체", "국내"])
        #expect(block.items.map { $0.name(.en, blockYear: block.year) } == ["Revenue", "Total", "Korea"])
        #expect(block.items.map(\.before) == [Support.decimal("53200"), Support.decimal("4158300"), nil])
        #expect(block.items[1].isSalesTarget)
        // A label for another year keeps the company's words.
        #expect(block.items[1].name(.en, blockYear: "2027") == "2026년 판매목표(대수)")
    }

    @Test func outlookTableWithoutFigures() throws {
        let sql = "UPDATE filings SET title_original = '영업실적등에대한전망(공정공시)' WHERE id = '\(Self.outlookPlan)';"
        let table = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: Self.outlookPlan))
        #expect(table.outlookHasNoFigures)
        #expect(table.blocks.isEmpty)
        // A business plan is prose: it never shows the no-figures state.
        let plan = try #require(FilingPage(
            store: try BundleStore(contentsOf: Support.fixtureURL), filingID: Self.outlookPlan))
        #expect(!plan.outlookHasNoFigures)
    }

    @Test func unitSalesCompareTotalsAndTheYearToDate() throws {
        let filing = Self.earnings
        let sql = [
            "UPDATE filings SET category = 'unit_sales', title_original = '영업(잠정)실적(공정공시)' WHERE id = '\(filing)';",
            Self.fact(filing, 1, "units_period_start", "date", "2026-10-01", nil, "dartdoc:units.units_period_start"),
            Self.fact(filing, 2, "units_period_end", "date", "2026-10-31", nil, "dartdoc:units.units_period_end"),
            Self.fact(filing, 3, "units_total_current", "amount", "329773", "대", "dartdoc:units.units_total_current"),
            Self.fact(filing, 4, "units_total_year_ago", "amount", "352083", "대", "dartdoc:units.units_total_year_ago"),
            Self.fact(filing, 5, "units_total_cumulative", "amount", "3218586", "대", "dartdoc:units.units_total_cumulative"),
            Self.fact(filing, 6, "units_total_cumulative_year_ago", "amount", "3457429", "대", "dartdoc:units.units_total_cumulative_year_ago"),
        ].joined(separator: "\n")
        let page = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: filing))
        guard case .comparison(let block) = try #require(page.blocks.first) else {
            Issue.record("no comparison block")
            return
        }
        #expect(block.kind == .units)
        #expect(block.basis == nil)
        #expect(block.rows.map(\.name.ko) == ["전체 판매", "올해 누적 판매"])
        #expect(block.rows[0].change == Support.decimal("-6.34"))
        #expect(block.rows[1].isYearToDate)
    }

    @Test func clarificationStatusComesFromTheReportName() throws {
        let sql = "UPDATE filings SET category = 'clarification', "
            + "title_original = '풍문또는보도에대한해명(미확정)' WHERE id = '\(Self.outlookPlan)';"
        let page = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: Self.outlookPlan))
        #expect(page.clarificationStatus == .undecided)
        #expect(page.blocks.isEmpty)
        let plain = "UPDATE filings SET category = 'clarification', "
            + "title_original = '풍문또는보도에대한해명' WHERE id = '\(Self.outlookPlan)';"
        #expect(FilingPage(store: try Support.editedFixture(plain), filingID: Self.outlookPlan)?
            .clarificationStatus == nil)
    }

    @Test func secFilingListsItemsAndTheEventDate() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.appleEarnings))
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        #expect(rows.map(\.value) == [.text("2.02, 9.01"), .date(Support.date("2026-11-02"))])
        #expect(page.source.regulator == .sec)
        #expect(page.source.receiptNumber == "0000320193-26-000024")
        #expect(page.source.form == "8-K")
    }

    @Test func sourceDetailsForDart() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.correctedEarnings))
        #expect(page.source.receiptNumber == "20261029800099")
        #expect(page.source.url?.host == "dart.fss.or.kr")
        #expect(page.filing.isCorrected)
    }

    /// Only approved summaries reach the page: the bundle refuses any other review state.
    @Test func summaryLinesAreApprovedOnly() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.disposal))
        #expect(page.summaryLines(.ko).isEmpty)
        let approved = "INSERT INTO filing_summaries VALUES ('\(Self.disposal)', 'ko', 'summary', "
            + "'test line one', 'test line two', NULL, 'approved', 'x');"
        let withSummary = try #require(FilingPage(
            store: try Support.editedFixture(approved), filingID: Self.disposal))
        #expect(withSummary.summaryLines(.ko) == ["test line one", "test line two"])
        #expect(withSummary.summaryLines(.en).isEmpty)
        // The schema refuses any other state at insert, and the store refuses it on read.
        let staged = approved.replacingOccurrences(of: "'approved'", with: "'staged'")
        #expect(throws: (any Error).self) { try Support.editedFixture(staged) }
    }

    /// Every number and date of an event filing is on its page, up to the six-number cap:
    /// in a block, folded into a period, or as a row named from `FactNames` or the contract.
    @Test func everyNumberAndDateInTheFixtureIsShown() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        for filing in store.filings where filing.kind == .event {
            let facts = store.facts(forFiling: filing.id).filter { $0.value.kind != .text }
            let page = try #require(FilingPage(store: store, filingID: filing.id))
            let shown = page.blocks.reduce(into: Set<String>()) { origins, block in
                if case .rows(let rows) = block { origins.formUnion(rows.map(\.origin)) }
            }
            let folded = Set(facts.compactMap { FactRowValue.endOrigin(for: $0.origin) })
            let missing = facts.filter { !shown.contains($0.origin) && !folded.contains($0.origin) }
            #expect(missing.isEmpty || page.numberCount == FilingPage.maxNumbers,
                    "\(filing.id): \(missing.map(\.origin))")
            #expect(page.numberCount <= FilingPage.maxNumbers)
        }
    }

    @Test func purchaseRowsIncludeTheHoldingRatio() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FilingPage(store: store, filingID: Self.purchase))
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        #expect(rows.map(\.name?.ko) == [
            "취득 주식 수 (보통주)", "취득 금액 (보통주)", "취득 전 자기주식 비율 (보통주)", "취득 기간", "이사회 결정일",
        ])
    }

    /// A number `FactNames` does not name still shows; the app names it from the contract.
    @Test func anUnnamedNumberStillShows() throws {
        let sql = "UPDATE filing_facts SET origin = 'opendart:tsstkDpDecsn.new_field' "
            + "WHERE filing_id = '\(Self.disposal)' AND position = 1;"
        let page = try #require(FilingPage(store: try Support.editedFixture(sql), filingID: Self.disposal))
        guard case .rows(let rows) = try #require(page.blocks.first) else {
            Issue.record("no rows")
            return
        }
        #expect(rows.last?.origin == "opendart:tsstkDpDecsn.new_field")
        #expect(rows.last?.name == nil)
    }
}

@Suite("Annual page")
struct AnnualPageTests {
    static let samsungAnnual = "dart:20260310000123"
    static let appleAnnual = "sec:0000320193-25-000079"

    @Test func everyMetricWithTwoYears() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(AnnualPage(store: store, filingID: Self.samsungAnnual))
        #expect(page.fiscalYear == 2025)
        #expect(page.basis == "consolidated")
        #expect(page.currency == "KRW")
        #expect(page.rows.map(\.metric) == ReportedMetric.allCases)
        let revenue = page.rows[0]
        #expect(revenue.current?.fiscalYear == 2025)
        #expect(revenue.prior?.fiscalYear == 2024)
        guard case .result(let change)? = revenue.comparison else {
            Issue.record("revenue did not compare")
            return
        }
        // (300870903 - 258935494) / 258935494 * 100 = 16.195...
        #expect(change.percentChange == Support.decimal("16.20"))
        guard case .result(let margin)? = page.margin?.current else {
            Issue.record("no margin")
            return
        }
        #expect(margin.operatingMargin == Support.decimal("10.88"))
        #expect(page.notStated.isEmpty)
    }

    @Test func aMissingYearHasNoComparison() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(AnnualPage(store: store, filingID: Self.appleAnnual))
        #expect(page.rows.allSatisfy { $0.prior == nil && $0.comparison == nil })
        #expect(page.notStated == [.netIncome])
        #expect(page.margin?.prior == nil)
        #expect(page.currency == "USD")
    }

    @Test func aNegativeBaselineIsRefused() throws {
        let sql = "UPDATE figures SET value = '-2131' WHERE metric = 'eps' AND fiscal_year = 2024 "
            + "AND company_id = 'dart:00126380';"
        let page = try #require(AnnualPage(store: try Support.editedFixture(sql), filingID: Self.samsungAnnual))
        let eps = try #require(page.rows.first { $0.metric == .eps })
        #expect(eps.comparison == .refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline)))
    }

    @Test func restatedRowsAreMarked() throws {
        let sql = "UPDATE figures SET is_restated = 1 WHERE metric = 'revenue' AND fiscal_year = 2024 "
            + "AND company_id = 'dart:00126380';"
        let page = try #require(AnnualPage(store: try Support.editedFixture(sql), filingID: Self.samsungAnnual))
        #expect(page.rows[0].isRestated)
        #expect(page.rows[0].prior?.isRestated == true)
        #expect(!page.rows[1].isRestated)
    }

    @Test func summarySectionsAreInReviewUntilApproved() throws {
        // The fixture's test-only approved rows for this report: one_line and business.
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(AnnualPage(store: store, filingID: Self.samsungAnnual))
        #expect(!page.summaryInReview(.ko))
        #expect(page.lines(.oneLine, .en) == ["The company said it filed this report."])
        #expect(page.lines(.changes, .en).isEmpty)
        let removed = "DELETE FROM filing_summaries WHERE filing_id = '\(Self.samsungAnnual)' AND lang = 'ko';"
        let inReview = try #require(AnnualPage(
            store: try Support.editedFixture(removed), filingID: Self.samsungAnnual))
        #expect(inReview.summaryInReview(.ko))
        #expect(!inReview.summaryInReview(.en))
    }

    @Test func eventFilingsHaveNoAnnualPage() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        #expect(AnnualPage(store: store, filingID: FilingPageTests.disposal) == nil)
    }
}

@Suite("Filing formatting")
struct FilingFormattingTests {
    @Test func exactKoreanAmounts() {
        #expect(Formatting.exactAmount(Support.decimal("271545960000"), currency: "KRW", language: .ko)
            == "2,715억 4,596만원")
        #expect(Formatting.exactAmount(Support.decimal("656885882500"), currency: "KRW", language: .ko)
            == "6,568억 8,588만 2,500원")
        #expect(Formatting.exactAmount(Support.decimal("296000"), currency: "KRW", language: .ko)
            == "29만 6,000원")
        #expect(Formatting.exactAmount(Support.decimal("2500"), currency: "KRW", language: .ko) == "2,500원")
        #expect(Formatting.exactAmount(Support.decimal("478834000000"), currency: "USD", language: .ko)
            == "4,788억 3,400만 달러")
        #expect(Formatting.exactAmount(Support.decimal("-1819449000000"), currency: "KRW", language: .ko)
            == "\(Formatting.minus)1조 8,194억 4,900만원")
        #expect(Formatting.exactAmount(Support.decimal("7.49"), currency: "USD", language: .ko) == "7.49 달러")
        #expect(Formatting.exactAmount(0, currency: "KRW", language: .ko) == "0원")
        // English writes every digit, grouped.
        #expect(Formatting.exactAmount(Support.decimal("271545960000"), currency: "KRW", language: .en)
            == "₩271,545,960,000")
        #expect(Formatting.exactAmount(Support.decimal("-7.5"), currency: "USD", language: .en)
            == "\(Formatting.minus)$7.50")
    }

    @Test func statedUnits() {
        let hundredMillion = Formatting.stated(
            Support.decimal("45110247"), unit: "백만원", fallbackCurrency: "KRW", language: .ko)
        #expect(hundredMillion == "45조 1,102억 4,700만원")
        #expect(Formatting.stated(Support.decimal("45110247"), unit: "백만원", fallbackCurrency: "KRW", language: .en)
            == "₩45,110,247,000,000")
        // Compact, as the company page writes it; only money is shortened.
        #expect(Formatting.stated(
            Support.decimal("45110247"), unit: "백만원", fallbackCurrency: "KRW", language: .ko, precision: .compact)
            == "45조 1,102억원")
        #expect(Formatting.stated(
            Support.decimal("45110247"), unit: "백만원", fallbackCurrency: "KRW", language: .en, precision: .compact)
            == "₩45.11 trillion")
        #expect(Formatting.stated(
            Support.decimal("917385"), unit: "shares", fallbackCurrency: "KRW", language: .en, precision: .compact)
            == "917,385 shares")
        #expect(Formatting.stated(
            Support.decimal("0.8"), unit: "%", fallbackCurrency: "KRW", language: .en, precision: .compact)
            == "0.8%")
        #expect(Formatting.stated(Support.decimal("54684"), unit: "억원", fallbackCurrency: "KRW", language: .ko)
            == "5조 4,684억원")
        #expect(Formatting.stated(Support.decimal("4000000"), unit: "대수", fallbackCurrency: "KRW", language: .ko)
            == "4,000,000대")
        #expect(Formatting.stated(Support.decimal("4000000"), unit: "대", fallbackCurrency: "KRW", language: .en)
            == "4,000,000 units")
        #expect(Formatting.stated(Support.decimal("917385"), unit: "shares", fallbackCurrency: "KRW", language: .ko)
            == "917,385주")
        #expect(Formatting.stated(Support.decimal("0.8"), unit: "%", fallbackCurrency: "KRW", language: .en) == "0.8%")
        #expect(Formatting.stated(Support.decimal("-12.345"), unit: "%", fallbackCurrency: "KRW", language: .ko)
            == "−12.345%")
        #expect(Formatting.stated(Support.decimal("4950"), unit: "KRW_PER_SHARE", fallbackCurrency: "KRW", language: .en)
            == "₩4,950")
        #expect(Formatting.stated(1, unit: "furlongs", fallbackCurrency: "KRW", language: .ko) == nil)
    }

    @Test func periods() {
        let q3 = (Support.date("2026-07-01"), Support.date("2026-09-30"))
        #expect(Formatting.period(q3.0, q3.1, language: .ko) == "2026년 7–9월")
        #expect(Formatting.period(q3.0, q3.1, language: .en) == "Jul–Sep 2026")
        let october = (Support.date("2026-10-01"), Support.date("2026-10-31"))
        #expect(Formatting.period(october.0, october.1, language: .ko) == "2026년 10월")
        #expect(Formatting.period(october.0, october.1, language: .en) == "Oct 2026")
        let apple = (Support.date("2025-09-28"), Support.date("2026-09-26"))
        #expect(Formatting.period(apple.0, apple.1, language: .en) == "Sep 28, 2025–Sep 26, 2026")
        let split = (Support.date("2025-10-01"), Support.date("2026-09-30"))
        #expect(Formatting.period(split.0, split.1, language: .ko) == "2025년 10월–2026년 9월")
    }
}

@Suite("Figure history")
struct FigureHistoryTests {
    @Test func newestFirstWithTheLatestChange() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let history = try #require(FigureHistory(store: store, companyID: "dart:00126380", metric: .revenue))
        #expect(history.years.map(\.fiscalYear) == [2025, 2024])
        guard case .result(let change)? = history.change(fiscalYear: 2025) else {
            Issue.record("no change")
            return
        }
        #expect(change.percentChange == Support.decimal("16.20"))
        let apple = try #require(FigureHistory(store: store, companyID: "sec:0000320193", metric: .revenue))
        #expect(apple.years.count == 1)
        #expect(apple.change(fiscalYear: apple.years[0].fiscalYear) == nil)
        #expect(history.change(fiscalYear: 2024) == nil)
    }
}

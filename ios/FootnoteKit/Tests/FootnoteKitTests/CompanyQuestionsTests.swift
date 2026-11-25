import Foundation
import Testing
@testable import FootnoteKit

/// "Ask about this company" (D95) on the fixture: Samsung has a quarter report, two annual
/// years, an approved business section and an outlook filing; Apple has a quarter report,
/// one annual year, no annual summary and no outlook.
@Suite("Company questions")
struct CompanyQuestionsTests {
    static let samsung = "dart:00126380"
    static let apple = "sec:0000320193"
    static let samsungQuarter = "dart:20261116000111"
    static let samsungAnnual = "dart:20260310000123"
    static let samsungOutlook = "dart:20261029800102"
    static let appleQuarter = "sec:0000320193-26-000020"
    static let appleAnnual = "sec:0000320193-25-000079"

    let store: BundleStore

    init() throws {
        store = try BundleStore(contentsOf: Support.fixtureURL)
    }

    private func answer(_ intent: QuestionIntent, _ companyID: String = samsung, in store: BundleStore? = nil) throws -> Answer {
        try #require(CompanyAnswerer.answer(intent, store: store ?? self.store, companyID: companyID))
    }

    private func figures(_ answer: Answer) -> [AnswerFigures] {
        answer.parts.compactMap { if case .figures(let figures) = $0 { figures } else { nil } }
    }

    private func statements(_ answer: Answer) -> [AnswerSentence] {
        answer.parts.compactMap { part in
            switch part {
            case .statement(let sentence), .filing(let sentence, _): sentence
            case .figures(let figures): figures.statement
            case .summary: nil
            }
        }
    }

    private func row(_ figures: AnswerFigures, _ metric: ReportedMetric) throws -> AnswerFigureRow {
        try #require(figures.rows.first { $0.metric == metric })
    }

    // MARK: - Every intent

    @Test(arguments: QuestionIntent.allCases)
    func everyIntentAnswersEveryCompany(_ intent: QuestionIntent) throws {
        for company in store.companies {
            let first = try answer(intent, company.id)
            #expect(first.intent == intent)
            #expect(first.company == company)
            #expect(!first.parts.isEmpty)
            // Deterministic: the same bundle, company and intent give the same answer.
            #expect(try answer(intent, company.id) == first)
        }
        #expect(CompanyAnswerer.answer(intent, store: store, companyID: "dart:missing") == nil)
    }

    @Test func intentsAreOfferedInTheOwnersOrder() {
        #expect(QuestionIntent.allCases.map(\.rawValue) == [
            "should_buy", "fundamentals", "recent_trend", "profit_or_loss", "revenue", "next_quarter_revenue",
        ])
        #expect(QuestionIntent.allCases.filter(\.isDeflected) == [.shouldBuy, .nextQuarterRevenue])
    }

    // MARK: - Fundamentals

    @Test func fundamentalsQuoteTheBusinessAndShowTheQuarter() throws {
        let answer = try answer(.fundamentals)
        guard case .summary(let business) = answer.parts[0] else {
            Issue.record("expected the business summary first")
            return
        }
        #expect(business.filing.id == Self.samsungAnnual)
        #expect(business.section == .business)
        #expect(business.lines(.ko) == store.summary(forFiling: Self.samsungAnnual, language: .ko, section: .business)?.lines)
        #expect(business.lines(.en) == ["The company said it filed this report."])

        let quarter = try #require(figures(answer).first)
        #expect(quarter.filing.id == Self.samsungQuarter)
        #expect(quarter.span == .quarter(fiscalYear: 2026, fiscalQuarter: 3))
        #expect(quarter.statement == nil)
        #expect(quarter.period == AnswerPeriod(start: Support.date("2026-07-01"), end: Support.date("2026-09-30")))
        #expect(quarter.priorPeriod == AnswerPeriod(start: Support.date("2025-07-01"), end: Support.date("2025-09-30")))
        #expect(quarter.basis == "consolidated")
        #expect(quarter.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncomeAttributable])

        // Exact decimals, never rounded or turned into floating point.
        let revenue = try row(quarter, .revenue)
        #expect(revenue.current == AnswerAmount(value: Support.decimal("86061747000000"), unit: "KRW", currency: "KRW"))
        #expect(revenue.prior?.value == Support.decimal("79098718000000"))
        #expect(revenue.change == .result(Support.decimal("8.80")))
        // A loss a year earlier: the calculator refuses the percentage.
        let operating = try row(quarter, .operatingIncome)
        #expect(operating.prior?.value == Support.decimal("-1200000000000"))
        #expect(operating.change == .refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline)))
        #expect(answer.sources.map(\.id) == [Self.samsungAnnual, Self.samsungQuarter])
        #expect(answer.related.isEmpty)
    }

    @Test func fundamentalsSayWhenTheBusinessSummaryIsMissing() throws {
        let answer = try answer(.fundamentals, Self.apple)
        #expect(answer.parts.first == .statement(.businessMissing))
        #expect(figures(answer).map(\.filing.id) == [Self.appleQuarter])
    }

    // MARK: - Recent trend and revenue

    @Test func recentTrendComparesTheQuarterAndTheYear() throws {
        let answer = try answer(.recentTrend)
        #expect(answer.parts.first == .statement(.trendScope))
        let blocks = figures(answer)
        #expect(blocks.map(\.filing.id) == [Self.samsungQuarter, Self.samsungAnnual])
        #expect(blocks.map(\.statement) == [.revenueQuarterUp, .revenueYearUp])
        let year = blocks[1]
        #expect(year.span == .year(fiscalYear: 2025))
        #expect(year.period == AnswerPeriod(start: Support.date("2025-01-01"), end: Support.date("2025-12-31")))
        #expect(year.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncomeAttributable])
        let revenue = try row(year, .revenue)
        #expect(revenue.current?.value == Support.decimal("300870903000000"))
        #expect(revenue.prior?.value == Support.decimal("258935494000000"))
        #expect(revenue.change == .result(Support.decimal("16.20")))
    }

    @Test func aYearWithoutThePriorYearIsNotCompared() throws {
        let answer = try answer(.recentTrend, Self.apple)
        let year = try #require(figures(answer).last)
        #expect(year.filing.id == Self.appleAnnual)
        #expect(year.priorPeriod == nil)
        #expect(year.statement == .revenueYearNotCompared)
        let revenue = try row(year, .revenue)
        #expect(revenue.current?.value == Support.decimal("416161000000"))
        #expect(revenue.prior == nil)
        #expect(revenue.change == .refusal(Refusal(.missingPeriod, .missingFact)))
    }

    @Test func revenueShowsOnlyRevenue() throws {
        let answer = try answer(.revenue, Self.apple)
        let blocks = figures(answer)
        #expect(blocks.map { $0.rows.map(\.metric) } == [[.revenue], [.revenue]])
        #expect(blocks[0].statement == .revenueQuarterUp)
        #expect(try row(blocks[0], .revenue).change == .result(Support.decimal("11.76")))
    }

    @Test func revenueDirectionFollowsTheRoundedChange() throws {
        let cases: [(String, AnswerSentence)] = [
            ("70000000000000", .revenueQuarterDown),
            ("79098718000000", .revenueQuarterSame),
            // +0.004%: shown as 0.00%, so it reads as about the same.
            ("79101882000000", .revenueQuarterSame),
            ("79105000000000", .revenueQuarterUp),
        ]
        for (value, expected) in cases {
            let edited = try Support.editedFixture("""
                UPDATE quarter_figures SET value = '\(value)'
                WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'revenue' AND fiscal_year = 2026
                """)
            let quarter = try #require(figures(try answer(.revenue, in: edited)).first)
            #expect(quarter.statement == expected, "\(value)")
        }
    }

    @Test func aMissingQuarterRevenueIsUnavailableNotZero() throws {
        let edited = try Support.editedFixture(
            "DELETE FROM quarter_figures WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'revenue'")
        let quarter = try #require(figures(try answer(.revenue, in: edited)).first)
        #expect(quarter.statement == .revenueQuarterMissing)
        let revenue = try row(quarter, .revenue)
        #expect(revenue.current == nil)
        #expect(revenue.change == nil)
    }

    // MARK: - Profit or loss

    @Test func profitOrLossReadsNetIncome() throws {
        let answer = try answer(.profitOrLoss)
        let blocks = figures(answer)
        #expect(blocks.map(\.statement) == [.profitQuarter, .profitYear])
        #expect(blocks.map { $0.rows.map(\.metric) } == [
            [.netIncomeAttributable, .operatingIncome], [.netIncomeAttributable, .operatingIncome],
        ])
        #expect(try row(blocks[0], .netIncomeAttributable).current?.value == Support.decimal("12006461000000"))
        #expect(try row(blocks[1], .netIncomeAttributable).current?.value == Support.decimal("33621363000000"))
    }

    @Test(arguments: [
        ("-648181000000", AnswerSentence.lossQuarter),
        ("0", AnswerSentence.breakEvenQuarter),
    ])
    func aLossOrZeroIsSaidAsSuch(_ value: String, _ expected: AnswerSentence) throws {
        let edited = try Support.editedFixture("""
            UPDATE quarter_figures SET value = '\(value)'
            WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'net_income_attributable' AND fiscal_year = 2026
            """)
        let quarter = try #require(figures(try answer(.profitOrLoss, in: edited)).first)
        #expect(quarter.statement == expected)
        #expect(try row(quarter, .netIncomeAttributable).current?.value == Support.decimal(value))
    }

    @Test func netIncomeStandsInWhenNoAttributableFigureIsStated() throws {
        let edited = try Support.editedFixture("""
            DELETE FROM quarter_figures WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'net_income_attributable';
            DELETE FROM figures WHERE company_id = '\(Self.samsung)' AND metric = 'net_income_attributable';
            """)
        let blocks = figures(try answer(.profitOrLoss, in: edited))
        #expect(blocks.map { $0.rows.first?.metric } == [.netIncome, .netIncome])
        #expect(try row(blocks[0], .netIncome).current?.value == Support.decimal("12225747000000"))
        #expect(try row(blocks[1], .netIncome).current?.value == Support.decimal("34451351000000"))
        #expect(blocks.map(\.statement) == [.profitQuarter, .profitYear])
    }

    @Test func noNetIncomeIsUnavailable() throws {
        let edited = try Support.editedFixture("""
            DELETE FROM quarter_figures WHERE filing_id = '\(Self.samsungQuarter)' AND metric IN ('net_income', 'net_income_attributable');
            DELETE FROM figures WHERE company_id = '\(Self.samsung)' AND metric IN ('net_income', 'net_income_attributable');
            """)
        let blocks = figures(try answer(.profitOrLoss, in: edited))
        #expect(blocks.map(\.statement) == [.incomeQuarterMissing, .incomeYearMissing])
        for block in blocks {
            let income = try row(block, .netIncomeAttributable)
            #expect(income.current == nil && income.prior == nil && income.change == nil)
            // The other row still shows what the report states.
            #expect(try row(block, .operatingIncome).current != nil)
        }
    }

    // MARK: - Missing reports

    @Test func noQuarterlyReportIsSaid() throws {
        let edited = try Support.editedFixture("""
            DELETE FROM quarter_figures WHERE company_id = '\(Self.samsung)';
            DELETE FROM filings WHERE id = '\(Self.samsungQuarter)';
            """)
        for intent in [QuestionIntent.fundamentals, .recentTrend, .profitOrLoss, .revenue] {
            let answer = try answer(intent, in: edited)
            #expect(answer.parts.contains(.statement(.quarterMissing)), "\(intent)")
            #expect(!answer.sources.contains { $0.id == Self.samsungQuarter })
        }
    }

    @Test func noAnnualFiguresIsSaid() throws {
        let edited = try Support.editedFixture(
            "UPDATE filings SET period_label = NULL WHERE id = '\(Self.samsungAnnual)'")
        let answer = try answer(.recentTrend, in: edited)
        #expect(answer.parts.last == .statement(.yearMissing))
        #expect(figures(answer).map(\.filing.id) == [Self.samsungQuarter])
    }

    // MARK: - Deflected questions

    @Test(arguments: [samsung, apple])
    func buyingIsDeflectedToReportedFacts(_ companyID: String) throws {
        let answer = try answer(.shouldBuy, companyID)
        #expect(answer.parts == [.statement(.noAdvice), .statement(.reportedFacts)])
        #expect(answer.sources.isEmpty)
        #expect(answer.related == [.fundamentals, .profitOrLoss, .recentTrend])
        #expect(answer.related.allSatisfy { !$0.isDeflected })
    }

    @Test func nextQuarterPointsToTheCompanysOwnOutlook() throws {
        let answer = try answer(.nextQuarterRevenue)
        let outlook = try #require(store.filing(id: Self.samsungOutlook))
        #expect(outlook.category == .outlook)
        #expect(answer.parts == [.statement(.noEstimates), .filing(.outlookFiled, outlook)])
        // No figure is ever offered as next quarter's revenue.
        #expect(figures(answer).isEmpty)
        #expect(answer.related == [.revenue, .recentTrend])
    }

    @Test func nextQuarterWithoutAnOutlookSaysSo() throws {
        let answer = try answer(.nextQuarterRevenue, Self.apple)
        #expect(answer.parts == [.statement(.noEstimates), .statement(.noOutlook)])
        #expect(answer.sources.isEmpty)
    }

    // MARK: - Wording

    /// The answer's prose is fixed text: figures appear only as structured amounts.
    @Test func sentencesAndQuestionsHoldNoDigits() {
        let texts = AnswerSentence.allCases.flatMap { [$0.text(.ko), $0.text(.en)] }
            + QuestionIntent.allCases.flatMap { [$0.question(.ko), $0.question(.en)] }
        for text in texts {
            #expect(!text.unicodeScalars.contains { CharacterSet.decimalDigits.contains($0) }, "\(text)")
            #expect(!text.contains("\u{2014}"), "\(text)")
        }
    }

    @Test func eachLanguageIsWrittenInItsOwnScript() {
        func hasHangul(_ text: String) -> Bool { text.unicodeScalars.contains { (0xAC00...0xD7A3).contains($0.value) } }
        for sentence in AnswerSentence.allCases {
            #expect(hasHangul(sentence.text(.ko)), "\(sentence)")
            #expect(!hasHangul(sentence.text(.en)), "\(sentence)")
        }
        for intent in QuestionIntent.allCases {
            #expect(hasHangul(intent.question(.ko)) && !hasHangul(intent.question(.en)))
        }
    }
}

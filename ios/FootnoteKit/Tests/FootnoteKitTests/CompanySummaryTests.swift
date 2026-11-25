import Foundation
import Testing
@testable import FootnoteKit

/// The company page's summary card, a filing row's second line and the search across
/// filings and terms (D100) on the fixture.
@Suite("Company summary")
struct CompanySummaryTests {
    static let samsung = CompanyQuestionsTests.samsung
    static let apple = CompanyQuestionsTests.apple
    static let samsungQuarter = CompanyQuestionsTests.samsungQuarter
    static let samsungAnnual = CompanyQuestionsTests.samsungAnnual

    let store: BundleStore

    init() throws {
        store = try BundleStore(contentsOf: Support.fixtureURL)
    }

    // MARK: - Summary card

    @Test func samsungShowsTheYearAndTheQuarter() throws {
        let summary = try #require(CompanyAnswerer.summary(store: store, companyID: Self.samsung))
        let year = try #require(summary.yearFigures)
        #expect(year.filing.id == Self.samsungAnnual)
        #expect(year.statement == .revenueYearUp)
        #expect(year.rows.map(\.metric) == [.revenue])
        #expect(year.rows[0].current?.value == Support.decimal("300870903000000"))
        #expect(year.rows[0].change == .result(Support.decimal("16.20")))

        let quarter = try #require(summary.quarterFigures)
        #expect(quarter.filing.id == Self.samsungQuarter)
        #expect(quarter.statement == .revenueQuarterUp)
        #expect(quarter.rows.map(\.metric) == [.revenue, .operatingIncome, .netIncomeAttributable])
        #expect(quarter.rows[0].change == .result(Support.decimal("8.80")))
    }

    /// The card is the answers' own figures, so the two never disagree.
    @Test func theCardMatchesTheRecentTrendAnswer() throws {
        for company in store.companies {
            let summary = try #require(CompanyAnswerer.summary(store: store, companyID: company.id))
            let answer = try #require(CompanyAnswerer.answer(.recentTrend, store: store, companyID: company.id))
            let answered = answer.parts.compactMap { if case .figures(let f) = $0 { f } else { nil } }
            if let quarter = summary.quarterFigures {
                #expect(answered.first { if case .quarter = $0.span { true } else { false } } == quarter)
            }
            if let year = summary.yearFigures {
                let annual = try #require(answered.first { if case .year = $0.span { true } else { false } })
                #expect(year.filing == annual.filing)
                #expect(year.rows.first == annual.rows.first)
            }
        }
    }

    @Test func aMissingQuarterIsSaidNotZero() throws {
        let edited = try Support.editedFixture("""
            DELETE FROM quarter_figures WHERE company_id = '\(Self.samsung)';
            DELETE FROM filings WHERE id = '\(Self.samsungQuarter)';
            """)
        let summary = try #require(CompanyAnswerer.summary(store: edited, companyID: Self.samsung))
        #expect(summary.quarter == .statement(.quarterMissing))
        #expect(summary.quarterFigures == nil)
        #expect(summary.yearFigures != nil)
    }

    @Test func aMissingYearIsSaidNotZero() throws {
        let edited = try Support.editedFixture(
            "UPDATE filings SET period_label = NULL WHERE id = '\(Self.samsungAnnual)'")
        let summary = try #require(CompanyAnswerer.summary(store: edited, companyID: Self.samsung))
        #expect(summary.year == .statement(.yearMissing))
    }

    @Test func aMissingQuarterRevenueKeepsItsRowWithNoFigure() throws {
        let edited = try Support.editedFixture(
            "DELETE FROM quarter_figures WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'revenue'")
        let quarter = try #require(CompanyAnswerer.summary(store: edited, companyID: Self.samsung)?.quarterFigures)
        #expect(quarter.statement == .revenueQuarterMissing)
        #expect(quarter.rows[0].metric == .revenue)
        #expect(quarter.rows[0].current == nil)
        #expect(quarter.rows[0].change == nil)
    }

    @Test func anUnknownCompanyHasNoSummary() {
        #expect(CompanyAnswerer.summary(store: store, companyID: "dart:missing") == nil)
    }

    // MARK: - Quarter sentence

    @Test func theQuarterReportUsesTheAnswersSentence() throws {
        let page = try #require(QuarterPage(store: store, filingID: Self.samsungQuarter))
        #expect(page.revenueSentence == .revenueQuarterUp)
        let edited = try Support.editedFixture("""
            UPDATE quarter_figures SET value = '70000000000000'
            WHERE filing_id = '\(Self.samsungQuarter)' AND metric = 'revenue' AND fiscal_year = 2026
            """)
        let lower = try #require(QuarterPage(store: edited, filingID: Self.samsungQuarter))
        #expect(lower.revenueSentence == .revenueQuarterDown)
    }

    // MARK: - Second line

    @Test func onlyAnApprovedSummaryGivesASecondLine() {
        #expect(store.firstSummaryLine(filingID: "dart:20260821000616", language: .ko) == "회사는 이 공시를 제출했다고 밝혔어요")
        #expect(store.firstSummaryLine(filingID: "dart:20260821000616", language: .en) == "The company said it filed this report.")
        // An annual report's business section is not a row's summary.
        #expect(store.firstSummaryLine(filingID: Self.samsungAnnual, language: .ko) == nil)
        #expect(store.firstSummaryLine(filingID: "dart:20261029800748", language: .ko) == nil)
    }

    @Test func repeatedTitlesAreFound() throws {
        let page = try #require(CompanyPage(store: store, companyID: Self.samsung))
        let filings = page.filings
        let repeated = Titles.repeatedTitleIDs(filings, language: .ko)
        #expect(repeated.isSuperset(of: ["dart:20261029800748", "dart:20261029800752"]))
        #expect(!repeated.contains("dart:20261029800101"))
        for id in repeated {
            let filing = try #require(filings.first { $0.id == id })
            let title = Titles.title(for: filing, language: .ko)
            #expect(filings.filter { Titles.title(for: $0, language: .ko) == title }.count > 1)
        }
        #expect(Titles.repeatedTitleIDs([], language: .en).isEmpty)
    }

    // MARK: - Search

    @Test func aCategoryWordFindsItsFilings() {
        let matches = store.directoryMatches("배당", language: .ko)
        #expect(matches.filings.map(\.id) == ["dart:20261029800101"])
        #expect(matches.filingCount == 1)
        // English words find the same filings while the app shows Korean.
        #expect(store.directoryMatches("dividend", language: .ko).filings.map(\.id) == ["dart:20261029800101"])
    }

    @Test func filingsComeNewestFirstAndAreCapped() {
        let matches = store.directoryMatches("자사주", language: .ko)
        #expect(matches.filings.map(\.id) == ["dart:20261029000539", "dart:20260821000616"])
        let all = store.directoryMatches("8-K", language: .en)
        #expect(all.filings.count <= DirectoryMatches.maxFilings)
        #expect(all.filingCount >= all.filings.count)
        #expect(all.filings == all.filings.sorted { $0.filedOn > $1.filedOn })
    }

    @Test func aTermWordFindsTheGlossaryEntry() {
        let matches = store.directoryMatches("영업이익률", language: .ko)
        #expect(matches.terms.map(\.termKey) == ["operating_margin"])
        // The glossary's own search: a term's definition counts too (operating margin names
        // revenue), in dictionary order.
        #expect(store.directoryMatches("Revenue", language: .en).terms.map(\.termKey) == ["operating_margin", "revenue"])
    }

    @Test func blankOrUnmatchedQueriesFindNothing() {
        #expect(store.directoryMatches("   ", language: .ko).isEmpty)
        #expect(store.directoryMatches("zzzz", language: .en).isEmpty)
    }
}

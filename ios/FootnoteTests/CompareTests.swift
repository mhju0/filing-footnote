import Foundation
import FootnoteKit
import Testing
@testable import Footnote

private final class CompareBundle {}

private let fixture = Bundle(for: CompareBundle.self).url(forResource: "footnote", withExtension: "sqlite")!
private let samsung = "dart:00126380"
private let apple = "sec:0000320193"
private let hynix = "dart:00164779"

/// The fixture with SK hynix added: Samsung's own figures under another DART company, so
/// both report in won.
private func withHynix(_ extra: String = "") throws -> BundleStore {
    try BundleStore(contentsOf: FilingPageTests.edited("""
        INSERT INTO companies SELECT '\(hynix)', regulator, '000660', 'SK하이닉스', 'SK hynix', market,
          currency, fiscal_year_end, sort_order + 1 FROM companies WHERE id = '\(samsung)';
        INSERT INTO figures SELECT 'hynix-' || id, '\(hynix)', filing_id, metric, fiscal_year, period_start,
          period_end, value, unit, currency, basis, is_restated, regulator_tag
          FROM figures WHERE company_id = '\(samsung)';
        \(extra)
        """))
}

@Suite("Compare launch routes")
struct CompareLaunchRouteTests {
    @Test func figureAndCompareRoutesStackOverTheCompany() throws {
        let year = try #require(LaunchRoute(argument: "yearcalc=\(samsung)|revenue|2025"))
        #expect(year.companiesPath == [
            .company(samsung), .figure(samsung, "revenue", 2025),
            .yearCompare(samsung, "revenue", 2025), .yearCalculation(samsung, "revenue", 2025),
        ])
        #expect(year.detailPath.count == 3)
        let compare = try #require(LaunchRoute(argument: "compare=\(samsung)|\(apple)|ebitda|none|2025"))
        // No figure screen for a metric the app does not cover; no measure chosen.
        #expect(compare.detailPath == [.companyCompare(CompanyCompareRoute(
            companyID: samsung, peerID: apple, metric: "ebitda", measure: nil, fiscalYear: 2025))])
        let picker = try #require(LaunchRoute(argument: "picker=\(samsung)|revenue|2025"))
        #expect(picker.opensPicker(samsung))
        #expect(!picker.opensPicker(apple))
        #expect(picker.figureFilingID(try BundleStore(contentsOf: fixture)) == "dart:20260310000123")
    }
}

@Suite("Compare copy")
struct CompareCopyTests {
    private let store = try! BundleStore(contentsOf: fixture)

    /// An explanation for each of the six reasons, through the screens' models.
    private func explanations() throws -> [RefusalExplanation] {
        let pages = [
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: nil, fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "operating_margin", measure: "growth_rate", fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: "growth_rate", fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: "absolute_amount", fiscalYear: 2025),
        ].compactMap { $0?.explanation }
        let separate = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET basis = 'separate' WHERE company_id = '\(samsung)'"))
        let negative = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET value = '-2131' WHERE company_id = '\(samsung)' AND metric = 'eps' AND fiscal_year = 2024"))
        let years = [
            YearComparePage(store: separate, companyID: samsung, metric: "revenue", fiscalYear: 2025),
            YearComparePage(store: negative, companyID: samsung, metric: "eps", fiscalYear: 2025),
            YearComparePage(store: store, companyID: apple, metric: "revenue", fiscalYear: 2025),
            YearComparePage(store: store, companyID: samsung, metric: nil, fiscalYear: 2025),
        ].compactMap { $0?.explanation }
        return pages + years
    }

    @Test func everyReasonHasItsCopyAndNoRanking() throws {
        let all = try explanations()
        #expect(Set(all.map(\.refusal.reason)) == Set(RefusalReason.allCases))
        let ranking = ["better", "worse", "outperform", "underperform", "beat", "lag", "나아", "나빠", "앞서", "뒤처"]
        for explanation in all {
            #expect(!explanation.actions.isEmpty)
            for language in Language.allCases {
                var strings = [
                    PageCopy.refusalTitle(explanation, language), PageCopy.refusalReason(explanation, language),
                    PageCopy.refusalCode(explanation.refusal, language),
                ]
                strings += explanation.actions.map {
                    PageCopy.actionLabel(
                        $0, reason: explanation.refusal.reason, detail: explanation.refusal.detail,
                        metric: explanation.metric, language)
                }
                if let body = PageCopy.refusalBody(explanation.refusal, language) { strings.append(body) }
                for string in strings {
                    #expect(!string.isEmpty)
                    #expect(!string.contains("\u{2014}"), "\(string)")
                    #expect(!ranking.contains { string.lowercased().contains($0) }, "\(string)")
                }
            }
        }
    }

    @Test func reasonSentencesNameCompaniesYearsAndCurrencies() throws {
        let all = try explanations()
        let currency = try #require(all.first { $0.refusal.reason == .incompatibleCurrency })
        #expect(PageCopy.refusalReason(currency, .ko) == "삼성전자는 원, 애플은 달러로 보고해요.")
        #expect(PageCopy.refusalReason(currency, .en) == "Samsung Electronics reports in won and Apple in dollars.")
        let missing = try #require(all.first { $0.refusal.reason == .missingPeriod && $0.context != .lastYear })
        #expect(PageCopy.refusalReason(missing, .ko) == "애플의 2024 회계연도 매출 숫자가 공시에 없어요.")
        #expect(PageCopy.refusalReason(missing, .en) == "The filings on file have no FY2024 revenue for Apple.")
        let baseline = try #require(all.first { $0.refusal.detail == .nonpositiveBaseline })
        #expect(PageCopy.refusalReason(baseline, .ko) == "삼성전자의 2024 회계연도 주당순이익은 \u{2212}2,131원이에요.")
        #expect(PageCopy.refusalBody(baseline.refusal, .ko) == nil)
        #expect(baseline.actions.map {
            PageCopy.actionLabel($0, reason: baseline.refusal.reason, detail: baseline.refusal.detail,
                                 metric: baseline.metric, .ko)
        } == ["연도별 숫자 보기"])
        let ambiguous = try #require(all.first { $0.refusal.detail == .measureNotSpecified })
        #expect(PageCopy.refusalReason(ambiguous, .ko) == "삼성전자와 애플의 무엇을 비교할지 정해지지\u{00A0}않았어요.")
    }

    @Test func koreanParticlesFollowTheSpokenEnd() {
        #expect(Korean.topic("삼성전자") == "삼성전자는")
        #expect(Korean.topic("애플") == "애플은")
        #expect(Korean.topic("삼성SDI") == "삼성SDI는")
        #expect(Korean.topic("NAVER") == "NAVER는")
        #expect(Korean.and("애플") == "애플과 ")
        #expect(Korean.copula("\u{2212}7.49 달러") == "\u{2212}7.49 달러예요")
        #expect(Korean.copula("\u{2212}2,131원") == "\u{2212}2,131원이에요")
    }

    @Test func caveatAndDifference() throws {
        let page = try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2025))
        // Both are FY2025, ending three months apart, so the periods sentence comes first.
        #expect(PageCopy.caveat(page.caveat, .ko)
            == "두\u{00A0}회사의 2025\u{00A0}회계연도는 같은 기간이 아니에요. "
            + "두\u{00A0}회사는 회계 기준(K-IFRS, US GAAP)과 결산월(12월,\u{00A0}9월)이 달라요. 같은 이름의 숫자라도 계산 범위가 조금 다를 수 있어요.")
        #expect(PageCopy.caveat(page.caveat, .en) == "The two companies’ FY2025 years cover different periods. "
            + "The two companies use different accounting standards "
            + "(K-IFRS, US GAAP) and year-ends (December,\u{00A0}September). Figures with the same name can cover slightly different items.")
        let difference = try #require(page.difference)
        #expect(PageCopy.rateDifference(difference, .ko) == "21.09%포인트")
        #expect(PageCopy.rateDifference(difference, .en) == "21.09 percentage points")
        #expect(CalculationView.differenceText(difference, page.calculations, .ko)
                == "|10.88 \u{2212} 31.97| = 21.09%포인트")
        #expect(CalculationView.differenceText(difference, page.calculations, .en)
                == "|10.88 \u{2212} 31.97| = 21.09 percentage points")
        for language in Language.allCases {
            #expect(!PageCopy.caveat(page.caveat, language).contains("\u{2014}"))
        }
    }

    @Test func calculationCopy() throws {
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: "revenue", fiscalYear: 2025))
        let calculation = try #require(page.calculation)
        #expect(PageCopy.growthEquation(calculation.result)
            == "(300,870,903,000,000 \u{2212} 258,935,494,000,000) ÷ 258,935,494,000,000 × 100")
        #expect(PageCopy.signedPercent(calculation.result.percentChange) == "+16.20%")
        #expect(PageCopy.exact(calculation.current, .ko) == "300조 8,709억 300만원")
        #expect(PageCopy.exact(calculation.current, .en) == "₩300,870,903,000,000")
        #expect(PageCopy.periodLengths(366, 365, .ko) == "12개월씩")
        #expect(PageCopy.periodLengths(364, 371, .en) == "52 and 53 weeks")
        #expect(PageCopy.unitAndRounding("KRW", .en) == "Unit: KRW" + Copy.dot + "rounded to two decimals")
        #expect(PageCopy.checkLabel(.consecutiveYears(priorDays: 365, currentDays: 366), .en)
            == "Consecutive years, same length")
        #expect(PageCopy.checkLabel(.consecutiveYears(priorDays: 364, currentDays: 371), .en) == "Consecutive years")
        #expect(PageCopy.checkLabel(.consecutiveYears(priorDays: 364, currentDays: 371), .ko) == "이어지는 두 해")
        #expect(PageCopy.bothFrom(try #require(calculation.currentSource), .en).hasPrefix("Both figures come from the annual report"))
        let strings = calculation.checks.flatMap { [PageCopy.checkLabel($0, .ko), PageCopy.checkValue($0, .en)] }
        for string in strings { #expect(!string.isEmpty && !string.contains("\u{2014}")) }
    }

    /// Two won reporters: the amount refusal names amounts, not a mismatch of conditions.
    @Test func amountsBetweenTwoWonCompanies() throws {
        let page = try #require(CompanyComparePage(
            store: withHynix(), companyID: samsung, peerID: hynix, metric: "revenue",
            measure: "absolute_amount", fiscalYear: 2025))
        let explanation = try #require(page.explanation)
        #expect(explanation.refusal == Refusal(.incompatibleComparison, .absoluteAmountAcrossCompanies))
        #expect(PageCopy.refusalTitle(explanation, .ko) == "금액은 비교하지 않아요")
        #expect(PageCopy.refusalTitle(explanation, .en) == "Amounts are not compared")
        #expect(PageCopy.refusalBody(explanation.refusal, .ko)
            == "회사끼리는 금액 대신 증가율과 영업이익률 같은 비율을 비교해요.")
        #expect(PageCopy.refusalCode(explanation.refusal, .ko) == "사유: 금액은 비교 대상이 아니에요")
        #expect(PageCopy.refusalReason(explanation, .ko) == "삼성전자와 SK하이닉스의 금액은 나란히 놓지\u{00A0}않아요.")
        for language in Language.allCases {
            let strings = [PageCopy.refusalTitle(explanation, language), PageCopy.refusalBody(explanation.refusal, language) ?? "",
                           PageCopy.refusalCode(explanation.refusal, language)]
            for string in strings {
                for word in ["기간", "기준", "단위", "period", "basis", "unit", "조건", "condition"] {
                    #expect(!string.lowercased().contains(word), "\(string)")
                }
            }
        }
    }

    /// The sentence names the company whose figures fail, here the one picked.
    @Test func reasonNamesTheCulprit() throws {
        let separate = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET basis = 'separate' WHERE company_id = '\(apple)'"))
        let basis = try #require(CompanyComparePage(
            store: separate, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2025)?.explanation)
        #expect(PageCopy.refusalReason(basis, .ko) == "애플의 매출 숫자는 연결 기준이 아니에요.")
        // Two won reporters, the peer's two years ending on different days.
        let shifted = try withHynix(
            "UPDATE figures SET period_end = '2024-11-30' WHERE company_id = '\(hynix)' AND metric = 'revenue' AND fiscal_year = 2024;")
        let mismatch = try #require(CompanyComparePage(
            store: shifted, companyID: samsung, peerID: hynix, metric: "revenue",
            measure: "growth_rate", fiscalYear: 2025)?.explanation)
        #expect(mismatch.refusal.reason == .incompatibleComparison)
        #expect(mismatch.culpritID == hynix)
        #expect(PageCopy.refusalReason(mismatch, .ko) == "SK하이닉스의 매출 두 해 숫자에서 조건 하나가 맞지 않아요.")
    }

    /// Revenue of zero or below in a margin compare gets the margin's own title.
    @Test func marginBaselineTitle() throws {
        let zero = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET value = '0' WHERE company_id = '\(apple)' AND metric = 'revenue'"))
        let explanation = try #require(CompanyComparePage(
            store: zero, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2025)?.explanation)
        #expect(explanation.refusal.detail == .nonpositiveBaseline)
        #expect(PageCopy.refusalTitle(explanation, .ko) == "그 해 매출이 0 이하라 영업이익률을 계산하지 않아요")
        #expect(PageCopy.refusalTitle(explanation, .en) == "Revenue was zero or below that year, so there is no operating margin")
        #expect(PageCopy.refusalReason(explanation, .ko) == "애플의 2025 회계연도 매출은 0 달러예요.")
    }

    /// Labels that differ are named; an unknown year-end month is left out of the caveat.
    @Test func caveatPeriodsAndUnknownYearEnd() throws {
        let labels = try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2024))
        #expect(PageCopy.caveat(labels.caveat, .ko).hasPrefix("삼성전자의 2024\u{00A0}회계연도와 애플의 2025\u{00A0}회계연도는 같은 기간이 아니에요. "))
        #expect(PageCopy.caveat(labels.caveat, .en)
            .hasPrefix("Samsung Electronics’ FY2024 and Apple’s FY2025 are not the same period. "))
        let unknown = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE companies SET fiscal_year_end = '13-01' WHERE id = '\(apple)'"))
        let page = try #require(CompanyComparePage(
            store: unknown, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2025))
        let ko = PageCopy.caveat(page.caveat, .ko)
        #expect(!ko.contains("결산월") && !ko.contains("13"), "\(ko)")
        #expect(ko.hasSuffix("두\u{00A0}회사는 회계 기준(K-IFRS, US GAAP)이 달라요. 같은 이름의 숫자라도 계산 범위가 조금 다를 수 있어요."))
        #expect(PageCopy.ratePeriod(page.companies[1], fiscalYear: 2025, basis: "consolidated", .en)
            == "FY2025" + Copy.dot + "US GAAP consolidated")
    }
}

@Suite("Line breaks at accessibility sizes")
struct PhraseBreakTests {
    /// The figure's direction line splits between the rate and its words only; joined with
    /// a space the phrases are the approved line exactly.
    @Test(arguments: [Decimal(string: "16.2")!, Decimal(string: "-14.334")!, Decimal(0)])
    func directionPhrasesJoinToTheApprovedLine(_ percent: Decimal) {
        for language in [Language.ko, .en] {
            let phrases = PageCopy.changeFromLastYearPhrases(percent, language)
            #expect(phrases.count == 2)
            #expect(phrases.joined(separator: " ") == PageCopy.changeFromLastYear(percent, language))
        }
        #expect(PageCopy.changeFromLastYearPhrases(Decimal(string: "16.2")!, .ko)
            == ["▲\u{00A0}16.20%", "늘었어요\u{00A0}· 작년보다"])
        #expect(PageCopy.changeFromLastYearPhrases(Decimal(string: "-14.334")!, .en)
            == ["▼\u{00A0}14.33%", "down from last year"])
    }
}

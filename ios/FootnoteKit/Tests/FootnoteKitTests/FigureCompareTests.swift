import Foundation
import Testing
@testable import FootnoteKit

private let samsung = "dart:00126380"
private let apple = "sec:0000320193"

@Suite("Figure screen")
struct FigurePageTests {
    @Test func everyYearAndTheChangeOfTheReportYear() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FigurePage(store: store, companyID: samsung, metric: .revenue, fiscalYear: 2025))
        #expect(page.years.map(\.fiscalYear) == [2025, 2024])
        #expect(page.basis == "consolidated")
        #expect(page.current?.value == Support.decimal("300870903000000"))
        #expect(page.source(of: page.years[0])?.id == "dart:20260310000123")
        guard case .result(let change) = page.change else {
            Issue.record("no change")
            return
        }
        #expect(change.percentChange == Support.decimal("16.20"))
        #expect(!page.hasRestated)
    }

    @Test func meaningComesFromTheMetricGlossaryEntry() throws {
        let store = try Support.editedFixture("""
            INSERT INTO glossary VALUES
              ('metric_revenue', 'ko', '매출', '회사가 물건이나 서비스를 팔아 번 돈이에요.', '수익(매출액)'),
              ('metric_revenue', 'en', 'Revenue', 'Money from selling goods or services.', NULL);
            """)
        let page = try #require(FigurePage(store: store, companyID: samsung, metric: .revenue, fiscalYear: 2025))
        #expect(page.meaning(.ko)?.plain == "회사가 물건이나 서비스를 팔아 번 돈이에요.")
        #expect(page.meaning(.ko)?.formal == "수익(매출액)")
        #expect(page.meaning(.en)?.formal == nil)
        // The fixture's own rows are keyed without the `metric_` prefix, so they are not used.
        let plain = try #require(FigurePage(
            store: BundleStore(contentsOf: Support.fixtureURL), companyID: samsung, metric: .revenue, fiscalYear: 2025))
        #expect(plain.meaning(.ko) == nil)
    }

    @Test func oneYearIsAMissingPeriod() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(FigurePage(store: store, companyID: apple, metric: .revenue, fiscalYear: 2025))
        #expect(page.years.count == 1)
        #expect(page.change == .refusal(Refusal(.missingPeriod, .missingFact)))
    }

    @Test func restatedYearsAreMarked() throws {
        let store = try Support.editedFixture(
            "UPDATE figures SET is_restated = 1 WHERE company_id = '\(samsung)' AND metric = 'revenue' AND fiscal_year = 2024")
        let page = try #require(FigurePage(store: store, companyID: samsung, metric: .revenue, fiscalYear: 2025))
        #expect(page.hasRestated)
        #expect(page.figure(fiscalYear: 2024)?.isRestated == true)
        guard case .result(let change) = page.change else {
            Issue.record("no change")
            return
        }
        #expect(change.priorIsRestated)
    }
}

@Suite("Compare with last year")
struct YearCompareTests {
    @Test func calculationNamesItsInputsAndChecks() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: "revenue", fiscalYear: 2025))
        let calculation = try #require(page.calculation)
        #expect(calculation.result.priorValue == Support.decimal("258935494000000"))
        #expect(calculation.result.currentValue == Support.decimal("300870903000000"))
        #expect(calculation.result.delta == Support.decimal("41935409000000"))
        #expect(calculation.result.percentChange == Support.decimal("16.20"))
        #expect(calculation.currentSource?.id == "dart:20260310000123")
        #expect(calculation.checks.count == 6)
        // 2024 is a leap year.
        #expect(calculation.checks[4] == .consecutiveYears(priorDays: 366, currentDays: 365))
        #expect(page.explanation == nil)
    }

    /// The figures of the contract's Samsung cases, loaded into the fixture, give the
    /// contract's results through the screen's model.
    @Test("Contract case through the screen", arguments: ["yoy-samsung-fy2023-revenue",
        "yoy-samsung-fy2023-operating-income", "yoy-samsung-fy2023-net-income"])
    func contractCase(_ id: String) throws {
        let testCase = try #require(ComparisonCase.all.first { $0.id == id })
        let store = try ContractFixture.store(with: testCase)
        let metric = testCase.input["metric"]!.string!
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: metric, fiscalYear: 2023))
        #expect(CalculatorContractTests.encode(page.outcome, CalculatorContractTests.yearOverYear) == testCase.expected)
    }

    @Test func eachRefusalExplainsItselfAndOffersAnotherView() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let missing = try #require(YearComparePage(store: store, companyID: apple, metric: "revenue", fiscalYear: 2025))
        let explanation = try #require(missing.explanation)
        #expect(explanation.refusal == Refusal(.missingPeriod, .missingFact))
        #expect(explanation.missing == MissingYear(companyID: apple, fiscalYear: 2024, metric: .revenue))
        #expect(explanation.actions == [.showYears(companyID: apple)])

        let unknown = try #require(YearComparePage(store: store, companyID: samsung, metric: "ebitda", fiscalYear: 2025))
        #expect(unknown.outcome == .refusal(Refusal(.metricOutOfScope, .unknownMetric)))
        #expect(unknown.explanation?.actions == [.coveredFigures(companyID: samsung)])

        let none = try #require(YearComparePage(store: store, companyID: samsung, metric: nil, fiscalYear: 2025))
        #expect(none.outcome == .refusal(Refusal(.ambiguousRequest, .metricNotSpecified)))
        #expect(none.explanation?.actions == [.chooseFigure])
    }

    @Test func aBaselineOfZeroOrBelowIsRefusedWithItsValue() throws {
        // As LG Chem's 2024 EPS is in the real bundle.
        let store = try Support.editedFixture(
            "UPDATE figures SET value = '-2131' WHERE company_id = '\(samsung)' AND metric = 'eps' AND fiscal_year = 2024")
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: "eps", fiscalYear: 2025))
        let explanation = try #require(page.explanation)
        #expect(explanation.refusal == Refusal(.incompatibleComparison, .nonpositiveBaseline))
        #expect(explanation.baseline?.value == Support.decimal("-2131"))
        #expect(page.calculation == nil)
    }

    @Test func aSeparateBasisIsRefused() throws {
        let store = try Support.editedFixture("UPDATE figures SET basis = 'separate' WHERE company_id = '\(samsung)'")
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: "revenue", fiscalYear: 2025))
        #expect(page.outcome == .refusal(Refusal(.unsupportedBasis, .unsupportedBasis)))
        #expect(page.explanation?.actions == [.showYears(companyID: samsung)])
    }
}

@Suite("Compare with another company")
struct CompanyCompareTests {
    private func page(_ store: BundleStore, metric: String? = "revenue", measure: String?) throws -> CompanyComparePage {
        try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: apple, metric: metric, measure: measure, fiscalYear: 2025))
    }

    @Test func marginsSideBySideWithTheCaveat() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let compare = try page(store, measure: "operating_margin")
        guard case .result(let result) = compare.outcome else {
            Issue.record("refused: \(compare.outcome)")
            return
        }
        #expect(result.companies.map(\.companyID) == [samsung, apple])
        // 32725961000000 ÷ 300870903000000 and 133050000000 ÷ 416161000000, each in its own currency.
        #expect(result.companies.map(\.rate) == [Support.decimal("10.88"), Support.decimal("31.97")])
        #expect(compare.difference == Support.decimal("21.09"))
        #expect(compare.caveat.standards == [.kIFRS, .usGAAP])
        #expect(compare.caveat.yearEndMonths == [12, 9])
        #expect(compare.caveat.standardsDiffer && compare.caveat.yearEndsDiffer)
        #expect(compare.calculations.count == 2)
        #expect(compare.explanation == nil)
    }

    @Test func growthWithTheContractCase() throws {
        let testCase = try #require(ComparisonCase.all.first { $0.id == "cross-company-growth-samsung-microsoft" })
        let store = try ContractFixture.store(with: testCase)
        let compare = try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: ContractFixture.microsoft, metric: "revenue",
            measure: "growth_rate", fiscalYear: 2023))
        #expect(CalculatorContractTests.encode(compare.outcome, CalculatorContractTests.crossCompany) == testCase.expected)
        #expect(compare.caveat.yearEndMonths == [12, 6])
        #expect(compare.caveat.standardsDiffer)
        #expect(compare.calculations.count == 2)
        #expect(compare.difference == Support.decimal("30.00"))
    }

    // Each of the six refusal reasons, reached through the screen's model with the fixture.

    @Test func ambiguousRequest() throws {
        let compare = try page(BundleStore(contentsOf: Support.fixtureURL), measure: nil)
        #expect(compare.outcome == .refusal(Refusal(.ambiguousRequest, .measureNotSpecified)))
        #expect(compare.explanation?.actions == [.compare(.operatingMargin), .compare(.growthRate)])
    }

    @Test func unsupportedBasis() throws {
        let store = try Support.editedFixture("UPDATE figures SET basis = 'separate' WHERE company_id = '\(samsung)'")
        let compare = try page(store, measure: "growth_rate")
        #expect(compare.outcome == .refusal(Refusal(.unsupportedBasis, .unsupportedBasis)))
        #expect(compare.explanation?.actions.contains(.compare(.operatingMargin)) == true)
    }

    @Test func metricOutOfScope() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let margin = try page(store, metric: "operating_margin", measure: "growth_rate")
        #expect(margin.outcome == .refusal(Refusal(.metricOutOfScope, .metricNotSupportedForKind)))
        #expect(margin.explanation?.actions.first == .compare(.operatingMargin))
        let unknown = try page(store, metric: "ebitda", measure: "growth_rate")
        #expect(unknown.outcome == .refusal(Refusal(.metricOutOfScope, .unknownMetric)))
    }

    @Test func missingPeriod() throws {
        let compare = try page(BundleStore(contentsOf: Support.fixtureURL), measure: "growth_rate")
        #expect(compare.outcome == .refusal(Refusal(.missingPeriod, .missingFact)))
        let explanation = try #require(compare.explanation)
        #expect(explanation.missing == MissingYear(companyID: apple, fiscalYear: 2024, metric: .revenue))
        #expect(explanation.actions == [.compare(.operatingMargin), .showYears(companyID: apple)])
    }

    @Test func aCompanyWithoutTheFigureIsAMissingPeriod() throws {
        let store = try Support.editedFixture("DELETE FROM figures WHERE company_id = '\(apple)' AND metric = 'revenue'")
        let compare = try page(store, measure: "growth_rate")
        #expect(compare.outcome == .refusal(Refusal(.missingPeriod, .missingFact)))
        #expect(compare.explanation?.missing == MissingYear(companyID: apple, fiscalYear: nil, metric: .revenue))
    }

    @Test func incompatibleCurrency() throws {
        let compare = try page(BundleStore(contentsOf: Support.fixtureURL), measure: "absolute_amount")
        #expect(compare.outcome == .refusal(Refusal(.incompatibleCurrency, .absoluteAmountAcrossCurrencies)))
        #expect(compare.explanation?.actions == [.compare(.operatingMargin), .compare(.growthRate)])
    }

    @Test func incompatibleComparison() throws {
        let store = try Support.editedFixture(
            "UPDATE figures SET value = '-2131' WHERE company_id = '\(samsung)' AND metric = 'eps' AND fiscal_year = 2024")
        let compare = try page(store, metric: "eps", measure: "growth_rate")
        #expect(compare.outcome == .refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline)))
        let explanation = try #require(compare.explanation)
        #expect(explanation.baseline?.value == Support.decimal("-2131"))
        #expect(explanation.actions == [.compare(.operatingMargin), .showYears(companyID: samsung)])

        // Amounts of two companies in one currency are not set side by side either.
        let won = try Support.editedFixture("UPDATE figures SET currency = 'KRW', unit = 'KRW' WHERE company_id = '\(apple)'")
        let amounts = try page(won, measure: "absolute_amount")
        #expect(amounts.outcome == .refusal(Refusal(.incompatibleComparison, .absoluteAmountAcrossCompanies)))
    }

    @Test func everyReasonIsReached() throws {
        let fixture = try BundleStore(contentsOf: Support.fixtureURL)
        let separate = try Support.editedFixture("UPDATE figures SET basis = 'separate' WHERE company_id = '\(samsung)'")
        let negative = try Support.editedFixture(
            "UPDATE figures SET value = '-2131' WHERE company_id = '\(samsung)' AND metric = 'eps' AND fiscal_year = 2024")
        let outcomes = try [
            page(fixture, measure: nil), page(separate, measure: "growth_rate"),
            page(fixture, metric: "ebitda", measure: "growth_rate"), page(fixture, measure: "growth_rate"),
            page(fixture, measure: "absolute_amount"), page(negative, metric: "eps", measure: "growth_rate"),
        ].map(\.outcome)
        let reasons = outcomes.compactMap { outcome -> RefusalReason? in
            if case .refusal(let refusal) = outcome { return refusal.reason }
            return nil
        }
        #expect(reasons == RefusalReason.allCases)
    }
}

/// Amounts are never converted between currencies (PRODUCT.md, comparison-rules.md).
@Suite("No currency conversion")
struct NoCurrencyConversionTests {
    @Test func amountsAcrossCompaniesAreAlwaysRefused() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        for metric in ReportedMetric.allCases {
            for (base, peer) in [(samsung, apple), (apple, samsung)] {
                let compare = try #require(CompanyComparePage(
                    store: store, companyID: base, peerID: peer, metric: metric.rawValue,
                    measure: "absolute_amount", fiscalYear: 2025))
                guard case .refusal(let refusal) = compare.outcome else {
                    Issue.record("\(metric) amounts were set side by side")
                    continue
                }
                #expect(refusal.reason == .incompatibleCurrency)
                #expect(compare.calculations.isEmpty)
                #expect(compare.difference == nil)
            }
        }
    }

    @Test func eachRateStaysInsideOneCompanysFigures() throws {
        let store = try BundleStore(contentsOf: Support.fixtureURL)
        let compare = try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: apple, metric: "revenue", measure: "operating_margin",
            fiscalYear: 2025))
        guard case .result(let result) = compare.outcome else {
            Issue.record("refused")
            return
        }
        for (rate, input) in zip(result.companies, compare.inputs) {
            #expect(Set(input.figures.map(\.currency)).count == 1)
            guard case .result(let own) = Calculator.operatingMargin(
                metric: "operating_margin", facts: input.figures.map(\.fact)) else {
                Issue.record("own margin refused")
                continue
            }
            #expect(rate.rate == own.operatingMargin)
        }
    }

    /// No source file holds an exchange rate or a conversion. The same grep runs in
    /// `scripts/check.sh`.
    @Test func noSourceConvertsACurrency() throws {
        let roots = [Support.packageSources, Support.repositoryRoot.appendingPathComponent("ios/Footnote")]
        let pattern = try Regex(#"(?i)(exchange_?rate|fx_?rate|conversion_?rate|convert(ed)?_?(currency|amount)|currency_?conver)"#)
        var offenders: [String] = []
        for root in roots {
            let files = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)?
                .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" } ?? []
            #expect(!files.isEmpty)
            for file in files where try String(contentsOf: file, encoding: .utf8).contains(pattern) {
                offenders.append(file.lastPathComponent)
            }
        }
        #expect(offenders.isEmpty, "\(offenders)")
    }
}

/// The fixture with a contract case's figures in place of the company's own.
enum ContractFixture {
    static let microsoft = "sec:0000789019"

    static func store(with testCase: ComparisonCase) throws -> BundleStore {
        let facts = testCase.input["facts"]!.array
        let companies = Set(facts.map { $0["company_id"]!.string! })
        var sql = companies.map { "DELETE FROM figures WHERE company_id = '\($0)';" }
        if companies.contains(microsoft) {
            sql.append("""
                INSERT INTO companies VALUES ('\(microsoft)', 'SEC', 'MSFT', '마이크로소프트', 'Microsoft',
                  NULL, 'USD', '06-30', 3);
                """)
        }
        for (index, fact) in facts.enumerated() {
            let company = fact["company_id"]!.string!
            let filing = company == samsung ? "dart:20260310000123" : "sec:0000320193-25-000079"
            let end = fact["period_end"]!.string!
            let restated = fact["is_restated"] == .bool(true) ? 1 : 0
            sql.append("""
                INSERT INTO figures VALUES ('contract-\(index)', '\(company)', '\(filing)',
                  '\(fact["metric"]!.string!)', \(end.prefix(4)), '\(fact["period_start"]!.string!)', '\(end)',
                  '\(fact["value"]!.string!)', '\(fact["unit"]!.string!)', '\(fact["currency"]!.string!)',
                  '\(fact["basis"]!.string!)', \(restated), 'contract');
                """)
        }
        return try Support.editedFixture(sql.joined(separator: "\n"))
    }
}

import Foundation
import Testing
@testable import FootnoteKit

/// The Swift calculator against `contracts/comparison-cases.json`, the cases the Python
/// calculator passes (`backend/tests/test_comparison_cases.py`).
struct ComparisonCase: Sendable, CustomTestStringConvertible {
    let id: String
    let input: JSONValue
    let expected: JSONValue

    var testDescription: String { id }

    static let contract: JSONValue = try! Support.contract("comparison-cases.json")
    static let all: [ComparisonCase] = contract["cases"]!.array.map {
        ComparisonCase(id: $0["id"]!.string!, input: $0["input"]!, expected: $0["expected"]!)
    }
}

@Suite("Comparison cases contract")
struct CalculatorContractTests {
    @Test("Shared case", arguments: ComparisonCase.all)
    func sharedCase(_ testCase: ComparisonCase) throws {
        #expect(Self.run(testCase.input) == testCase.expected)
    }

    @Test func everyCaseIsLoaded() {
        #expect(ComparisonCase.all.count == ComparisonCase.contract["cases"]!.array.count)
        #expect(ComparisonCase.all.count >= 94)
        #expect(Set(ComparisonCase.all.map(\.id)).count == ComparisonCase.all.count)
    }

    @Test func vocabularyMatchesTheContract() {
        let contract = ComparisonCase.contract
        #expect(contract["version"] == .integer(1))
        #expect(contract["refusal_reasons"]!.strings == RefusalReason.allCases.map(\.rawValue))
        let listed = RefusalReason.allCases.flatMap { contract["refusal_details"]![$0.rawValue]!.strings }
        #expect(listed.sorted() == RefusalDetail.allCases.map(\.rawValue).sorted())
        #expect(listed.count == RefusalDetail.allCases.count)
        #expect(contract["caveats"]!.strings == [Calculator.crossCompanyCaveat])
        #expect(Set(contract["supported_bases"]!.strings) == Calculator.supportedBases)
        #expect(contract["cross_company_measures"]!.strings
            == CrossCompanyMeasure.allCases.map(\.rawValue))
        #expect(contract["kinds"]!.strings == ["yoy", "operating_margin", "cross_company"])
        #expect(contract["rounded_fields"]!.strings.sorted()
            == ["operating_margin", "percent_change", "rate"])
        #expect(contract["exact_fields"]!.strings.sorted()
            == ["current_value", "delta", "operating_income", "prior_value", "revenue"])
    }

    @Test func refusalReasonsPairWithTheirDetails() {
        // Every refusal the cases expect pairs a reason with a detail listed under it.
        let details = ComparisonCase.contract["refusal_details"]!
        for testCase in ComparisonCase.all {
            guard let reason = testCase.expected["refusal"]?.string else { continue }
            let detail = testCase.expected["detail"]!.string!
            #expect(details[reason]!.strings.contains(detail), "\(testCase.id)")
        }
    }

    // MARK: - Running a case

    static func run(_ input: JSONValue) -> JSONValue {
        let facts = input["facts"]!.array.map(fact)
        let metric = input["metric"]?.string
        switch input["kind"]!.string! {
        case "yoy":
            return encode(Calculator.yearOverYear(metric: metric, facts: facts), yearOverYear)
        case "operating_margin":
            return encode(Calculator.operatingMargin(metric: metric, facts: facts), margin)
        case "cross_company":
            let measure = input["measure"]?.string
            return encode(
                Calculator.crossCompany(metric: metric, measure: measure, facts: facts),
                crossCompany)
        case let kind:
            fatalError("unknown kind \(kind)")
        }
    }

    static func fact(_ raw: JSONValue) -> Fact {
        guard case .bool(let restated) = raw["is_restated"]! else { fatalError("is_restated") }
        return try! Fact(
            companyID: raw["company_id"]!.string!, metric: raw["metric"]!.string!,
            value: Support.decimal(raw["value"]!.string!), unit: raw["unit"]!.string!,
            currency: raw["currency"]!.string, basis: raw["basis"]!.string!,
            periodStart: Support.date(raw["period_start"]!.string!),
            periodEnd: Support.date(raw["period_end"]!.string!), isRestated: restated)
    }

    static func encode<T>(_ outcome: Comparison<T>, _ body: (T) -> [String: JSONValue]) -> JSONValue {
        switch outcome {
        case .result(let value):
            return .object(["result": .object(body(value))])
        case .refusal(let refusal):
            return .object([
                "refusal": .string(refusal.reason.rawValue),
                "detail": .string(refusal.detail.rawValue),
            ])
        }
    }

    static func exact(_ value: Decimal) -> JSONValue { .string(DecimalText.canonical(value)) }
    static func rounded(_ value: Decimal) -> JSONValue { .string(DecimalText.twoPlaces(value)) }
    static func day(_ value: CivilDate) -> JSONValue { .string(value.iso) }
    static func optional(_ value: String?) -> JSONValue { value.map(JSONValue.string) ?? .null }

    static func yearOverYear(_ r: YearOverYear) -> [String: JSONValue] {
        [
            "company_id": .string(r.companyID), "metric": .string(r.metric),
            "prior_value": exact(r.priorValue), "current_value": exact(r.currentValue),
            "delta": exact(r.delta), "percent_change": rounded(r.percentChange),
            "currency": optional(r.currency), "unit": .string(r.unit),
            "prior_period_start": day(r.priorPeriodStart),
            "prior_period_end": day(r.priorPeriodEnd),
            "current_period_start": day(r.currentPeriodStart),
            "current_period_end": day(r.currentPeriodEnd),
            "prior_is_restated": .bool(r.priorIsRestated),
            "current_is_restated": .bool(r.currentIsRestated),
        ]
    }

    static func margin(_ r: OperatingMargin) -> [String: JSONValue] {
        [
            "company_id": .string(r.companyID), "revenue": exact(r.revenue),
            "operating_income": exact(r.operatingIncome),
            "operating_margin": rounded(r.operatingMargin), "currency": optional(r.currency),
            "period_start": day(r.periodStart), "period_end": day(r.periodEnd),
            "is_restated": .bool(r.isRestated),
        ]
    }

    static func crossCompany(_ r: CrossCompany) -> [String: JSONValue] {
        [
            "metric": .string(r.metric), "measure": .string(r.measure.rawValue),
            "caveat": .string(r.caveat), "same_period_end": .bool(r.samePeriodEnd),
            "companies": .array(r.companies.map { rate in
                .object([
                    "company_id": .string(rate.companyID), "rate": rounded(rate.rate),
                    "period_start": day(rate.periodStart), "period_end": day(rate.periodEnd),
                    "is_restated": .bool(rate.isRestated),
                ])
            }),
        ]
    }
}

@Suite("Calculator details")
struct CalculatorTests {
    @Test func factRefusesAPeriodThatStartsAfterItEnds() {
        #expect(throws: FactError.periodStartAfterEnd(
            start: Support.date("2025-01-02"), end: Support.date("2025-01-01"))) {
            try Fact(companyID: "c", metric: "revenue", value: Support.decimal("1"), unit: "KRW",
                     currency: "KRW", basis: "consolidated", periodStart: Support.date("2025-01-02"),
                     periodEnd: Support.date("2025-01-01"))
        }
        #expect(throws: FactError.nonFiniteValue) {
            try Fact(companyID: "c", metric: "revenue", value: Decimal.nan, unit: "KRW",
                     currency: "KRW", basis: "consolidated", periodStart: Support.date("2025-01-01"),
                     periodEnd: Support.date("2025-12-31"))
        }
        // A one-day period is allowed.
        #expect(throws: Never.self) {
            try Fact(companyID: "c", metric: "revenue", value: Support.decimal("1"), unit: "KRW",
                     currency: "KRW", basis: "consolidated", periodStart: Support.date("2025-01-01"),
                     periodEnd: Support.date("2025-01-01"))
        }
    }

    @Test func tinyNegativeChangeIsZeroNotMinusZero() throws {
        let percent = try #require(Calculator.percentage(Support.decimal("-1"), of: Support.decimal("1000000")))
        #expect(DecimalText.twoPlaces(percent) == "0.00")
        #expect(!(percent < 0))
    }

    @Test func halfRoundsAwayFromZero() {
        #expect(DecimalText.twoPlaces(Calculator.percentage(Support.decimal("12345"), of: Support.decimal("100000"))!) == "12.35")
        #expect(DecimalText.twoPlaces(Calculator.percentage(Support.decimal("-12345"), of: Support.decimal("100000"))!) == "-12.35")
        #expect(DecimalText.twoPlaces(Calculator.percentage(Support.decimal("1234499"), of: Support.decimal("10000000"))!) == "12.34")
    }

    @Test func zeroOrNegativeBaselineHasNoPercentage() {
        #expect(Calculator.percentage(Support.decimal("5"), of: Support.decimal("0")) == nil)
        #expect(Calculator.percentage(Support.decimal("5"), of: Support.decimal("-1")) == nil)
    }

    @Test func significantRoundingMatchesAPythonContext() {
        // 34 significant digits, half to even.
        let value = Support.decimal("12.344" + String(repeating: "9", count: 32))  // 37 digits
        #expect(DecimalText.canonical(DecimalText.roundSignificant(value, digits: 34)) == "12.345")
        let small = Support.decimal("0.000123456")
        #expect(DecimalText.canonical(DecimalText.roundSignificant(small, digits: 3)) == "0.000123")
        #expect(DecimalText.canonical(DecimalText.roundSignificant(Support.decimal("125"), digits: 2)) == "120")
    }
}

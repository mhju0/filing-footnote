import Foundation
import Testing
@testable import FootnoteKit

@Suite("Formatting")
struct FormattingTests {
    static func amount(_ text: String, _ currency: String, _ language: Language) -> String {
        Formatting.amount(Support.decimal(text), currency: currency, language: language)
    }

    @Test(arguments: [
        ("45110200000000", "KRW", "45조 1,102억원"),
        ("45110249999999", "KRW", "45조 1,102억원"),
        ("45110250000000", "KRW", "45조 1,103억원"),
        ("300870903000000", "KRW", "300조 8,709억원"),
        ("45000000000000", "KRW", "45조원"),
        ("110200000000", "KRW", "1,102억원"),
        ("-110200000000", "KRW", "−1,102억원"),
        ("999999990000", "KRW", "1조원"),
        ("1234567000000000", "KRW", "1,234조 5,670억원"),
        ("4950", "KRW", "4,950원"),
        ("416161000000", "USD", "4,162억 달러"),
        ("133050000000", "USD", "1,331억 달러"),
        ("7.46", "USD", "7.46 달러"),
    ])
    func koreanAmounts(_ value: String, _ currency: String, _ expected: String) {
        #expect(Self.amount(value, currency, .ko) == expected)
    }

    @Test(arguments: [
        ("45110200000000", "KRW", "₩45.11 trillion"),
        ("45115000000000", "KRW", "₩45.12 trillion"),
        ("3860000000", "USD", "$3.86 billion"),
        ("3855000000", "USD", "$3.86 billion"),
        ("416161000000", "USD", "$416.16 billion"),
        ("999995000000", "USD", "$1.00 trillion"),
        ("-3860000000", "USD", "−$3.86 billion"),
        ("12500000", "USD", "$12.50 million"),
        ("7.46", "USD", "$7.46"),
        ("4950", "KRW", "₩4,950"),
        ("0", "USD", "$0"),
    ])
    func englishAmounts(_ value: String, _ currency: String, _ expected: String) {
        #expect(Self.amount(value, currency, .en) == expected)
    }

    @Test(arguments: [
        ("6.29", "+6.29% 늘었어요", "+6.29%, up"),
        ("-3.45", "−3.45% 줄었어요", "−3.45%, down"),
        ("0", "0.00% 변동 없어요", "0.00%, no change"),
        ("-0.004", "0.00% 변동 없어요", "0.00%, no change"),
        ("6.295", "+6.30% 늘었어요", "+6.30%, up"),
        ("-14.33", "−14.33% 줄었어요", "−14.33%, down"),
        ("120", "+120.00% 늘었어요", "+120.00%, up"),
    ])
    func percentChanges(_ value: String, _ korean: String, _ english: String) {
        #expect(Formatting.percentChange(Support.decimal(value), language: .ko) == korean)
        #expect(Formatting.percentChange(Support.decimal(value), language: .en) == english)
    }

    @Test func percentWithoutDirection() {
        #expect(Formatting.percent(Support.decimal("15")) == "15.00%")
        #expect(Formatting.percent(Support.decimal("-2.5")) == "−2.50%")
        #expect(Formatting.percent(Support.decimal("-0.001")) == "0.00%")
    }

    @Test func monthAndDay() {
        #expect(Formatting.monthDay(Support.date("2026-11-18"), language: .ko) == "11월 18일")
        #expect(Formatting.monthDay(Support.date("2026-11-18"), language: .en) == "Nov 18")
        #expect(Formatting.monthDay(Support.date("2026-01-05"), language: .ko) == "1월 5일")
        #expect(Formatting.monthDay(Support.date("2026-01-05"), language: .en) == "Jan 5")
    }

    @Test func minusIsTheUnicodeSign() {
        #expect(Formatting.minus.unicodeScalars.map(\.value) == [0x2212])
    }
}

@Suite("Decimal text and dates")
struct DecimalTextTests {
    @Test(arguments: ["0", "7", "-1.5", "302231360000000", "0.001", "14999999992000"])
    func acceptsCanonical(_ text: String) throws {
        let value = try #require(DecimalText.parseCanonical(text))
        #expect(DecimalText.canonical(value) == text)
    }

    @Test(arguments: ["", "-", "-0", "01", "1.50", "1.", ".5", "+1", "1e5", "1,000", " 1", "1.2.3",
                      "１", String(repeating: "9", count: 39)])
    func rejectsNonCanonical(_ text: String) {
        #expect(DecimalText.parseCanonical(text) == nil)
    }

    @Test func plainParsingAllowsTrailingZeros() {
        #expect(DecimalText.parsePlain("1.50").map(DecimalText.canonical) == "1.5")
        #expect(DecimalText.parsePlain("-0").map(DecimalText.canonical) == "0")
        #expect(DecimalText.parsePlain("1e5") == nil)
    }

    @Test func twoPlaces() {
        #expect(DecimalText.twoPlaces(Support.decimal("15")) == "15.00")
        #expect(DecimalText.twoPlaces(Support.decimal("-0.004")) == "0.00")
        #expect(DecimalText.twoPlaces(Support.decimal("-0.005")) == "-0.01")
        #expect(DecimalText.twoPlaces(Support.decimal("2.675")) == "2.68")
    }

    @Test func civilDates() {
        #expect(CivilDate(iso: "2026-02-30") == nil)
        #expect(CivilDate(iso: "2026-1-05") == nil)
        #expect(CivilDate(iso: "2024-02-29") != nil)
        #expect(CivilDate(iso: "2025-02-29") == nil)
        #expect(Support.date("2024-01-01").days(to: Support.date("2024-12-31")) == 365)
        #expect(Support.date("1970-01-01").dayNumber == 0)
        #expect(Support.date("2026-11-18").iso == "2026-11-18")
        #expect(Support.date("2025-12-31") < Support.date("2026-01-01"))
    }
}

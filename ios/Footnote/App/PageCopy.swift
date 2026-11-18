import FootnoteKit
import Foundation

/// Copy for the filing page (board 12A), the annual page (board 4) and the figure screen.
/// Approved wording is marked with its board. `Draft:` marks wording no board covers; the
/// pull request lists each one for the owner.
enum PageCopy {
    // MARK: - Sections

    static func sentences(_ language: Language) -> String { language("공시 내용", "What the filing says") }
    static func numbers(_ language: Language) -> String { language("공시의 숫자", "Numbers in the filing") }
    static func original(_ language: Language) -> String { language("원문", "The original") }

    // MARK: - States (board 19)

    static func inReviewTitle(_ language: Language) -> String {
        language("요약을 확인하고 있어요", "Summary in review")
    }

    static func inReviewBody(_ language: Language) -> String {
        language(
            "확인을 마친 요약만 보여 줘요. 공시의 숫자와 원문은 지금 볼 수 있어요.",
            "Only checked summaries are shown. The filing’s numbers and the original are available now.")
    }

    static func corrected(_ language: Language) -> String {
        language("회사가 처음 낸 공시를 고쳐 다시 냈어요.", "The company corrected and refiled this filing.")
    }

    static func outlookWithoutFigures(_ language: Language) -> String {
        language("이 공시에는 숫자로 된 목표가 없어요.", "This filing gives no numeric target.")
    }

    /// Board 9: a base of zero or below has no growth rate.
    static func baseNotPositive(_ language: Language) -> String {
        language("작년 숫자가 0 이하라 증가율을 계산하지 않아요", "Last year was zero or below, so there is no growth rate")
    }

    /// Draft: how the sentences were written. The bundle does not say whether a sentence came
    /// from a template or a model, so the note covers both.
    static func howWritten(_ language: Language) -> String {
        language(
            "공시를 바탕으로 쓰고, 게시 전에 확인한 문장이에요.",
            "Written from the filing and checked before publishing.")
    }

    /// Lead decision (D83): pages show money amounts in the company page's compact form, and
    /// the exact value on tap. One sentence per line, so neither wraps a lone word.
    static func amountsShortened(_ language: Language) -> String {
        language(
            "금액은 줄여서 보여 줘요.\n숫자를 누르면 정확한 값을 볼 수 있어요.",
            "Amounts are shortened.\nTap a figure to see the exact value.")
    }

    // MARK: - Outlook (board 16)

    /// Board 16; the English says "outlook" for "forecast" (D78 names it the company outlook).
    static func outlookBanner(_ language: Language) -> String {
        language(
            "회사가 내놓은 전망이에요. 실제 결과가 아니고, 앱은 이 숫자를 비교에 쓰지 않아요.",
            "This is the company’s own outlook, not a result. The app never uses these numbers in comparisons.")
    }

    /// Draft: the heading of one outlook column.
    static func outlookHeading(year: String?, salesTargets: Bool, _ language: Language) -> String {
        let year = year ?? ""
        if salesTargets {
            return year.isEmpty
                ? language("판매 목표 (대수)", "Sales target (units)")
                : language("\(year)년 판매 목표 (대수)", "\(year) sales target (units)")
        }
        return year.isEmpty ? language("회사 전망", "Company outlook") : language("\(year)년 전망", "\(year) outlook")
    }

    /// The exact value under a shortened amount, shown on a tap.
    static func exactValue(_ value: String, _ language: Language) -> String {
        language("정확한 값 \(value)", "Exact: \(value)")
    }

    /// Draft: the value a corrected outlook item had before this filing.
    static func beforeCorrection(_ value: String, _ language: Language) -> String {
        language("정정 전 \(value)", "Before the correction: \(value)")
    }

    // MARK: - Compared figures

    /// Draft: what a results, change or unit-sales block compares with.
    static func comparisonHeading(_ block: ComparisonBlock, _ language: Language) -> String {
        var parts: [String] = []
        if let period = block.period {
            parts.append(Formatting.period(period.start, period.end, language: language))
        }
        switch block.basis {
        case .consolidated: parts.append(language("연결", "Consolidated"))
        case .separate: parts.append(language("별도", "Separate"))
        case nil: break
        }
        if parts.isEmpty {
            return block.kind == .units ? language("판매 실적", "Units sold") : numbers(language)
        }
        return parts.joined(separator: Copy.dot)
    }

    /// Draft: the note under a compared block, naming the base period.
    static func comparisonNote(_ block: ComparisonBlock, _ language: Language) -> String {
        switch block.kind {
        case .results:
            guard let base = block.basePeriod else {
                return language("작년 같은 기간과 비교했어요.", "Compared with the same period a year earlier.")
            }
            let span = Formatting.period(base.start, base.end, language: language)
            return language("작년 같은 기간(\(span))과 비교했어요.", "Compared with \(span).")
        case .change:
            guard let base = block.basePeriod else {
                return language("직전 사업연도와 비교했어요.", "Compared with the previous fiscal year.")
            }
            let span = Formatting.period(base.start, base.end, language: language)
            return language("직전 사업연도(\(span))와 비교했어요.", "Compared with the previous fiscal year, \(span).")
        case .units:
            guard let span = yearEarlier(block.period, language) else {
                return language("작년 같은 기간과 비교했어요. 누적은 작년 누적과 비교했어요.",
                                "Compared with the same period a year earlier; year to date with last year’s.")
            }
            return language("작년 같은 기간(\(span))과 비교했어요. 누적은 작년 누적과 비교했어요.",
                            "Compared with \(span); year to date with last year’s.")
        }
    }

    /// The same months one year earlier, written as a period; nil without a period.
    private static func yearEarlier(_ period: DatePeriod?, _ language: Language) -> String? {
        guard let period,
              let start = CivilDate(year: period.start.year - 1, month: period.start.month, day: period.start.day),
              let end = CivilDate(year: period.end.year - 1, month: period.end.month, day: period.end.day)
                ?? CivilDate(year: period.end.year - 1, month: period.end.month, day: period.end.day - 1)
        else { return nil }
        return Formatting.period(start, end, language: language)
    }

    /// Draft: the base value beside a compared figure.
    static func baseValue(_ value: String, kind: ComparisonBlock.Kind, _ language: Language) -> String {
        switch kind {
        case .results, .units: language("작년 \(value)", "A year earlier: \(value)")
        case .change: language("직전 연도 \(value)", "Previous year: \(value)")
        }
    }

    // MARK: - Clarification (board 17)

    static func status(_ language: Language) -> String { language("상태", "Status") }

    static func statusValue(_ status: ClarificationStatus, _ language: Language) -> String {
        switch status {
        case .undecided: language("미확정", "Not decided")
        }
    }

    static func statusNote(_ status: ClarificationStatus, _ language: Language) -> String {
        switch status {
        case .undecided: language("회사가 아직 정하지 않았다는 뜻이에요.", "The company has not decided yet.")
        }
    }

    // MARK: - Source details

    static func form(_ language: Language) -> String { language("서식", "Form") }
    static func filed(_ language: Language) -> String { language("공시일", "Filed") }

    static func receiptNumber(_ regulator: Regulator, _ language: Language) -> String {
        regulator == .dart ? language("접수번호", "Receipt number") : language("접수번호", "Accession number")
    }

    // MARK: - Annual page (board 4)

    static func annualSections(_ section: SummarySection, _ language: Language) -> String {
        switch section {
        case .business: language("무슨 사업", "What the business is")
        case .changes: language("무엇이 바뀌었나", "What changed")
        case .risks: language("회사가 꼽은 위험", "Risks the company names")
        case .oneLine, .summary: ""
        }
    }

    static func keyFigures(_ language: Language) -> String { language("핵심 숫자", "Key figures") }

    /// `2025 회계연도 · 연결 기준 · 원` / `FY2025 · Consolidated · Korean won`.
    static func figuresBasis(fiscalYear: Int, basis: String?, currency: String, _ language: Language) -> String {
        var parts = [Self.fiscalYear(fiscalYear, language)]
        if basis == "consolidated" { parts.append(language("연결 기준", "Consolidated")) }
        if basis == "separate" { parts.append(language("별도 기준", "Separate")) }
        parts.append(currencyName(currency, language))
        return parts.joined(separator: Copy.dot)
    }

    static func currencyName(_ currency: String, _ language: Language) -> String {
        switch currency {
        case "KRW": language("원", "Korean won")
        case "USD": language("달러", "US dollars")
        default: currency
        }
    }

    /// `2025 회계연도` / `FY2025`.
    static func fiscalYear(_ year: Int, _ language: Language) -> String {
        language("\(year) 회계연도", "FY\(year)")
    }

    /// The approved restated note (board 19, G1): beside a 정정됨 / Restated tag.
    static func restatedNote(_ language: Language) -> String {
        language(
            "회사가 나중에 고쳐 다시 낸 숫자예요. 처음 공시한 숫자와 달라요.",
            "The company later corrected this figure. It differs from the first filing.")
    }

    static func restatedTag(_ language: Language) -> String { language("정정됨", "Restated") }

    /// Draft: a year with no figure in the bundle.
    static func noFigure(_ language: Language) -> String {
        language("이 해의 숫자가 없어요", "No figure for this year")
    }

    /// Draft: the reported metrics that have no figure for either year.
    static func notStated(_ metrics: [ReportedMetric], _ language: Language) -> String? {
        guard !metrics.isEmpty else { return nil }
        let names = metrics.map { $0.name(language) }.joined(separator: language(", ", ", "))
        return language("이 두 해의 숫자가 없는 항목: \(names)", "No figure for either year: \(names)")
    }

    /// The formula line under the operating margin (board 4 derives it).
    static func marginFormula(_ language: Language) -> String {
        language("영업이익 ÷ 매출", "Operating income ÷ revenue")
    }

    // MARK: - Refusals (board 10, approved)

    /// The approved title for a refusal; a base of zero or below uses board 9's line.
    static func refusal(_ refusal: Refusal, _ language: Language) -> String {
        if refusal.detail == .nonpositiveBaseline { return baseNotPositive(language) }
        return switch refusal.reason {
        case .ambiguousRequest: language("무엇을 비교할지 골라 주세요", "Choose what to compare")
        case .unsupportedBasis: language("이 기준의 숫자는 비교하지 않아요", "This basis is not compared")
        case .metricOutOfScope: language("이 지표는 다루지 않아요", "This figure is not covered")
        case .missingPeriod: language("비교할 해의 숫자가 없어요", "A year is missing")
        case .incompatibleCurrency:
            language("통화가 달라 금액은 비교하지 않아요", "Different currencies, so amounts are not compared")
        case .incompatibleComparison: language("두 숫자의 조건이 달라요", "The two figures are not alike")
        }
    }

    /// Board 10's explanation under the incompatible-comparison title; nil for the others.
    static func refusalBody(_ refusal: Refusal, _ language: Language) -> String? {
        guard refusal.reason == .incompatibleComparison, refusal.detail != .nonpositiveBaseline else { return nil }
        return language(
            "기간, 기준, 단위 가운데 하나가 달라요. 작년 숫자가 0 이하이면 증가율도 계산하지 않아요.",
            "Their period, basis or unit differs. When last year is zero or below, there is no growth rate either.")
    }

    // MARK: - Figure screen

    static func meaning(_ language: Language) -> String { language("뜻", "Meaning") }
    static func earlierYears(_ language: Language) -> String { language("연도별 숫자", "By year") }
    static func calculation(_ language: Language) -> String { language("계산", "Calculation") }

    /// Draft: the growth formula, written out.
    static func growthFormula(_ language: Language) -> String {
        language("(올해 − 작년) ÷ 작년 × 100", "(this year − last year) ÷ last year × 100")
    }

    /// Draft: a figure that has only one year.
    static func oneYearOnly(_ language: Language) -> String {
        language("비교할 해의 숫자가 없어요", "A year is missing")
    }
}

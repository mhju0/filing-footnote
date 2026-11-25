import FootnoteKit
import Foundation

/// Copy around "Ask about this company" (D95). The questions and the answer sentences are
/// FootnoteKit's fixed text (`contracts/company-questions.json`); these are the labels
/// around them.
enum AskCopy {
    static func sectionTitle(_ language: Language) -> String {
        language("이 기업에 물어보기", "Ask about this company")
    }

    static func sectionNote(_ language: Language) -> String {
        language("답은 이 앱에 담긴 공시로만 만들어요.", "Answers come only from the filings in this app.")
    }

    static func chipHint(_ language: Language) -> String {
        language("답을 열어요", "Opens the answer")
    }

    static func business(_ language: Language) -> String {
        language("회사가 밝힌 사업", "The business, in the company's words")
    }

    static func outlook(_ language: Language) -> String {
        language("회사의 전망 공시", "The company's outlook filing")
    }

    static func related(_ language: Language) -> String {
        language("공시로 답할 수 있는 질문", "Questions the filings can answer")
    }

    /// A figure the report does not state: said, never shown as zero.
    static func notInReport(_ language: Language) -> String {
        language("보고서에 없어요", "Not in the report")
    }

    static func source(_ language: Language) -> String { language("출처", "Source") }

    /// Above a quarter's figures: `최근 분기 · 7–9월 실적 · 연결`.
    static func quarterHeading(_ period: AnswerPeriod, _ language: Language) -> String {
        language("최근 분기", "Latest quarter") + Copy.dot
            + PageCopy.quarterFigures(start: period.start, end: period.end, language)
    }

    /// Above a year's figures: `최근 회계연도 · 2025 회계연도 · 연결 기준`.
    static func yearHeading(_ fiscalYear: Int, basis: String, _ language: Language) -> String {
        var parts = [language("최근 회계연도", "Latest fiscal year"), PageCopy.fiscalYear(fiscalYear, language)]
        if let name = PageCopy.basisName(basis, language) { parts.append(name) }
        return parts.joined(separator: Copy.dot)
    }

    /// Under a figures block: the period compared with, then what a tap shows.
    static func figuresNote(prior: AnswerPeriod?, _ language: Language) -> String {
        let tap = language("숫자를 누르면 정확한 금액을 볼 수 있어요.", "Tap a figure to see the exact amount.")
        guard let prior else { return tap }
        let period = Formatting.period(prior.start, prior.end, language: language)
        return language("비교 기간: \(period). ", "Compared with \(period). ") + tap
    }

    /// The line under a figure: the change in sign and word, or why there is none.
    static func change(_ row: AnswerFigureRow, _ language: Language) -> String? {
        switch row.change {
        case .result(let percent)?: Formatting.percentChange(percent, language: language)
        case .refusal(let refusal)?: PageCopy.refusal(refusal, language)
        case nil: nil
        }
    }

    /// The exact amounts a tap reveals: this period, then the same period a year earlier.
    static func exactLines(_ row: AnswerFigureRow, _ language: Language) -> [String] {
        var lines: [String] = []
        if let current = row.current {
            lines.append(language("이번 기간 ", "This period ") + exact(current, language))
        }
        if let prior = row.prior {
            lines.append(language("작년 같은 기간 ", "A year earlier ") + exact(prior, language))
        }
        return lines
    }

    static func shortened(_ amount: AnswerAmount, _ language: Language) -> String {
        Formatting.amount(amount.value, currency: amount.currency ?? amount.unit, language: language)
    }

    static func exact(_ amount: AnswerAmount, _ language: Language) -> String {
        PageCopy.exact(amount.value, unit: amount.unit, currency: amount.currency, language)
    }

    /// What VoiceOver reads for a figure: name, exact amount, then the change in words.
    static func spoken(_ row: AnswerFigureRow, _ language: Language) -> String {
        var parts = [row.metric.name(language)]
        guard let current = row.current else { return (parts + [notInReport(language)]).joined(separator: ", ") }
        parts.append(exact(current, language))
        switch row.change {
        case .result(let percent)?: parts.append(Formatting.percentChangeSpoken(percent, language: language))
        case .refusal(let refusal)?: parts.append(PageCopy.refusal(refusal, language))
        case nil: break
        }
        return parts.joined(separator: ", ")
    }
}

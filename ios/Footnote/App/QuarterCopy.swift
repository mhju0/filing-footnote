import FootnoteKit
import Foundation

/// Copy for the quarter report (I11). Boards 14 and 15 show the company row and report screen.
/// D91 records the owner's approval of wording added during implementation.
extension PageCopy {
    private static let monthNames = [
        "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December",
    ]

    /// True for whole calendar months within one year, as DART quarters are.
    private static func isWholeMonths(_ start: CivilDate, _ end: CivilDate) -> Bool {
        start.day == 1 && end.nextDay.day == 1 && start.year == end.year
    }

    /// Board 15: `7–9월 실적 · 연결` / `July–September · Consolidated`.
    /// For a quarter spanning partial months (D91):
    /// `3월 29일–6월 27일 실적 · 연결` / `Mar 29–Jun 27 · Consolidated`.
    static func quarterFigures(start: CivilDate, end: CivilDate, _ language: Language) -> String {
        let consolidated = language("연결", "Consolidated")
        guard isWholeMonths(start, end) else {
            let span = Formatting.monthDay(start, language: language) + "–" + Formatting.monthDay(end, language: language)
            return language("\(span) 실적", span) + Copy.dot + consolidated
        }
        return language(
            "\(start.month)–\(end.month)월 실적",
            "\(monthNames[start.month - 1])–\(monthNames[end.month - 1])") + Copy.dot + consolidated
    }

    /// Board 15: `2025년 7–9월` / `July–September 2025`. Other spans use both full dates (D91).
    private static func quarterPeriod(start: CivilDate, end: CivilDate, _ language: Language) -> String {
        guard isWholeMonths(start, end) else { return Formatting.period(start, end, language: language) }
        return language(
            Formatting.period(start, end, language: .ko),
            "\(monthNames[start.month - 1])–\(monthNames[end.month - 1]) \(start.year)")
    }

    /// Board 15 names the quarter a year earlier. The second sentence describes the
    /// figure screen that opens on tap (D91).
    static func quarterNote(prior: (start: CivilDate, end: CivilDate)?, _ language: Language) -> String {
        let tap = language("숫자를 누르면 뜻과 연도별 숫자를 볼 수 있어요.",
                           "Tap a figure for its meaning and its figures by year.")
        guard let prior else { return tap }
        let period = quarterPeriod(start: prior.start, end: prior.end, language)
        return language("작년 같은 기간(\(period))과 비교했어요. ", "Compared with \(period). ") + tap
    }

    /// Board 15.
    static func related(_ language: Language) -> String { language("관련 자료", "Related") }

    /// Board 15: under the preliminary results: `10월 29일 공시 · 이 보고서보다 먼저 냈어요`.
    /// For same-day filings, the order is unknown (DART's
    /// exchange and FSS receipt numbers are separate sequences).
    static func preliminaryDetail(_ filedOn: CivilDate, report: CivilDate, _ language: Language) -> String {
        let day = Copy.unbroken(Formatting.monthDay(filedOn, language: language))
        if filedOn == report {
            return language("\(day) 공시" + Copy.dot + "이 보고서와 같은 날 냈어요", "Filed \(day), the same day as this report")
        }
        return language("\(day) 공시" + Copy.dot + "이 보고서보다 먼저 냈어요", "Filed \(day), before this report")
    }

    /// Investor event notices link to the regulator. The bundle has no IR site links.
    static func investorEventDetail(_ filedOn: CivilDate, _ regulator: Regulator, _ language: Language) -> String {
        let day = Copy.unbroken(Formatting.monthDay(filedOn, language: language))
        let site = regulator == .dart ? "DART" : "SEC"
        return language("\(day) 공시" + Copy.dot + "\(site)에서 열려요", "Filed \(day)" + Copy.dot + "Opens on \(site)")
    }

    /// A quarter figure shortened, as board 15 shows it: `45조 1,102억원` / `₩45.11 trillion`.
    static func shortened(_ figure: QuarterFigure, currency: String, _ language: Language) -> String {
        Formatting.amount(figure.value, currency: figure.currency ?? currency, language: language)
    }
}

extension Copy {
    /// Board 14: `매출 45조 1,102억원 · −3.45% 줄었어요` under the quarterly row.
    static func quarterRevenueLine(_ report: QuarterReport, currency: String, _ language: Language) -> String? {
        guard let revenue = report.revenue?.current else { return nil }
        var line = language("매출", "Revenue") + " "
            + Formatting.amount(revenue.value, currency: revenue.currency ?? currency, language: language)
        if let change = report.change {
            line += dot + Formatting.percentChange(change.percentChange, language: language)
        }
        return line
    }

    /// What VoiceOver reads for that line: the amount, then the change in words.
    static func quarterRevenueSpoken(_ report: QuarterReport, currency: String, _ language: Language) -> String? {
        guard let revenue = report.revenue?.current else { return nil }
        var parts = [language("매출", "Revenue") + " "
            + Formatting.amount(revenue.value, currency: revenue.currency ?? currency, language: language)]
        if let change = report.change {
            parts.append(Formatting.percentChangeSpoken(change.percentChange, language: language))
        }
        return parts.joined(separator: ", ")
    }
}

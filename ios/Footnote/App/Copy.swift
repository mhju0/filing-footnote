import FootnoteKit
import SwiftUI

extension EnvironmentValues {
    /// The reader's language. Korean first; the globe button switches the whole UI.
    @Entry var language: Language = .ko
}

extension Language {
    /// `language("기업", "Companies")`: the Korean or English copy.
    func callAsFunction(_ ko: String, _ en: String) -> String { self == .ko ? ko : en }

    var locale: Locale { Locale(identifier: self == .ko ? "ko_KR" : "en_US") }

    var other: Language { self == .ko ? .en : .ko }
}

/// Copy that depends on data. The approved wording is board 19 (state copy) and board 14
/// (company page); every string has a Korean and an English form.
enum Copy {
    /// Joins a date's parts with no-break spaces, so `11월 19일` never splits across lines.
    static func unbroken(_ text: String) -> String {
        text.replacingOccurrences(of: " ", with: noBreak)
    }

    static let noBreak = "\u{00A0}"
    /// A middle dot held to the word before it by a no-break space, so a line never starts
    /// with `·` (D86). A line may end on `word ·`; the next part starts the next line.
    static let dot = "\u{00A0}· "

    static func dataDate(_ date: CivilDate, _ language: Language) -> String {
        let day = unbroken(Formatting.monthDay(date, language: language))
        return language("\(day)까지 낸\(noBreak)공시", "Filings up to \(day)")
    }

    static func companySubtitle(_ company: Company, dataAsOf: CivilDate, _ language: Language) -> String {
        company.ticker + dot + dataDate(dataAsOf, language)
    }

    static func noticesRow(count: Int, _ language: Language) -> String {
        language("안내 공시 \(count)건", count == 1 ? "1 notice" : "\(count) notices")
    }

    /// The categories under the notices row: `IR 행사 5 · 기준일`, at most three.
    static func noticeBreakdown(_ counts: [(category: NoticeCategory, count: Int)], _ language: Language) -> String {
        counts.prefix(3)
            .map { $0.count > 1 ? "\($0.category.label(language)) \($0.count)" : $0.category.label(language) }
            .joined(separator: dot)
    }

    /// `since` carries its year when it falls in an earlier year than the data date.
    static func noticesIntro(count: Int, since: CivilDate, dataAsOf: CivilDate, _ language: Language) -> String {
        let base = language(
            "일정이나 절차를 알리는 공시예요. 요약하지 않고 날짜와 원문만 보여 줘요.",
            "Filings that announce a date or a procedure. Shown with the date and the original only, no summary.")
        // No-break spaces keep the count with its date, so neither ends a line alone.
        let day = unbroken(since.year == dataAsOf.year
            ? Formatting.monthDay(since, language: language)
            : Formatting.fullDate(since, language: language))
        return base + " " + language(
            "\(day)부터 낸 \(count)건이에요.", "\(count)\(noBreak)since\(noBreak)\(day).")
    }

    static func endNote(listed: Int, capped: Bool, _ language: Language) -> String {
        if listed == 0 {
            return language("최근 1년 동안 낸 공시가 없어요.", "No filings in the last 12 months.")
        }
        if capped {
            return language(
                "최근 1년 공시 가운데 최근 \(CompanyPage.maxFilings)건이에요.",
                "The \(CompanyPage.maxFilings) newest filings from the last 12 months.")
        }
        return language(
            "최근 1년 동안 낸 공시 \(listed)건을 모두 보여 줘요.",
            "These are all \(listed) filings from the last 12 months.")
    }

    /// Draft: the note under the 소식 feed (D86). The empty feed uses board 19's
    /// "no filings in the last 12 months" line (`endNote(listed: 0, …)`).
    static func newsEndNote(listed: Int, capped: Bool, _ language: Language) -> String {
        if capped {
            return language(
                "모든 기업의 최근 공시 \(listed)건이에요. 기업마다 최근 공시를 더 보려면 기업 화면을 여세요.",
                "The \(listed) newest filings across all companies. Each company’s page lists more.")
        }
        return language(
            "모든 기업의 최근 공시 \(listed)건을 모두 보여 줘요.",
            "These are all \(listed) recent filings across the companies.")
    }

    /// Draft: the link from a filing or annual page to the glossary entry for its category.
    static func glossaryLink(_ term: String, _ language: Language) -> String {
        language("용어 풀이: \(term)", "Glossary: \(term)")
    }

    /// Draft: the split view's detail column before a term is chosen.
    static func chooseTerm(_ language: Language) -> String {
        language("용어를 고르면 여기에 보여 줘요", "Choose a term to see it here")
    }

    static func allFilingsLink(_ regulator: Regulator, _ language: Language) -> String {
        let site = regulator == .dart ? "DART" : "SEC"
        return language("\(site)에서 전체 공시 보기", "See every filing on \(site)")
    }

    static func openOriginal(_ regulator: Regulator, _ language: Language) -> String {
        let site = regulator == .dart ? "DART" : "SEC"
        return language("\(site)에서 원문 보기", "Open the original on \(site)")
    }

    static func filedOn(_ date: CivilDate, _ language: Language) -> String {
        let day = unbroken(Formatting.fullDate(date, language: language))
        return language("\(day) 공시", "Filed \(day)")
    }

    static func market(_ regulator: Regulator, _ language: Language) -> String {
        regulator == .dart ? language("한국", "Korea") : language("미국", "United States")
    }

    /// `매출 186조 2,545억원 · +6.29% 늘었어요`.
    static func revenueLine(_ report: PeriodicReport, currency: String, _ language: Language) -> String? {
        guard let revenue = report.revenue else { return nil }
        var line = language("매출", "Revenue") + " "
            + Formatting.amount(revenue.value, currency: revenue.currency ?? currency, language: language)
        if let change = report.change {
            line += dot + Formatting.percentChange(change.percentChange, language: language)
        }
        return line
    }

    /// The note under a periodic row whose revenue or prior-year revenue a later report
    /// restated (DESIGN.md G1: a 정정됨 / Restated tag beside the value and a note below).
    static func restatedNote(_ report: PeriodicReport, _ language: Language) -> String? {
        let notes = report.restated.map { figure in
            let fromThisReport = figure.filingID == report.filing.id
            return language(
                "\(figure.fiscalYear) 회계연도 매출은 "
                    + (fromThisReport ? "이 보고서가 정정한 값이에요." : "정정된 값이에요."),
                "FY\(figure.fiscalYear) revenue is "
                    + (fromThisReport ? "as restated in this report." : "a restated value."))
        }
        return notes.isEmpty ? nil : notes.joined(separator: " ")
    }

    /// The note under a periodic row whose change compares two fiscal years that end on
    /// different days, as 52/53-week years do (D82). A year a week longer than the other is
    /// the clearer fact, so that note replaces the one about the ends.
    static func fiscalYearEndsNote(_ report: PeriodicReport, _ language: Language) -> String? {
        guard let change = report.change else { return nil }
        if change.periodLengthsDiffer {
            return language("한 해가 다른 해보다 한 주 길어요.", "One of the years is a week longer.")
        }
        guard change.periodEndsDiffer else { return nil }
        return language("회계연도 마감일이 며칠 달라요.", "The fiscal years end a few days apart.")
    }

    /// What VoiceOver reads for the revenue line: the amount, then the change in words.
    static func revenueSpoken(_ report: PeriodicReport, currency: String, _ language: Language) -> String? {
        guard let revenue = report.revenue else { return nil }
        let amount = Formatting.amount(revenue.value, currency: revenue.currency ?? currency, language: language)
        let year = language("\(revenue.fiscalYear) 회계연도 매출 \(amount)", "Revenue for fiscal \(revenue.fiscalYear), \(amount)")
        guard let change = report.change else { return year }
        let words = Formatting.percentChangeSpoken(change.percentChange, language: language)
        return year + ", " + words
    }
}

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
    static func dataDate(_ date: CivilDate, _ language: Language) -> String {
        let day = Formatting.monthDay(date, language: language)
        return language("\(day)까지 낸 공시", "Filings up to \(day)")
    }

    static func companySubtitle(_ company: Company, dataAsOf: CivilDate, _ language: Language) -> String {
        "\(company.ticker) · " + dataDate(dataAsOf, language)
    }

    static func noticesRow(count: Int, _ language: Language) -> String {
        language("안내 공시 \(count)건", count == 1 ? "1 notice" : "\(count) notices")
    }

    /// The categories under the notices row: `IR 행사 5 · 기준일`, at most three.
    static func noticeBreakdown(_ counts: [(category: NoticeCategory, count: Int)], _ language: Language) -> String {
        counts.prefix(3)
            .map { $0.count > 1 ? "\($0.category.label(language)) \($0.count)" : $0.category.label(language) }
            .joined(separator: " · ")
    }

    static func noticesIntro(count: Int, since: CivilDate?, _ language: Language) -> String {
        let base = language(
            "일정이나 절차를 알리는 공시예요. 요약하지 않고 날짜와 원문만 보여 줘요.",
            "Filings that announce a date or a procedure. Shown with the date and the original only, no summary.")
        guard let since else { return base }
        // No-break spaces keep the count with its date, so neither ends a line alone.
        let day = Formatting.monthDay(since, language: language).replacingOccurrences(of: " ", with: "\u{00A0}")
        return base + " " + language(
            "\(day)부터 낸 \(count)건이에요.", "\(count)\u{00A0}since\u{00A0}\(day).")
    }

    static func endNote(listed: Int, capped: Bool, _ language: Language) -> String {
        if capped {
            return language(
                "최근 1년 공시 가운데 최근 \(CompanyPage.maxFilings)건이에요.",
                "The \(CompanyPage.maxFilings) newest filings from the last 12 months.")
        }
        return language(
            "최근 1년 동안 낸 공시 \(listed)건을 모두 보여 줘요.",
            "These are all \(listed) filings from the last 12 months.")
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
        let day = Formatting.fullDate(date, language: language)
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
            line += " · " + Formatting.percentChange(change.percentChange, language: language)
        }
        return line
    }

    /// What VoiceOver reads for the revenue line: the amount, then the change in words.
    static func revenueSpoken(_ report: PeriodicReport, currency: String, _ language: Language) -> String? {
        guard let revenue = report.revenue else { return nil }
        let amount = Formatting.amount(revenue.value, currency: revenue.currency ?? currency, language: language)
        let year = language("\(revenue.fiscalYear) 회계연도 매출 \(amount)", "Revenue for fiscal \(revenue.fiscalYear), \(amount)")
        guard let change = report.change else { return year }
        let rounded = DecimalText.twoPlaces(change.percentChange < 0 ? -change.percentChange : change.percentChange)
        let words: String = if change.percentChange > 0 {
            language("전년보다 \(rounded)퍼센트 늘었어요", "up \(rounded) percent from the year before")
        } else if change.percentChange < 0 {
            language("전년보다 \(rounded)퍼센트 줄었어요", "down \(rounded) percent from the year before")
        } else {
            language("전년과 같아요", "no change from the year before")
        }
        return year + ", " + words
    }
}

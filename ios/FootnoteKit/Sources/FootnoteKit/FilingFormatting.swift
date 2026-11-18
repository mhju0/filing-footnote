import Foundation

/// The unit a filing fact or figure is stated in, read from its `unit` column. DART tables
/// state amounts in 백만원, 억원 and similar; the endpoints and SEC state currency codes.
public enum StatedUnit: Sendable, Hashable {
    /// Money in `currency`; the stored value times `scale` is the amount in that currency.
    case money(currency: String, scale: Decimal)
    /// A count of units (대, 대수).
    case units
    case shares
    case percent

    /// Nil for a unit this table does not know; the caller then shows the value as written.
    public init?(_ unit: String?, fallbackCurrency: String) {
        switch unit {
        case nil: self = .money(currency: fallbackCurrency, scale: 1)
        case "KRW", "원", "KRW_PER_SHARE": self = .money(currency: "KRW", scale: 1)
        case "USD", "USD_PER_SHARE": self = .money(currency: "USD", scale: 1)
        case "천원": self = .money(currency: "KRW", scale: 1_000)
        case "백만원": self = .money(currency: "KRW", scale: 1_000_000)
        case "억원": self = .money(currency: "KRW", scale: 100_000_000)
        case "조원": self = .money(currency: "KRW", scale: Decimal(string: "1000000000000")!)
        case "대", "대수": self = .units
        case "shares": self = .shares
        case "%", "percent": self = .percent
        default: return nil
        }
    }
}

extension Formatting {
    // MARK: - Exact amounts

    /// A money amount as a filing page shows it. Korean writes every digit in 조, 억 and 만
    /// with nothing rounded (`2,715억 4,596만원`, `45조 1,102억 4,700만원`); English uses
    /// `amount(_:currency:language:)` (`₩271.55 billion`), as the approved boards do.
    public static func exactAmount(_ value: Decimal, currency: String, language: Language) -> String {
        guard language == .ko else { return amount(value, currency: currency, language: language) }
        let sign = value < 0 ? minus : ""
        let magnitude = value < 0 ? -value : value
        let suffix = switch currency {
        case "KRW": "원"
        case "USD": " 달러"
        default: " \(currency)"
        }
        let text = DecimalText.canonical(magnitude)
        let pieces = text.split(separator: ".", maxSplits: 1, omittingEmptySubsequences: false)
        let integer = String(pieces[0])
        let fraction = pieces.count > 1 ? "." + pieces[1] : ""
        // Groups of four digits from the right: 만, 억, 조, then 경 for anything larger.
        var groups: [String] = []
        var rest = Substring(integer)
        while !rest.isEmpty {
            groups.insert(String(rest.suffix(4)), at: 0)
            rest = rest.dropLast(min(4, rest.count))
        }
        let names = ["", "만", "억", "조", "경"]
        guard groups.count <= names.count else { return sign + number(magnitude) + suffix }
        var parts: [String] = []
        for (offset, group) in groups.enumerated() {
            let place = groups.count - 1 - offset
            let digits = String(Int(group)!)
            let last = place == 0
            if digits == "0" && !(last && !fraction.isEmpty) { continue }
            parts.append(groupedNumber(digits) + (last ? fraction : "") + names[place])
        }
        if parts.isEmpty { parts = ["0" + fraction] }
        return sign + parts.joined(separator: " ") + suffix
    }

    /// A value in its stated unit: money as `exactAmount`, units as `4,000,000대` or
    /// `4,000,000 units`, shares as `917,385주` or `917,385 shares`, a percentage with two
    /// places. Nil for a unit `StatedUnit` does not know.
    public static func stated(
        _ value: Decimal, unit: String?, fallbackCurrency: String, language: Language
    ) -> String? {
        guard let stated = StatedUnit(unit, fallbackCurrency: fallbackCurrency) else { return nil }
        switch stated {
        case .money(let currency, let scale):
            return exactAmount(value * scale, currency: currency, language: language)
        case .units:
            return number(value) + (language == .ko ? "대" : " units")
        case .shares:
            return number(value) + (language == .ko ? "주" : " shares")
        case .percent:
            return percent(value)
        }
    }

    // MARK: - Periods

    /// A period of whole calendar months as a filing names it: Korean `2026년 7–9월`,
    /// `2026년 10월`, `2025년 10월–2026년 9월`; English `Jul–Sep 2026`, `Oct 2026`,
    /// `Oct 2025–Sep 2026`. A period that does not start on a first and end on a last day
    /// is written as two full dates.
    public static func period(_ start: CivilDate, _ end: CivilDate, language: Language) -> String {
        let wholeMonths = start.day == 1 && end.nextDay.day == 1 && start <= end
        guard wholeMonths else {
            return fullDate(start, language: language) + "–" + fullDate(end, language: language)
        }
        let months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        let sameMonth = start.year == end.year && start.month == end.month
        switch language {
        case .ko:
            if sameMonth { return "\(start.year)년 \(start.month)월" }
            if start.year == end.year { return "\(start.year)년 \(start.month)–\(end.month)월" }
            return "\(start.year)년 \(start.month)월–\(end.year)년 \(end.month)월"
        case .en:
            if sameMonth { return "\(months[start.month - 1]) \(start.year)" }
            if start.year == end.year {
                return "\(months[start.month - 1])–\(months[end.month - 1]) \(start.year)"
            }
            return "\(months[start.month - 1]) \(start.year)–\(months[end.month - 1]) \(end.year)"
        }
    }
}

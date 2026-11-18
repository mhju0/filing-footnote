import Foundation

/// Display strings for figures, changes and dates. Pure functions over `Decimal` and
/// `CivilDate`: no locale, time zone or binary floating point is involved, so the same value
/// reads the same on every device.
public enum Formatting {
    /// U+2212, the typographic minus sign.
    public static let minus = "\u{2212}"

    // MARK: - Amounts

    /// A money amount for a figure card.
    ///
    /// Korean: rounded half-up to 억 and written in 조 and 억 (`45조 1,102억원`,
    /// `4,161억 달러`). English: two decimals in trillions, billions or millions
    /// (`₩45.11 trillion`, `$3.86 billion`). Amounts below 1억 (Korean) or one million
    /// (English) are written exactly with digit grouping (`4,950원`, `$7.46`).
    public static func amount(_ value: Decimal, currency: String, language: Language) -> String {
        let sign = value < 0 ? minus : ""
        let magnitude = value < 0 ? -value : value
        switch language {
        case .ko: return sign + koreanAmount(magnitude, currency: currency)
        case .en: return sign + englishAmount(magnitude, currency: currency)
        }
    }

    private static let eok = Decimal(100_000_000)

    private static func koreanAmount(_ magnitude: Decimal, currency: String) -> String {
        let suffix = switch currency {
        case "KRW": "원"
        case "USD": " 달러"
        default: " \(currency)"
        }
        guard magnitude >= eok else { return exact(magnitude) + suffix }
        let units = DecimalText.canonical(DecimalText.roundHalfUp(magnitude / eok, scale: 0))
        let jo = String(units.dropLast(4))
        let rest = Int(units.suffix(4))!
        var parts: [String] = []
        if !jo.isEmpty { parts.append(grouped(jo) + "조") }
        if rest > 0 { parts.append(grouped(String(rest)) + "억") }
        return parts.joined(separator: " ") + suffix
    }

    private static let englishScales: [(Decimal, String)] = [
        (Decimal(string: "1000000000000")!, "trillion"),
        (Decimal(1_000_000_000), "billion"),
        (Decimal(1_000_000), "million"),
    ]

    private static func englishAmount(_ magnitude: Decimal, currency: String) -> String {
        let symbol = switch currency {
        case "KRW": "₩"
        case "USD": "$"
        default: "\(currency) "
        }
        for (divisor, word) in englishScales {
            let scaled = DecimalText.roundHalfUp(magnitude / divisor, scale: 2)
            if scaled >= 1 { return "\(symbol)\(groupedNumber(DecimalText.twoPlaces(scaled))) \(word)" }
        }
        return symbol + exact(magnitude)
    }

    /// The exact value with digit grouping and no trailing fractional zeros.
    private static func exact(_ magnitude: Decimal) -> String {
        groupedNumber(DecimalText.canonical(magnitude))
    }

    // MARK: - Percentages

    /// A change in percent with its sign and a direction word, never colour alone:
    /// Korean `+6.29% 늘었어요`, `−3.45% 줄었어요`, `0.00% 변동 없어요`;
    /// English `+6.29%, up`, `−3.45%, down`, `0.00%, no change`.
    /// The value is rounded half-up to two places first.
    public static func percentChange(_ percent: Decimal, language: Language) -> String {
        let rounded = DecimalText.roundHalfUp(percent, scale: 2)
        let digits = DecimalText.twoPlaces(rounded < 0 ? -rounded : rounded) + "%"
        if rounded > 0 {
            return language == .ko ? "+\(digits) 늘었어요" : "+\(digits), up"
        }
        if rounded < 0 {
            return language == .ko ? "\(minus)\(digits) 줄었어요" : "\(minus)\(digits), down"
        }
        return language == .ko ? "\(digits) 변동 없어요" : "\(digits), no change"
    }

    /// A rate such as an operating margin: two places, the true minus sign, no direction word.
    public static func percent(_ value: Decimal) -> String {
        let rounded = DecimalText.roundHalfUp(value, scale: 2)
        let digits = DecimalText.twoPlaces(rounded < 0 ? -rounded : rounded) + "%"
        return rounded < 0 ? minus + digits : digits
    }

    // MARK: - Dates

    private static let englishMonths = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    /// Month and day: Korean `11월 18일`, English `Nov 18`.
    public static func monthDay(_ date: CivilDate, language: Language) -> String {
        switch language {
        case .ko: "\(date.month)월 \(date.day)일"
        case .en: "\(englishMonths[date.month - 1]) \(date.day)"
        }
    }

    // MARK: - Grouping

    /// Commas every three digits of the integer part of an unsigned plain decimal string.
    static func groupedNumber(_ text: String) -> String {
        let pieces = text.split(separator: ".", maxSplits: 1, omittingEmptySubsequences: false)
        let integer = grouped(String(pieces[0]))
        return pieces.count > 1 ? "\(integer).\(pieces[1])" : integer
    }

    private static func grouped(_ digits: String) -> String {
        var result = ""
        for (index, character) in digits.enumerated() {
            if index > 0 && (digits.count - index) % 3 == 0 { result.append(",") }
            result.append(character)
        }
        return result
    }
}

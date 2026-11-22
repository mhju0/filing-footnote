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
    /// `4,162억 달러`). English: two decimals in trillions, billions or millions
    /// (`₩45.11 trillion`, `$3.86 billion`), in the largest unit not above the value. Amounts
    /// below 1억 (Korean) or one million (English) are written exactly with digit grouping
    /// (`4,950원`, `$7.50`).
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

    /// Ascending, so a larger unit follows the one it replaces.
    private static let englishScales: [(Decimal, String)] = [
        (Decimal(1_000_000), "million"),
        (Decimal(1_000_000_000), "billion"),
        (Decimal(string: "1000000000000")!, "trillion"),
    ]

    static func currencySymbol(_ currency: String) -> String {
        switch currency {
        case "KRW": "₩"
        case "USD": "$"
        default: "\(currency) "
        }
    }

    private static func englishAmount(_ magnitude: Decimal, currency: String) -> String {
        let symbol = currencySymbol(currency)
        // The unit is the largest one not above the unrounded value; it moves up only when
        // rounding reaches a thousand of it (999,995,000,000 -> 1.00 trillion).
        guard var index = englishScales.lastIndex(where: { magnitude >= $0.0 }) else {
            return symbol + exact(magnitude)
        }
        var scaled = DecimalText.roundHalfUp(magnitude / englishScales[index].0, scale: 2)
        if scaled >= 1000 && index + 1 < englishScales.count {
            index += 1
            scaled = DecimalText.roundHalfUp(magnitude / englishScales[index].0, scale: 2)
        }
        return "\(symbol)\(groupedNumber(DecimalText.twoPlaces(scaled))) \(englishScales[index].1)"
    }

    /// The exact value with digit grouping. A whole amount stays whole (`4,950`); one with a
    /// fraction shows at least two fraction digits (`7.50`) and is never rounded.
    static func exact(_ magnitude: Decimal) -> String {
        var text = DecimalText.canonical(magnitude)
        if let point = text.firstIndex(of: ".") {
            let digits = text.distance(from: point, to: text.endIndex) - 1
            if digits < 2 { text += String(repeating: "0", count: 2 - digits) }
        }
        return groupedNumber(text)
    }

    // MARK: - Percentages

    /// A change in percent with its sign and a direction word, never colour alone:
    /// Korean `+6.29% 늘었어요`, `−3.45% 줄었어요`, `0.00% 변동 없어요`;
    /// English `+6.29% up`, `−3.45% down`, `0.00% no change`.
    /// The value is rounded half-up to two places first.
    public static func percentChange(_ percent: Decimal, language: Language) -> String {
        let (sign, digits) = roundedChange(percent)
        switch sign {
        case 1: return language == .ko ? "+\(digits)% 늘었어요" : "+\(digits)% up"
        case -1: return language == .ko ? "\(minus)\(digits)% 줄었어요" : "\(minus)\(digits)% down"
        default: return language == .ko ? "\(digits)% 변동 없어요" : "\(digits)% no change"
        }
    }

    /// The change from the year before as VoiceOver reads it, with the direction taken from
    /// the same rounded value the visible line shows: Korean `전년보다 6.29퍼센트 늘었어요`,
    /// English `up 6.29 percent from the year before`; `전년과 같아요` / `no change from the
    /// year before` when it rounds to zero.
    public static func percentChangeSpoken(_ percent: Decimal, language: Language) -> String {
        let (sign, digits) = roundedChange(percent)
        switch sign {
        case 1: return language == .ko ? "전년보다 \(digits)퍼센트 늘었어요" : "up \(digits) percent from the year before"
        case -1: return language == .ko ? "전년보다 \(digits)퍼센트 줄었어요" : "down \(digits) percent from the year before"
        default: return language == .ko ? "전년과 같아요" : "no change from the year before"
        }
    }

    /// The sign (1, 0 or -1) and two-place magnitude of a change rounded half-up to two places.
    private static func roundedChange(_ percent: Decimal) -> (sign: Int, digits: String) {
        let rounded = DecimalText.roundHalfUp(percent, scale: 2)
        let digits = DecimalText.twoPlaces(rounded < 0 ? -rounded : rounded)
        return (rounded > 0 ? 1 : rounded < 0 ? -1 : 0, digits)
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

    /// A full date: Korean `2026년 11월 20일`, English `Nov 20, 2026`.
    public static func fullDate(_ date: CivilDate, language: Language) -> String {
        switch language {
        case .ko: "\(date.year)년 \(date.month)월 \(date.day)일"
        case .en: "\(englishMonths[date.month - 1]) \(date.day), \(date.year)"
        }
    }

    private static let englishMonthNames = [
        "January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December",
    ]

    /// A month heading: Korean `10월`, English `October`; the year is added when it is not
    /// `currentYear` (`2025년 12월`, `December 2025`).
    public static func month(_ month: Int, year: Int, currentYear: Int, language: Language) -> String {
        let sameYear = year == currentYear
        switch language {
        case .ko: return sameYear ? "\(month)월" : "\(year)년 \(month)월"
        case .en:
            let name = englishMonthNames[month - 1]
            return sameYear ? name : "\(name) \(year)"
        }
    }

    // MARK: - Counts

    /// An exact number with digit grouping and the true minus sign (`917,385`, `0.125`).
    /// Nothing is rounded.
    public static func number(_ value: Decimal) -> String {
        let magnitude = value < 0 ? -value : value
        let text = groupedNumber(DecimalText.canonical(magnitude))
        return value < 0 ? minus + text : text
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

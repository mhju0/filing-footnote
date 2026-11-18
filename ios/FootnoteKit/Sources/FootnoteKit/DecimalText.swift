import Foundation

/// Exact decimal parsing, rounding and the contract's canonical strings.
///
/// Values travel as `Decimal` from the bundle's text columns to the screen. Nothing here
/// converts through binary floating point.
public enum DecimalText {
    /// `Decimal` keeps 38 significant digits; longer input would be rounded, so it is refused.
    static let maxSignificantDigits = 38

    /// Parses the bundle's canonical form only: `-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?`, never `-0`.
    public static func parseCanonical(_ text: String) -> Decimal? {
        guard let parts = split(text) else { return nil }
        if parts.integer.count > 1 && parts.integer.hasPrefix("0") { return nil }
        if let fraction = parts.fraction, fraction.hasSuffix("0") { return nil }
        if parts.negative && parts.integer == "0" && parts.fraction == nil { return nil }
        return make(text, parts)
    }

    /// Parses plain decimal notation, `-?[0-9]+(\.[0-9]+)?`, as the comparison cases write inputs.
    public static func parsePlain(_ text: String) -> Decimal? {
        guard let parts = split(text) else { return nil }
        return make(text, parts)
    }

    /// The exact canonical string: no exponent, no trailing fractional zeros, no `-0`.
    public static func canonical(_ value: Decimal) -> String {
        var text = plain(value)
        if text.contains(".") {
            while text.hasSuffix("0") { text.removeLast() }
            if text.hasSuffix(".") { text.removeLast() }
        }
        return text == "-0" ? "0" : text
    }

    /// Rounds half away from zero (Python's `ROUND_HALF_UP`) to two places and writes
    /// exactly two fraction digits; zero is always `0.00`, never `-0.00`.
    public static func twoPlaces(_ value: Decimal) -> String {
        let text = canonical(roundHalfUp(value, scale: 2))
        let pieces = text.split(separator: ".", omittingEmptySubsequences: false)
        let fraction = pieces.count > 1 ? String(pieces[1]) : ""
        let padded = fraction + String(repeating: "0", count: 2 - fraction.count)
        let result = "\(pieces[0]).\(padded)"
        return result == "-0.00" ? "0.00" : result
    }

    /// Rounds half away from zero to `scale` fraction digits.
    public static func roundHalfUp(_ value: Decimal, scale: Int) -> Decimal {
        var input = value
        var result = Decimal()
        NSDecimalRound(&result, &input, scale, .plain)
        return result.isZero ? Decimal(0) : result
    }

    /// Rounds half to even to `digits` significant digits, as a Python decimal context of
    /// that precision rounds each operation's result.
    static func roundSignificant(_ value: Decimal, digits: Int) -> Decimal {
        if value.isZero { return value }
        let text = canonical(value < 0 ? -value : value)
        let pieces = text.split(separator: ".", omittingEmptySubsequences: false)
        let scale: Int
        if pieces[0] != "0" {
            scale = digits - pieces[0].count
        } else {
            let fraction = pieces.count > 1 ? pieces[1] : ""
            scale = digits + fraction.prefix(while: { $0 == "0" }).count
        }
        var input = value
        var result = Decimal()
        NSDecimalRound(&result, &input, scale, .bankers)
        return result
    }

    // MARK: - Parsing parts

    private struct Parts {
        let negative: Bool
        let integer: Substring
        let fraction: Substring?
    }

    private static func split(_ text: String) -> Parts? {
        var rest = Substring(text)
        let negative = rest.hasPrefix("-")
        if negative { rest = rest.dropFirst() }
        let pieces = rest.split(separator: ".", maxSplits: 1, omittingEmptySubsequences: false)
        let integer = pieces[0]
        let fraction = pieces.count > 1 ? pieces[1] : nil
        func digits(_ part: Substring) -> Bool {
            !part.isEmpty && part.utf8.allSatisfy { (48...57).contains($0) }
        }
        guard digits(integer) else { return nil }
        if let fraction, !digits(fraction) { return nil }
        return Parts(negative: negative, integer: integer, fraction: fraction)
    }

    private static func make(_ text: String, _ parts: Parts) -> Decimal? {
        let all = parts.integer + (parts.fraction ?? "")
        let significant = all.drop(while: { $0 == "0" })
        guard significant.count <= maxSignificantDigits else { return nil }
        let value = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX"))
        guard let value, !value.isNaN else { return nil }
        return value
    }

    /// Plain notation of the stored digits. `Decimal.description` never uses an exponent
    /// and always writes `.` as the separator.
    private static func plain(_ value: Decimal) -> String {
        value.description
    }
}

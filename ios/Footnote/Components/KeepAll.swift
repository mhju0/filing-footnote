import FootnoteKit
import SwiftUI

extension String {
    /// Korean wraps only between words (어절), never inside one, like CSS `word-break:
    /// keep-all`. SwiftUI has no such setting, so a WORD JOINER (U+2060) goes between the
    /// characters of each word that holds Hangul. Other words are left alone.
    var keepingWords: String {
        split(separator: " ", omittingEmptySubsequences: false)
            .map { word in
                guard word.unicodeScalars.contains(where: \.isHangul) else { return String(word) }
                return word.map(String.init).joined(separator: "\u{2060}")
            }
            .joined(separator: " ")
    }

    /// The string as VoiceOver should read it: each separator becomes a comma, so the dot
    /// is a pause, not the word "middle dot".
    var spokenSeparators: String { replacingOccurrences(of: Titles.separator, with: ", ") }
}

private extension Unicode.Scalar {
    var isHangul: Bool {
        (0xAC00...0xD7A3).contains(value) || (0x1100...0x11FF).contains(value)
            || (0x3130...0x318F).contains(value)
    }
}

extension Text {
    /// Text that wraps only between words; VoiceOver reads the plain string, with a pause
    /// for each separator.
    init(words string: String) {
        self = Text(verbatim: string.keepingWords).accessibilityLabel(Text(verbatim: string.spokenSeparators))
    }
}

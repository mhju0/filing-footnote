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
    /// is a pause, not the word "middle dot", and a no-break space is a plain space.
    var spokenSeparators: String {
        replacingOccurrences(of: Titles.separator, with: ", ").replacingOccurrences(of: "\u{00A0}", with: " ")
    }
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

/// Text in phrases that break only between phrases when the whole line does not fit, so a
/// short last word never sits alone on a line at large text sizes
/// (`+16.20%` / `늘었어요 · 작년보다`). The phrases joined with spaces are the visible text,
/// unchanged. When even one phrase is wider than the line, the text wraps between words as
/// usual. The caller sets the font and the accessibility label.
struct PhraseLines: View {
    let phrases: [String]
    var alignment: HorizontalAlignment = .leading

    var body: some View {
        ViewThatFits(in: .horizontal) {
            Text(words: joined).fixedSize()
            VStack(alignment: alignment, spacing: 0) {
                ForEach(Array(phrases.enumerated()), id: \.offset) { _, phrase in
                    Text(words: phrase).fixedSize()
                }
            }
            Text(words: joined).fixedSize(horizontal: false, vertical: true)
        }
    }

    private var joined: String { phrases.joined(separator: " ") }
}

/// Figures in full digits (`(333,605,938,000,000 − 300,870,903,000,000) ÷ …`). The text
/// wraps only at its spaces, never inside a number; a number wider than the whole line
/// shrinks to fit instead. A word without digits wider than the line (a long DART form name)
/// wraps as usual, so it keeps its text size. VoiceOver reads it as one text, as it read the
/// single `Text` this replaces. The caller sets the font.
struct UnbrokenNumbers: View {
    let text: String

    var body: some View {
        FlowLayout(spacing: 5, lineSpacing: 2) {
            ForEach(Array(text.split(separator: " ").enumerated()), id: \.offset) { _, token in
                if token.contains(where: \.isNumber) {
                    Text(verbatim: String(token))
                        .lineLimit(1)
                        .minimumScaleFactor(0.4)
                } else {
                    Text(words: String(token)).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(verbatim: text.spokenSeparators))
        .accessibilityAddTraits(.isStaticText)
    }
}

/// Text that wraps only between words. A word wider than the whole line (`삼성바이오로직스` at
/// the accessibility sizes) shrinks to fit on its line instead of breaking inside the word
/// (2026-11-26 review, issue 4). VoiceOver reads it as one text. The caller sets the font and
/// colour.
struct UnbrokenWords: View {
    let text: String

    var body: some View {
        let words = text.split(separator: " ").map(String.init)
        // Each word but the last carries its space, so the gap is the font's own.
        FlowLayout(spacing: 0, lineSpacing: 0) {
            ForEach(Array(words.enumerated()), id: \.offset) { index, word in
                Text(verbatim: index < words.count - 1 ? word + " " : word)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(verbatim: text))
        .accessibilityAddTraits(.isStaticText)
    }
}

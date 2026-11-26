import FootnoteKit
import SwiftUI

/// The summary lines, each with its source sentence behind a disclosure (D100). Closed by
/// default. A line without a source row shows only the line, and lines without any source
/// look as `SentenceRows` does.
struct SourcedSentenceRows: View {
    let lines: [SummaryLine]
    let filing: Filing

    var body: some View {
        if lines.allSatisfy({ $0.source == nil }) {
            SentenceRows(lines: lines.map(\.text))
        } else {
            ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                SourcedSentenceRow(line: line, filing: filing)
                    .accessibilityIdentifier("summary-line-\(index + 1)")
            }
        }
    }
}

private struct SourcedSentenceRow: View {
    @Environment(\.language) private var language
    let line: SummaryLine
    let filing: Filing
    @State private var isExpanded = Self.startsOpen

    /// Debug builds only: `-FootnoteSources open` starts every disclosure open, so the
    /// screenshot script can capture the excerpts.
    private static let startsOpen: Bool = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteSources"), index + 1 < arguments.count
        else { return false }
        return arguments[index + 1] == "open"
        #else
        return false
        #endif
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(words: line.text)
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let source = line.source {
                DisclosureGroup(isExpanded: $isExpanded) {
                    SourceExcerpt(source: source, filing: filing)
                        .padding(.bottom, 6)
                } label: {
                    Text(words: SourceCopy.disclosure(count: source.count, language))
                        .font(.subheadline)
                        .foregroundStyle(Theme.pine)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(minHeight: Theme.minTarget, alignment: .leading)
                }
                .rowDisclosure()
                .tint(Theme.pine)
                .accessibilityIdentifier("source-sentence")
            }
        }
        .padding(.top, 6)
        .listRowBackground(Theme.surface)
    }
}

/// The verbatim excerpt in the filing's language, under the language and the filing's name.
private struct SourceExcerpt: View {
    @Environment(\.language) private var language
    let source: LineSource
    let filing: Filing

    var body: some View {
        switch source {
        case .template:
            Text(words: SourceCopy.template(language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .excerpts(let excerpts, let excerptLanguage):
            let caption = SourceCopy.caption(
                excerptLanguage: excerptLanguage,
                filingName: Titles.title(for: filing, language: excerptLanguage), language)
            VStack(alignment: .leading, spacing: 8) {
                Text(words: caption)
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(Array(excerpts.enumerated()), id: \.offset) { _, excerpt in
                    Text(verbatim: excerpt.withLastWordHeld.keepingWords)
                        .font(.subheadline)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.leading, 12)
                        .overlay(alignment: .leading) {
                            // A quotation rule: the text below is the filing's own wording.
                            Rectangle().fill(Theme.muted.opacity(0.5)).frame(width: 2)
                        }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text(spoken(caption: caption, excerpts: excerpts, excerptLanguage)))
        }
    }

    /// The caption, then each excerpt tagged with its language so VoiceOver reads it in that
    /// language's voice.
    private func spoken(caption: String, excerpts: [String], _ excerptLanguage: Language) -> AttributedString {
        var text = AttributedString(caption.spokenSeparators + ". ")
        for excerpt in excerpts {
            var part = AttributedString(excerpt + " ")
            part.languageIdentifier = excerptLanguage.rawValue
            text += part
        }
        return text
    }
}

private extension String {
    /// A no-break space before the last word, so the excerpt never ends on a lone word.
    var withLastWordHeld: String {
        guard let space = lastIndex(of: " ") else { return self }
        return replacingCharacters(in: space...space, with: "\u{00A0}")
    }
}

private extension LineSource {
    var count: Int {
        if case .excerpts(let excerpts, _) = self { excerpts.count } else { 1 }
    }
}

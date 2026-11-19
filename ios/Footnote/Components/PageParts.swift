import FootnoteKit
import SwiftUI

/// The header of a filing or annual page (board 12A): tags and the filed date, then the
/// title. The corrected note sits under it when the filing was refiled.
struct PageHeader: View {
    @Environment(\.language) private var language
    let filing: Filing
    let dataAsOf: CivilDate

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            FlowLayout(spacing: 6, lineSpacing: 4) {
                TagView(text: filing.category.label(language), kind: .category)
                if filing.isCorrected {
                    TagView(text: language("정정됨", "Corrected"), kind: .corrected)
                }
                if Freshness.isNew(filing.filedOn, dataAsOf: dataAsOf) {
                    TagView(text: language("새 공시", "New"), kind: .new)
                }
                Text(words: Copy.filedOn(filing.filedOn, language))
                    .font(.footnote)
                    .monospacedDigit()
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(words: Titles.title(for: filing, language: language))
                .font(.title.bold())
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if filing.isCorrected {
                Text(words: PageCopy.corrected(language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .listRowBackground(Color.clear)
        .listRowInsets(EdgeInsets(top: 4, leading: 4, bottom: 4, trailing: 4))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
        .accessibilityAddTraits(.isHeader)
    }

    private var spoken: String {
        var parts = [FilingRow.spoken(filing, dataAsOf: dataAsOf, companyName: nil, language)]
        if filing.isCorrected { parts.append(PageCopy.corrected(language)) }
        return parts.joined(separator: ", ")
    }
}

/// Board 19, summary_in_review.
struct InReviewRow: View {
    @Environment(\.language) private var language

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: PageCopy.inReviewTitle(language))
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: PageCopy.inReviewBody(language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .combine)
    }
}

/// Approved sentences, one per line, in a Surface card.
struct SentenceRows: View {
    let lines: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                Text(words: line)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(Theme.surface)
    }
}

/// A Tint note inside a list: the outlook banner, the annual one line.
struct TintNote: View {
    let text: String
    var emphasized = false

    var body: some View {
        Text(words: text)
            .font(emphasized ? .body.weight(.semibold) : .subheadline)
            .foregroundStyle(Theme.ink)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowBackground(Theme.tint)
    }
}

/// A label and value row: the value on the right while label and value fit on one line,
/// else under the label, so a long label wraps instead of squeezing the value. Any
/// `details` lines go under the value; any `exact` lines appear under the row on a tap.
struct FactRow: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let label: String
    let value: String
    var details: [String] = []
    var tag: String?
    /// What VoiceOver reads; the visible text when nil.
    var spoken: String?
    /// The exact values behind a shortened amount, shown when the row is tapped.
    var exact: [String] = []
    /// VoiceOver spells the value character by character (receipt and accession numbers).
    var spellsOutValue = false
    @State private var showsExact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if typeSize.isAccessibilitySize {
                stacked
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        labelText
                        Spacer(minLength: 12)
                        valueColumn.fixedSize()
                    }
                    stacked
                }
            }
            if showsExact {
                ForEach(Array(exact.enumerated()), id: \.offset) { _, line in
                    UnbrokenNumbers(text: line)
                        .font(.footnote)
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(.vertical, 2)
        .frame(minHeight: Theme.minTarget)
        .contentShape(Rectangle())
        .onTapGesture { if !exact.isEmpty { showsExact.toggle() } }
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: Text {
        if let spoken { return Text(spoken) }
        let rest = (tag.map { [$0] } ?? []) + details
        let valueText = spellsOutValue ? Text(value).speechSpellsOutCharacters() : Text(value)
        return rest.reduce(Text(label + ", ") + valueText) { $0 + Text(", " + $1) }
    }

    private var valueColumn: some View {
        VStack(alignment: .trailing, spacing: 2) {
            valueLine.multilineTextAlignment(.trailing)
            detailLines(.trailing)
        }
    }

    private var stacked: some View {
        VStack(alignment: .leading, spacing: 2) {
            labelText
            valueLine
            detailLines(.leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var labelText: some View {
        Text(words: label)
            .font(.body)
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func detailLines(_ alignment: TextAlignment) -> some View {
        ForEach(Array(details.enumerated()), id: \.offset) { _, line in
            Text(words: line)
                .font(.footnote)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(alignment)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var valueLine: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            // Amounts and receipt numbers wrap at spaces only, never inside a number.
            UnbrokenNumbers(text: value)
                .font(.body.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
            if let tag { TagView(text: tag, kind: .corrected) }
        }
    }
}

/// A section header: Muted, which the accessibility audit measures above the contrast
/// threshold on Background, where the system's header grey only nearly passed; Korean wraps
/// between words.
struct SectionTitle: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(words: text).foregroundStyle(Theme.muted)
    }
}

/// A section footer in the muted footnote style.
struct SectionNote: View {
    let text: String

    var body: some View {
        Text(words: text)
            .font(.footnote)
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// The original document: what the bundle knows offline (form, filed date, receipt number),
/// then the Pine button that opens it (board 12A), with the network note under it.
struct SourceSection: View {
    @Environment(\.openURL) private var openURL
    @Environment(\.language) private var language
    let source: SourceDetails

    var body: some View {
        Section {
            FactRow(label: PageCopy.form(language), value: source.form)
            FactRow(label: PageCopy.filed(language), value: Formatting.fullDate(source.filedOn, language: language))
            FactRow(label: PageCopy.receiptNumber(source.regulator, language), value: source.receiptNumber,
                    spellsOutValue: true)
        } header: {
            SectionTitle(PageCopy.original(language))
        }
        if let url = source.url {
            Section {
                VStack(spacing: 8) {
                    Button {
                        openURL(url)
                    } label: {
                        HStack(spacing: 8) {
                            Text(words: Copy.openOriginal(source.regulator, language))
                                .multilineTextAlignment(.center)
                                .fixedSize(horizontal: false, vertical: true)
                            Image(systemName: "arrow.up.right")
                                .accessibilityHidden(true)
                        }
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Theme.onPine)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(Theme.pine, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(.isLink)
                    .accessibilityHint(language("인터넷 연결이 필요해요", "Needs an internet connection"))
                    .accessibilityIdentifier("open-original")
                    Text(words: language("인터넷 연결이 필요해요", "Needs an internet connection"))
                        .font(.footnote)
                        .foregroundStyle(Theme.muted)
                        .accessibilityHidden(true)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
            }
        }
    }
}

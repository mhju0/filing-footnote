import FootnoteKit
import SwiftUI

/// 소식 / News: the filings the company pages list, across every company, newest first and
/// grouped by day (`NewsFeed`, D86). Rows are the company page's (tag, title, no preview line)
/// with the company's name in place of the date the heading already gives.
struct NewsView: View {
    @Environment(\.language) private var language
    @Environment(\.filingSelection) private var selection
    let store: BundleStore

    private var feed: NewsFeed { store.newsFeed }

    var body: some View {
        ScrollViewReader { proxy in
            SelectionList(selection: selection) {
                Text(words: Copy.dataDate(store.meta.dataAsOf, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
                if feed.isEmpty {
                    Section {
                        Text(words: Copy.endNote(listed: 0, capped: false, language))
                            .font(.body)
                            .foregroundStyle(Theme.muted)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(minHeight: Theme.minTarget, alignment: .leading)
                            .listRowBackground(Theme.surface)
                            .accessibilityIdentifier("news-empty")
                    }
                }
                ForEach(feed.days) { day in
                    Section {
                        ForEach(day.filings) { filing in
                            FilingRowLink(filingID: filing.id) {
                                FilingRow(
                                    filing: filing, dataAsOf: feed.dataAsOf,
                                    companyName: store.company(id: filing.companyID)
                                        .map { Titles.name(of: $0, language: language) },
                                    showsDate: false)
                            }
                        }
                    } header: {
                        Text(words: dayTitle(day.date))
                            .accessibilityAddTraits(.isHeader)
                    }
                }
                if !feed.isEmpty {
                    Section {
                    } footer: {
                        SectionNote(text: Copy.newsEndNote(
                            listed: feed.filings.count, capped: feed.isCapped, language))
                    }
                }
            }
            .task { await scrollToSelection(selection?.wrappedValue, proxy) }
        }
        .groupedScreen()
        .navigationTitle(language("소식", "News"))
        .languageToolbar()
        .accessibilityIdentifier("news-page")
    }

    /// `11월 17일`; the year is added for a day in an earlier year than the data date.
    private func dayTitle(_ date: CivilDate) -> String {
        date.year == feed.dataAsOf.year
            ? Formatting.monthDay(date, language: language)
            : Formatting.fullDate(date, language: language)
    }
}

/// 용어 / Glossary: each term in plain words, the formal term kept nearby, in dictionary
/// order. The tab exists only while the bundle holds glossary rows. On iPhone (and when
/// pushed from a figure or filing) every entry shows in full and `focus` marks the one the
/// reader came for; in the split view the list names the terms and the detail column shows
/// the chosen one.
struct GlossaryView: View {
    @Environment(\.language) private var language
    @Environment(\.glossarySelection) private var selection
    let store: BundleStore
    var focus: String?

    var body: some View {
        ScrollViewReader { proxy in
            SelectionList(selection: selection) {
                ForEach(store.sortedGlossary(language: language)) { entry in
                    if let selection {
                        SelectableRow(
                            value: entry.termKey, selection: selection, route: .glossary(entry.termKey),
                            identifier: "glossary-\(entry.termKey)"
                        ) {
                            GlossaryTermRow(entry: entry)
                        }
                    } else {
                        GlossaryEntryRow(entry: entry, isFocused: entry.termKey == focus)
                            .id(entry.termKey)
                            .accessibilityIdentifier("glossary-\(entry.termKey)")
                    }
                }
            }
            .task(id: focus) {
                guard let focus else { return }
                // Let the list lay out first, then bring the entry to the top.
                try? await Task.sleep(for: .milliseconds(300))
                proxy.scrollTo(focus, anchor: .top)
            }
            // The split view can open with a term already chosen (a launch route); bring it
            // into view once. Later choices are rows the reader can already see.
            .task { if focus == nil { await scrollToSelection(selection?.wrappedValue, proxy) } }
        }
        .groupedScreen()
        .navigationTitle(language("용어", "Glossary"))
        .languageToolbar()
        .accessibilityIdentifier("glossary-page")
    }
}

/// Scrolls a list to the row chosen before it appeared, after it has laid out.
@MainActor private func scrollToSelection(_ id: String?, _ proxy: ScrollViewProxy) async {
    guard let id else { return }
    try? await Task.sleep(for: .milliseconds(300))
    proxy.scrollTo(id, anchor: .center)
}

/// One entry in full: the plain word, what it means, then the formal term.
struct GlossaryEntryRow: View {
    @Environment(\.language) private var language
    let entry: GlossaryEntry
    var isFocused = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: entry.term)
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: entry.plain)
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let formal = entry.formal {
                Text(words: PageCopy.formalTerm(formal, language))
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Tint marks the selected row (DESIGN.md): here, the entry the link opened.
        .listRowBackground(isFocused ? Theme.tint : Theme.surface)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isFocused ? .isSelected : [])
    }
}

/// A term in the split view's list: the plain word, with the formal term under it.
private struct GlossaryTermRow: View {
    let entry: GlossaryEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(words: entry.term)
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let formal = entry.formal {
                Text(words: formal)
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .frame(minHeight: Theme.minTarget)
        .accessibilityElement(children: .combine)
    }
}

/// The split view's detail column for one term.
struct GlossaryDetailView: View {
    @Environment(\.language) private var language
    let entry: GlossaryEntry

    var body: some View {
        List {
            Text(words: entry.term)
                .font(.title.bold())
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
                .headerRow()
                .accessibilityAddTraits(.isHeader)
            Section {
                Text(words: entry.plain)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 4)
                    .listRowBackground(Theme.surface)
                if let formal = entry.formal {
                    Text(words: PageCopy.formalTerm(formal, language))
                        .font(.subheadline)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.vertical, 4)
                        .listRowBackground(Theme.surface)
                }
            }
        }
        .groupedScreen()
        .screenTitle(entry.term)
        .accessibilityIdentifier("glossary-detail")
    }
}

/// The filing and annual pages' link to the glossary entry for their category (board 20:
/// "Glossary for a tagged term"). Hidden when the bundle has no entry for it.
struct GlossaryLinkSection: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    let store: BundleStore
    let category: FilingCategory

    var body: some View {
        let key = Glossary.key(for: category)
        if let entry = store.glossaryEntry(termKey: key, language: language) {
            Section {
                LinkRow(title: Copy.glossaryLink(entry.term, language)) { navigate(.glossary(key)) }
                    .accessibilityIdentifier("glossary-link")
            }
        }
    }
}

/// Shown instead of the app when the bundled data file cannot be used. Plain on purpose:
/// it only happens to a broken build.
struct BundleErrorView: View {
    @Environment(\.language) private var language
    let error: BundleError

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle)
                .foregroundStyle(Theme.ink)
                .accessibilityHidden(true)
            Text(words: language("데이터 파일을 열 수 없어요", "The data file can’t be opened"))
                .font(.title2.bold())
                .foregroundStyle(Theme.ink)
            Text(words: message)
                .font(.body)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(24)
        .frame(maxWidth: 520, maxHeight: .infinity, alignment: .center)
        .frame(maxWidth: .infinity)
        .background(Theme.background)
    }

    private var message: String {
        switch error {
        case .developmentBundle:
            language(
                "이 빌드에는 개발용 데이터 파일이 들어 있어요. 출시용 빌드는 승인된 요약만 담은 데이터 파일이 필요해요.",
                "This build holds a development data file. A release build needs a data file with approved summaries only.")
        case .unsupportedSchemaVersion(let found, let supported):
            language(
                "데이터 파일 형식 \(found)은 이 앱이 읽는 형식 \(supported)과 달라요.",
                "The data file has format \(found); this app reads format \(supported).")
        case .cannotOpen(_, let message), .sqlite(let message):
            language("파일을 읽지 못했어요: \(message)", "The file could not be read: \(message)")
        case .missingBuildMeta, .invalidValue:
            language("데이터 파일의 내용이 형식에 맞지 않아요.", "The data file’s contents do not match its format.")
        }
    }
}

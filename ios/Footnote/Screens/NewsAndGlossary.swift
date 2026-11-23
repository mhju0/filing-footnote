import FootnoteKit
import SwiftUI

/// 소식 / News: the filings the company pages list, across every company, newest first and
/// grouped by day (`NewsFeed`, D86). Rows are the company page's (tag, title, no preview line)
/// with the company's name in place of the date the heading already gives.
struct NewsView: View {
    @Environment(\.language) private var language
    @Environment(\.filingSelection) private var selection
    @State private var category: FilingCategory?
    let store: BundleStore

    var body: some View {
        let unfiltered = store.newsFeed
        let feed = category.map { unfiltered.filtered(to: $0) } ?? unfiltered
        ScrollViewReader { proxy in
            SelectionList(selection: selection) {
                Text(words: Copy.dataDate(store.meta.dataAsOf, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
                    .id("news-top")
                if !unfiltered.isEmpty {
                    typeFilter(unfiltered.availableCategories)
                }
                if feed.isEmpty {
                    Section {
                        Text(words: emptyMessage)
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
                        SectionTitle(dayTitle(day.date, dataAsOf: feed.dataAsOf))
                            .accessibilityAddTraits(.isHeader)
                    }
                }
                if !feed.isEmpty {
                    Section {
                    } footer: {
                        SectionNote(text: endNote(for: feed))
                    }
                }
            }
            .task { await scrollToSelection(selection?.wrappedValue, proxy) }
            .onChange(of: category) {
                if let selection, let selected = selection.wrappedValue,
                   !feed.filings.contains(where: { $0.id == selected }) {
                    selection.wrappedValue = nil
                }
                proxy.scrollTo("news-top", anchor: .top)
            }
        }
        .groupedScreen()
        .navigationTitle(language("소식", "News"))
        .languageToolbar()
        .accessibilityIdentifier("news-page")
    }

    /// `11월 17일`; the year is added for a day in an earlier year than the data date.
    private func dayTitle(_ date: CivilDate, dataAsOf: CivilDate) -> String {
        date.year == dataAsOf.year
            ? Formatting.monthDay(date, language: language)
            : Formatting.fullDate(date, language: language)
    }

    private func typeFilter(_ available: [FilingCategory]) -> some View {
        let label = language("공시 유형", "Filing type")
        let all = language("전체 공시", "All filings")
        let selected = category?.label(language) ?? all
        return Menu {
            Picker(label, selection: $category) {
                Text(words: all).tag(nil as FilingCategory?)
                ForEach(available, id: \.self) { type in
                    Text(words: type.label(language)).tag(Optional(type))
                }
            }
            .pickerStyle(.inline)
        } label: {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) {
                    Text(words: label).foregroundStyle(Theme.ink).fixedSize()
                    Spacer()
                    filterValue(selected).fixedSize()
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(words: label).foregroundStyle(Theme.ink)
                    filterValue(selected)
                }
            }
            .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
            .padding(.vertical, 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Theme.surface)
        .accessibilityLabel(label)
        .accessibilityValue(selected)
        .accessibilityIdentifier("news-type")
    }

    private func filterValue(_ value: String) -> some View {
        HStack(spacing: 6) {
            Text(words: value).fixedSize(horizontal: false, vertical: true)
            Image(systemName: "chevron.down")
                .font(.caption.weight(.semibold))
                .accessibilityHidden(true)
        }
        .foregroundStyle(Theme.pine)
    }

    private var emptyMessage: String {
        guard category != nil else {
            return Copy.endNote(listed: 0, capped: false, language)
        }
        return language("이 유형의 최근 공시가 없어요.", "No recent filings of this type.")
    }

    private func endNote(for feed: NewsFeed) -> String {
        let count = feed.filings.count
        guard category != nil else {
            return Copy.newsEndNote(listed: count, capped: feed.isCapped, language)
        }
        return feed.isCapped
            ? language("이 유형의 공시 중 가장 최근 \(count)건이에요.", "Showing the \(count) newest matches.")
            : language("기업별 최근 공시 중 이 유형에 해당하는 \(count)건이에요.",
                       "Showing all \(count) matches from the companies’ recent filings.")
    }
}

/// Browse initials or search for a term in either language.
/// Definitions open inline on iPhone and in the detail column on iPad and Mac.
struct GlossaryView: View {
    @Environment(\.language) private var language
    @Environment(\.glossarySelection) private var selection
    @State private var query = ""
    @State private var expanded: Set<String>
    let store: BundleStore
    let focus: String?

    init(store: BundleStore, focus: String? = nil) {
        self.store = store
        self.focus = focus
        _expanded = State(initialValue: Set([focus].compactMap { $0 }))
    }

    private var isSearching: Bool {
        !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var sections: [(initial: String, entries: [GlossaryEntry])] {
        var initials = [String]()
        var seen = Set<String>()
        let groups = Dictionary(grouping: store.sortedGlossary(language: language, matching: query)) { entry in
            let initial = Self.initial(of: entry.term)
            if seen.insert(initial).inserted { initials.append(initial) }
            return initial
        }
        return initials.compactMap { initial in
            groups[initial].map { (initial, $0) }
        }
    }

    var body: some View {
        ScrollViewReader { proxy in
            let sections = sections
            SelectionList(selection: selection) {
                DirectorySearchField(
                    title: language("용어 검색", "Search terms"),
                    prompt: language("용어 또는 약어", "Term or abbreviation"),
                    identifier: "glossary-search", query: $query)
                    .headerRow()
                if sections.isEmpty {
                    Text(words: language("검색 결과가 없어요. 더 짧은 용어로 검색해 보세요.",
                                         "No matching terms. Try a shorter search."))
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .headerRow()
                        .accessibilityIdentifier("glossary-empty")
                }
                ForEach(sections, id: \.initial) { group in
                    let section = Section {
                        ForEach(group.entries) { entry in
                            if let selection {
                                SelectableRow(
                                    value: entry.termKey, selection: selection, route: .glossary(entry.termKey),
                                    identifier: "glossary-\(entry.termKey)"
                                ) {
                                    GlossaryTermRow(entry: entry)
                                }
                            } else {
                                GlossaryEntryRow(
                                    entry: entry, isFocused: entry.termKey == focus,
                                    isExpanded: expanded.contains(entry.termKey)
                                ) {
                                    if expanded.remove(entry.termKey) == nil {
                                        expanded.insert(entry.termKey)
                                    }
                                }
                                .id(entry.termKey)
                            }
                        }
                    } header: {
                        SectionTitle(group.initial)
                            .accessibilityAddTraits(.isHeader)
                    }
                    #if os(iOS)
                    if #available(iOS 26.0, *) {
                        section.sectionIndexLabel(isSearching ? nil : group.initial)
                    } else {
                        section
                    }
                    #else
                    section
                    #endif
                }
            }
            .toolbar {
                if usesJumpMenu, !isSearching, sections.count > 1 {
                    ToolbarItem {
                        Menu {
                            ForEach(sections, id: \.initial) { group in
                                if let first = group.entries.first {
                                    Button(group.initial) { proxy.scrollTo(first.termKey, anchor: .top) }
                                }
                            }
                        } label: {
                            Label(language("초성으로 이동", "Jump to letter"), systemImage: "textformat.abc")
                        }
                        .accessibilityIdentifier("glossary-index")
                    }
                }
            }
            .task(id: focus) {
                guard let focus else { return }
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled else { return }
                proxy.scrollTo(focus, anchor: .top)
            }
            .task { if focus == nil { await scrollToSelection(selection?.wrappedValue, proxy) } }
        }
        .groupedScreen()
        .navigationTitle(language("용어", "Glossary"))
        .languageToolbar()
        .accessibilityIdentifier("glossary-page")
    }

    private var usesJumpMenu: Bool {
        #if os(iOS)
        if #available(iOS 26.0, *) { return false }
        #endif
        return true
    }

    static func initial(of term: String) -> String {
        guard let first = term.first else { return "#" }
        let consonants = Array("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
        if let scalar = String(first).precomposedStringWithCanonicalMapping.unicodeScalars.first,
           (0xAC00...0xD7A3).contains(scalar.value) {
            return String(consonants[Int((scalar.value - 0xAC00) / 588)])
        }
        if consonants.contains(first) { return String(first) }
        let latin = String(first).folding(options: [.diacriticInsensitive, .widthInsensitive], locale: nil)
            .uppercased()
        return latin.count == 1 && "ABCDEFGHIJKLMNOPQRSTUVWXYZ".contains(latin) ? latin : "#"
    }
}

/// Scrolls a list to the row chosen before it appeared, after it has laid out.
@MainActor private func scrollToSelection(_ id: String?, _ proxy: ScrollViewProxy) async {
    guard let id else { return }
    try? await Task.sleep(for: .milliseconds(300))
    proxy.scrollTo(id, anchor: .center)
}

private struct GlossaryEntryRow: View {
    @Environment(\.language) private var language
    let entry: GlossaryEntry
    let isFocused: Bool
    let isExpanded: Bool
    let toggle: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: toggle) {
                HStack(spacing: 12) {
                    GlossaryTermRow(entry: entry)
                    Spacer(minLength: 4)
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.pine)
                        .accessibilityHidden(true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(isExpanded ? language("펼쳐짐", "Expanded") : language("접힘", "Collapsed"))
            .accessibilityAddTraits(isFocused ? .isSelected : [])
            .accessibilityIdentifier("glossary-\(entry.termKey)")
            if isExpanded {
                VStack(alignment: .leading, spacing: 4) {
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
                .padding(.bottom, 8)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("glossary-definition-\(entry.termKey)")
            }
        }
        .listRowBackground(isFocused ? Theme.tint : Theme.surface)
    }
}

private struct GlossaryTermRow: View {
    let entry: GlossaryEntry

    var body: some View {
        Text(words: entry.term)
            .font(.body.weight(.semibold))
            .foregroundStyle(Theme.ink)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 4)
            .frame(minHeight: Theme.minTarget, alignment: .leading)
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

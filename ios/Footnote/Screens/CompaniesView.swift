import FootnoteKit
import SwiftUI

struct CompaniesView: View {
    @Environment(\.language) private var language
    @State private var market: Regulator = .dart
    @State private var sort: CompanySort = .latest
    @State private var query = ""
    let store: BundleStore

    var body: some View {
        List {
            // What the app does and the data date, before any control (2026-11-26 review,
            // issue 7).
            Text(words: Copy.appIntro(store.meta.dataAsOf, language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
                .headerRow()
                .listRowSeparator(.hidden)
                .accessibilityIdentifier("app-intro")
            CompanyDirectory(store: store, query: $query, market: $market, sort: $sort, showsDataFooter: true) { company in
                NavigationLink(value: Route.company(company.id)) {
                    CompanyRow(company: company, latest: store.latestFiling(companyID: company.id))
                }
                .listRowBackground(Theme.surface)
                .accessibilityIdentifier("company-\(company.id)")
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .groupedScreen()
        .navigationTitle(language("기업", "Companies"))
        .companySearch($query, placement: phoneSearchPlacement)
        .toolbar {
            if !CompanySearch(query).isActive {
                #if os(iOS)
                ToolbarItem(placement: .topBarLeading) { CompanySortMenu(sort: $sort) }
                #else
                ToolbarItem { CompanySortMenu(sort: $sort) }
                #endif
            }
        }
        .languageToolbar()
    }

    private var phoneSearchPlacement: SearchFieldPlacement {
        #if os(iOS)
        .navigationBarDrawer(displayMode: .always)
        #else
        .automatic
        #endif
    }
}

extension View {
    /// The system search field for companies (owner pick 2026-11-26, design direction 4 B):
    /// Cancel, keyboard return and the Mac find shortcut come from the system. The prompt is
    /// the app's own copy, so it follows the in-app language, not the device's.
    fileprivate func companySearch(_ query: Binding<String>, placement: SearchFieldPlacement) -> some View {
        modifier(CompanySearchField(query: query, placement: placement))
    }
}

private struct CompanySearchField: ViewModifier {
    @Environment(\.language) private var language
    @Binding var query: String
    let placement: SearchFieldPlacement

    func body(content: Content) -> some View {
        content.searchable(
            text: $query, placement: placement,
            prompt: Text(verbatim: language("기업명 또는 종목 코드", "Company name or ticker")))
    }
}

private struct CompanyDirectory<Row: View>: View {
    @Environment(\.language) private var language
    let store: BundleStore
    @Binding var query: String
    @Binding var market: Regulator
    @Binding var sort: CompanySort
    var showsDataFooter = false
    @ViewBuilder let row: (Company) -> Row

    var body: some View {
        let search = CompanySearch(query)
        let companies = search.isActive
            ? search.companies(in: store, language: language)
            : sort.companies(in: market, store: store, language: language)

        // The search field is the system one (`companySearch`); sort is a toolbar menu
        // (2026-11-26 review, issue 7).
        if !search.isActive {
            CompanyMarketPicker(market: $market)
                .padding(.bottom, 8)
                .headerRow()
                .listRowSeparator(.hidden)
            if sort == .marketCap {
                MarketCapNote()
                    .headerRow()
                    .listRowSeparator(.hidden)
            }
        }

        Section {
            if search.isActive && companies.isEmpty {
                ContentUnavailableView {
                    Label(language("찾는 기업이 없어요", "No matching companies"), systemImage: "magnifyingglass")
                } description: {
                    Text(words: language("다른 기업명이나 종목 코드로 검색해 보세요.", "Try another company name or ticker."))
                }
                .listRowBackground(Theme.surface)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("company-search-empty")
            }
            ForEach(companies, content: row)
        } header: {
            if search.isActive {
                SectionTitle(language("한국·미국 전체", "Across both markets"))
            }
        } footer: {
            if showsDataFooter {
                DataFooter(meta: store.meta)
            }
        }
    }
}

private struct CompanySearch {
    private let query: String

    init(_ query: String) {
        self.query = Self.normalized(query)
    }

    var isActive: Bool { !query.isEmpty }

    func companies(in store: BundleStore, language: Language) -> [Company] {
        store.companies.filter { company in
            [company.nameKo, Titles.name(of: company, language: .en), company.nameEn, company.ticker]
                .contains { Self.normalized($0).contains(query) }
        }
        .sorted { CompanySort.namePrecedes($0, $1, language: language) }
    }

    private static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: nil)
            .filter { !$0.isWhitespace && $0 != "." && $0 != "-" }
    }
}

struct DirectorySearchField: View {
    @Environment(\.language) private var language
    @FocusState private var focused: Bool
    let title: String
    let prompt: String
    let identifier: String
    @Binding var query: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(words: title)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .accessibilityHidden(true)
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Theme.muted)
                    .accessibilityHidden(true)
                TextField(title, text: $query, prompt: Text(words: prompt).foregroundStyle(Theme.muted))
                    .textFieldStyle(.plain)
                    .foregroundStyle(Theme.ink)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($focused)
                    .submitLabel(.search)
                    .onSubmit { focused = false }
                    .accessibilityIdentifier(identifier)
                    .padding(.vertical, 8)
                    .frame(minHeight: Theme.minTarget)
                if !query.isEmpty {
                    Button {
                        query = ""
                        focused = false
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(Theme.muted)
                            .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(language("검색어 지우기", "Clear search"))
                    .accessibilityIdentifier("\(identifier)-clear")
                }
            }
            .padding(.leading, 12)
            .padding(.trailing, query.isEmpty ? 12 : 0)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(focused ? Theme.pine : Theme.line, lineWidth: focused ? 2 : 1)
                    .allowsHitTesting(false)
            }
        }
    }
}

enum CompanySort: CaseIterable {
    case latest, name, marketCap

    func title(_ language: Language) -> String {
        switch self {
        case .latest: language("최근 공시순", "Latest filing")
        case .name: language("이름순", "Company name")
        case .marketCap: language("시가총액순", "Market cap")
        }
    }

    func companies(in market: Regulator, store: BundleStore, language: Language) -> [Company] {
        let companies = store.companies.filter { $0.regulator == market }
        // The same date the row shows under the name.
        let dates = self == .latest
            ? Dictionary(uniqueKeysWithValues: companies.compactMap { company in
                store.latestFiling(companyID: company.id).map { (company.id, $0.filedOn) }
            })
            : [:]
        return companies.sorted { lhs, rhs in
            switch self {
            case .latest:
                switch (dates[lhs.id], dates[rhs.id]) {
                case (let left?, let right?) where left != right: return left > right
                case (_?, nil): return true
                case (nil, _?): return false
                default: break
                }
            case .marketCap:
                let a = MarketCapSnapshot.position(lhs)
                let b = MarketCapSnapshot.position(rhs)
                if a != b { return a < b }
            case .name:
                break
            }
            return Self.namePrecedes(lhs, rhs, language: language)
        }
    }

    fileprivate static func namePrecedes(_ lhs: Company, _ rhs: Company, language: Language) -> Bool {
        let a = Titles.name(of: lhs, language: language)
        let b = Titles.name(of: rhs, language: language)
        return switch a.compare(b, options: [.caseInsensitive], locale: language.locale) {
        case .orderedAscending: true
        case .orderedDescending: false
        case .orderedSame: lhs.id < rhs.id
        }
    }
}

private struct CompanyMarketPicker: View {
    @Environment(\.language) private var language
    @Binding var market: Regulator

    var body: some View {
        Picker(language("시장", "Market"), selection: $market) {
            Text(language("한국", "Korea")).tag(Regulator.dart)
            Text(language("미국", "US")).tag(Regulator.sec)
        }
        .pickerStyle(.segmented)
        .frame(minHeight: Theme.minTarget)
        .accessibilityIdentifier("company-market")
    }
}

/// The sort as a toolbar menu showing the current order (2026-11-26 review, issues 5 and 7):
/// a native toolbar control, so it reads in light and dark and in an inactive Mac window.
private struct CompanySortMenu: View {
    @Environment(\.language) private var language
    @Binding var sort: CompanySort

    var body: some View {
        Menu {
            Picker(language("정렬", "Sort by"), selection: $sort) {
                ForEach(CompanySort.allCases, id: \.self) { option in
                    Text(option.title(language)).tag(option)
                }
            }
            .pickerStyle(.inline)
        } label: {
            // An HStack, not a Label: the iOS toolbar reduces a Label to its icon, and the
            // current order should stay visible (DESIGN.md, Companies list).
            HStack(spacing: 4) {
                Image(systemName: "arrow.up.arrow.down")
                    .accessibilityHidden(true)
                Text(words: sort.title(language))
            }
            .fixedSize()
            #if os(iOS)
            .padding(.horizontal, 6)
            .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
            .contentShape(Rectangle())
            #endif
        }
        #if os(iOS)
        .accessibilityShowsLargeContentViewer {
            Image(systemName: "arrow.up.arrow.down")
            Text(verbatim: language("정렬", "Sort by") + ": " + sort.title(language))
        }
        #endif
        .accessibilityLabel(language("정렬", "Sort by"))
        .accessibilityValue(sort.title(language))
        .accessibilityIdentifier("company-sort")
    }
}

/// Dated rank order from ADR 0009. Only the order is bundled.
enum MarketCapSnapshot {
    static let date = CivilDate(iso: "2026-11-20")!
    private static let korea = ["005930", "000660", "207940", "005380", "000270", "006400", "035420", "066570", "051910"]
    private static let us = ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA", "WMT", "COST"]

    static func position(_ company: Company) -> Int {
        (company.regulator == .dart ? korea : us).firstIndex(of: company.ticker) ?? Int.max
    }
}

private struct MarketCapNote: View {
    @Environment(\.language) private var language

    var body: some View {
        let date = Formatting.fullDate(MarketCapSnapshot.date, language: language)
        SectionNote(text: language("시가총액 순위 기준일 \(date)", "Market cap ranking as of \(date)"))
    }
}

/// The data date and, for a preview bundle, a second line saying summaries are left out.
struct DataFooter: View {
    @Environment(\.language) private var language
    let meta: BuildMeta

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: Copy.dataFooter(meta.dataAsOf, language))
                .accessibilityIdentifier("data-footer")
            if meta.preview {
                Text(words: Copy.previewNote(language))
                    .accessibilityIdentifier("preview-note")
            }
        }
        .font(.footnote)
        .foregroundStyle(Theme.muted)
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A company: its name, then its newest filing's date and type (2026-11-26 review, issue 2).
/// The name wraps only between words; a one-word name wider than the row shrinks instead
/// (issue 4).
struct CompanyRow: View {
    @Environment(\.language) private var language
    let company: Company
    let latest: LatestFiling?
    var isSelected = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            UnbrokenWords(text: Titles.name(of: company, language: language))
                .font(.body)
                .foregroundStyle(onFill ? AnyShapeStyle(.primary) : AnyShapeStyle(Theme.ink))
            if let latest {
                Text(words: Copy.latestFiling(latest, language))
                    .font(.footnote)
                    .monospacedDigit()
                    .foregroundStyle(onFill ? AnyShapeStyle(.secondary) : AnyShapeStyle(Theme.muted))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
        #if os(iOS)
        .padding(.vertical, 6)
        #endif
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var onFill: Bool {
        #if os(iOS)
        isSelected
        #else
        false
        #endif
    }

    private var spoken: String {
        var parts = [Titles.name(of: company, language: language)]
        if let latest { parts.append(Copy.latestFilingSpoken(latest, language)) }
        return parts.joined(separator: ", ")
    }
}

/// The iPad and Mac sidebar: the news and glossary, then the companies by market.
struct SidebarView: View {
    enum Item: Hashable {
        case news
        case glossary
        case company(String)
    }

    @Environment(\.language) private var language
    let store: BundleStore
    @Binding var selection: Item?
    @State private var market: Regulator
    @State private var sort: CompanySort = .latest
    @State private var query = ""

    init(store: BundleStore, selection: Binding<Item?>) {
        self.store = store
        _selection = selection
        if case .company(let id) = selection.wrappedValue {
            _market = State(initialValue: store.company(id: id)?.regulator ?? .dart)
        } else {
            _market = State(initialValue: .dart)
        }
    }

    var body: some View {
        List(selection: $selection) {
            Section {
                Label(language("소식", "News"), systemImage: "newspaper")
                    .tag(Item.news)
                if !store.glossary(language: language).isEmpty {
                    Label(language("용어", "Glossary"), systemImage: "book")
                        .tag(Item.glossary)
                }
            }
            CompanyDirectory(store: store, query: $query, market: $market, sort: $sort) { company in
                CompanyRow(company: company, latest: store.latestFiling(companyID: company.id),
                           isSelected: selection == .company(company.id))
                    .accessibilityIdentifier("company-\(company.id)")
                    .tag(Item.company(company.id))
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .onChange(of: market) {
            if case .company(let id) = selection, store.company(id: id)?.regulator != market {
                selection = nil
            }
        }
        .navigationTitle(language("기업", "Companies"))
        .companySearch($query, placement: .sidebar)
        .toolbar {
            if !CompanySearch(query).isActive {
                ToolbarItem { CompanySortMenu(sort: $sort) }
            }
        }
        #if os(macOS)
        .navigationSplitViewColumnWidth(min: 280, ideal: 300)
        #endif
    }
}

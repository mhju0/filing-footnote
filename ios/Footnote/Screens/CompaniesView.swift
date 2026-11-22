import FootnoteKit
import SwiftUI

struct CompaniesView: View {
    @Environment(\.language) private var language
    @State private var market: Regulator = .dart
    @State private var sort: CompanySort = .latest
    let store: BundleStore

    var body: some View {
        List {
            CompanyMarketPicker(market: $market)
                .headerRow()
            if sort == .marketCap { MarketCapNote().headerRow() }
            Section {
                ForEach(sort.companies(in: market, store: store, language: language)) { company in
                    NavigationLink(value: Route.company(company.id)) {
                        CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id))
                    }
                    .listRowBackground(Theme.surface)
                    .accessibilityIdentifier("company-\(company.id)")
                }
            } footer: {
                DataFooter(meta: store.meta)
            }
        }
        .groupedScreen()
        .navigationTitle(language("기업", "Companies"))
        .toolbar { ToolbarItem { CompanySortMenu(sort: $sort) } }
        .languageToolbar()
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
        let dates = self == .latest
            ? Dictionary(store.filings.map { ($0.companyID, $0.filedOn) }
                         + store.notices.map { ($0.companyID, $0.filedOn) }, uniquingKeysWith: max)
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
            let a = Titles.name(of: lhs, language: language)
            let b = Titles.name(of: rhs, language: language)
            switch a.compare(b, options: [.caseInsensitive], locale: language.locale) {
            case .orderedAscending: return true
            case .orderedDescending: return false
            case .orderedSame: return lhs.id < rhs.id
            }
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

private struct CompanySortMenu: View {
    @Environment(\.language) private var language
    @Binding var sort: CompanySort

    var body: some View {
        Menu {
            Picker(language("정렬", "Sort"), selection: $sort) {
                ForEach(CompanySort.allCases, id: \.self) { option in
                    Text(option.title(language)).tag(option)
                }
            }
        } label: {
            Label(language("정렬", "Sort"), systemImage: "arrow.up.arrow.down")
        }
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

struct CompanyRow: View {
    @Environment(\.language) private var language
    let company: Company
    let isNew: Bool
    var isSelected = false

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                name.fixedSize()
                Spacer(minLength: 8)
                newTag
            }
            VStack(alignment: .leading, spacing: 4) {
                name.fixedSize(horizontal: false, vertical: true)
                newTag
            }
        }
        .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var name: some View {
        Text(words: Titles.name(of: company, language: language))
            .font(.body)
            .foregroundStyle(onFill ? AnyShapeStyle(.primary) : AnyShapeStyle(Theme.ink))
    }

    @ViewBuilder private var newTag: some View {
        if isNew {
            TagView(text: language("새 공시", "New"), kind: .new)
        }
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
        if isNew { parts.append(language("새 공시 있음", "has a new filing")) }
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
            CompanyMarketPicker(market: $market)
            if sort == .marketCap { MarketCapNote() }
            Section {
                ForEach(sort.companies(in: market, store: store, language: language)) { company in
                    CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id),
                               isSelected: selection == .company(company.id))
                        .accessibilityIdentifier("company-\(company.id)")
                        .tag(Item.company(company.id))
                }
            }
        }
        .onChange(of: market) {
            if case .company(let id) = selection, store.company(id: id)?.regulator != market {
                selection = nil
            }
        }
        .navigationTitle(language("기업", "Companies"))
        .toolbar { ToolbarItem { CompanySortMenu(sort: $sort) } }
        #if os(macOS)
        .navigationSplitViewColumnWidth(min: 280, ideal: 300)
        #endif
    }
}

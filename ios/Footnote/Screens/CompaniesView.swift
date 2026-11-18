import FootnoteKit
import SwiftUI

/// The companies list: one list by market (G1 pick 7A), name and ticker, and a 새 공시 tag.
/// Nothing else (DESIGN.md, Screens).
struct CompaniesView: View {
    @Environment(\.language) private var language
    let store: BundleStore

    var body: some View {
        List {
            ForEach(store.companiesByMarket(), id: \.market) { group in
                Section(Copy.market(group.companies[0].regulator, language)) {
                    ForEach(group.companies) { company in
                        NavigationLink(value: Route.company(company.id)) {
                            CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id))
                        }
                        .listRowBackground(Theme.surface)
                    }
                }
            }
        }
        .groupedScreen()
        .navigationTitle(language("기업", "Companies"))
        .languageToolbar()
    }
}

struct CompanyRow: View {
    @Environment(\.language) private var language
    let company: Company
    let isNew: Bool

    var body: some View {
        HStack(spacing: 8) {
            Text(words: Titles.name(of: company, language: language))
                .font(.body)
                .foregroundStyle(Theme.ink)
                .lineLimit(nil)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            if isNew {
                TagView(text: language("새 공시", "New"), kind: .new)
            }
            Text(words: company.ticker)
                .font(.body)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .fixedSize()
        }
        .frame(minHeight: Theme.minTarget)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var spoken: String {
        var parts = [Titles.name(of: company, language: language), company.ticker]
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
            ForEach(store.companiesByMarket(), id: \.market) { group in
                Section(Copy.market(group.companies[0].regulator, language)) {
                    ForEach(group.companies) { company in
                        CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id))
                            .tag(Item.company(company.id))
                    }
                }
            }
        }
        .navigationTitle(language("기업", "Companies"))
        #if os(macOS)
        .navigationSplitViewColumnWidth(min: 280, ideal: 300)
        #endif
    }
}

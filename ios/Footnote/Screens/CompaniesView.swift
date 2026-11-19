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
                Section {
                    ForEach(group.companies) { company in
                        NavigationLink(value: Route.company(company.id)) {
                            CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id))
                        }
                        .listRowBackground(Theme.surface)
                    }
                } header: {
                    SectionTitle(Copy.market(group.companies[0].regulator, language))
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
    /// True when the iPad sidebar has this row selected. The selection fill is Pine while the
    /// sidebar has focus and light grey while another column has it, so the name and ticker
    /// take the system's primary style, as the labels beside them do: light on Pine, dark on
    /// grey. Ink and Muted stayed dark on Pine. The Mac draws its own highlight and keeps them.
    var isSelected = false

    var body: some View {
        // Name and ticker on one line while the name fits whole; at large text sizes the
        // ticker moves under the name, so the name never breaks inside a word (`SK하/이닉/스`).
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                name.fixedSize()
                Spacer(minLength: 8)
                trailing
            }
            VStack(alignment: .leading, spacing: 2) {
                name.fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) { trailing }
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

    @ViewBuilder private var trailing: some View {
        if isNew {
            TagView(text: language("새 공시", "New"), kind: .new)
        }
        Text(words: company.ticker)
            .font(.body)
            .monospacedDigit()
            .foregroundStyle(onFill ? AnyShapeStyle(.primary) : AnyShapeStyle(Theme.muted))
            .fixedSize()
    }

    private var onFill: Bool {
        #if os(iOS)
        isSelected
        #else
        false
        #endif
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
                Section {
                    ForEach(group.companies) { company in
                        CompanyRow(company: company, isNew: store.hasNewFiling(companyID: company.id),
                                       isSelected: selection == .company(company.id))
                            .tag(Item.company(company.id))
                    }
                } header: {
                    SectionTitle(Copy.market(group.companies[0].regulator, language))
                }
            }
        }
        .navigationTitle(language("기업", "Companies"))
        #if os(macOS)
        .navigationSplitViewColumnWidth(min: 280, ideal: 300)
        #endif
    }
}

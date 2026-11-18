import FootnoteKit
import SwiftUI

struct RootView: View {
    let library: Library
    @AppStorage("language") private var stored = Language.ko.rawValue

    private var language: Language { Language(rawValue: stored) ?? .ko }

    var body: some View {
        Group {
            switch library {
            case .ready(let store, let labels):
                AppShell(store: store, labels: labels)
            case .failed(let error):
                BundleErrorView(error: error)
            }
        }
        .environment(\.language, language)
        .environment(\.locale, language.locale)
        .tint(Theme.pine)
        .opensLinksInApp()
    }
}

/// Tabs on iPhone; sidebar, content and detail columns on iPad and Mac (ADR 0008).
struct AppShell: View {
    let store: BundleStore
    let labels: FactLabels
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif

    var body: some View {
        #if os(iOS)
        if sizeClass == .compact {
            PhoneTabs(store: store, labels: labels)
        } else {
            SplitShell(store: store, labels: labels)
        }
        #else
        SplitShell(store: store, labels: labels)
        #endif
    }
}

/// Resolves a route to its screen; shared by every navigation stack.
struct RouteDestination: View {
    let store: BundleStore
    let labels: FactLabels
    let route: Route

    var body: some View {
        switch route {
        case .company(let id):
            if let page = CompanyPage(store: store, companyID: id) {
                CompanyPageView(store: store, page: page)
            }
        case .filing(let id):
            if let filing = store.filing(id: id) {
                FilingDetailView(store: store, labels: labels, filing: filing)
            }
        }
    }
}

struct PhoneTabs: View {
    enum TabID: Hashable { case companies, news, glossary }

    @Environment(\.language) private var language
    let store: BundleStore
    let labels: FactLabels
    @State private var tab: TabID = LaunchRoute.current?.tab ?? .companies
    @State private var companiesPath: [Route] = LaunchRoute.current?.companiesPath ?? []
    @State private var newsPath: [Route] = LaunchRoute.current?.newsPath ?? []

    var body: some View {
        TabView(selection: $tab) {
            Tab(language("기업", "Companies"), systemImage: "building.2", value: TabID.companies) {
                NavigationStack(path: $companiesPath) {
                    CompaniesView(store: store)
                        .navigationDestination(for: Route.self) {
                            RouteDestination(store: store, labels: labels, route: $0)
                        }
                }
            }
            Tab(language("소식", "News"), systemImage: "newspaper", value: TabID.news) {
                NavigationStack(path: $newsPath) {
                    NewsView(store: store)
                        .navigationDestination(for: Route.self) {
                            RouteDestination(store: store, labels: labels, route: $0)
                        }
                }
            }
            // The glossary tab appears once the bundle holds glossary rows (R-24: no tab
            // without a real destination).
            if !store.glossary.isEmpty {
                Tab(language("용어", "Glossary"), systemImage: "book", value: TabID.glossary) {
                    NavigationStack {
                        GlossaryView(store: store)
                    }
                }
            }
        }
    }
}

struct SplitShell: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let labels: FactLabels
    @State private var sidebar: SidebarView.Item?
    @State private var filingID: String?

    init(store: BundleStore, labels: FactLabels) {
        self.store = store
        self.labels = labels
        let launch = LaunchRoute.current
        _sidebar = State(initialValue: launch?.sidebarItem
            ?? store.companies.first.map { .company($0.id) })
        _filingID = State(initialValue: launch?.filingID)
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(store: store, selection: $sidebar)
        } content: {
            content
                .environment(\.filingSelection, $filingID)
                #if os(macOS)
                .navigationSplitViewColumnWidth(min: 360, ideal: 420)
                #endif
        } detail: {
            NavigationStack {
                if let filingID, let filing = store.filing(id: filingID) {
                    FilingDetailView(store: store, labels: labels, filing: filing)
                } else {
                    noFiling
                }
            }
            .environment(\.showsLanguageButton, false)
        }
        .onChange(of: sidebar) { filingID = nil }
    }

    @ViewBuilder private var content: some View {
        switch sidebar {
        case .company(let id):
            if let page = CompanyPage(store: store, companyID: id) {
                CompanyPageView(store: store, page: page)
                    .id(id)
            }
        case .news:
            NewsView(store: store)
        case .glossary:
            GlossaryView(store: store)
        case nil:
            Text(words: language("왼쪽에서 기업을 고르세요", "Choose a company on the left"))
                .foregroundStyle(Theme.muted)
        }
    }

    private var noFiling: some View {
        VStack(spacing: 8) {
            Image(systemName: "doc.text")
                .font(.largeTitle)
                .foregroundStyle(Theme.muted)
                .accessibilityHidden(true)
            Text(words: language("공시를 고르면 여기에 보여 줘요", "Choose a filing to see it here"))
                .font(.body)
                .foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.background)
    }
}

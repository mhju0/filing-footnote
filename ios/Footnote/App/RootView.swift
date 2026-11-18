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
    @Environment(\.language) private var language
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
            FilingDestination(store: store, labels: labels, filingID: id)
        case .figure(let companyID, let metric, let fiscalYear):
            if let metric = ReportedMetric(rawValue: metric),
               let page = FigurePage(store: store, companyID: companyID, metric: metric, fiscalYear: fiscalYear)
            {
                FigureView(store: store, page: page)
            }
        case .yearCompare(let companyID, let metric, let fiscalYear):
            if let page = YearComparePage(store: store, companyID: companyID, metric: metric, fiscalYear: fiscalYear) {
                YearCompareView(store: store, page: page)
            }
        case .yearCalculation(let companyID, let metric, let fiscalYear):
            if let page = YearComparePage(store: store, companyID: companyID, metric: metric, fiscalYear: fiscalYear),
               let calculation = page.calculation
            {
                CalculationView(
                    context: PageCopy.compareContext(
                        page.company, metric: calculation.metric.name(language), basis: page.basis, language),
                    calculations: [.growth(calculation)])
            }
        case .companyCompare(let compare):
            CompanyCompareView(store: store, route: compare)
        case .companyCalculation(let compare):
            if let page = CompanyComparePage(
                store: store, companyID: compare.companyID, peerID: compare.peerID, metric: compare.metric,
                measure: compare.measure, fiscalYear: compare.fiscalYear)
            {
                CalculationView(
                    context: PageCopy.companiesContext(page.companies, language)
                        + Copy.dot + PageCopy.ratesHeading(page.chosenMeasure, metric: page.reportedMetric, language),
                    calculations: page.calculations, difference: page.difference)
            }
        case .glossary:
            GlossaryView(store: store)
        }
    }
}

/// A filing's page: the annual report at a glance, or an event filing's page.
struct FilingDestination: View {
    let store: BundleStore
    let labels: FactLabels
    let filingID: String

    var body: some View {
        if let annual = AnnualPage(store: store, filingID: filingID) {
            AnnualReportView(page: annual)
        } else if let page = FilingPage(store: store, filingID: filingID) {
            FilingPageView(page: page, labels: labels)
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
                .environment(\.navigate, NavigateAction { companiesPath.append($0) })
            }
            Tab(language("소식", "News"), systemImage: "newspaper", value: TabID.news) {
                NavigationStack(path: $newsPath) {
                    NewsView(store: store)
                        .navigationDestination(for: Route.self) {
                            RouteDestination(store: store, labels: labels, route: $0)
                        }
                }
                .environment(\.navigate, NavigateAction { newsPath.append($0) })
            }
            // The glossary tab appears once the bundle holds glossary rows in the current
            // language (R-24: no tab without a real destination).
            if !store.glossary(language: language).isEmpty {
                Tab(language("용어", "Glossary"), systemImage: "book", value: TabID.glossary) {
                    NavigationStack {
                        GlossaryView(store: store)
                    }
                }
            }
        }
        .onChange(of: language) {
            if tab == .glossary && store.glossary(language: language).isEmpty { tab = .companies }
        }
    }
}

struct SplitShell: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let labels: FactLabels
    @State private var sidebar: SidebarView.Item?
    @State private var filingID: String?
    /// The screens pushed over the filing in the detail column: figure, compare, calculation.
    @State private var detailPath: [Route]

    init(store: BundleStore, labels: FactLabels) {
        self.store = store
        self.labels = labels
        let launch = LaunchRoute.current
        _sidebar = State(initialValue: launch?.sidebarItem
            ?? store.companies.first.map { .company($0.id) })
        _filingID = State(initialValue: launch?.filingID ?? launch?.figureFilingID(store))
        _detailPath = State(initialValue: launch?.detailPath ?? [])
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(store: store, selection: $sidebar)
        } content: {
            content
                .environment(\.filingSelection, $filingID)
                // Wide enough for a company's large title on iPad ("Samsung Electronics").
                .navigationSplitViewColumnWidth(min: 360, ideal: 420)
        } detail: {
            NavigationStack(path: $detailPath) {
                Group {
                    if let filingID, store.filing(id: filingID) != nil {
                        FilingDestination(store: store, labels: labels, filingID: filingID)
                            .id(filingID)
                    } else {
                        noFiling
                    }
                }
                .navigationDestination(for: Route.self) {
                    RouteDestination(store: store, labels: labels, route: $0)
                }
            }
            .id(filingID)
            .environment(\.showsLanguageButton, false)
            .environment(\.navigate, NavigateAction { detailPath.append($0) })
        }
        .onChange(of: sidebar) { filingID = nil }
        .onChange(of: filingID) { detailPath = [] }
        .onChange(of: language) {
            if sidebar == .glossary && store.glossary(language: language).isEmpty {
                sidebar = store.companies.first.map { .company($0.id) }
            }
        }
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

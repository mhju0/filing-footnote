import FootnoteKit
import SwiftUI

/// Debug builds only: opens a screen at launch from `-FootnoteOpen <kind>=<id>`, so the
/// screenshot script (`ios/scripts/screenshots.sh`) can capture each screen without UI
/// scripting. Kinds: `company`, `notices` (company id), `filing` (filing id), `news` (an
/// optional filing id to open), `glossary` (an optional term key to mark);
/// `figure`, `picker` (the figure with the company picker open), `yearcompare`
/// and `yearcalc` take `<company id>|<metric>|<fiscal year>`; `compare` and `companycalc`
/// take `<company id>|<peer id>|<metric>|<measure or none>|<fiscal year>`; `ask` takes
/// `<company id>|<question intent>` and opens its answer (D99). Release builds ignore the
/// argument.
struct LaunchRoute: Sendable {
    enum Kind: String, Sendable {
        case company, notices, filing, news, glossary
        /// `<company id>|<filing id>|<metric>`: a quarter report's figure screen.
        case quarterfigure
        case figure, picker, yearcompare, yearcalc, compare, companycalc
        case ask
    }

    let kind: Kind
    let id: String?

    static let current: LaunchRoute? = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteOpen"), index + 1 < arguments.count
        else { return nil }
        return LaunchRoute(argument: arguments[index + 1])
        #else
        return nil
        #endif
    }()

    init?(argument: String) {
        let pieces = argument.split(separator: "=", maxSplits: 1).map(String.init)
        guard let kind = Kind(rawValue: pieces[0]) else { return nil }
        self.kind = kind
        id = pieces.count > 1 ? pieces[1] : nil
    }

    /// For a filing route: the company part of a filing id is not in the id, so the filing
    /// route carries `<company id>|<filing id>`.
    private var parts: (company: String?, filing: String?) {
        guard let id else { return (nil, nil) }
        switch kind {
        case .filing:
            let pieces = id.split(separator: "|", maxSplits: 1).map(String.init)
            return pieces.count == 2 ? (pieces[0], pieces[1]) : (nil, id)
        case .quarterfigure:
            return pieces.count == 3 ? (pieces[0], pieces[1]) : (nil, nil)
        case .company, .notices: return (id, nil)
        case .news: return (nil, id)
        case .glossary: return (nil, nil)
        case .figure, .picker, .yearcompare, .yearcalc, .compare, .companycalc, .ask:
            return (id.split(separator: "|").first.map(String.init), nil)
        }
    }

    private var pieces: [String] {
        (id ?? "").split(separator: "|", omittingEmptySubsequences: false).map(String.init)
    }

    /// The figure screen's company, metric and year, for the figure and compare kinds.
    private var figureKey: (company: String, metric: String, year: Int)? {
        switch kind {
        case .figure, .picker, .yearcompare, .yearcalc:
            guard pieces.count == 3, let year = Int(pieces[2]) else { return nil }
            return (pieces[0], pieces[1], year)
        case .compare, .companycalc:
            guard pieces.count == 5, let year = Int(pieces[4]) else { return nil }
            return (pieces[0], pieces[2], year)
        default:
            return nil
        }
    }

    private var compareRoute: CompanyCompareRoute? {
        guard kind == .compare || kind == .companycalc, pieces.count == 5, let year = Int(pieces[4]) else { return nil }
        return CompanyCompareRoute(
            companyID: pieces[0], peerID: pieces[1], metric: pieces[2],
            measure: pieces[3] == "none" ? nil : pieces[3], fiscalYear: year)
    }

    /// The question an `ask` launch opens.
    var askIntent: QuestionIntent? {
        guard kind == .ask, pieces.count == 2 else { return nil }
        return QuestionIntent(rawValue: pieces[1])
    }

    /// The screens over the company page: the figure (when the metric has one), then the
    /// compare screen and its calculation.
    var detailPath: [Route] {
        if kind == .quarterfigure, let filing = parts.filing, let metric = ReportedMetric(rawValue: pieces[2]) {
            return [.quarterFigure(filing, metric)]
        }
        guard let key = figureKey else { return [] }
        var path: [Route] = []
        if ReportedMetric(rawValue: key.metric) != nil {
            path.append(.figure(key.company, key.metric, key.year))
        }
        switch kind {
        case .yearcompare:
            path.append(.yearCompare(key.company, key.metric, key.year))
        case .yearcalc:
            path += [.yearCompare(key.company, key.metric, key.year), .yearCalculation(key.company, key.metric, key.year)]
        case .compare:
            if let route = compareRoute { path.append(.companyCompare(route)) }
        case .companycalc:
            if let route = compareRoute { path += [.companyCompare(route), .companyCalculation(route)] }
        default:
            break
        }
        return path
    }

    /// The annual filing the figure comes from, shown under the figure in the split view.
    func figureFilingID(_ store: BundleStore) -> String? {
        guard let key = figureKey else { return nil }
        return store.figures.first { $0.companyID == key.company && $0.fiscalYear == key.year }?.filingID
    }

    func opensPicker(_ companyID: String) -> Bool {
        kind == .picker && figureKey?.company == companyID
    }

    var tab: PhoneTabs.TabID {
        switch kind {
        case .news: .news
        case .glossary: .glossary
        default: .companies
        }
    }

    var companiesPath: [Route] {
        var path: [Route] = []
        if let company = parts.company { path.append(.company(company)) }
        if let filing = parts.filing, kind == .filing || kind == .quarterfigure { path.append(.filing(filing)) }
        if let company = parts.company, let intent = askIntent { path.append(.answer(company, intent)) }
        return path + detailPath
    }

    var newsPath: [Route] { kind == .news ? parts.filing.map { [.filing($0)] } ?? [] : [] }

    /// The glossary entry a `glossary=<term key>` launch opens and marks.
    var glossaryFocus: String? { kind == .glossary ? id : nil }

    var sidebarItem: SidebarView.Item? {
        switch kind {
        case .news: .news
        case .glossary: .glossary
        default: parts.company.map { .company($0) }
        }
    }

    /// The detail column's selection: a filing, or an `ask` launch's answer.
    var filingID: String? { askIntent.map(AskSelection.id) ?? parts.filing }

    func opensNotices(_ company: Company) -> Bool {
        kind == .notices && id == company.id
    }

    /// Debug builds only: `-FootnoteScroll top|center|bottom|ask` opens a filing or annual
    /// page scrolled to its numbers (`center`) or its end (`bottom`), a figure, calculation
    /// or company compare page scrolled to its end, and a company page scrolled to its
    /// questions (`ask`), so the screenshot script can capture a page longer than the screen.
    static let scrollTarget: (id: String, anchor: UnitPoint)? = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteScroll"), index + 1 < arguments.count
        else { return nil }
        return switch arguments[index + 1] {
        case "center": (PageScroll.numbers, .top)
        case "bottom": (PageScroll.end, .bottom)
        case "ask": (PageScroll.ask, .center)
        default: nil
        }
        #else
        return nil
        #endif
    }()
}

extension LaunchRoute {
    /// Debug builds only: `-FootnoteSearch <text>` opens the Companies tab (the sidebar on
    /// iPad and Mac) with `<text>` in its search field, so the screenshot script can capture
    /// the search results.
    static let searchQuery: String? = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteSearch"), index + 1 < arguments.count
        else { return nil }
        return arguments[index + 1]
        #else
        return nil
        #endif
    }()
}

/// Row ids a page marks for `LaunchRoute.scrollTarget`.
enum PageScroll {
    static let numbers = "page-numbers"
    static let end = "page-end"
    static let ask = "page-ask"
}

extension View {
    /// Scrolls a page's list to the launch scroll target once it appears (debug builds).
    func launchScroll(_ proxy: ScrollViewProxy) -> some View {
        task {
            guard let target = LaunchRoute.scrollTarget else { return }
            try? await Task.sleep(for: .milliseconds(600))
            proxy.scrollTo(target.id, anchor: target.anchor)
        }
    }
}

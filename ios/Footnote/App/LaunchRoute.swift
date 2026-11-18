import FootnoteKit
import SwiftUI

/// Debug builds only: opens a screen at launch from `-FootnoteOpen <kind>=<id>`, so the
/// screenshot script (`ios/scripts/screenshots.sh`) can capture each screen without UI
/// scripting. Kinds: `company`, `notices` (company id), `filing` (filing id), `news`,
/// `glossary`. Release builds ignore the argument.
struct LaunchRoute: Sendable {
    enum Kind: String, Sendable { case company, notices, filing, news, glossary }

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
        case .company, .notices: return (id, nil)
        case .news, .glossary: return (nil, nil)
        }
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
        if let filing = parts.filing, kind == .filing { path.append(.filing(filing)) }
        return path
    }

    var newsPath: [Route] { [] }

    var sidebarItem: SidebarView.Item? {
        switch kind {
        case .news: .news
        case .glossary: .glossary
        default: parts.company.map { .company($0) }
        }
    }

    var filingID: String? { parts.filing }

    func opensNotices(_ company: Company) -> Bool {
        kind == .notices && id == company.id
    }

    /// Debug builds only: `-FootnoteScroll top|center|bottom` opens a filing or annual page
    /// scrolled to its numbers (`center`) or its end (`bottom`), so the screenshot script can
    /// capture a page longer than the screen.
    static let scrollTarget: (id: String, anchor: UnitPoint)? = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteScroll"), index + 1 < arguments.count
        else { return nil }
        return switch arguments[index + 1] {
        case "center": (PageScroll.numbers, .top)
        case "bottom": (PageScroll.end, .bottom)
        default: nil
        }
        #else
        return nil
        #endif
    }()
}

/// Row ids a page marks for `LaunchRoute.scrollTarget`.
enum PageScroll {
    static let numbers = "page-numbers"
    static let end = "page-end"
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

import FootnoteKit
import SwiftUI

/// The first-run guide (design direction 8, owner picks q1 A, D and reopen A): four intro
/// pages shown once, on the very first launch. Start, Skip or closing the sheet marks the
/// guide seen; quitting the app mid-guide does not, so it shows again on the next launch.
/// It reopens from the bottom of 용어 / Glossary and from the Help menu.
@MainActor @Observable final class GuideModel {
    static let seenKey = "guideSeen"

    var isPresented: Bool
    @ObservationIgnored private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard, launch: GuideLaunch = .current) {
        self.defaults = defaults
        if launch.resetsGuide { defaults.removeObject(forKey: Self.seenKey) }
        isPresented = !launch.skipsGuideAndTips && !defaults.bool(forKey: Self.seenKey)
    }

    var hasBeenSeen: Bool { defaults.bool(forKey: Self.seenKey) }

    func reopen() { isPresented = true }

    func finish() {
        defaults.set(true, forKey: Self.seenKey)
        isPresented = false
    }
}

/// Debug launch arguments for the guide and the tips. Release builds ignore them.
/// - `-FootnoteSkipGuideAndTips`: no guide and no tips on this launch (UI tests and the
///   screenshot script). The guide is not marked seen.
/// - `-FootnoteResetGuide`: forgets that the guide was seen, so it shows on this launch.
/// - `-FootnoteResetTips`: clears TipKit's datastore before it is configured.
/// - `-FootnoteShowAllTips`: shows every tip whatever its rules (still not while the guide
///   is up).
/// - `-FootnoteGuidePage <n>`: opens the guide on page n (1 to 4), for screenshots.
struct GuideLaunch: Sendable {
    var skipsGuideAndTips = false
    var resetsGuide = false
    var resetsTips = false
    var showsAllTips = false
    var startPage = 0

    init(arguments: [String], isDebugBuild: Bool) {
        guard isDebugBuild else { return }
        skipsGuideAndTips = arguments.contains("-FootnoteSkipGuideAndTips")
        resetsGuide = arguments.contains("-FootnoteResetGuide")
        resetsTips = arguments.contains("-FootnoteResetTips")
        showsAllTips = arguments.contains("-FootnoteShowAllTips")
        if let index = arguments.firstIndex(of: "-FootnoteGuidePage"), index + 1 < arguments.count,
           let page = Int(arguments[index + 1]), GuideCopy.pages.indices.contains(page - 1) {
            startPage = page - 1
        }
    }

    static let current = GuideLaunch(
        arguments: ProcessInfo.processInfo.arguments, isDebugBuild: Library.isDebugBuild)
}

/// The guide's owner-approved copy (2026-11-26, `onboarding-tips` decisions, pages p1 to p4).
/// The first line of each page is its title, the rest its body. Not reworded.
enum GuideCopy {
    struct Page: Sendable, Equatable {
        let ko: String
        let en: String
        /// The page's SF Symbol; nil for page 3, which shows the company page itself.
        let symbol: String?

        func title(_ language: Language) -> String { lines(language).title }
        func body(_ language: Language) -> String { lines(language).body }

        private func lines(_ language: Language) -> (title: String, body: String) {
            let text = language(ko, en)
            let parts = text.split(separator: "\n", maxSplits: 1).map(String.init)
            return (parts[0], parts.count > 1 ? parts[1] : "")
        }
    }

    static let pages: [Page] = [
        Page(
            ko: "공시를 쉬운 말로\n한국과 미국의 잘 알려진 기업이 낸 공식 공시를 쉬운 말로 정리해요. 사업보고서부터 배당, 자사주 같은 회사의 결정까지 담았어요.",
            en: "Company filings in plain words\nFootnote summarises what well-known Korean and US companies officially filed, from annual reports to decisions such as dividends and buybacks.",
            symbol: "doc.text.magnifyingglass"),
        Page(
            ko: "숫자는 공시에서 그대로\n모든 숫자는 DART와 SEC에 낸 공시에서 가져와요. 숫자를 누르면 어느 공시에서 왔는지 볼 수 있어요. Footnote는 투자 조언을 하지 않아요.",
            en: "Every number comes from a filing\nFigures come from filings made to DART and the SEC. Tap a number to see which filing it came from. Footnote gives no investment advice.",
            symbol: "checkmark.seal"),
        Page(
            ko: "기업 한 곳 읽기\n기업을 고르면 맨 위에 최근 실적이 보여요. 그 아래 질문을 누르면 공시에 나온 답을, 더 아래에서는 최근 공시를 볼 수 있어요.",
            en: "Reading a company\nPick a company to see its latest results at the top. Below them, tap a question to see what the filings say, then browse recent filings.",
            symbol: nil),
        Page(
            ko: "소식과 용어\n소식에서는 모든 기업의 새 공시를 날짜순으로 볼 수 있어요. 낯선 말은 용어에서 쉬운 말로 풀어 드려요.",
            en: "News and Glossary\nNews lists every company's newest filings by date. Glossary explains unfamiliar terms in plain words.",
            symbol: "newspaper"),
    ]

    static func skip(_ language: Language) -> String { language("건너뛰기", "Skip") }
    static func next(_ language: Language) -> String { language("다음", "Next") }
    static func start(_ language: Language) -> String { language("시작하기", "Get started") }

    /// `페이지 2/4` / `Page 2 of 4`, for VoiceOver on the page dots.
    static func position(_ index: Int, of count: Int, _ language: Language) -> String {
        language("페이지 \(index + 1)/\(count)", "Page \(index + 1) of \(count)")
    }

    /// The row at the bottom of 용어 / Glossary.
    static func reopenRow(_ language: Language) -> String {
        language("Footnote 안내 다시 보기", "Show the Footnote guide again")
    }

    /// The Help menu item.
    static func helpItem(_ language: Language) -> String { language("Footnote 안내", "Footnote Guide") }
}

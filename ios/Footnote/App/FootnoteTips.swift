import FootnoteKit
import SwiftUI
import TipKit

/// In-app tips (design direction 8, owner picks q2 E and q4 B; D100). Each is a TipKit
/// popover on the one control it explains; none is a centred pop-up or a sheet. At most one
/// new tip a day, and no tip while the guide is up: every tip waits for `guideDone`, and
/// `footnoteTip` hides its popover while `tipsPaused` is set. Closing a tip or using what it
/// describes ends it for good; one ignored on three visits retires.
enum FootnoteTips {
    /// True once the guide has closed; false while it is up, including when it is reopened.
    @Parameter static var guideDone: Bool = false

    static let companyPageOpened = Tips.Event(id: "companyPageOpened")
    static let figureOpened = Tips.Event(id: "figureOpened")
    static let newsOpened = Tips.Event(id: "newsOpened")

    /// Called once at launch, before any tip view appears.
    static func configure(_ launch: GuideLaunch, guideShowing: Bool) {
        if launch.resetsTips { try? Tips.resetDatastore() }
        try? Tips.configure([.displayFrequency(.daily)])
        if launch.skipsGuideAndTips {
            Tips.hideAllTipsForTesting()
        } else if launch.showsAllTips {
            Tips.showAllTipsForTesting()
        }
        guideDone = !guideShowing
    }

    /// Counts a visit to 소식 / News: the tab or sidebar item was chosen, not a return from
    /// a filing pushed over it.
    static func countNewsVisit(paused: Bool) {
        if !paused { newsOpened.sendDonation() }
    }

    /// A tip's text in the in-app language. A tip is not a view, so it reads the stored
    /// language (`@AppStorage("language")`) instead of the environment.
    static var language: Language {
        UserDefaults.standard.string(forKey: "language").flatMap(Language.init(rawValue:)) ?? .ko
    }
}

/// Shared by the four tips: wait for the guide, retire after three ignored visits.
protocol FootnoteTip: Tip {
    var ko: (title: String, message: String) { get }
    var en: (title: String, message: String) { get }
    var symbol: String { get }
}

extension FootnoteTip {
    private var copy: (title: String, message: String) { FootnoteTips.language == .ko ? ko : en }
    var title: Text { Text(words: AskCopy.keepingTail(copy.title)) }
    var message: Text? { Text(words: AskCopy.keepingTail(copy.message)) }
    var image: Image? { Image(systemName: symbol) }
    var options: [any TipOption] { [Tips.MaxDisplayCount(3)] }
}

/// t2: on the company page's figure. Shows from the second company page; ends when a
/// figure is opened.
struct FigureSourceTip: FootnoteTip {
    let ko: (title: String, message: String) = ("숫자를 누르면 출처가 보여요", "어느 공시에서 왔는지, 어떻게 계산했는지 볼 수 있어요.")
    let en: (title: String, message: String) = ("Tap a figure to see its source", "See which filing it came from and how it was calculated.")
    let symbol = "hand.tap"

    var rules: [Rule] {
        #Rule(FootnoteTips.$guideDone) { $0 == true }
        #Rule(FootnoteTips.companyPageOpened) { $0.donations.count >= 2 }
    }
}

/// t3: on the first question to ask. Shows from the third company page, after t2 has ended
/// (the company page's ordered group); ends when any question is tapped.
struct AskTip: FootnoteTip {
    let ko: (title: String, message: String) = ("질문을 눌러 보세요", "공시에 나온 내용으로 답해요.")
    let en: (title: String, message: String) = ("Tap a question", "The answer comes from the company's filings.")
    let symbol = "hand.tap"

    var rules: [Rule] {
        #Rule(FootnoteTips.$guideDone) { $0 == true }
        #Rule(FootnoteTips.companyPageOpened) { $0.donations.count >= 3 }
    }
}

/// t4: on 작년과 비교 / Compare with last year. Shows from the second figure screen; ends
/// when either comparison is opened.
struct CompareTip: FootnoteTip {
    let ko: (title: String, message: String) = ("작년과 비교해 보세요", "같은 기준의 작년 숫자와 비교하고, 계산 과정도 볼 수 있어요.")
    let en: (title: String, message: String) = ("Compare with last year", "See the same figure a year earlier and how the change was calculated.")
    let symbol = "arrow.left.arrow.right"

    var rules: [Rule] {
        #Rule(FootnoteTips.$guideDone) { $0 == true }
        #Rule(FootnoteTips.figureOpened) { $0.donations.count >= 2 }
    }
}

/// t5: on 소식 / News' filing-type filter. Shows from the second visit; ends when a type is
/// chosen.
struct NewsFilterTip: FootnoteTip {
    let ko: (title: String, message: String) = ("공시 종류로 골라 보기", "배당이나 자사주처럼 원하는 종류만 볼 수 있어요.")
    let en: (title: String, message: String) = ("Filter by filing type", "Show only the kinds you want, such as dividends or buybacks.")
    let symbol = "line.3.horizontal.decrease.circle"

    var rules: [Rule] {
        #Rule(FootnoteTips.$guideDone) { $0 == true }
        #Rule(FootnoteTips.newsOpened) { $0.donations.count >= 2 }
    }
}

extension EnvironmentValues {
    /// True while the guide is up, and inside the guide's company page preview: no tip
    /// shows and no tip event is counted.
    @Entry var tipsPaused = false
}

private struct FootnoteTipModifier: ViewModifier {
    @Environment(\.tipsPaused) private var paused
    @Environment(\.language) private var language
    let tip: (any Tip)?
    let arrowEdge: Edge

    func body(content: Content) -> some View {
        // The language in the id redraws an open tip when the language switches.
        content
            .popoverTip(paused ? nil : tip, arrowEdge: arrowEdge)
            .id(language)
    }
}

private struct TipEventModifier: ViewModifier {
    @Environment(\.tipsPaused) private var paused
    @State private var counted = false
    let event: Tips.Event<Tips.EmptyDonation>

    func body(content: Content) -> some View {
        content.task {
            guard !paused, !counted else { return }
            counted = true
            await event.donate()
        }
    }
}

extension View {
    /// The tip as a popover on this control, unless tips are paused.
    func footnoteTip(_ tip: (any Tip)?, arrowEdge: Edge = .top) -> some View {
        modifier(FootnoteTipModifier(tip: tip, arrowEdge: arrowEdge))
    }

    /// Counts a tip event once per screen: coming back from a pushed screen is not a
    /// second visit.
    func countsTipEvent(_ event: Tips.Event<Tips.EmptyDonation>) -> some View {
        modifier(TipEventModifier(event: event))
    }
}

private struct EndsFigureSourceTip: ViewModifier {
    @Environment(\.tipsPaused) private var paused

    func body(content: Content) -> some View {
        content.onAppear {
            if !paused { FigureSourceTip().invalidate(reason: .actionPerformed) }
        }
    }
}

extension View {
    /// Ends t2 for good: a figure screen or a report with figures was opened.
    func endsFigureSourceTip() -> some View { modifier(EndsFigureSourceTip()) }
}

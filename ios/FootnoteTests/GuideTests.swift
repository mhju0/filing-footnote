import Foundation
import FootnoteKit
import Testing
@testable import Footnote

/// The first-run guide and the tips' pause (D104).
@MainActor
@Suite("First-run guide and tips")
struct GuideTests {
    /// A private defaults domain per test, removed afterwards.
    private final class Defaults {
        let name = "guide-tests-\(UUID().uuidString)"
        lazy var store = UserDefaults(suiteName: name)!
        deinit { UserDefaults().removePersistentDomain(forName: name) }
    }

    private static let plain = GuideLaunch(arguments: [], isDebugBuild: true)

    @Test func showsOnFirstLaunchOnly() {
        let defaults = Defaults()
        let first = GuideModel(defaults: defaults.store, launch: Self.plain)
        #expect(first.isPresented)
        #expect(!first.hasBeenSeen)

        first.finish()
        #expect(!first.isPresented)
        #expect(first.hasBeenSeen)

        let second = GuideModel(defaults: defaults.store, launch: Self.plain)
        #expect(!second.isPresented)
    }

    /// Quitting mid-guide marks nothing, so the guide shows again on the next launch.
    @Test func showsAgainWhenNotFinished() {
        let defaults = Defaults()
        _ = GuideModel(defaults: defaults.store, launch: Self.plain)
        #expect(GuideModel(defaults: defaults.store, launch: Self.plain).isPresented)
    }

    /// Skip and Get started both call `finish`; closing the sheet does too.
    @Test func finishingTwiceIsHarmless() {
        let defaults = Defaults()
        let guide = GuideModel(defaults: defaults.store, launch: Self.plain)
        guide.finish()
        guide.finish()
        #expect(!guide.isPresented)
        #expect(guide.hasBeenSeen)
    }

    @Test func reopensAfterBeingSeen() {
        let defaults = Defaults()
        let guide = GuideModel(defaults: defaults.store, launch: Self.plain)
        guide.finish()
        guide.reopen()
        #expect(guide.isPresented)
        guide.finish()
        #expect(!guide.isPresented)
        #expect(!GuideModel(defaults: defaults.store, launch: Self.plain).isPresented)
    }

    /// The test argument hides the guide for one launch without marking it seen.
    @Test func skipArgumentHidesWithoutMarkingSeen() {
        let defaults = Defaults()
        let skip = GuideLaunch(arguments: ["-FootnoteSkipGuideAndTips"], isDebugBuild: true)
        let guide = GuideModel(defaults: defaults.store, launch: skip)
        #expect(!guide.isPresented)
        #expect(!guide.hasBeenSeen)
        #expect(GuideModel(defaults: defaults.store, launch: Self.plain).isPresented)
    }

    @Test func resetArgumentShowsASeenGuide() {
        let defaults = Defaults()
        GuideModel(defaults: defaults.store, launch: Self.plain).finish()
        let reset = GuideLaunch(arguments: ["-FootnoteResetGuide"], isDebugBuild: true)
        #expect(GuideModel(defaults: defaults.store, launch: reset).isPresented)
    }

    @Test func launchArguments() {
        let all = GuideLaunch(
            arguments: ["-FootnoteSkipGuideAndTips", "-FootnoteResetGuide", "-FootnoteResetTips",
                        "-FootnoteShowAllTips", "-FootnoteGuidePage", "3"],
            isDebugBuild: true)
        #expect(all.skipsGuideAndTips && all.resetsGuide && all.resetsTips && all.showsAllTips)
        #expect(all.startPage == 2)
        #expect(GuideLaunch(arguments: ["-FootnoteGuidePage", "9"], isDebugBuild: true).startPage == 0)
        #expect(GuideLaunch(arguments: ["-FootnoteGuidePage"], isDebugBuild: true).startPage == 0)
    }

    /// A release build ignores every test argument: the guide shows on first launch.
    @Test func releaseBuildIgnoresTheArguments() {
        let release = GuideLaunch(
            arguments: ["-FootnoteSkipGuideAndTips", "-FootnoteShowAllTips", "-FootnoteGuidePage", "3"],
            isDebugBuild: false)
        #expect(!release.skipsGuideAndTips && !release.showsAllTips && release.startPage == 0)
        let defaults = Defaults()
        #expect(GuideModel(defaults: defaults.store, launch: release).isPresented)
    }

    /// Tips wait for `guideDone`, which is false while the guide shows.
    @Test func tipsWaitForTheGuide() {
        FootnoteTips.configure(Self.plain, guideShowing: true)
        #expect(FootnoteTips.guideDone == false)
        FootnoteTips.configure(Self.plain, guideShowing: false)
        #expect(FootnoteTips.guideDone == true)
    }

    /// Four pages, each a title and a body in both languages; page 3 is the company page.
    @Test func guideCopy() {
        let pages = GuideCopy.pages
        #expect(pages.count == 4)
        #expect(pages.map { $0.symbol == nil } == [false, false, true, false])
        for page in pages {
            for language in Language.allCases {
                #expect(!page.title(language).isEmpty)
                #expect(!page.body(language).isEmpty)
                #expect(!page.body(language).contains("\n"))
            }
        }
        #expect(pages[0].title(.ko) == "공시를 쉬운 말로")
        #expect(pages[3].body(.en) == "News lists every company's newest filings by date. Glossary explains unfamiliar terms in plain words.")
        #expect(GuideCopy.position(1, of: 4, .ko) == "페이지 2/4")
        #expect(GuideCopy.position(1, of: 4, .en) == "Page 2 of 4")
    }

    /// A one-letter word never ends a line: it is joined to the next word (`그 아래`), and
    /// the visible text is unchanged.
    @Test func shortWordsStayWithTheNextWord() {
        let body = GuideCopy.pages[2].body(.ko).bindingShortWords
        #expect(body.contains("그\u{00A0}아래"))
        #expect(body.contains("맨\u{00A0}위에"))
        #expect(body.contains("볼\u{00A0}수\u{00A0}있어요."))
        #expect(body.replacingOccurrences(of: "\u{00A0}", with: " ") == GuideCopy.pages[2].body(.ko))
        #expect(GuideCopy.wrapping(GuideCopy.pages[1].body(.ko)).contains("투자\u{00A0}조언을"))
        #expect(GuideCopy.wrapping(GuideCopy.pages[3].body(.ko)).contains("쉬운\u{00A0}말로"))
        for page in GuideCopy.pages {
            let wrapped = GuideCopy.wrapping(page.body(.ko))
            #expect(wrapped.replacingOccurrences(of: "\u{00A0}", with: " ") == page.body(.ko))
        }
        #expect("Pick a company".bindingShortWords == "Pick a\u{00A0}company")
        #expect("배당, 자사주".bindingShortWords == "배당, 자사주")
        for page in GuideCopy.pages {
            for language in Language.allCases {
                for text in [page.title(language), page.body(language)] {
                    let words = text.bindingShortWords.split(separator: " ")
                    #expect(words.dropLast().allSatisfy { $0.count > 1 })
                }
            }
        }
    }

    /// The four kept tips (t2 to t5), with the approved copy; t1, t6 and t7 are not built.
    @Test func tipCopy() {
        let tips: [any FootnoteTip] = [FigureSourceTip(), AskTip(), CompareTip(), NewsFilterTip()]
        #expect(Set(tips.map { $0.id }).count == 4)
        #expect(tips.map { $0.ko.title } == ["숫자를 누르면 출처가 보여요", "질문을 눌러 보세요", "작년과 비교해 보세요", "공시 종류로 골라 보기"])
        #expect(tips.map { $0.en.title } == ["Tap a figure to see its source", "Tap a question", "Compare with last year", "Filter by filing type"])
        for tip in tips {
            #expect(!tip.ko.message.isEmpty && !tip.en.message.isEmpty)
            #expect(tip.ko.message.unicodeScalars.contains { (0xAC00...0xD7A3).contains($0.value) })
        }
    }
}

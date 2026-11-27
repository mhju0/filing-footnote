import FootnoteKit
import SwiftUI
#if os(iOS)
import UIKit
#endif

extension EnvironmentValues {
    /// The typed-question router (D108). Nil hides the field and leaves the six questions as
    /// they are.
    @Entry var questionRouter: (any QuestionRouter)? = nil
}

/// Which router the app uses, decided once at launch (D108). Typed questions are for iPad
/// and Mac only (PRODUCT.md), and only where the on-device model can run now. iPhone gets
/// nothing, so its company page is unchanged.
enum QuestionRouting {
    @MainActor static let router: (any QuestionRouter)? = make(arguments: ProcessInfo.processInfo.arguments)

    @MainActor static func make(arguments: [String]) -> (any QuestionRouter)? {
        #if DEBUG
        // `-FootnoteTypedQuestions stub` shows the field with a fixed stand-in router, on any
        // device, for UI tests and screenshots; `off` hides it.
        if let index = arguments.firstIndex(of: "-FootnoteTypedQuestions"), index + 1 < arguments.count {
            switch arguments[index + 1] {
            case "stub": return StubQuestionRouter()
            case "off": return nil
            default: break
            }
        }
        #endif
        guard supportsTypedQuestions else { return nil }
        if #available(iOS 26.0, macOS 26.0, *), OnDeviceQuestionRouter.isAvailable {
            return OnDeviceQuestionRouter()
        }
        return nil
    }

    @MainActor private static var supportsTypedQuestions: Bool {
        #if os(macOS)
        true
        #else
        UIDevice.current.userInterfaceIdiom == .pad
        #endif
    }

    /// Debug builds only: `-FootnoteAsk <text>` types `<text>` into the field and submits it
    /// when the company page opens, so screenshots and the audit can show each state.
    static let launchQuestion: String? = {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-FootnoteAsk"), index + 1 < arguments.count else { return nil }
        return arguments[index + 1]
        #else
        return nil
        #endif
    }()
}

#if DEBUG
/// A fixed stand-in for the model in UI tests and screenshots: a few words pick a question,
/// anything else is none.
struct StubQuestionRouter: QuestionRouter {
    func route(_ text: String) async throws -> QuestionRoute {
        let text = text.lowercased()
        if ["사도", "buy"].contains(where: text.contains) { return .intent(.shouldBuy) }
        if ["흑자", "적자", "profit"].contains(where: text.contains) { return .intent(.profitOrLoss) }
        if ["매출", "revenue"].contains(where: text.contains) { return .intent(.revenue) }
        return .none
    }
}
#endif

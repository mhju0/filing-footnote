import FootnoteKit
import SwiftUI

@main
struct FootnoteApp: App {
    private let library = Library.loadBundled()

    var body: some Scene {
        WindowGroup {
            RootView(library: library)
        }
        #if os(macOS)
        .defaultSize(width: 1180, height: 760)
        #endif
    }
}

/// The bundled data file, opened once at launch.
enum Library: Sendable {
    case ready(BundleStore, FactLabels)
    case failed(BundleError)

    /// Opens `footnote.sqlite` from the app bundle. Debug builds accept a development bundle;
    /// release builds refuse one, so a build with unapproved summaries cannot ship by accident.
    static func loadBundled() -> Library {
        let arguments = ProcessInfo.processInfo.arguments
        let requireRelease = requiresRelease(isDebugBuild: isDebugBuild, arguments: arguments)
        #if DEBUG
        // UI tests open the FootnoteKit fixture: `-FootnoteBundle <absolute path>`.
        if let index = arguments.firstIndex(of: "-FootnoteBundle"), index + 1 < arguments.count {
            return load(url: URL(fileURLWithPath: arguments[index + 1]), labels: FactLabels.bundled,
                        requireRelease: requireRelease)
        }
        #endif
        guard let url = Bundle.main.url(forResource: "footnote", withExtension: "sqlite") else {
            return .failed(.cannotOpen(path: "footnote.sqlite", message: "missing from the app bundle"))
        }
        return load(url: url, labels: FactLabels.bundled, requireRelease: requireRelease)
    }

    /// False in the Release configuration. Unit tests build Debug, so they test
    /// `requiresRelease(isDebugBuild: false, …)` rather than this constant.
    static let isDebugBuild: Bool = {
        #if DEBUG
        true
        #else
        false
        #endif
    }()

    /// Whether this launch refuses a development bundle: always in a release build; in a
    /// debug build only with `-FootnoteRequireRelease`.
    static func requiresRelease(isDebugBuild: Bool, arguments: [String]) -> Bool {
        !isDebugBuild || arguments.contains("-FootnoteRequireRelease")
    }

    static func load(url: URL, labels: FactLabels, requireRelease: Bool) -> Library {
        do {
            let store = try BundleStore(contentsOf: url)
            if requireRelease { try store.requireRelease() }
            return .ready(store, labels)
        } catch {
            return .failed(error)
        }
    }
}

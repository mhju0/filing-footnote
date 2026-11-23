import FootnoteKit
import SwiftUI
#if canImport(SafariServices) && os(iOS)
import SafariServices
#endif

extension View {
    /// Opens web links (the original filing on DART or SEC) in an in-app Safari view on
    /// iPhone and iPad, and in the default browser on the Mac (ADR 0008). Apply once per
    /// presentation level: the root screen and each sheet.
    func opensLinksInApp() -> some View {
        modifier(InAppLinks())
    }
}

private struct InAppLinks: ViewModifier {
    #if os(iOS)
    @State private var page: WebPage?

    func body(content: Content) -> some View {
        content
            .environment(\.openURL, OpenURLAction { url in
                guard url.scheme == "https" || url.scheme == "http" else { return .systemAction }
                page = WebPage(url: url)
                return .handled
            })
            .sheet(item: $page) { page in
                SafariView(url: page.url).ignoresSafeArea()
            }
    }
    #else
    func body(content: Content) -> some View { content }
    #endif
}

#if os(iOS)
private struct WebPage: Identifiable {
    let url: URL
    var id: URL { url }
}

private struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let controller = SFSafariViewController(url: url)
        controller.preferredControlTintColor = UIColor(named: "Pine")
        return controller
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
#endif

/// A link row to an outside page: the label, the external-link mark, and a note that it
/// needs the internet. Everything else in the app works offline.
struct ExternalLinkRow: View {
    @Environment(\.openURL) private var openURL
    @Environment(\.language) private var language
    let title: String
    let url: URL?
    var showsNetworkNote = false

    var body: some View {
        if let url {
            Button {
                openURL(url)
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(words: title)
                            .font(.body)
                            .foregroundStyle(Theme.pine)
                        if showsNetworkNote {
                            Text(words: networkNote(for: url))
                                .font(.footnote)
                                .foregroundStyle(Theme.muted)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: "arrow.up.right.square")
                        .foregroundStyle(Theme.pine)
                        .accessibilityHidden(true)
                }
                .frame(minHeight: Theme.minTarget)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(.isLink)
            .accessibilityHint(language("인터넷 연결이 필요해요", "Needs an internet connection"))
        }
    }

    private func networkNote(for url: URL) -> String {
        let connection = language("인터넷 연결이 필요해요", "Needs an internet connection")
        guard let host = url.host else { return connection }
        return host + Copy.dot + connection
    }
}

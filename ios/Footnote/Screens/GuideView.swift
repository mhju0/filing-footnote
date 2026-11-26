import FootnoteKit
import SwiftUI

/// The first-run guide (owner picks q1 A and D): four pages, text with an SF Symbol in a
/// Tint square, and page 3 shows the real company page scaled down. Skip on every page,
/// page dots, Next, and 시작하기 / Get started on the last page. A full-screen cover on
/// iPhone, a fixed-size sheet on iPad and Mac (`GuidePresentation`).
struct GuideView: View {
    @Environment(\.language) private var language
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let store: BundleStore
    let finish: () -> Void
    @State private var page = GuideLaunch.current.startPage
    /// Keeps keyboard focus in the guide, for the arrow keys on Mac and with an iPad keyboard.
    @FocusState private var focused: Bool

    private let pages = GuideCopy.pages
    private var isLast: Bool { page == pages.count - 1 }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button(GuideCopy.skip(language), action: finish)
                    .font(.body)
                    .foregroundStyle(Theme.pine)
                    .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
                    .padding(.horizontal, 8)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("guide-skip")
            }
            .padding(.horizontal, 8)
            .padding(.top, 4)
            pager
            VStack(spacing: 12) {
                dots
                ActionButton(title: isLast ? GuideCopy.start(language) : GuideCopy.next(language), primary: true) {
                    if isLast { finish() } else { go(to: page + 1) }
                }
                .accessibilityIdentifier(isLast ? "guide-start" : "guide-next")
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 16)
        }
        .background(Theme.background)
        .focusable()
        .focusEffectDisabled()
        .focused($focused)
        .onAppear { focused = true }
        .onKeyPress(.leftArrow) { go(to: page - 1); return .handled }
        .onKeyPress(.rightArrow) { go(to: page + 1); return .handled }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("guide")
    }

    @ViewBuilder private var pager: some View {
        #if os(iOS)
        // Swipe pages; the dots and Next move with the same animation.
        TabView(selection: $page) {
            ForEach(pages.indices, id: \.self) { index in
                GuidePage(store: store, page: pages[index]).tag(index)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        #else
        // `.page` is unavailable on macOS: one page at a time, moved by the dots, Next and
        // the arrow keys.
        GuidePage(store: store, page: pages[page])
            .id(page)
            .transition(reduceMotion ? .opacity : .push(from: .trailing))
        #endif
    }

    /// One dot per page; a dot jumps to its page. VoiceOver reads the dots as one adjustable
    /// element: "페이지 2/4".
    private var dots: some View {
        HStack(spacing: 0) {
            ForEach(pages.indices, id: \.self) { index in
                Button {
                    go(to: index)
                } label: {
                    Circle()
                        .fill(index == page ? Theme.pine : Theme.muted.opacity(0.4))
                        .frame(width: 8, height: 8)
                        .frame(width: 28, height: Theme.minTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(GuideCopy.position(page, of: pages.count, language))
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: go(to: page + 1)
            case .decrement: go(to: page - 1)
            @unknown default: break
            }
        }
        .accessibilityIdentifier("guide-dots")
    }

    private func go(to index: Int) {
        guard pages.indices.contains(index), index != page else { return }
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) { page = index }
    }
}

/// One page: the symbol or the company page preview, the title, the body. At large text
/// sizes the page scrolls and Next stays pinned below it.
private struct GuidePage: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let page: GuideCopy.Page

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(spacing: 20) {
                    if let symbol = page.symbol {
                        Image(systemName: symbol)
                            .font(.system(size: 34, weight: .regular))
                            .foregroundStyle(Theme.pine)
                            .frame(width: 72, height: 72)
                            .background(Theme.tint, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                            .accessibilityHidden(true)
                    } else {
                        CompanyPreview(store: store)
                    }
                    VStack(spacing: 10) {
                        Text(words: GuideCopy.wrapping(page.title(language)))
                            .font(.title2.bold())
                            .foregroundStyle(Theme.ink)
                            .accessibilityAddTraits(.isHeader)
                        Text(words: GuideCopy.wrapping(page.body(language)))
                            .font(.body)
                            .foregroundStyle(Theme.muted)
                    }
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 440)
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 16)
                .frame(maxWidth: .infinity, minHeight: proxy.size.height)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }
}

/// Page 3: the real company page, drawn by the app's own views at a fixed text size and
/// scaled down, so it always matches the language, the appearance and the data. It is a
/// picture: no taps, no tips, and VoiceOver reads the page's text instead.
private struct CompanyPreview: View {
    let store: BundleStore

    /// The page is drawn at a mini's width, then scaled.
    private static let width: CGFloat = 375
    private static let height: CGFloat = 420
    private static let scale: CGFloat = 0.68

    /// The first company with a quarterly or annual report, so the crop shows a figure.
    private var page: CompanyPage? {
        store.companies.lazy
            .compactMap { CompanyPage(store: store, companyID: $0.id) }
            .first { $0.quarterReport != nil || !$0.periodicReports.isEmpty }
    }

    var body: some View {
        if let page {
            NavigationStack {
                CompanyPageView(store: store, page: page)
            }
            .environment(\.showsLanguageButton, false)
            .environment(\.tipsPaused, true)
            .environment(\.drawsTitleInList, true)
            // The approved preview shows the six questions only, on every device (D108).
            .environment(\.questionRouter, nil)
            .dynamicTypeSize(.large)
            .frame(width: Self.width, height: Self.height)
            .scaleEffect(Self.scale, anchor: .topLeading)
            .frame(width: Self.width * Self.scale, height: Self.height * Self.scale, alignment: .topLeading)
            .clipShape(shape)
            .overlay { shape.strokeBorder(Theme.line) }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }

    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: 14, style: .continuous) }
}

/// Presents the guide over the app: a full-screen cover on iPhone, a sheet of fixed size on
/// iPad and Mac. However it closes, it counts as seen. Tips wait while it is up.
struct GuidePresentation: ViewModifier {
    @Bindable var guide: GuideModel
    let store: BundleStore
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif

    func body(content: Content) -> some View {
        content
            .environment(\.tipsPaused, guide.isPresented)
            #if os(iOS)
            .fullScreenCover(isPresented: shown(compact: true), onDismiss: guide.finish) { guideView }
            .sheet(isPresented: shown(compact: false), onDismiss: guide.finish) {
                guideView.presentationSizing(.form)
            }
            #else
            .sheet(isPresented: $guide.isPresented, onDismiss: guide.finish) {
                guideView.frame(width: 520, height: 620)
            }
            #endif
            .onChange(of: guide.isPresented, initial: true) {
                FootnoteTips.guideDone = !guide.isPresented
            }
    }

    private var guideView: some View {
        GuideView(store: store, finish: guide.finish)
    }

    #if os(iOS)
    private func shown(compact: Bool) -> Binding<Bool> {
        Binding(
            get: { guide.isPresented && (sizeClass == .compact) == compact },
            set: { if !$0 { guide.isPresented = false } })
    }
    #endif
}

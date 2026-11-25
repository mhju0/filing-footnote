import FootnoteKit
import SwiftUI

/// DESIGN.md palette. Each colour is an asset-catalog colour with its light and dark value.
enum Theme {
    /// Actions, links, selected tab, category marks.
    static let pine = Color("Pine")
    /// Only the 새 공시 tag, plus at most one highlight per screen.
    static let saffron = Color("Saffron")
    static let ink = Color("Ink")
    static let tint = Color("Tint")
    static let background = Color("Background")
    static let surface = Color("Surface")
    static let muted = Color("Muted")
    static let line = Color("Line")
    static let onPine = Color("OnPine")
    static let onSaffron = Color("OnSaffron")

    /// The smallest tap target, in points.
    static let minTarget: CGFloat = 44
}

/// Brief, native motion where content changes (owner pick 2026-11-26, design direction 5 B):
/// no bounce, a quarter second, and none at all when Reduce Motion is on.
enum Motion {
    static let snappy = Animation.snappy(duration: 0.25)

    /// Runs `change` animated, or at once under Reduce Motion.
    @MainActor static func perform(reduceMotion: Bool, _ change: () -> Void) {
        if reduceMotion {
            change()
        } else {
            withAnimation(snappy, change)
        }
    }
}

extension View {
    /// A figure whose digits roll in place when its text changes, as on a language switch.
    func numberTransition(_ text: String) -> some View {
        modifier(NumberTransition(text: text))
    }
}

private struct NumberTransition: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let text: String

    func body(content: Content) -> some View {
        content
            .contentTransition(reduceMotion ? .identity : .numericText())
            .animation(reduceMotion ? nil : Motion.snappy, value: text)
    }
}

/// A small label in a filing row: its category, 정정됨 / Corrected, or 새 공시 / New. A
/// category tag leads with its symbol (owner pick 2026-11-26, design direction 7 B), so the
/// type never rests on colour alone; VoiceOver reads the text only.
struct TagView: View {
    enum Kind { case category, corrected, new }

    let text: String
    let kind: Kind
    var symbol: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            if let symbol {
                Image(systemName: symbol)
                    .imageScale(.small)
                    .accessibilityHidden(true)
            }
            Text(words: text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .font(.caption.weight(kind == .new ? .bold : .semibold))
        .foregroundStyle(foreground)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(background, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        // Its own width unless that is wider than the row (`Management matters` at the
        // accessibility sizes): then it wraps inside the row instead of pushing the whole
        // row past both edges of its card. Text beside it gives way first.
        .fixedSize(horizontal: false, vertical: true)
        .layoutPriority(1)
    }

    private var foreground: Color {
        switch kind {
        case .category: Theme.pine
        case .corrected: Theme.muted
        case .new: Theme.onSaffron
        }
    }

    private var background: Color {
        switch kind {
        case .category: Theme.tint
        case .corrected: Theme.line
        case .new: Theme.saffron
        }
    }
}

extension FilingCategory {
    /// The SF Symbol beside the category's name in its tag (design direction 7 B).
    var symbol: String {
        switch self {
        case .earnings: "chart.bar"
        case .unitSales: "shippingbox"
        case .buyback: "arrow.triangle.2.circlepath"
        case .dividend: "banknote"
        case .capital: "chart.pie"
        case .deal: "signature"
        case .leadership: "person.crop.circle"
        case .legal: "building.columns"
        case .outlook: "binoculars"
        case .shareholderValue: "person.2.circle"
        case .meeting: "person.3"
        case .operations: "gearshape.2"
        case .lending: "arrow.left.arrow.right"
        case .management: "briefcase"
        case .clarification: "questionmark.bubble"
        case .annual: "doc.text"
        case .quarterly: "calendar"
        }
    }
}

/// Lays children out in rows and wraps to the next row when the width runs out, so a row of
/// tags and a date never truncates at large text sizes.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let width = rows.map(\.width).max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + lineSpacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.indices {
                let size = Self.size(of: subviews[index], maxWidth: bounds.width)
                subviews[index].place(
                    at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                    proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    /// A subview's ideal size, narrowed to the row width so long text wraps inside it.
    private static func size(of subview: LayoutSubview, maxWidth: CGFloat) -> CGSize {
        let ideal = subview.sizeThatFits(.unspecified)
        guard ideal.width > maxWidth else { return ideal }
        return subview.sizeThatFits(ProposedViewSize(width: maxWidth, height: nil))
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for index in subviews.indices {
            let size = Self.size(of: subviews[index], maxWidth: width)
            let needed = row.indices.isEmpty ? size.width : row.width + spacing + size.width
            if needed > width && !row.indices.isEmpty {
                rows.append(row)
                row = Row()
            }
            row.width = row.indices.isEmpty ? size.width : row.width + spacing + size.width
            row.height = max(row.height, size.height)
            row.indices.append(index)
        }
        if !row.indices.isEmpty { rows.append(row) }
        return rows
    }
}

/// The trailing chevron of a row that opens a sheet or a selection (a `NavigationLink`
/// draws its own on iPhone).
struct Chevron: View {
    var body: some View {
        Image(systemName: "chevron.right")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(.tertiary)
            .accessibilityHidden(true)
    }
}

/// The globe "EN" button in the navigation bar (G1 pick 1A). One tap switches the whole UI.
struct LanguageButton: View {
    @Environment(\.language) private var language
    @AppStorage("language") private var stored = Language.ko.rawValue

    var body: some View {
        Button {
            stored = language.other.rawValue
        } label: {
            // An HStack, not a Label: the iOS toolbar reduces a Label to its icon.
            HStack(spacing: 4) {
                Image(systemName: "globe")
                Text(words: language == .ko ? "EN" : "한국어")
            }
            .font(.body)
            .fixedSize()
            .padding(.horizontal, 6)
            .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
            .contentShape(Rectangle())
        }
        // The navigation bar caps its items' text size; at accessibility sizes a long press
        // shows the label in the large content viewer, as system bar buttons do.
        .accessibilityShowsLargeContentViewer {
            Image(systemName: "globe")
            Text(verbatim: language == .ko ? "EN" : "한국어")
        }
        .accessibilityLabel(language("Switch to English", "한국어로 보기"))
        .accessibilityHint(language("화면 전체를 영어로 바꿔요", "Shows the whole app in Korean"))
    }
}

extension EnvironmentValues {
    /// False in the split view's sidebar and detail columns, so the window shows one
    /// language button (in the content column), not three.
    @Entry var showsLanguageButton = true
}

private struct LanguageToolbar: ViewModifier {
    @Environment(\.showsLanguageButton) private var shows

    func body(content: Content) -> some View {
        content.toolbar {
            if shows {
                ToolbarItem(placement: .primaryAction) { LanguageButton() }
            }
        }
    }
}

extension View {
    /// The language button in the trailing navigation-bar slot.
    func languageToolbar() -> some View {
        modifier(LanguageToolbar())
    }

    /// The grouped-list look of DESIGN.md: Background behind, Surface rows.
    func groupedScreen() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(Theme.background)
    }
}

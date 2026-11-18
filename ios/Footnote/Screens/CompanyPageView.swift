import FootnoteKit
import SwiftUI

/// Board 14: periodic reports pinned, up to ten filings by month, the notices row, then the
/// end note and the link to every filing on DART or SEC.
struct CompanyPageView: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let page: CompanyPage
    @Environment(\.filingSelection) private var selection
    @State private var showsNotices: Bool

    init(store: BundleStore, page: CompanyPage) {
        self.store = store
        self.page = page
        _showsNotices = State(initialValue: LaunchRoute.current?.opensNotices(page.company) ?? false)
    }

    private var name: String { Titles.name(of: page.company, language: language) }

    var body: some View {
        SelectionList(selection: selection) {
            header
            if !page.periodicReports.isEmpty {
                Section(language("정기 보고서", "Periodic reports")) {
                    ForEach(page.periodicReports, id: \.filing.id) { report in
                        FilingRowLink(filingID: report.filing.id) {
                            PeriodicRow(report: report, company: page.company, dataAsOf: page.dataAsOf)
                        }
                    }
                }
            }
            ForEach(Array(page.months.enumerated()), id: \.element.id) { index, month in
                Section(monthTitle(month, first: index == 0)) {
                    ForEach(month.filings) { filing in
                        FilingRowLink(filingID: filing.id) {
                            FilingRow(filing: filing, dataAsOf: page.dataAsOf)
                        }
                    }
                }
            }
            if !page.notices.isEmpty {
                Section(language("그 밖의 공시", "Other filings")) {
                    noticesRow
                }
            }
            Section {
                ExternalLinkRow(
                    title: Copy.allFilingsLink(page.company.regulator, language),
                    url: page.allFilingsURL)
                    .listRowBackground(Theme.surface)
            } header: {
                EmptyView()
            } footer: {
                Text(words: Copy.endNote(listed: page.filings.count, capped: page.isCapped, language))
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
            }
        }
        .groupedScreen()
        .navigationTitle(name)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.large)
        #else
        .navigationSubtitle(Copy.companySubtitle(page.company, dataAsOf: page.dataAsOf, language))
        #endif
        .languageToolbar()
        .sheet(isPresented: $showsNotices) {
            NoticesSheet(page: page)
        }
    }

    /// The ticker and data date under the large title. The Mac shows it as the toolbar's
    /// subtitle instead.
    @ViewBuilder private var header: some View {
        #if os(iOS)
        Text(words: Copy.companySubtitle(page.company, dataAsOf: page.dataAsOf, language))
            .font(.subheadline)
            .monospacedDigit()
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
        #endif
    }

    private func monthTitle(_ month: FilingMonth, first: Bool) -> String {
        let title = Formatting.month(
            month.month, year: month.year, currentYear: page.dataAsOf.year, language: language)
        return first ? language("최근 공시", "Recent filings") + Copy.dot + title : title
    }

    private var noticesRow: some View {
        Button {
            showsNotices = true
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(words: Copy.noticesRow(count: page.notices.count, language))
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                    Text(words: Copy.noticeBreakdown(page.noticeCounts, language))
                        .font(.footnote)
                        .monospacedDigit()
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Chevron()
            }
            .padding(.vertical, 4)
            .frame(minHeight: Theme.minTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .combine)
        .accessibilityHint(language("날짜와 원문 목록을 열어요", "Opens the list of dates and originals"))
    }
}

/// Board 18: a medium-detent sheet listing each notice's date, title and original link.
struct NoticesSheet: View {
    @Environment(\.language) private var language
    @Environment(\.dismiss) private var dismiss
    let page: CompanyPage

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(page.notices) { notice in
                        NoticeRow(notice: notice, regulator: page.company.regulator)
                    }
                } header: {
                    Text(words: Copy.noticesIntro(
                        count: page.notices.count, since: page.noticesSince, dataAsOf: page.dataAsOf, language))
                        .font(.footnote)
                        .foregroundStyle(Theme.muted)
                        .textCase(nil)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.bottom, 4)
                }
            }
            .groupedScreen()
            .navigationTitle(language("안내 공시", "Notices"))
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(language("닫기", "Close")) { dismiss() }
                        .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
                }
            }
        }
        .opensLinksInApp()
        .presentationDetents([.medium, .large])
        #if os(macOS)
        .frame(minWidth: 460, idealWidth: 520, minHeight: 480, idealHeight: 600)
        #endif
    }
}

struct NoticeRow: View {
    @Environment(\.openURL) private var openURL
    @Environment(\.language) private var language
    let notice: Notice
    let regulator: Regulator

    var body: some View {
        Button {
            if let url = URL(string: notice.sourceURL) { openURL(url) }
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(words: Titles.title(for: notice, language: language))
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 6) {
                        Text(words: Formatting.monthDay(notice.filedOn, language: language))
                            .monospacedDigit()
                        if notice.isCorrected {
                            Text(words: "· " + language("정정됨", "Corrected"))
                        }
                    }
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "arrow.up.right.square")
                    .foregroundStyle(Theme.pine)
                    .accessibilityHidden(true)
            }
            .padding(.vertical, 4)
            .frame(minHeight: Theme.minTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            Titles.title(for: notice, language: language) + ", "
                + Formatting.fullDate(notice.filedOn, language: language))
        .accessibilityAddTraits(.isLink)
        .accessibilityHint(Copy.openOriginal(regulator, language))
    }
}

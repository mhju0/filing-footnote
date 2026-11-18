import FootnoteKit
import SwiftUI

/// 소식 / News: every listed filing across the companies, newest first, by month, in the
/// company page's row style with the company's name added.
struct NewsView: View {
    @Environment(\.language) private var language
    let store: BundleStore

    private var months: [FilingMonth] {
        let listed = store.companies.flatMap { company in
            store.eventFilings(forCompany: company.id).prefix(CompanyPage.maxFilings)
        }
        let newestFirst = listed.sorted { ($0.filedOn, $0.id) > ($1.filedOn, $1.id) }
        return FilingMonth.group(newestFirst)
    }

    var body: some View {
        List {
            Text(words: Copy.dataDate(store.meta.dataAsOf, language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
            ForEach(months) { month in
                Section(Formatting.month(
                    month.month, year: month.year, currentYear: store.meta.dataAsOf.year,
                    language: language)) {
                    ForEach(month.filings) { filing in
                        FilingRowLink(filingID: filing.id) {
                            FilingRow(
                                filing: filing, dataAsOf: store.meta.dataAsOf,
                                companyName: store.company(id: filing.companyID)
                                    .map { Titles.name(of: $0, language: language) })
                        }
                    }
                }
            }
        }
        .groupedScreen()
        .navigationTitle(language("소식", "News"))
        .languageToolbar()
    }
}

/// 용어 / Glossary: each term in plain words, the formal term kept nearby. The tab exists only
/// while the bundle holds glossary rows.
struct GlossaryView: View {
    @Environment(\.language) private var language
    let store: BundleStore

    var body: some View {
        List {
            ForEach(store.glossary(language: language), id: \.termKey) { entry in
                VStack(alignment: .leading, spacing: 4) {
                    Text(words: entry.term)
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    Text(words: entry.plain)
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    if let formal = entry.formal {
                        Text(words: language("공식 용어: ", "Formal term: ") + formal)
                            .font(.footnote)
                            .foregroundStyle(Theme.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.vertical, 6)
                .listRowBackground(Theme.surface)
                .accessibilityElement(children: .combine)
            }
        }
        .groupedScreen()
        .navigationTitle(language("용어", "Glossary"))
        .languageToolbar()
    }
}

/// Shown instead of the app when the bundled data file cannot be used. Plain on purpose:
/// it only happens to a broken build.
struct BundleErrorView: View {
    @Environment(\.language) private var language
    let error: BundleError

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle)
                .foregroundStyle(Theme.ink)
                .accessibilityHidden(true)
            Text(words: language("데이터 파일을 열 수 없어요", "The data file can’t be opened"))
                .font(.title2.bold())
                .foregroundStyle(Theme.ink)
            Text(words: message)
                .font(.body)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(24)
        .frame(maxWidth: 520, maxHeight: .infinity, alignment: .center)
        .frame(maxWidth: .infinity)
        .background(Theme.background)
    }

    private var message: String {
        switch error {
        case .developmentBundle:
            language(
                "이 빌드에는 개발용 데이터 파일이 들어 있어요. 출시용 빌드는 승인된 요약만 담은 데이터 파일이 필요해요.",
                "This build holds a development data file. A release build needs a data file with approved summaries only.")
        case .unsupportedSchemaVersion(let found, let supported):
            language(
                "데이터 파일 형식 \(found)은 이 앱이 읽는 형식 \(supported)과 달라요.",
                "The data file has format \(found); this app reads format \(supported).")
        case .cannotOpen(_, let message), .sqlite(let message):
            language("파일을 읽지 못했어요: \(message)", "The file could not be read: \(message)")
        case .missingBuildMeta, .invalidValue:
            language("데이터 파일의 내용이 형식에 맞지 않아요.", "The data file’s contents do not match its format.")
        }
    }
}

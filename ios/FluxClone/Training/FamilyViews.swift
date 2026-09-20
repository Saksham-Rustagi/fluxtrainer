import SwiftUI

private let accent = Color(uiColor: FluxTheme.main)
private let bg = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)
private let error = Color(uiColor: FluxTheme.colorfulError)

/// The family page. Reachable from any review item, any stem, or My Stems.
///
/// The headline is the point of the screen: **"You have 6 of the 9 branches worth
/// knowing."** Everything under it is sorted by expected value and never alphabetically,
/// and the branches below the line are folded away rather than deleted, because "TUTORED
/// is a word and it does not matter" is itself worth knowing once.
struct FamilyPageView: View {
    let stem: String
    var drill: ((String) -> Void)?

    @State private var page: FamilyPage?
    @State private var showingRest = false
    @State private var showingDead = false

    var body: some View {
        ScrollView {
            if let page {
                VStack(alignment: .leading, spacing: 16) {
                    header(page)
                    ForEach(page.worthKnowing) { BranchRow(row: $0) }
                    rest(page)
                    dead(page)
                    if let drill {
                        Button { drill(stem) } label: {
                            Text("Drill this family")
                                .font(.title3.weight(.heavy))
                                .frame(maxWidth: .infinity).padding()
                        }
                        .buttonStyle(.borderedProminent).tint(accent).foregroundStyle(bg)
                        .padding(.top, 8)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 30)
            } else {
                ProgressView().tint(accent).padding(.top, 60)
            }
        }
        .background(bg)
        .navigationTitle("\(stem)-")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: stem) { await load() }
    }

    private func load() async {
        guard let hook = HookBundle.shared?.hooks.first(where: { $0.stem == stem }) else { return }
        let loaded = await Task.detached(priority: .userInitiated) {
            FamilyPage.load(hook: hook)
        }.value
        page = loaded
    }

    private func header(_ page: FamilyPage) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(page.headline)
                .font(.title3.weight(.heavy))
                .foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            if !page.slipping.isEmpty {
                // The inverse of learning, and the player's own history says it is the
                // normal case rather than the exception.
                Text("Slipping: " + page.slipping.map(\.word).joined(separator: ", "))
                    .font(.footnote)
                    .foregroundStyle(error)
            }
            if let trend = page.trendLine {
                Text(trend).font(.footnote).foregroundStyle(.secondary)
            }
            Text(metaLine(page)).font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(.top, 12)
    }

    private func metaLine(_ page: FamilyPage) -> String {
        var parts: [String] = []
        if let first = page.trend.firstDrilled {
            parts.append("drilled \(FamilyPageView.day(first))")
        } else {
            parts.append("never drilled")
        }
        parts.append("met on \(page.trend.meetings) board\(page.trend.meetings == 1 ? "" : "s")")
        parts.append(page.hook.why)
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder
    private func rest(_ page: FamilyPage) -> some View {
        let others = page.live.filter { !$0.worthKnowing }
        if !others.isEmpty {
            DisclosureGroup(isExpanded: $showingRest) {
                VStack(spacing: 8) { ForEach(others) { BranchRow(row: $0) } }
                    .padding(.top, 8)
            } label: {
                Text("\(others.count) more that are words and are not worth much")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            .tint(accent)
        }
    }

    @ViewBuilder
    private func dead(_ page: FamilyPage) -> some View {
        if !page.dead.isEmpty {
            DisclosureGroup(isExpanded: $showingDead) {
                VStack(spacing: 8) { ForEach(page.dead) { BranchRow(row: $0) } }
                    .padding(.top, 8)
            } label: {
                // Their own block, because knowing that -IER does not take is worth
                // something and it is not worth what knowing -ER is.
                Text("\(page.dead.count) that do not take")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            .tint(accent)
        }
    }

    static func day(_ iso: String) -> String { String(iso.prefix(10)) }
}

private struct BranchRow: View {
    let row: FamilyPage.Row

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(row.word)
                    .font(.body.monospaced())
                    .foregroundStyle(row.branch.cls.earnsPoints ? .white : Color.secondary)
                Text(row.branch.ext).font(.caption2).foregroundStyle(.tertiary)
                if row.branch.isAlpha { AlphaBadge() }
                Spacer()
                statusChip
                if row.branch.earns {
                    Text("\(row.branch.points)")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            HStack {
                Text(row.shape).font(.caption2).foregroundStyle(.tertiary)
                Text(row.rateLine).font(.caption2).foregroundStyle(.tertiary)
                Spacer()
                if row.branch.expectedGain > 0 {
                    Text(String(format: "+%.1f/game", row.branch.expectedGain))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(row.worthKnowing ? accent : Color.tertiaryLabelColor)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(panel))
    }

    private var statusChip: some View {
        let (text, colour): (String, Color) = {
            switch row.status {
            case "known": return ("owned", accent)
            case "slipping": return ("slipping", error)
            case "learning": return ("learning", .orange)
            case "unknown": return ("unknown", .secondary)
            default: return (row.status, .secondary)
            }
        }()
        return Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(colour.opacity(0.18)))
            .foregroundStyle(colour)
    }
}

extension Color {
    static let tertiaryLabelColor = Color(uiColor: .tertiaryLabel)
}

/// Section 4: the record of what has actually been done. Without it the app has no memory
/// the player can see, and no answer to "what have I learned this month".
struct StemsView: View {
    var drill: ((String) -> Void)?

    @State private var records: [StemRecord] = []
    @State private var slipping: Set<String> = []
    @State private var filter = StemRecord.Filter.all
    @State private var track: String?
    @State private var loading = true

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("", selection: $filter) {
                    ForEach(StemRecord.Filter.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16).padding(.vertical, 8)

                if loading {
                    Spacer(); ProgressView().tint(accent); Spacer()
                } else if shown.isEmpty {
                    Spacer()
                    Text(records.isEmpty
                         ? "Nothing yet. Play a board and the families you meet land here."
                         : "Nothing matches that filter.")
                        .font(.footnote).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center).padding(.horizontal, 40)
                    Spacer()
                } else {
                    List(shown) { record in
                        NavigationLink(value: record.stem) { StemRow(record: record,
                                                                     slipping: slipping.contains(record.stem)) }
                            .listRowBackground(Color.clear)
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .background(bg)
            .navigationTitle("My stems")
            .toolbar {
                Menu {
                    Picker("Track", selection: $track) {
                        Text("Every track").tag(String?.none)
                        ForEach(tracks, id: \.self) { Text($0).tag(String?.some($0)) }
                    }
                } label: {
                    Image(systemName: track == nil ? "line.3.horizontal.decrease.circle"
                                                   : "line.3.horizontal.decrease.circle.fill")
                }
            }
            .navigationDestination(for: String.self) { FamilyPageView(stem: $0, drill: drill) }
        }
        .task { await load() }
    }

    private var tracks: [String] {
        Array(Set(records.map(\.track))).filter { !$0.isEmpty }.sorted()
    }

    private var shown: [StemRecord] {
        let byTrack = track.map { t in records.filter { $0.track == t } } ?? records
        switch filter {
        case .all: return byTrack
        case .drilled: return byTrack.filter(\.drilled)
        case .improving: return byTrack.filter { $0.improving == true }
        case .slipping: return byTrack.filter { slipping.contains($0.stem) }
        }
    }

    private func load() async {
        let index = FamilyIndex.shared
        let loaded = await Task.detached(priority: .userInitiated) {
            (StemRecord.load(index: index), index.map(StemRecord.slippingStems(index:)) ?? [])
        }.value
        records = loaded.0
        slipping = loaded.1
        loading = false
    }
}

private struct StemRow: View {
    let record: StemRecord
    let slipping: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(record.stem)-")
                    .font(.body.monospaced().weight(.bold))
                    .foregroundStyle(accent)
                if record.drilled {
                    Text("drilled \(record.exposures)x")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
                if slipping {
                    Text("slipping").font(.caption2).foregroundStyle(error)
                }
                Spacer()
                if record.worthKnowing > 0 {
                    // Completion means owned branches worth knowing, which is the family
                    // page's headline. Find rate is a different question and sits below.
                    Text("\(record.owned)/\(record.worthKnowing)")
                        .font(.body.monospacedDigit())
                        .foregroundStyle(.white)
                }
            }
            HStack(spacing: 8) {
                Text("\(record.found) of \(record.present) over \(record.meetings) boards")
                if let before = record.beforeRate, let after = record.afterRate {
                    // The counts travel with the number, because three presences is not
                    // evidence and twenty is.
                    Text("· \(pct(before)) → \(pct(after))")
                        .foregroundStyle(record.readable
                                         ? (after > before ? accent : error)
                                         : Color.secondary)
                }
                Spacer()
                if let met = record.lastMet { Text(met.prefix(10)) }
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    private func pct(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }
}

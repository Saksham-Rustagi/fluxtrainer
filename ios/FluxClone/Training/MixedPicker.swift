import SwiftUI

private let accent = Color(uiColor: FluxTheme.main)
private let bg = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)

/// Which families go into a mixed board.
///
/// The first version chose for him, off the top of the queue, and that has two failures a
/// picker fixes at once: the choice was never his, and because `queue.ranked` is sorted
/// deterministically it came back with **the same five families every time**. A practice
/// board that is the same board every time is not practice.
///
/// The candidate list is everything it makes sense to practise -- drilled, due, slipping,
/// and the top of the queue -- with the reason each one is on the list, so the choice is
/// informed rather than a list of stems.
struct MixedCandidate: Identifiable {
    enum Reason: String {
        case drilled       // worked on in a session
        case due           // the simple Phase 3 scheduler says it is time
        /// At least one branch was being taken and is not any more.
        case slipping
        case queued        // top of the ranked queue, never drilled

        var label: String {
            switch self {
            case .drilled: return "drilled"
            case .due: return "due"
            case .slipping: return "slipping"
            case .queued: return "next up"
            }
        }
    }

    let hook: Hook
    let reason: Reason
    let lastMet: String?
    let owned: Int
    let worthKnowing: Int

    var id: String { hook.stem }

    /// "6 of 9 worth knowing · 12.4/game"
    var detail: String {
        var parts: [String] = []
        if worthKnowing > 0 { parts.append("\(owned) of \(worthKnowing) worth knowing") }
        if hook.expectedGain > 0 {
            parts.append(String(format: "%.1f/game", hook.expectedGain))
        }
        if let lastMet { parts.append("met \(lastMet.prefix(10))") }
        return parts.joined(separator: " · ")
    }
}

enum MixedCandidates {
    /// Three to five is the brief's range. Two still makes a board; one is a sweep.
    static let range = 2...5
    static let suggested = 4

    /// Everything worth practising, best reason first. Runs off the main thread.
    static func load(queue: [TrainingQueue.Ranked], index: FamilyIndex?,
                     limit: Int = 40) -> [MixedCandidate] {
        var reasons: [String: MixedCandidate.Reason] = [:]
        var lastMet: [String: String] = [:]

        Database.shared.query(
            "SELECT stem, last_drilled, due_wall FROM hook_state") { row in
            let stem = row.text(0)
            reasons[stem] = .drilled
            if let due = row.optionalText(2), due <= TrainingLog.now() { reasons[stem] = .due }
        }
        Database.shared.query(
            "SELECT stem, MAX(wall) FROM hook_meeting GROUP BY stem") { row in
            lastMet[row.text(0)] = row.text(1)
        }
        if let index {
            for stem in StemRecord.slippingStems(index: index) { reasons[stem] = .slipping }
        }
        // Owned has to be counted over the *same* branches as "worth knowing", or the row
        // reads "7 of 5 worth knowing": `Ranked.owned` counts every live branch the
        // recompute calls known, and the denominator here is only the branches above the
        // value floor. Same source as the family page's headline, so the two agree.
        var ownedWords: Set<String> = []
        Database.shared.query("SELECT word FROM word_belief WHERE status = 'known'") {
            ownedWords.insert($0.text(0))
        }

        var out: [MixedCandidate] = []
        var seen: Set<String> = []
        func add(_ ranked: TrainingQueue.Ranked, _ reason: MixedCandidate.Reason) {
            guard !seen.contains(ranked.hook.stem) else { return }
            seen.insert(ranked.hook.stem)
            let worth = ranked.hook.liveBranches.filter {
                $0.earns && $0.expectedGain >= FamilyPage.worthKnowingFloor
            }
            out.append(MixedCandidate(
                hook: ranked.hook, reason: reason, lastMet: lastMet[ranked.hook.stem],
                owned: worth.filter { ownedWords.contains($0.word) }.count,
                worthKnowing: worth.count))
        }

        // Order of interest, not of value: a family he has worked on and one that is
        // slipping are both more interesting to test than the next one off the queue.
        for wanted in [MixedCandidate.Reason.slipping, .due, .drilled] {
            for ranked in queue where reasons[ranked.hook.stem] == wanted { add(ranked, wanted) }
        }
        for ranked in queue where ranked.eligible && out.count < limit { add(ranked, .queued) }
        return Array(out.prefix(limit))
    }

    /// What to open the sheet with. Drilled, due and slipping first, then the queue -- but
    /// **shuffled within the top of the list**, so two sessions in a row are not the same
    /// board. The whole complaint about the old behaviour was that it never varied.
    static func defaultSelection(from candidates: [MixedCandidate],
                                 count: Int = suggested) -> Set<String> {
        let pool = candidates.prefix(max(count * 3, 12))
        return Set(pool.shuffled().prefix(count).map(\.hook.stem))
    }
}

struct MixedPickerView: View {
    let candidates: [MixedCandidate]
    @Binding var selection: Set<String>
    let play: () -> Void
    let cancel: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text("Three to five families, hidden in an ordinary 80-second board. "
                     + "Nothing on the board says which; the breakdown comes afterwards.")
                    .font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 20).padding(.bottom, 10)

                List {
                    ForEach(candidates) { candidate in
                        Button { toggle(candidate.hook.stem) } label: {
                            row(candidate)
                        }
                        .listRowBackground(Color.clear)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)

                footer
            }
            .background(bg)
            .navigationTitle("Mixed practice")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: cancel).tint(accent)
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("Shuffle") {
                        selection = MixedCandidates.defaultSelection(from: candidates)
                    }
                    .tint(accent)
                }
            }
        }
    }

    private func row(_ candidate: MixedCandidate) -> some View {
        HStack(spacing: 10) {
            Image(systemName: selection.contains(candidate.hook.stem)
                  ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(selection.contains(candidate.hook.stem) ? accent : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("\(candidate.hook.stem)-")
                        .font(.body.monospaced().weight(.bold))
                        .foregroundStyle(.white)
                    Text(candidate.reason.label)
                        .font(.caption2)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(RoundedRectangle(cornerRadius: 3)
                            .fill(colour(candidate.reason).opacity(0.2)))
                        .foregroundStyle(colour(candidate.reason))
                }
                Text(candidate.detail).font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer()
        }
        .contentShape(Rectangle())
    }

    private func colour(_ reason: MixedCandidate.Reason) -> Color {
        switch reason {
        case .slipping: return Color(uiColor: FluxTheme.colorfulError)
        case .due: return .orange
        case .drilled: return accent
        case .queued: return .secondary
        }
    }

    private var footer: some View {
        VStack(spacing: 8) {
            Text(status)
                .font(.caption)
                .foregroundStyle(ready ? Color.secondary : Color.orange)
            Button(action: play) {
                Text("Play").font(.title3.weight(.heavy))
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent).tint(accent).foregroundStyle(bg)
            .disabled(!ready)
            // The home screen's Play button is still in the hierarchy behind the sheet.
            .accessibilityIdentifier("mixed.play")
        }
        .padding(.horizontal, 20).padding(.bottom, 16)
    }

    private var ready: Bool { MixedCandidates.range.contains(selection.count) }

    private var status: String {
        switch selection.count {
        case 0: return "Pick at least \(MixedCandidates.range.lowerBound)."
        case 1: return "One family is a sweep, not a mix. Pick another."
        case let n where n > MixedCandidates.range.upperBound:
            return "\(n) chosen. More than \(MixedCandidates.range.upperBound) will not fit "
                + "on one board."
        default: return "\(selection.count) families"
        }
    }

    private func toggle(_ stem: String) {
        if selection.contains(stem) { selection.remove(stem) } else { selection.insert(stem) }
    }
}

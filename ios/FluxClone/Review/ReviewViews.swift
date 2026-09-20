import SwiftUI

private let accent = Color(uiColor: FluxTheme.main)
private let bg = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)
private let error = Color(uiColor: FluxTheme.colorfulError)

/// Review. After every board, and the engine of the app.
///
/// Four tabs over one board, because the four questions are different and a single scroll
/// answers none of them well:
///
/// | tab | the question |
/// | Leaks | what should I act on -- six items, ranked by expected value across all boards |
/// | Words | what are the best words here to learn, in points a game |
/// | Families | everything that was on the board, and how much of each I took |
/// | Board | the full solution |
///
/// Leaks is the opinionated one and stays the default: a board with forty misses gets six
/// items. The other three are for reading down, and they are deliberately **not** ranked
/// the same way -- each section says why.
struct ReviewView: View {
    let review: BoardReview
    let again: () -> Void
    let home: () -> Void
    let drill: (String) -> Void

    enum Tab: String, CaseIterable, Identifiable {
        case leaks = "Leaks"
        case words = "Words"
        case families = "Families"
        case board = "Board"
        var id: String { rawValue }
    }

    @State private var tab = Tab.leaks

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                verdict
                Picker("", selection: $tab) {
                    ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)

                switch tab {
                case .leaks: LeaksTab(review: review)
                case .words: WordsTab(review: review)
                case .families: FamiliesTab(review: review)
                case .board: SolutionBrowser(review: review)
                }

                buttons
            }
            .background(bg)
            .navigationDestination(for: String.self) { stem in
                FamilyPageView(stem: stem, drill: drill)
            }
        }
        .onAppear { Progression.markAnnounced(review.transitions) }
    }

    /// SPEC 9.2: one line. Score, percentile against his own history on that grid and
    /// tier, and the single biggest thing that went wrong. Above the tabs, always on.
    private var verdict: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("\(review.score.formatted())")
                    .font(Font(FluxFont.bold(40)))
                    .foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 1) {
                    if let p = review.percentile {
                        Text("\(ordinal(Int((p * 100).rounded()))) on \(review.side)x\(review.side) "
                             + review.tier.displayName)
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        Text("\(review.comparedWith) game\(review.comparedWith == 1 ? "" : "s") on "
                             + "\(review.side)x\(review.side) \(review.tier.displayName) so far")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                    Text("\(review.words) of \(review.boardWords) words")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            if let leak = review.leak {
                Text("Biggest leak: \(leak.sentence)")
                    .font(.caption)
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 10)
    }

    private var buttons: some View {
        HStack(spacing: 12) {
            Button("Done", action: home).tint(accent)
            Spacer()
            Button(action: again) {
                Text("Play again").font(.headline)
                    .padding(.horizontal, 22).padding(.vertical, 10)
            }
            .buttonStyle(.borderedProminent).tint(accent).foregroundStyle(bg)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(bg)
    }

    private func ordinal(_ n: Int) -> String {
        let suffix: String
        switch (n % 100, n % 10) {
        case (11, _), (12, _), (13, _): suffix = "th"
        case (_, 1): suffix = "st"
        case (_, 2): suffix = "nd"
        case (_, 3): suffix = "rd"
        default: suffix = "th"
        }
        return "\(n)\(suffix)"
    }
}

// MARK: - Leaks

/// The opinionated tab: at most six items, ranked by what closing them is worth across
/// every board, never by what cost the most here. One board's misses are mostly board luck.
private struct LeaksTab: View {
    let review: BoardReview

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !review.mixed.isEmpty { mixed }
                if !review.transitions.isEmpty { transitions }
                if review.items.isEmpty {
                    Text("Nothing on this board was worth more than a point a game to you. "
                         + "That is a good board, not a quiet review.")
                        .font(.footnote).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                ForEach(review.items) { item in
                    switch item {
                    case .family(let gap): FamilyGapCard(review: review, gap: gap)
                    case .word(let gap): WordGapCard(review: review, gap: gap)
                    }
                }
                if !review.misswipes.isEmpty { misswipes }
                if !review.duplicates.isEmpty { duplicates }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    /// Mixed practice, scored per family. The board itself said nothing about which
    /// families were in it, which is the whole point; this is the breakdown afterwards.
    private var mixed: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("The families you were carrying", detail: "")
            ForEach(review.mixed) { row in
                NavigationLink(value: row.stem) {
                    HStack {
                        Text("\(row.stem)-").font(.body.monospaced()).foregroundStyle(accent)
                        Spacer()
                        Text(row.label)
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(colour(row.outcome))
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(panel))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func colour(_ outcome: BoardReview.MixedResult.Outcome) -> Color {
        switch outcome {
        case .completed: return accent
        case .part: return .orange
        case .missed: return error
        case .absent: return .secondary
        }
    }

    /// Said once, and then never again. No streaks, no XP: the point is information.
    private var transitions: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(review.transitions) { t in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: t.to == "known" ? "checkmark.seal.fill"
                                                      : "arrow.uturn.backward")
                        .foregroundStyle(t.to == "known" ? accent : error)
                    Text(t.sentence)
                        .font(.footnote).foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(panel))
    }

    /// Only two of the four causes are learnable. The other two are shown as what they
    /// are -- motor slips -- and teach nothing, which is the point of separating them.
    private var misswipes: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("Strings you swiped that are not words",
                         detail: String(format: "%d · %.1f s", review.misswipes.count,
                                        review.misswipeSeconds))
            ForEach(review.misswipes) { finding in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(finding.word).font(.body.monospaced()).foregroundStyle(error)
                        Text(finding.cause.label).font(.caption2).foregroundStyle(.tertiary)
                        Spacer()
                        if finding.lifetimeCount > 1 {
                            Text("\(finding.lifetimeCount)x")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(finding.lifetimeCount >= 4 ? .orange : .secondary)
                        }
                    }
                    Text(finding.sentence)
                        .font(.caption)
                        .foregroundStyle(finding.cause.isLearnable ? .secondary : .tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(panel))
            }
        }
    }

    /// Nothing outside review tells him this is happening, and it is the cheapest thing on
    /// any board to stop doing.
    private var duplicates: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("Words you swiped twice",
                         detail: String(format: "%.1f s", review.duplicateSeconds))
            HStack {
                ForEach(review.duplicates, id: \.word) { d in
                    Text(d.word)
                        .font(.caption.monospaced())
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(RoundedRectangle(cornerRadius: 6).fill(panel))
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
    }

    private func sectionTitle(_ text: String, detail: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(text).font(.subheadline.weight(.semibold)).foregroundStyle(.white)
            Spacer()
            Text(detail).font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
        }
    }
}

// MARK: - Words

/// Every missed word the queue can price, in points a game.
///
/// `expectedGain` is `presences per game x points x (achievable rate - my rate)`, measured
/// over 2,865 ranked boards -- so a word near the top turns up often, is worth a lot, and
/// is one that somebody who sees it takes and he does not. It is not "the biggest word on
/// this board", and it deliberately does not reward a word he already takes reliably.
///
/// The **alpha** filter is the other half of the question. rank.py splits every word on
/// whether the field takes it less than 10% of the time: below that it is vocabulary
/// almost nobody has, and finding it at all is the win; at or above it, it is a word he is
/// expected to take and is not seeing. Two different problems, and this is how to look at
/// one without the other.
private struct WordsTab: View {
    let review: BoardReview
    @State private var alphaOnly = false
    @State private var selected: String?

    private var alphaCount: Int { review.rankedWords.filter(\.branch.isAlpha).count }
    private var rows: [WordGap] {
        alphaOnly ? review.rankedWords.filter(\.branch.isAlpha) : review.rankedWords
    }

    var body: some View {
        VStack(spacing: 8) {
            Picker("", selection: $alphaOnly) {
                Text("All \(review.rankedWords.count)").tag(false)
                Text("Alpha \(alphaCount)").tag(true)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 20)

            if alphaOnly {
                Text("\u{03B1} — the field finds these on fewer than one board in ten. "
                     + "Learning them is vocabulary, not vision.")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .padding(.horizontal, 20)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if rows.isEmpty {
                Spacer()
                Text(alphaOnly ? "No alpha words were missed here."
                               : "Nothing the queue can price was missed here.")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
            } else {
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(rows, id: \.word) { gap in
                            WordRow(review: review, gap: gap, expanded: selected == gap.word) {
                                selected = selected == gap.word ? nil : gap.word
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 24)
                }
            }
        }
    }
}

/// One word, with the numbers that say why it is worth learning, and its path on tap.
private struct WordRow: View {
    let review: BoardReview
    let gap: WordGap
    let expanded: Bool
    let tap: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: tap) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(gap.word).font(.body.monospaced()).foregroundStyle(.white)
                            .lineLimit(1).minimumScaleFactor(0.7)
                        if gap.branch.isAlpha { AlphaBadge() }
                        Spacer(minLength: 4)
                        Text(String(format: "+%.1f/game", gap.branch.expectedGain))
                            .font(.caption.monospacedDigit()).foregroundStyle(accent)
                            .lineLimit(1)
                    }
                    Text(rateLine).font(.caption2).foregroundStyle(.tertiary)
                        .lineLimit(2).minimumScaleFactor(0.85)
                }
            }
            .buttonStyle(.plain)

            if expanded {
                HStack(alignment: .top, spacing: 14) {
                    MiniBoard(letters: review.letters, side: review.side, path: gap.path,
                              tileSize: cardTile(side: review.side), spacing: 3)
                    VStack(alignment: .leading, spacing: 4) {
                        NavigationLink(value: gap.stem) {
                            Text("\(gap.stem)-  \(gap.branch.ext)")
                                .font(.caption.monospaced()).foregroundStyle(accent)
                        }
                        Text(gap.sentence)
                            .font(.caption2).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(panel))
    }

    /// "1400 pts · on 243 boards · you 1% · field 8% · top 25% 28%" -- everything needed
    /// to judge whether the word is worth the effort, in one line.
    private var rateLine: String {
        var parts = ["\(gap.points) pts"]
        if gap.branch.presences > 0 { parts.append("on \(gap.branch.presences) boards") }
        if let mine = gap.branch.myRate { parts.append("you \(pct(mine))") }
        if let field = gap.branch.fieldRate { parts.append("field \(pct(field))") }
        if let top = gap.branch.topQuartileRate { parts.append("top 25% \(pct(top))") }
        return parts.joined(separator: " · ")
    }

    private func pct(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }
}

/// The field takes it less than one time in ten (rank.py). Vocabulary, not vision.
///
/// One glyph, because it sits inside a word row next to the word, the points and the
/// gain, and the word "alpha" spelled out wraps to four lines in that space. The Words tab
/// carries the sentence that explains it.
struct AlphaBadge: View {
    var body: some View {
        Text("\u{03B1}")
            .font(.caption.weight(.bold))
            .frame(width: 16, height: 16)
            .background(Circle().fill(Color.purple.opacity(0.45)))
            .foregroundStyle(Color(uiColor: FluxTheme.text))
            .fixedSize()
    }
}

/// Tile size for a board drawn inside a card. A 5x5 at the 4x4 size is 190 points wide
/// and leaves nothing for the words beside it, which is how ERASE ended up broken across
/// three lines.
func cardTile(side: Int) -> CGFloat { side >= 5 ? 22 : 27 }

// MARK: - Families

/// Everything on the board, read off the solve rather than out of the shipped record, so
/// the big obvious families are in it too.
///
/// Sorted by the points left on the table, which is the question a browse answers: what
/// was here, and how much of it did I take. Leaks is the tab sorted by what closing a gap
/// is worth a game; sorting this list that way would order it by whether Phase 2 had an
/// opinion about the family, which most of the time it does not.
private struct FamiliesTab: View {
    let review: BoardReview

    /// Points left is a defensible order and it degenerates: a family's points are its
    /// size, so the list opens with ING- and its 89 members, which is not a family anyone
    /// hunts for. **Cues** is the filter that fixes it, using SPEC 7.5's own band rather
    /// than a number picked for the screen -- between two and six members, "what else
    /// hangs off this" is a question with an answer. All and In the queue are still there,
    /// because the big obvious families are worth being able to open too.
    enum Scope: String, CaseIterable, Identifiable {
        case cues = "Cues"
        case all = "All"
        case queue = "In the queue"
        var id: String { rawValue }
    }

    @State private var scope = Scope.cues
    @State private var open: String?

    private func matching(_ scope: Scope) -> [BoardFamily] {
        switch scope {
        case .all: return review.families
        case .cues: return review.families.filter(\.isCue)
        case .queue: return review.families.filter(\.ranked)
        }
    }

    private var rows: [BoardFamily] {
        Array(matching(scope).prefix(BoardFamilies.listCap))
    }

    var body: some View {
        VStack(spacing: 8) {
            Picker("", selection: $scope) {
                ForEach(Scope.allCases) { s in
                    Text("\(s.rawValue) \(matching(s).count)").tag(s)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 20)

            if scope == .cues {
                Text("Two to six members: small enough to finish once you are on the stem.")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .padding(.horizontal, 20)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ScrollView {
                VStack(spacing: 8) {
                    ForEach(rows) { family in
                        FamilyRow(review: review, family: family, expanded: open == family.stem) {
                            open = open == family.stem ? nil : family.stem
                        }
                    }
                    let shown = rows.count
                    let total = matching(scope).count
                    if total > shown {
                        Text("\(total - shown) more families with two or more members here.")
                            .font(.caption2).foregroundStyle(.tertiary).padding(.top, 6)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
        }
    }
}

private struct FamilyRow: View {
    let review: BoardReview
    let family: BoardFamily
    let expanded: Bool
    let tap: () -> Void

    @State private var path: [Int] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: tap) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(family.stem)-")
                        .font(.body.monospaced().weight(.bold)).foregroundStyle(accent)
                    Text("\(family.found.count)/\(family.members.count)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(family.missed.isEmpty ? accent : .secondary)
                    if !family.alphaMissed.isEmpty { AlphaBadge() }
                    if !family.narrower.isEmpty {
                        Text("+\(family.narrower.count)")
                            .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                    }
                    Spacer()
                    if family.pointsMissed > 0 {
                        Text("\(family.pointsMissed.formatted()) left")
                            .font(.caption.monospacedDigit()).foregroundStyle(error)
                    }
                    if family.gainMissed > 0 {
                        Text(String(format: "+%.1f/g", family.gainMissed))
                            .font(.caption2.monospacedDigit()).foregroundStyle(accent)
                    }
                }
            }
            .buttonStyle(.plain)

            if expanded {
                HStack(alignment: .top, spacing: 14) {
                    MiniBoard(letters: review.letters, side: review.side, path: path,
                              tileSize: cardTile(side: review.side) - 2, spacing: 3)
                    VStack(alignment: .leading, spacing: 6) {
                        chips(family.missed, found: false)
                        if !family.found.isEmpty { chips(family.found, found: true) }
                        if !family.narrower.isEmpty {
                            // SPEC 12.2's breadcrumb: the narrower stems that live inside
                            // this one, so the chain can be widened or narrowed by eye.
                            Text("also " + family.narrower.prefix(6)
                                .map { "\($0)-" }.joined(separator: " "))
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                        if family.ranked {
                            NavigationLink(value: family.stem) {
                                Text("Open \(family.stem)-")
                                    .font(.caption2).foregroundStyle(accent)
                            }
                        }
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(panel))
    }

    /// Missed in red, found in the accent, all of them tappable to draw the path. Longest
    /// first: the expensive miss is the one worth looking at.
    private func chips(_ words: [SolvedWord], found: Bool) -> some View {
        FlowRow(spacing: 5) {
            ForEach(words.sorted { $0.points != $1.points ? $0.points > $1.points
                                                          : $0.word < $1.word },
                    id: \.word) { word in
                Button { path = word.paths.first ?? [] } label: {
                    Text(word.word)
                        .font(.caption2.monospaced())
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(RoundedRectangle(cornerRadius: 4)
                            .fill(Color(uiColor: FluxTheme.bg)))
                        .foregroundStyle(found ? accent : error)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// A wrapping row of chips. A family can have thirty members, and an `HStack` puts all
/// thirty on one line off the edge of the screen.
struct FlowRow: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > width, x > 0 {
                x = 0
                y += lineHeight + spacing
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: proposal.width ?? x, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews,
                       cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += lineHeight + spacing
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}

// MARK: - Cards used by Leaks

/// A family gap, drawn where it was: the stem lit under the board, the missed branches
/// beside it, each one tappable to put its path on the grid.
private struct FamilyGapCard: View {
    let review: BoardReview
    let gap: FamilyGap
    @State private var path: [Int] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            NavigationLink(value: gap.stem) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(gap.stem)-")
                        .font(Font(FluxFont.bold(26))).foregroundStyle(accent)
                    Text(gap.reason).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(String(format: "%.1f/game", gap.meeting.missedExpectedGain))
                        .font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                    Image(systemName: "chevron.right")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .buttonStyle(.plain)

            HStack(alignment: .top, spacing: 14) {
                MiniBoard(letters: review.letters, side: review.side,
                          stemPath: gap.stemPath ?? [],
                          path: path.isEmpty ? (gap.missed.first?.path ?? []) : path,
                          tileSize: cardTile(side: review.side), spacing: 3)
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(gap.missed.prefix(5), id: \.word) { m in
                        Button { path = m.path } label: {
                            HStack(spacing: 5) {
                                Text(m.word)
                                    .font(.caption.monospaced())
                                    .foregroundStyle(error)
                                    .lineLimit(1).minimumScaleFactor(0.7)
                                if gap.meeting.branches[m.word]?.isAlpha == true { AlphaBadge() }
                                Spacer(minLength: 2)
                                // Two different units in one column read as one, so they
                                // are labelled: points on this board, or what the queue
                                // says the word is worth a game across all of them.
                                if let g = gap.meeting.branches[m.word]?.expectedGain, g > 0 {
                                    Text(String(format: "+%.1f/g", g))
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(accent).lineLimit(1)
                                } else {
                                    Text("\(m.points) pts")
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(.tertiary).lineLimit(1)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                    if !gap.meeting.found.isEmpty {
                        Text("had: " + gap.meeting.found.map(\.word).sorted()
                            .prefix(3).joined(separator: ", "))
                            .font(.caption2).foregroundStyle(.tertiary)
                            .lineLimit(1).minimumScaleFactor(0.8)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(panel))
    }
}

/// One word, on screen because of what it is worth across every board he has played --
/// never because of what happened on this one.
private struct WordGapCard: View {
    let review: BoardReview
    let gap: WordGap

    var body: some View {
        NavigationLink(value: gap.stem) {
            HStack(alignment: .top, spacing: 14) {
                MiniBoard(letters: review.letters, side: review.side, path: gap.path,
                          tileSize: cardTile(side: review.side) - 3, spacing: 3)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(gap.word).font(.body.monospaced()).foregroundStyle(error)
                            .lineLimit(1).minimumScaleFactor(0.7)
                        Text("\(gap.points)")
                            .font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                        if gap.branch.isAlpha { AlphaBadge() }
                        Spacer()
                        Text("\(gap.stem)-").font(.caption.monospaced()).foregroundStyle(accent)
                    }
                    Text(gap.sentence)
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(panel))
        }
        .buttonStyle(.plain)
    }
}

/// SPEC 12.3, the thin version: every word on the board, with its path one tap away.
private struct SolutionBrowser: View {
    let review: BoardReview
    @State private var missedOnly = true
    @State private var selected: String?

    private var rows: [SolvedWord] {
        review.solved.words
            .filter { !missedOnly || !review.found.contains($0.word) }
            .sorted { $0.points != $1.points ? $0.points > $1.points : $0.word < $1.word }
    }

    var body: some View {
        VStack(spacing: 8) {
            Picker("", selection: $missedOnly) {
                Text("Missed \(review.boardWords - review.words)").tag(true)
                Text("All \(review.boardWords)").tag(false)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 20)

            if let selected, let word = review.solved.word(selected) {
                MiniBoard(letters: review.letters, side: review.side,
                          path: word.paths.first ?? [], tileSize: cardTile(side: review.side),
                          spacing: 3)
            }

            List(rows, id: \.word) { word in
                Button { selected = selected == word.word ? nil : word.word } label: {
                    HStack {
                        Text(word.word)
                            .font(.body.monospaced())
                            .foregroundStyle(review.found.contains(word.word) ? accent : .white)
                        Spacer()
                        Text("\(word.points)")
                            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
                .listRowBackground(selected == word.word ? panel : Color.clear)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
    }
}

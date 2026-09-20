import SwiftUI

private let accent = Color(uiColor: FluxTheme.main)
private let bg = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)

/// The whole session, one screen at a time. Nothing here asks which hook to work on and
/// nothing here has a menu.
struct SessionView: View {
    @ObservedObject var session: TrainingSession
    let onExit: () -> Void

    var body: some View {
        Group {
            switch session.screen {
            case .preparing(let what):
                PreparingView(what: what, onExit: exit)
            case .brief(let hook, let gaps, let state):
                VisionBriefView(hook: hook, gaps: gaps) { session.startBriefedBoard(state) }
            case .board(let state):
                GameHost(board: state.board.board, mode: state.mode) { result in
                    session.boardFinished(state, result: result)
                }
                .id(state.exerciseId)
                .ignoresSafeArea()
            case .verdict(let verdict):
                VerdictView(verdict: verdict,
                            again: session.repeatBoard,
                            onward: verdict.canRepeat ? session.skipHook : session.next)
            case .affixGrid(let hook, let id, let seq):
                AffixGridView(hook: hook, exerciseId: id, sessionId: session.sessionId,
                              seq: seq) { correct, total, abandoned in
                    session.affixGridFinished(exerciseId: id, correct: correct, total: total,
                                              abandoned: abandoned)
                }
            case .summary(let summary):
                SummaryView(summary: summary, queue: session.queue, done: exit)
            case .failed(let message):
                FailureView(message: message, done: exit)
            }
        }
        .background(bg)
    }

    private func exit() {
        if case .summary = session.screen {} else { session.abandon() }
        onExit()
    }
}

private struct PreparingView: View {
    let what: String
    let onExit: () -> Void

    var body: some View {
        VStack(spacing: 18) {
            ProgressView().tint(accent).scaleEffect(1.4)
            Text(what).foregroundStyle(.secondary)
            Button("Leave", action: onExit).padding(.top, 30)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }
}

/// After a drill board. The spatial half used to happen on the board itself -- the missed
/// branches walked their paths on a timer -- and that is gone: the answer is already known
/// by the time an animation starts, and waiting for it is the cost of every board. The
/// paths are here instead, static, and tapping a word puts it on the grid for as long as
/// it is wanted.
///
/// **Ordered by what each word is worth a game, not by how fast it was found.** Time is
/// the result; value is the reason the word is on the list. A page sorted by result cannot
/// be read as "these are the ones to learn", which is the only thing this page is for.
private struct VerdictView: View {
    let verdict: TrainingSession.Verdict
    let again: () -> Void
    let onward: () -> Void

    @State private var path: [Int] = []
    @State private var selected: String?

    private var rows: [TrainingSession.Verdict.Outcome] { verdict.missed + verdict.found }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if !rows.isEmpty {
                HStack {
                    Spacer()
                    MiniBoard(letters: verdict.letters, side: verdict.side,
                              stemPath: verdict.stemPath,
                              path: path.isEmpty ? (rows.first?.path ?? []) : path,
                              tileSize: verdict.side >= 5 ? 26 : 32)
                    Spacer()
                }
            }
            ScrollView {
                VStack(spacing: 6) {
                    ForEach(rows) { outcome in
                        row(outcome)
                    }
                }
            }
            buttons
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let hook = verdict.hook {
                Text(verdict.stemWasLit ? "\(hook.stem)- lit" : "\(hook.stem)-")
                    .font(Font(FluxFont.bold(34)))
                    .foregroundStyle(accent)
                Text("\(verdict.found.count) of \(verdict.found.count + verdict.missed.count)"
                     + (verdict.stemWasLit ? " with the stem lit" : " unprompted")
                     + " · worth \(String(format: "%.1f", totalGain)) a game")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                Text("Warm-up done")
                    .font(Font(FluxFont.bold(30)))
                    .foregroundStyle(accent)
                Text("\(verdict.score) points. Nothing recorded against the queue.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .padding(.top, 16)
    }

    private var totalGain: Double { rows.reduce(0) { $0 + $1.gain } }

    /// Seconds, and the numbers that say whether the word is worth the effort. On a word
    /// the grid says he knows, seconds is the only thing that can move, and "3 of 4" would
    /// read the same in week 1 and week 6.
    private func row(_ outcome: TrainingSession.Verdict.Outcome) -> some View {
        let found = outcome.seconds != nil
        return Button {
            path = outcome.path
            selected = selected == outcome.word ? nil : outcome.word
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(outcome.word)
                        .font(.body.monospaced())
                        .foregroundStyle(found ? accent : Color(uiColor: FluxTheme.colorfulError))
                    if outcome.branch?.isAlpha == true { AlphaBadge() }
                    if outcome.knowledge == .known {
                        Text("you know this").font(.caption2).foregroundStyle(.tertiary)
                    } else if outcome.knowledge == .unknown {
                        Text("new").font(.caption2).foregroundStyle(.tertiary)
                    }
                    Spacer()
                    if let seconds = outcome.seconds {
                        Text(String(format: "%.1fs", seconds))
                            .font(.body.monospacedDigit()).foregroundStyle(.white)
                        if let delta = outcome.improvement, abs(delta) >= 0.2 {
                            Text(String(format: "%@%.1f", delta > 0 ? "\u{2212}" : "+", abs(delta)))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(delta > 0 ? accent : .orange)
                        }
                    } else {
                        Text("missed").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let line = detail(outcome) {
                    Text(line).font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8)
                .fill(selected == outcome.word ? Color(uiColor: FluxTheme.sub) : panel))
        }
        .buttonStyle(.plain)
    }

    /// "-ERS · 800 pts · +10.7/game · on 241 boards · you 42% · field 47% · top 25% 58%".
    /// The case for learning the word, in his own numbers and the field's.
    private func detail(_ outcome: TrainingSession.Verdict.Outcome) -> String? {
        guard let b = outcome.branch else { return nil }
        var parts: [String] = []
        if !b.ext.isEmpty { parts.append(b.ext) }
        parts.append("\(b.points) pts")
        if b.expectedGain > 0 { parts.append(String(format: "+%.1f/game", b.expectedGain)) }
        if b.presences > 0 { parts.append("on \(b.presences) boards") }
        if let mine = b.myRate { parts.append("you \(pct(mine))") }
        if let field = b.fieldRate { parts.append("field \(pct(field))") }
        if let top = b.topQuartileRate { parts.append("top 25% \(pct(top))") }
        return parts.joined(separator: " · ")
    }

    private func pct(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }

    private var buttons: some View {
        VStack(spacing: 8) {
            if verdict.canRepeat {
                // One tap to repeat. The second attempt is where it sticks.
                Button(action: again) {
                    Text("Again, new board")
                        .font(.title3.weight(.heavy))
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent).tint(accent)
                .foregroundStyle(bg)
            }
            Button(action: onward) {
                Text(verdict.canRepeat ? "Move on" : "Next")
                    .font(.body.weight(.bold))
                    .frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .tint(accent)
        }
    }
}

/// The card that was missing. One hook, its worst two words, in the player's own numbers.
private struct VisionBriefView: View {
    let hook: Hook
    let gaps: [SightGap]
    let start: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            Text("\(hook.stem)-")
                .font(Font(FluxFont.bold(52)))
                .foregroundStyle(accent)
            ForEach(gaps, id: \.word) { gap in
                Text(gap.sentence)
                    .font(.body)
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 10).fill(panel))
            }
            Text("This is a seeing problem, not a knowing problem. The stem will be lit; "
                 + "find what hangs off it.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button(action: start) {
                Text("Go").font(.title2.weight(.heavy))
                    .frame(maxWidth: .infinity).padding()
            }
            .buttonStyle(.borderedProminent).tint(accent).foregroundStyle(bg)
        }
        .padding(.horizontal, 26)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }
}

/// Twenty seconds. What stuck, and what to expect tomorrow.
private struct SummaryView: View {
    let summary: TrainingSession.Summary
    let queue: TrainingQueue
    let done: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer()
            Text("Done").font(Font(FluxFont.bold(48))).foregroundStyle(accent)

            if summary.litTotal > 0 {
                line("With the stem lit", "\(summary.litFound) of \(summary.litTotal)")
            }
            if summary.unpromptedTotal > 0 {
                // The number that actually matters, and the one the gate is about.
                line("Unprompted", "\(summary.unpromptedFound) of \(summary.unpromptedTotal)")
            }
            if summary.judgements > 0 {
                line("Affix grid", "\(summary.judgementsCorrect) of \(summary.judgements)"
                     + (summary.medianJudgementLatency.map { String(format: " · %.2f s", $0) } ?? ""))
            }
            if summary.judgedKnown + summary.judgedShaky + summary.judgedUnknown > 0 {
                // The distinction the app could not make before: of the words the queue
                // is teaching, how many are vocabulary and how many are vision.
                line("Words you knew", "\(summary.judgedKnown)")
                if summary.judgedShaky > 0 { line("Had to work for", "\(summary.judgedShaky)") }
                if summary.judgedUnknown > 0 { line("Genuinely new", "\(summary.judgedUnknown)") }
            }
            if !summary.sightTimes.isEmpty {
                let sorted = summary.sightTimes.sorted()
                line("Median time to find", String(format: "%.1fs", sorted[sorted.count / 2]))
            }
            line("Boards", "\(summary.boards)")
            if summary.degradedBoards > 0 {
                // Never silently serve a board that missed its targets.
                line("Boards short of their constraints", "\(summary.degradedBoards)")
            }

            Divider().overlay(Color.white.opacity(0.15)).padding(.vertical, 6)

            Text("Tomorrow").font(.headline).foregroundStyle(.white)
            if let tomorrow = summary.tomorrowHook {
                Text("\(tomorrow)- is next up.").foregroundStyle(.secondary)
            }
            if summary.dueTomorrow > 0 {
                Text("\(summary.dueTomorrow) hook\(summary.dueTomorrow == 1 ? "" : "s") due for a sweep.")
                    .foregroundStyle(.secondary)
            }
            Spacer()

            Text(queue.recomputedText)
                .font(.caption2)
                .foregroundStyle(.tertiary)
            Button(action: done) {
                Text("Close").font(.title3.weight(.heavy))
                    .frame(maxWidth: .infinity).padding()
            }
            .buttonStyle(.borderedProminent).tint(accent).foregroundStyle(bg)
        }
        .padding(.horizontal, 26)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }

    private func line(_ key: String, _ value: String) -> some View {
        HStack {
            Text(key).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.body.monospacedDigit()).foregroundStyle(.white)
        }
    }
}

private struct FailureView: View {
    let message: String
    let done: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Text(message).multilineTextAlignment(.center).foregroundStyle(.secondary)
            Button("Back", action: done).tint(accent)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }
}

/// The daily session, as a row rather than a slab.
///
/// Phase 3 had this as the biggest thing on the screen, above Play. It is smaller now on
/// purpose: the drill is something review sends you to, and a session that has to compete
/// with the board for attention is a session that gets opened out of guilt. It is still
/// one tap, and it still never asks which hook.
struct TrainCard: View {
    @ObservedObject var queue: TrainingQueue
    let start: (_ shortDay: Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { start(false) } label: {
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(TrainingSession.Resume.pending ? "Resume today's session" : "Train")
                            .font(.headline)
                            .foregroundStyle(.white)
                        Text(subtitle).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                }
            }
            HStack {
                Button("Short day") { start(true) }
                    .font(.caption.weight(.semibold))
                    .tint(accent)
                Spacer()
                Text(queue.recomputedText)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private var subtitle: String {
        guard let next = queue.ranked.first(where: \.eligible) else {
            return "warm-up and a sweep"
        }
        return "next up: \(next.hook.stem)- · \(next.unknown + next.learning) branches open"
    }
}

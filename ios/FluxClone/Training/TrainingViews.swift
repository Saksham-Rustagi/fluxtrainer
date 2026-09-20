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

/// SPEC 9.2: one card, fifteen seconds, then straight on. The spatial half of the review
/// already happened on the board -- the missed branches were drawn along their paths.
private struct VerdictView: View {
    let verdict: TrainingSession.Verdict
    let again: () -> Void
    let onward: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer()
            if let hook = verdict.hook {
                Text(verdict.stemWasLit ? "\(hook.stem)- lit" : "\(hook.stem)-")
                    .font(Font(FluxFont.bold(40)))
                    .foregroundStyle(accent)
                Text("\(verdict.found.count) of \(verdict.found.count + verdict.missed.count)"
                     + (verdict.stemWasLit ? " with the stem lit" : " unprompted"))
                    .font(.title3)
                    .foregroundStyle(.white)
            } else {
                Text("Warm-up done")
                    .font(Font(FluxFont.bold(36)))
                    .foregroundStyle(accent)
                Text("\(verdict.score) points. Nothing recorded against the queue.")
                    .foregroundStyle(.secondary)
            }

            VStack(spacing: 6) {
                ForEach(verdict.found) { row($0, found: true) }
                ForEach(verdict.missed) { row($0, found: false) }
            }
            Spacer()

            if verdict.canRepeat {
                // One tap to repeat. The second attempt is where it sticks.
                Button(action: again) {
                    Text("Again, new board")
                        .font(.title2.weight(.heavy))
                        .frame(maxWidth: .infinity).padding()
                }
                .buttonStyle(.borderedProminent).tint(accent)
                .foregroundStyle(bg)
            }
            Button(action: onward) {
                Text(verdict.canRepeat ? "Move on" : "Next")
                    .font(.title3.weight(.bold))
                    .frame(maxWidth: .infinity).padding(.vertical, 10)
            }
            .tint(accent)
        }
        .padding(.horizontal, 26)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(bg)
    }

    /// Seconds, not a tick. On a word the grid says you know, seconds is the only thing
    /// that can move, and "3 of 4" would read the same in week 1 and week 6.
    private func row(_ outcome: TrainingSession.Verdict.Outcome, found: Bool) -> some View {
        HStack(spacing: 10) {
            Text(outcome.word)
                .font(.body.monospaced())
                .foregroundStyle(found ? accent : Color(uiColor: FluxTheme.colorfulError))
            if outcome.knowledge == .known {
                Text("you know this")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else if outcome.knowledge == .unknown {
                Text("new")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            if let seconds = outcome.seconds {
                Text(String(format: "%.1fs", seconds))
                    .font(.body.monospacedDigit())
                    .foregroundStyle(.white)
                if let delta = outcome.improvement, abs(delta) >= 0.2 {
                    Text(String(format: "%@%.1f", delta > 0 ? "−" : "+", abs(delta)))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(delta > 0 ? accent : .orange)
                }
            } else {
                Text("missed").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 8).fill(panel))
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

/// The one button. Everything about the session is decided behind it.
struct TrainCard: View {
    @ObservedObject var queue: TrainingQueue
    let start: (_ shortDay: Bool) -> Void

    var body: some View {
        VStack(spacing: 10) {
            Button { start(false) } label: {
                HStack {
                    Spacer()
                    Text(TrainingSession.Resume.pending ? "Resume" : "Train")
                        .font(.system(size: 28, weight: .heavy))
                    Spacer()
                }
                .padding(.vertical, 14)
            }
            Button("Short day (one board and a grid)") { start(true) }
                .font(.footnote)
                .tint(accent)
            if let next = queue.ranked.first(where: \.eligible) {
                Text("next: \(next.hook.stem)-")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.tertiary)
            }
            Text(queue.recomputedText)
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }
}

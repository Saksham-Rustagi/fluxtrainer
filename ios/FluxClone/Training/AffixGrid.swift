import SwiftUI

/// SPEC 7.3's affix grid: one stem, its branches one at a time, valid or not.
///
/// This is where vocabulary throughput actually lives -- 60 to 100 judgements in about
/// five minutes, against the handful of words a board gives you in the same time. It is
/// the only exercise in Phase 3 with no board, and it is the reason new hooks can enter
/// through a drill block rather than a reading screen.
///
/// **Dead branches carry equal weight.** 20% of the player's invalid attempts carry an
/// affix pattern, mostly -ER, -S, -ERS and -ES, and knowing a branch is dead is worth as
/// much as knowing one is live. So the deck is half live and half dead, and the dead half
/// is drawn from strings he has actually attempted before it is drawn from the dictionary.
struct AffixItem: Identifiable {
    let word: String
    let cls: HookClass
    /// "-ERS", "PRE-", "mutation". Shown under the word so the *pattern* is what is being
    /// learned, not the individual string.
    let ext: String
    /// Whether the string is a word. That is the judgement being asked for, and it is not
    /// the same as `cls == .additive`: a mutating form (PRATING) is a word that does not
    /// contain the stem.
    let isLive: Bool
    /// This exact string appears in the player's own invalid attempts.
    let fromMisswipe: Bool
    var id: String { word }
}

enum AffixGridBuilder {
    /// About five minutes at the 1.2 s target.
    static let deckSize = 80
    static let targetLatency = 1.2

    static func deck(for hook: Hook, size: Int = deckSize) -> [AffixItem] {
        // Live: every form that is a word. Cellmates are left out -- an anagram is not an
        // affix judgement, it is SPEC 7.6's separate drill, and mixing them would teach
        // the grid's pattern wrong.
        var live = hook.branches
            .filter { $0.cls == .additive || $0.cls == .mutating_ }
            .map { AffixItem(word: $0.word, cls: $0.cls, ext: $0.ext, isLive: true,
                             fromMisswipe: $0.misswiped > 0) }
        var dead = hook.branches
            .filter { $0.cls == .dead }
            .map { AffixItem(word: $0.word, cls: $0.cls, ext: $0.ext, isLive: false,
                             fromMisswipe: $0.misswiped > 0) }

        // Strings he has actually tried go first in both halves: a misswipe is the
        // strongest possible signal and it needs no model (SPEC 7.3.1).
        dead.sort { ($0.fromMisswipe ? 0 : 1, $0.word) < ($1.fromMisswipe ? 0 : 1, $1.word) }
        live.sort { ($0.fromMisswipe ? 0 : 1, $0.word) < ($1.fromMisswipe ? 0 : 1, $1.word) }

        let half = size / 2
        let takeLive = min(half, live.count)
        let takeDead = min(size - takeLive, dead.count)
        var deck = Array(live.prefix(takeLive)) + Array(dead.prefix(takeDead))
        if deck.count < size {  // one side ran out: top up from the other
            let extraLive = live.dropFirst(takeLive).prefix(size - deck.count)
            deck += extraLive
            let extraDead = dead.dropFirst(takeDead).prefix(size - deck.count)
            deck += extraDead
        }
        deck.shuffle()
        return deck
    }
}

struct AffixGridView: View {
    let hook: Hook
    let exerciseId: String
    let sessionId: String
    let seq: Int
    let onFinish: (_ correct: Int, _ total: Int, _ abandoned: Bool) -> Void

    @State private var deck: [AffixItem] = []
    @State private var index = 0
    @State private var shownAt = Date()
    @State private var correct = 0
    @State private var feedback: (right: Bool, item: AffixItem)?
    @State private var latencies: [Double] = []

    private var item: AffixItem? { index < deck.count ? deck[index] : nil }

    var body: some View {
        VStack(spacing: 0) {
            header
            Spacer()
            if let item {
                card(item)
            } else {
                summary
            }
            Spacer()
            if item != nil { buttons }
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: FluxTheme.bg))
        .onAppear {
            if deck.isEmpty {
                deck = AffixGridBuilder.deck(for: hook)
                shownAt = Date()
            }
        }
    }

    private var header: some View {
        HStack {
            Button { onFinish(correct, index, true) } label: {
                Image(systemName: "chevron.left").font(.title3)
            }
            .tint(Color(uiColor: FluxTheme.main))
            Spacer()
            Text("\(min(index + 1, deck.count)) / \(deck.count)")
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.top, 8)
    }

    /// SPEC 7.3: display leads with the shared part, since the pattern is the thing being
    /// learned. The stem stays in the text colour and the affix carries the emphasis.
    private func card(_ item: AffixItem) -> some View {
        VStack(spacing: 14) {
            Text(attributed(item.word))
                .font(Font(FluxFont.bold(46)))
                .minimumScaleFactor(0.5)
                .lineLimit(1)
            Text(item.ext)
                .font(.title3)
                .foregroundStyle(.secondary)
            if let feedback {
                Text(feedback.right ? "yes" : (feedback.item.isLive ? "it is a word" : "not a word"))
                    .font(.headline)
                    .foregroundStyle(feedback.right ? Color(uiColor: FluxTheme.main)
                                                    : Color(uiColor: FluxTheme.colorfulError))
            } else {
                Text(" ").font(.headline)
            }
        }
    }

    private func attributed(_ word: String) -> AttributedString {
        var out = AttributedString(word)
        out.foregroundColor = Color(uiColor: FluxTheme.main)
        if let range = out.range(of: hook.stem) {
            out[range].foregroundColor = Color(uiColor: FluxTheme.text)
        }
        return out
    }

    private var buttons: some View {
        HStack(spacing: 14) {
            answer(label: "Not a word", live: false, tint: FluxTheme.sub)
            answer(label: "Word", live: true, tint: FluxTheme.main)
        }
        .padding(.bottom, 28)
        .disabled(feedback != nil)
    }

    private func answer(label: String, live: Bool, tint: UIColor) -> some View {
        Button { record(answeredLive: live) } label: {
            Text(label)
                .font(.title3.weight(.heavy))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 22)
                .background(RoundedRectangle(cornerRadius: 14).fill(Color(uiColor: tint)))
                .foregroundStyle(Color(uiColor: FluxTheme.bg))
        }
    }

    private var summary: some View {
        VStack(spacing: 10) {
            Text("\(correct) / \(deck.count)")
                .font(Font(FluxFont.bold(58)))
                .foregroundStyle(Color(uiColor: FluxTheme.main))
            if !latencies.isEmpty {
                let median = latencies.sorted()[latencies.count / 2]
                Text(String(format: "median %.2f s", median))
                    .foregroundStyle(median <= AffixGridBuilder.targetLatency ? .secondary
                                                                             : Color.orange)
            }
            Button("Done") { onFinish(correct, deck.count, false) }
                .font(.title3.weight(.bold))
                .padding(.top, 18)
        }
        .onAppear { TrainingLog.finishAffixGrid(id: exerciseId, correct: correct,
                                                total: deck.count, abandoned: false) }
    }

    private func record(answeredLive: Bool) {
        guard let item else { return }
        let latency = Date().timeIntervalSince(shownAt)
        latencies.append(latency)
        let right = answeredLive == item.isLive
        if right { correct += 1 }
        TrainingLog.recordJudgement(exerciseId: exerciseId, seq: index, stem: hook.stem,
                                    item: item, answeredLive: answeredLive, latency: latency)
        feedback = (right, item)
        Haptics.shared.fire(right ? Haptics.submitValid : Haptics.submitInvalid)
        // A right answer moves on immediately; a wrong one holds long enough to read the
        // correction, which is the only part of the exercise that teaches.
        DispatchQueue.main.asyncAfter(deadline: .now() + (right ? 0.18 : 0.9)) {
            feedback = nil
            index += 1
            shownAt = Date()
        }
    }
}

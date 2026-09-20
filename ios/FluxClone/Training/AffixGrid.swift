import SwiftUI

/// SPEC 7.3's affix grid: one stem, its branches one at a time, valid or not.
///
/// The only exercise in Phase 3 with no board, and the way a new hook enters a session
/// without a reading screen.
///
/// **It is short.** The brief asks for 60 to 100 judgements in five minutes and calls that
/// where vocabulary throughput lives. That collides with SPEC 7.5.1 -- "the drill shows the
/// residual, not the family" -- and across the shipped queue the median hook has three
/// branches carrying any gain. Eighty cards about a three-word problem is eighty cards of
/// filler, so the deck is sized to the hook: at most eight live and at most eight dead,
/// usually nearer ten in total. The throughput claim does not survive that, and it should
/// not: the way back to 60-100 is more stems in the block, not more filler per stem.
///
/// **The dead half is the player's own invalid attempts, and nothing else.** SPEC 7.3
/// mechanism 3 mines dead affixes from the dictionary; in practice that produces TOREER
/// and GTORE, which nobody would ever swipe, and 7.3 itself says "not a word" is only
/// interesting for strings a player would plausibly try. The strongest evidence that a
/// string is plausible is that he has tried it. This starts thin -- 354 logged strings
/// cover 15% of the bundled hooks -- and fills from play at about 48 invalid attempts a
/// game.
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
    /// SPEC 7.5.1: "The drill shows the residual, not the family. You are not re-reading 38
    /// words you know to get to the two you don't." Its own bound on one sitting's work is
    /// 8, and the median hook across the whole queue has 3 branches carrying any gain, so
    /// a deck of 80 was asking an 80-item question about a 3-item problem.
    static let liveCap = 8
    static let deadCap = 8
    /// Minimum "not a word" cards in any deck, so the answer is never uniform. Met from
    /// the stem's own misswipes first and from the rest of the player's log otherwise.
    static let deadFloor = 3
    /// Below this a branch is not on the board often enough to be worth a card, even
    /// unknown (hooks.py's BRANCH_REACH_FLOOR, an order of magnitude up).
    static let topUpReachFloor = 0.02
    static let targetLatency = 1.2

    /// The live half: what the queue is actually teaching, in value order.
    ///
    /// Two tiers. First the branches carrying expected gain and not already owned -- the
    /// study items, which is what `residual` means. Then, to top up a thin hook, unknown
    /// or half-known branches that are reachable enough to meet on a board. Ordering by
    /// anything else buries STORE and STORED under PRESTORED and PROTORES.
    static func live(for hook: Hook) -> [AffixItem] {
        func item(_ b: Branch) -> AffixItem {
            AffixItem(word: b.word, cls: b.cls, ext: b.ext, isLive: true,
                      fromMisswipe: b.misswiped > 0)
        }
        let candidates = hook.branches.filter { $0.cls == .additive || $0.cls == .mutating_ }
        let study = candidates
            .filter { $0.earns && $0.status != "known" && $0.expectedGain > 0 }
            .sorted { $0.expectedGain > $1.expectedGain }
        var out = study.prefix(liveCap).map(item)
        if out.count < liveCap {
            let taken = Set(out.map(\.word))
            let topUp = candidates
                .filter { !taken.contains($0.word) && $0.status != "known"
                          && $0.reachability >= topUpReachFloor }
                .sorted { $0.reachability > $1.reachability }
            out += topUp.prefix(liveCap - out.count).map(item)
        }
        return out
    }

    /// The dead half: strings the player has actually swiped and had rejected, and nothing
    /// else.
    ///
    /// This departs from SPEC 7.3 mechanism 3, which mines dead affixes from the
    /// dictionary and keeps the ~30 most productive that do not complete the stem. That
    /// set is mostly unreachable in practice -- for TORE- it produces TOREER, TOREING,
    /// GTORE -- and 7.3 is itself explicit that "not a word" is only interesting for
    /// strings a player would plausibly try. The strongest evidence that a string is
    /// plausible is that he has tried it, which is SPEC 7.3.1's first ranking rule.
    ///
    /// The cost is coverage: 354 strings in the log today cover 15% of the bundled hooks,
    /// so most grids start with no dead half at all. It fills from play -- the clone
    /// measures 48 invalid attempts a game -- and `inApp` is that feed.
    static func dead(for hook: Hook, shipped: [String: Int], inApp: [String: Int])
        -> [AffixItem] {
        var counts: [String: Int] = [:]
        for (word, times) in shipped { counts[word] = times }
        for (word, times) in inApp { counts[word, default: 0] += times }
        let byFrequency = counts.sorted {
            $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key
        }
        func item(_ pair: (key: String, value: Int)) -> AffixItem {
            AffixItem(word: pair.key, cls: .dead,
                      ext: pair.key.contains(hook.stem) ? extDisplay(pair.key, stem: hook.stem)
                                                        : "your own misswipe",
                      isLive: false, fromMisswipe: true)
        }

        let onStem = byFrequency
            .filter { $0.key.count > hook.stem.count && $0.key.contains(hook.stem) }
        var out = onStem.prefix(deadCap).map(item)

        // A deck whose answer is "Word" every time teaches one thing: press Word. And
        // pressing Word fast on a word you do not know reads as `known` and corrupts the
        // sort, which is the one job this screen has. So a stem with nothing logged
        // against it borrows from the rest of his own log -- still only strings he has
        // actually swiped and had rejected, just met under a different stem.
        if out.count < deadFloor {
            let taken = Set(out.map(\.word))
            out += byFrequency
                .filter { !taken.contains($0.key) }
                .prefix(deadFloor - out.count)
                .map(item)
        }
        return out
    }

    /// "-ER", "PRE-", "RE--S": how the string reads against the stem.
    static func extDisplay(_ word: String, stem: String) -> String {
        guard let range = word.range(of: stem) else { return word }
        let front = String(word[word.startIndex..<range.lowerBound])
        let back = String(word[range.upperBound...])
        switch (front.isEmpty, back.isEmpty) {
        case (true, true): return stem
        case (false, true): return front + "-"
        case (true, false): return "-" + back
        case (false, false): return front + "--" + back
        }
    }

    static func deck(for hook: Hook, shipped: [String: Int] = [:],
                     inApp: [String: Int] = [:]) -> [AffixItem] {
        var deck = live(for: hook) + dead(for: hook, shipped: shipped, inApp: inApp)
        deck.shuffle()
        return deck
    }

    /// Invalid attempts made inside the app that contain this stem. Every board played
    /// here logs its rejected swipes exactly as the clone does, so the dead half grows
    /// out of the player's own play rather than out of the dictionary.
    static func inAppMisswipes(stem: String) -> [String: Int] {
        var out: [String: Int] = [:]
        Database.shared.query("""
            SELECT letters, COUNT(*) FROM attempt
            WHERE result = 'invalid' AND reason = 'not_word'
              AND length(letters) > ? AND instr(letters, ?) > 0
            GROUP BY letters
            """, [stem.count, stem]) { row in
            out[row.text(0)] = row.int(1)
        }
        return out
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
                deck = AffixGridBuilder.deck(
                    for: hook,
                    shipped: HookBundle.shared?.misswipes ?? [:],
                    inApp: AffixGridBuilder.inAppMisswipes(stem: hook.stem))
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
        .overlay(alignment: .bottom) {
            // Says what the grid is for, because it is no longer only a teaching screen:
            // the answer and the latency decide whether the board drill that follows is
            // about seeing the word or about knowing it.
            Text("quick check \u{2014} answer fast")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .offset(y: 16)
        }
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

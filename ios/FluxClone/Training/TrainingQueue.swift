import Foundation

/// The queue, as the app holds it: Phase 2's ranking plus everything the app has learned
/// since. Phase 2's ordering formula is reproduced here rather than re-derived, so a hook
/// that nothing has happened to keeps exactly the rank the TSV gives it.
///
/// Three things have to be visible as the app plays, and each is a line in `recompute`:
///
///   * a hook that has been learned falls in the ranking on its own
///   * a word picked up elsewhere stops being taught
///   * candidates Phase 2 dropped for want of evidence become rankable as presences pile up
///
/// The third is the one that does not fully work, and it is worth saying plainly rather
/// than shipping a function that pretends. Phase 2 dropped 2,161 alpha candidates because
/// their *top-quartile* rate rested on fewer than 30 presences (rank.py's `MIN_TOPQ`), and
/// in-app play adds the player's own presences, not the field's. Those words become
/// rankable only in the sense that `myRate` and the presence floor below move; the
/// top-quartile reference stays untrusted until the next ranked export. `promotable` below
/// reports how many crossed each of the two conditions, so the distinction is on screen.
@MainActor
final class TrainingQueue: ObservableObject {
    struct WordState {
        var inAppPresences = 0
        var inAppFinds = 0
        var weightedFinds = 0.0
        var weightedOpportunity = 0.0
    }

    struct Ranked: Identifiable {
        let hook: Hook
        var owned: Int
        var learning: Int
        var unknown: Int
        var expectedGain: Double
        var effort: Double
        var score: Double
        /// The session's filter: SPEC 7.5's cue band, and 7.5.1's "you already have the
        /// stem, the motor pattern and the habit of looking there".
        var eligible: Bool
        var id: String { hook.stem }
    }

    // Phase 2's ordering, rank.py. Reproduced, not reinvented: a change on either side
    // that is not made on both shows up as a hook jumping rank for no reason.
    static let cost: [HookClass: Double] = [.additive: 1.0, .cellmate: 1.3,
                                            .mutating_: 0.35, .dead: 0.35]
    static let ownedDiscount = 0.6
    static let deadGridCap = 8
    static let misswipeWeight = 0.2
    static let minTopQuartile = 30   // rank.py MIN_TOPQ
    static let minPresences = 20     // rank.py MIN_PRES_WORD
    static let minLength = 4         // rank.py MIN_LEN
    static let enumerabilityBand = 2.0...6.0
    static let minOwned = 2

    @Published private(set) var ranked: [Ranked] = []
    @Published private(set) var lastRecomputed: Date?
    @Published private(set) var promotable = (myRateMoved: 0, stillUntrusted: 0)

    let bundle: HookBundle
    private var words: [String: WordState] = [:]
    private var beliefs: [String: Double] = [:]

    init(bundle: HookBundle) {
        self.bundle = bundle
        lastRecomputed = Self.storedRecomputeDate()
        recompute()
    }

    // MARK: Picking

    /// The app chooses the hook. Never ask.
    ///
    /// Top of the queue, filtered to the cue band and to hooks with two branches already
    /// owned, skipping anything drilled in the last `cooldownDays` so a session does not
    /// serve the same stem twice in a week.
    func nextHook(cooldownDays: Int = 7, excluding: Set<String> = []) -> Hook? {
        let recent = Self.recentlyDrilled(days: cooldownDays)
        return ranked.first {
            $0.eligible && !excluding.contains($0.hook.stem) && !recent.contains($0.hook.stem)
        }?.hook
    }

    /// Hooks whose simple due date has arrived. Phase 4 replaces this with FSRS; the brief
    /// is explicit that Phase 3 gets a due date and nothing more.
    func dueHooks(limit: Int = 2) -> [Hook] {
        var due: [String] = []
        let now = Self.iso.string(from: Date())
        Database.shared.query(
            "SELECT stem FROM hook_state WHERE due_wall IS NOT NULL AND due_wall <= ? "
                + "ORDER BY due_wall LIMIT ?", [now, limit]) { row in
            due.append(row.text(0))
        }
        let byStem = Dictionary(uniqueKeysWithValues: bundle.hooks.map { ($0.stem, $0) })
        return due.compactMap { byStem[$0] }
    }

    func hook(_ stem: String) -> Hook? { bundle.hooks.first { $0.stem == stem } }

    // MARK: Recompute

    /// Reads everything the app has recorded and reprices. Cheap enough to run at session
    /// end: two grouped selects and a pass over the bundled hooks.
    func recompute() {
        words = Self.loadWordState()
        // The affix grid's sort overrides belief on the vocabulary question. Belief is
        // derived from find rate and so cannot tell "never heard of it" from "never see
        // it"; a fast correct call can, and it is direct evidence rather than inference.
        let judged = WordKnowledge.allVerdicts()
        var beliefs: [String: Double] = [:]
        var beliefRows: [[String: Any?]] = []
        var promotedRate = 0, stillUntrusted = 0

        var out: [Ranked] = []
        out.reserveCapacity(bundle.hooks.count)
        for hook in bundle.hooks {
            var owned = 0, learning = 0, unknown = 0
            var gain = 0.0, effort = 0.0
            var mutating = 0
            for branch in hook.branches {
                if branch.cls == .mutating_ { mutating += 1 }
                guard branch.cls != .dead, branch.cls != .mutating_ else { continue }
                let state = words[branch.word]
                    ?? WordState()
                let belief = Belief.belief(
                    length: branch.word.count,
                    rankedFinds: Double(branch.finds), rankedOpportunity: branch.opportunity,
                    inAppFinds: state.weightedFinds, inAppOpportunity: state.weightedOpportunity,
                    priors: bundle.beliefPriors)
                beliefs[branch.word] = belief
                var status = Belief.status(belief)
                switch judged[branch.word] {
                case .known: status = "known"
                case .unknown: status = "unknown"
                case .shaky: status = status == "known" ? "learning" : status
                case .none, .some(.unjudged): break
                }
                switch status {
                case "known": owned += 1
                case "learning": learning += 1
                default: unknown += 1
                }

                let presences = branch.presences + state.inAppPresences
                let finds = branch.finds + state.inAppFinds
                let myRate = presences > 0 ? Double(finds) / Double(presences) : 0
                // Materialise only what the app has actually observed. The other 100,000
                // words are already in the hook record at their ranked values, and writing
                // them back unchanged would be a hundred thousand rows saying nothing.
                if words[branch.word] != nil {
                    beliefRows.append([
                        "word": branch.word, "logit": log(belief / (1 - belief)),
                        "belief": belief,
                        "inapp_presences": state.inAppPresences, "inapp_finds": state.inAppFinds,
                        "inapp_weight": state.weightedOpportunity,
                        "inapp_find_weight": state.weightedFinds,
                        "my_rate": myRate, "updated_wall": TrainingLog.now(),
                    ])
                }
                let topQTrusted = branch.nTopQuartile >= Self.minTopQuartile
                if !topQTrusted {
                    // A word the queue cannot price. Split by which of the two conditions
                    // moved, so "becoming rankable" is not claimed for the wrong reason.
                    if presences >= Self.minPresences && state.inAppPresences > 0 {
                        promotedRate += 1
                    } else {
                        stillUntrusted += 1
                    }
                }
                let rankable = topQTrusted && presences >= Self.minPresences
                    && branch.word.count >= Self.minLength
                // Note the absence of a `status != "known"` test here. That was right
                // when the queue was read as a vocabulary list and is wrong now: a word
                // he knows and takes 42% of the time still has 16 points a game in it,
                // and that gap is exactly what a vision drill is for.
                guard rankable, branch.earns else { continue }
                let achievable = max(branch.topQuartileRate ?? 0, myRate)
                let value = branch.presencesPerGame * Double(branch.points)
                    * max(0, achievable - myRate)
                guard value > 0 else { continue }
                gain += value
                effort += Self.cost[branch.cls] ?? 1.0
            }
            effort += Double(min(hook.deadBranches + mutating, Self.deadGridCap))
                * (Self.cost[.dead] ?? 0.35)
            if owned >= 2 { effort *= Self.ownedDiscount }
            effort = max(effort, 0.5)
            let score = (gain + Self.misswipeWeight * hook.deadPoints) / effort
            out.append(Ranked(
                hook: hook, owned: owned, learning: learning, unknown: unknown,
                expectedGain: gain, effort: effort, score: score,
                eligible: Self.enumerabilityBand.contains(hook.enumerability)
                    && owned >= Self.minOwned && gain > 0))
        }

        out.sort { $0.score > $1.score }
        ranked = out
        Database.shared.writeMany("word_belief", beliefRows)
        self.beliefs = beliefs
        promotable = (promotedRate, stillUntrusted)
        let now = Date()
        lastRecomputed = now
        Database.shared.write("queue_state", ["key": "last_recomputed",
                                              "value": Self.iso.string(from: now)])
    }

    func belief(_ word: String) -> Double? { beliefs[word] }

    /// The line the brief asks for somewhere unobtrusive: whether what is on screen is
    /// current.
    var recomputedText: String {
        guard let lastRecomputed else { return "queue not yet recomputed" }
        let f = RelativeDateTimeFormatter()
        return "queue recomputed \(f.localizedString(for: lastRecomputed, relativeTo: Date()))"
    }

    // MARK: Storage

    static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static func storedRecomputeDate() -> Date? {
        var value: String?
        Database.shared.query("SELECT value FROM queue_state WHERE key = 'last_recomputed'") {
            value = $0.text(0)
        }
        return value.flatMap { iso.date(from: $0) }
    }

    private static func recentlyDrilled(days: Int) -> Set<String> {
        let cutoff = iso.string(from: Date().addingTimeInterval(-Double(days) * 86400))
        var out: Set<String> = []
        Database.shared.query("SELECT stem FROM hook_state WHERE last_drilled >= ?", [cutoff]) {
            out.insert($0.text(0))
        }
        return out
    }

    private static func loadWordState() -> [String: WordState] {
        var out: [String: WordState] = [:]
        Database.shared.query("""
            SELECT word, COUNT(*), SUM(found), SUM(COALESCE(w_finds, 0)),
                   SUM(COALESCE(w_opportunity, 0))
            FROM presence GROUP BY word
            """) { row in
            out[row.text(0)] = WordState(
                inAppPresences: row.int(1), inAppFinds: row.int(2),
                weightedFinds: row.double(3), weightedOpportunity: row.double(4))
        }
        // The affix grid contributes too, at a tenth of a board find: recognising a word
        // is not finding it, and a grid that could graduate a hook on its own would make
        // the drill self-certifying.
        let w = Belief.Evidence.affixGrid.weight
        Database.shared.query("""
            SELECT word, SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END), COUNT(*)
            FROM judgement WHERE live = 1 GROUP BY word
            """) { row in
            let word = row.text(0)
            var state = out[word] ?? WordState()
            state.weightedFinds += Double(row.int(1)) * w
            state.weightedOpportunity += Double(row.int(2)) * w
            out[word] = state
        }
        return out
    }
}
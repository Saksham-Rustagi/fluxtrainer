import Foundation

/// Learning, made visible, and made to change something.
///
/// The brief's warning here is the right one: a static list of what you have learned is
/// much less useful than a thing that notices. Three mechanisms, and this file holds two
/// of them. (The third -- the queue reprices itself -- is `TrainingQueue.recompute`, which
/// now sees ranked play as well as training boards.)
///
/// **Transitions are surfaced once.** A word crossing unknown -> learning -> owned is said
/// in that board's review and then never again. The difference between `status` and
/// `announced_status` on `word_belief` is exactly that one showing. No streaks, no XP: the
/// point is information, not reward.
///
/// **The inverse matters as much.** The player's own ranked history says retention is
/// weak -- a word is taken 25.2% of the time after a presence where it was taken and 10.3%
/// after one where it was missed, and 4,320 words were found once or twice and then missed
/// on five or more later presences. Decay is the normal case here, not the exception, so a
/// branch that was owned and is now being missed has to come back rather than sit in a
/// list of things achieved.
enum Progression {
    // MARK: Slipping

    /// The most recent unprompted presences a slip is judged on. Short enough to notice
    /// inside a fortnight of play, long enough that two unlucky boards do not trigger it.
    static let slipWindow = 6
    /// The window has to be nearly full. Three presences is not evidence; this is the
    /// same line the per-stem trend draws.
    static let slipMinObservations = 4
    /// Only a word that was demonstrably being taken can slip. Below this the ranked rate
    /// is not an "established rate", it is noise, and calling its absence a regression
    /// would fill the queue with words that were never found in the first place.
    static let slipEstablishedFloor = 0.4
    /// Recent rate at or below half the established rate. Halving is material at any
    /// established rate above the floor, and it does not fire on a single miss in six.
    static let slipRatio = 0.5

    struct Recent {
        let finds: Int
        let presences: Int
        var rate: Double { presences > 0 ? Double(finds) / Double(presences) : 0 }
    }

    /// The last `slipWindow` **unprompted** presences per word. Unprompted only, and for
    /// the same reason drill outcomes cannot drive belief: a find with the stem lit would
    /// hide a slip, and a miss on a drill board would invent one.
    static func recentUnprompted(window: Int = slipWindow) -> [String: Recent] {
        var out: [String: Recent] = [:]
        Database.shared.query("""
            SELECT word, SUM(found), COUNT(*) FROM (
                SELECT word, found,
                       ROW_NUMBER() OVER (PARTITION BY word ORDER BY rowid DESC) AS rn
                FROM presence WHERE evidence = 'unpromptedBoard'
            ) WHERE rn <= ? GROUP BY word
            """, [window]) { row in
            out[row.text(0)] = Recent(finds: row.int(1), presences: row.int(2))
        }
        return out
    }

    /// Has a branch that was being taken stopped being taken? `established` is the ranked
    /// rate from the hook record, which rests on 2,865 boards; `recent` is this app's own
    /// last few presences. Comparing a thin window against a thick baseline is the right
    /// way round -- the baseline is the thing we are confident about.
    static func isSlipping(established: Double?, recent: Recent?) -> Bool {
        guard let established, established >= slipEstablishedFloor,
              let recent, recent.presences >= slipMinObservations else { return false }
        return recent.rate <= slipRatio * established
    }

    // MARK: Status transitions

    /// A crossing the player has not been told about yet.
    struct Transition: Identifiable {
        let word: String
        let from: String?
        let to: String
        /// The evidence line, in his own numbers. "STORER: you have found it on 4 of the
        /// last 5 boards it appeared on."
        let detail: String
        var id: String { word }

        var sentence: String {
            switch to {
            case "known": return "\(word): \(detail) Owned."
            case "slipping": return "\(word): \(detail) Back in the queue."
            default: return "\(word): \(detail)"
            }
        }
    }

    /// Unannounced crossings among the words that were on this board. Restricting to the
    /// board is what keeps it one line in one review instead of a changelog: a word that
    /// crossed while he was not looking at it gets announced the next time he meets it.
    static func pendingTransitions(words: Set<String>, limit: Int = 2) -> [Transition] {
        guard !words.isEmpty else { return [] }
        let list = words.map { "'" + $0.replacingOccurrences(of: "'", with: "''") + "'" }
            .joined(separator: ",")
        var out: [Transition] = []
        let recent = recentUnprompted()
        Database.shared.query("""
            SELECT word, status, announced_status, inapp_presences, inapp_finds
            FROM word_belief
            WHERE word IN (\(list)) AND status IS NOT NULL
              AND (announced_status IS NULL OR announced_status != status)
            """) { row in
            let word = row.text(0)
            let to = row.text(1)
            // Only the two ends are worth an interruption. "learning" is where most words
            // live and announcing it would be announcing nothing.
            guard to == "known" || to == "slipping" else { return }
            let detail: String
            if let r = recent[word], r.presences > 0 {
                detail = "you found it on \(r.finds) of the last \(r.presences) boards it "
                    + "appeared on."
            } else {
                detail = "\(row.int(4)) of \(row.int(3)) in this app."
            }
            out.append(Transition(word: word, from: row.optionalText(2), to: to, detail: detail))
        }
        return Array(out.prefix(limit))
    }

    /// Said once. Called by review after the transitions have been on screen.
    static func markAnnounced(_ transitions: [Transition]) {
        for t in transitions {
            Database.shared.execute(
                "UPDATE word_belief SET announced_status = ? WHERE word = ?", [t.to, t.word])
        }
    }

    // MARK: Per-stem trend

    /// Find rate on a stem's branches before the first drill against since, with the
    /// presence counts, because the counts are what say whether the number means anything.
    /// Three presences is not evidence; twenty is.
    struct Trend {
        let beforeFinds: Int, beforePresences: Int
        let afterFinds: Int, afterPresences: Int
        let firstDrilled: String?
        let lastMet: String?
        let meetings: Int

        static let meaningful = 20

        var beforeRate: Double? {
            beforePresences > 0 ? Double(beforeFinds) / Double(beforePresences) : nil
        }
        var afterRate: Double? {
            afterPresences > 0 ? Double(afterFinds) / Double(afterPresences) : nil
        }
        /// Enough presences on both sides for the difference to mean anything at all.
        var readable: Bool {
            beforePresences >= Trend.meaningful && afterPresences >= Trend.meaningful
        }
    }

    /// Reads `hook_meeting`, which is written for every board played -- ranked games
    /// included. Before Phase 3.5 a ranked board recorded nothing, so this question had no
    /// answer at all outside the session.
    static func trend(stem: String) -> Trend {
        var firstDrilled: String?
        Database.shared.query("SELECT first_drilled FROM hook_state WHERE stem = ?", [stem]) {
            firstDrilled = $0.optionalText(0)
        }
        var before = (0, 0), after = (0, 0)
        var lastMet: String?
        var meetings = 0
        Database.shared.query("""
            SELECT found, present, wall FROM hook_meeting
            WHERE stem = ? AND purpose != 'drill' ORDER BY wall
            """, [stem]) { row in
            meetings += 1
            lastMet = row.text(2)
            if let drilled = firstDrilled, row.text(2) >= drilled {
                after = (after.0 + row.int(0), after.1 + row.int(1))
            } else {
                before = (before.0 + row.int(0), before.1 + row.int(1))
            }
        }
        return Trend(beforeFinds: before.0, beforePresences: before.1,
                     afterFinds: after.0, afterPresences: after.1,
                     firstDrilled: firstDrilled, lastMet: lastMet, meetings: meetings)
    }
}

import Foundation

/// "Have I learned the ones that matter?" -- the question the app could not answer.
///
/// Phase 3 drilled `ERAS-` and then had no way back to it. There was no screen that said
/// which branches are owned, which are worth having, or whether the drill did anything.
/// The hook record has carried every number needed for all three since Phase 2.
///
/// The screen's headline is the point of it: **"You have 6 of the 9 branches worth
/// knowing."** For `TORE-`, STORED and RESTORE sit above the line and TUTORED below it,
/// and the screen has to make that obvious without the player reasoning about it.
struct FamilyPage {
    /// The line between a branch worth knowing and one that is merely real. 1.0 point a
    /// game is the median expected gain of a live branch across the whole shipped queue,
    /// which makes "worth knowing" mean "at or above the middle of what the queue already
    /// thought was worth ranking" rather than a number picked to make the count look good.
    static let worthKnowingFloor = 1.0

    struct Row: Identifiable {
        let branch: Branch
        /// From `word_belief` when the app has observed the word, from the hook record
        /// when it has not. "slipping" can only come from the app: it is a statement about
        /// recent play.
        let status: String
        let myRate: Double?
        let inAppPresences: Int
        let inAppFinds: Int
        let worthKnowing: Bool

        var id: String { branch.word }
        var word: String { branch.word }
        var owned: Bool { status == "known" }
        var slipping: Bool { status == "slipping" }

        /// "on 243 boards · you 1% · top 25% 28%"
        ///
        /// Presence is a total and not a per-grid split, which SPEC 12.2 asks for. The
        /// shipped record carries `presenceByTierGrid` on the *hook* and not on the
        /// branch, so the split does not exist on device; inventing it from a handful of
        /// in-app boards would be worse than leaving it out. It is one field on
        /// `BRANCH_FIELDS` away whenever the record is regenerated.
        var rateLine: String {
            var parts: [String] = []
            if branch.presences > 0 { parts.append("on \(branch.presences) boards") }
            if inAppPresences > 0 { parts.append("+\(inAppPresences) here") }
            if let mine = myRate { parts.append("you \(Self.pct(mine))") }
            // The field's rate is the one that says which *kind* of problem this is: a
            // word almost nobody takes is vocabulary, a word most people take and he does
            // not is vision. Both are worth learning and they are not learned the same way.
            if let field = branch.fieldRate { parts.append("field \(Self.pct(field))") }
            if let top = branch.topQuartileRate { parts.append("top 25% \(Self.pct(top))") }
            return parts.joined(separator: " · ")
        }

        /// "6 letters · cellmate". SPEC 7.3's classes do different jobs and a cellmate is
        /// not an extension, so the row says which it is whenever it is not the default.
        var shape: String {
            let length = "\(branch.word.count) letters"
            switch branch.cls {
            case .additive: return length
            case .cellmate: return length + " · cellmate"
            case .mutating_: return length + " · mutation"
            case .dead: return length + " · does not take"
            }
        }

        static func pct(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }
    }

    let hook: Hook
    let live: [Row]
    let dead: [Row]
    let trend: Progression.Trend

    var worthKnowing: [Row] { live.filter(\.worthKnowing) }
    var ownedWorthKnowing: Int { worthKnowing.filter(\.owned).count }
    var slipping: [Row] { live.filter(\.slipping) }

    /// The one line the screen exists for.
    var headline: String {
        let total = worthKnowing.count
        guard total > 0 else { return "Nothing here is worth much a game." }
        return "You have \(ownedWorthKnowing) of the \(total) branch"
            + (total == 1 ? "" : "es") + " worth knowing."
    }

    /// The other half of "is it working": the same branches before the first drill and
    /// since, with the counts, because the counts are what say whether it means anything.
    var trendLine: String? {
        guard trend.firstDrilled != nil else { return nil }
        guard let before = trend.beforeRate, let after = trend.afterRate else {
            return "Drilled, and not met on a full board since."
        }
        let n = "\(trend.beforePresences) before, \(trend.afterPresences) since"
        let movement = "\(Row.pct(before)) → \(Row.pct(after))"
        return trend.readable
            ? "\(movement) on this family's branches (\(n))."
            : "\(movement) (\(n)) — too few to read yet."
    }

    /// Everything the page shows, in one pass over the log. Runs off the main thread.
    static func load(hook: Hook) -> FamilyPage {
        let observed = observedWords(hook: hook)
        func row(_ branch: Branch) -> Row {
            let seen = observed[branch.word]
            let ranked = branch.myRate
            let mine: Double?
            if let seen, seen.presences > 0 {
                // Ranked presences and in-app presences are the same kind of observation
                // and are pooled, which is the same rule the queue's recompute follows.
                let presences = branch.presences + seen.presences
                mine = presences > 0
                    ? Double(branch.finds + seen.finds) / Double(presences) : ranked
            } else {
                mine = ranked
            }
            return Row(branch: branch, status: seen?.status ?? branch.status, myRate: mine,
                       inAppPresences: seen?.presences ?? 0, inAppFinds: seen?.finds ?? 0,
                       worthKnowing: branch.earns && branch.expectedGain >= worthKnowingFloor)
        }

        // Sorted by expected value, never alphabetically. The whole complaint about the
        // old affix deck was that alphabetical ordering buried STORE under PRESTORED.
        let live = hook.liveBranches
            .map(row)
            .sorted { $0.branch.expectedGain > $1.branch.expectedGain }
        // Dead affixes get their own block: knowing that -IER does not take is worth
        // something, and it is not worth the same as knowing that -ER does.
        let dead = hook.deadAndMutating
            .map(row)
            .sorted { $0.branch.word < $1.branch.word }
        return FamilyPage(hook: hook, live: live, dead: dead,
                          trend: Progression.trend(stem: hook.stem))
    }

    private struct Observed {
        let status: String
        let presences: Int
        let finds: Int
    }

    private static func observedWords(hook: Hook) -> [String: Observed] {
        let words = hook.branches.map(\.word)
        guard !words.isEmpty else { return [:] }
        let list = words.map { "'" + $0.replacingOccurrences(of: "'", with: "''") + "'" }
            .joined(separator: ",")
        var out: [String: Observed] = [:]
        Database.shared.query("""
            SELECT word, COALESCE(status, ''), inapp_presences, inapp_finds
            FROM word_belief WHERE word IN (\(list))
            """) { row in
            let status = row.text(1)
            guard !status.isEmpty else { return }
            out[row.text(0)] = Observed(status: status, presences: row.int(2), finds: row.int(3))
        }
        return out
    }
}

/// Section 4: everything drilled or met in play, so the app has a memory the player can
/// see. Without it there is no answer to "what have I actually learned this month".
struct StemRecord: Identifiable {
    let stem: String
    let track: String
    let meetings: Int
    let present: Int
    let found: Int
    /// Branches worth knowing, and how many of them are owned. The same definition the
    /// family page's headline uses, so the list and the page cannot disagree.
    let worthKnowing: Int
    let owned: Int
    let lastMet: String?
    let lastDrilled: String?
    let firstDrilled: String?
    let exposures: Int
    /// Find rate on this family's branches since the first drill against before it. Nil
    /// on either side until there is something to compare.
    let beforeRate: Double?
    let afterRate: Double?
    let readable: Bool

    var id: String { stem }
    var rate: Double? { present > 0 ? Double(found) / Double(present) : nil }
    var completion: Double? {
        worthKnowing > 0 ? Double(owned) / Double(worthKnowing) : nil
    }
    var drilled: Bool { firstDrilled != nil }
    var improving: Bool? {
        guard let before = beforeRate, let after = afterRate else { return nil }
        return after > before
    }

    enum Filter: String, CaseIterable, Identifiable {
        case all = "All"
        case drilled = "Drilled"
        case improving = "Improving"
        case slipping = "Slipping"
        var id: String { rawValue }
    }

    /// One grouped select over `hook_meeting`, one over `hook_state` and one over
    /// `word_belief`. All three are written for every board played, ranked games included,
    /// which is what makes "met in play" mean anything at all.
    static func load(index: FamilyIndex?) -> [StemRecord] {
        struct Agg { var meetings = 0; var present = 0; var found = 0; var last: String? }
        var totals: [String: Agg] = [:]
        var before: [String: (Int, Int)] = [:]
        var after: [String: (Int, Int)] = [:]
        var state: [String: (first: String?, last: String?, exposures: Int)] = [:]

        Database.shared.query(
            "SELECT stem, first_drilled, last_drilled, exposures FROM hook_state") { row in
            state[row.text(0)] = (row.optionalText(1), row.optionalText(2), row.int(3))
        }
        var ownedWords: Set<String> = []
        Database.shared.query("SELECT word FROM word_belief WHERE status = 'known'") {
            ownedWords.insert($0.text(0))
        }
        Database.shared.query("""
            SELECT stem, present, found, wall, purpose FROM hook_meeting ORDER BY wall
            """) { row in
            let stem = row.text(0)
            var agg = totals[stem] ?? Agg()
            agg.meetings += 1
            agg.present += row.int(1)
            agg.found += row.int(2)
            agg.last = row.text(3)
            totals[stem] = agg
            guard row.text(4) != BoardPurpose.drill.rawValue else { return }
            if let drilled = state[stem]?.first, row.text(3) >= drilled {
                after[stem, default: (0, 0)].0 += row.int(2)
                after[stem, default: (0, 0)].1 += row.int(1)
            } else {
                before[stem, default: (0, 0)].0 += row.int(2)
                before[stem, default: (0, 0)].1 += row.int(1)
            }
        }

        return totals.map { stem, agg in
            let b = before[stem], a = after[stem]
            let beforeRate = (b?.1 ?? 0) > 0 ? Double(b!.0) / Double(b!.1) : nil
            let afterRate = (a?.1 ?? 0) > 0 ? Double(a!.0) / Double(a!.1) : nil
            let hook = index?.hook(stem)
            let worth = hook?.liveBranches.filter {
                $0.earns && $0.expectedGain >= FamilyPage.worthKnowingFloor
            } ?? []
            return StemRecord(
                stem: stem, track: hook?.track ?? "", meetings: agg.meetings,
                present: agg.present, found: agg.found,
                worthKnowing: worth.count,
                owned: worth.filter { ownedWords.contains($0.word) }.count,
                lastMet: agg.last, lastDrilled: state[stem]?.last,
                firstDrilled: state[stem]?.first, exposures: state[stem]?.exposures ?? 0,
                beforeRate: beforeRate, afterRate: afterRate,
                readable: (b?.1 ?? 0) >= Progression.Trend.meaningful
                    && (a?.1 ?? 0) >= Progression.Trend.meaningful)
        }
        .sorted {
            // Drilled first, then by how little of the family is owned: the ones going
            // wrong are the ones worth opening.
            if $0.drilled != $1.drilled { return $0.drilled }
            return ($0.completion ?? 1) < ($1.completion ?? 1)
        }
    }

    /// Stems with at least one branch the recompute has flagged as slipping.
    static func slippingStems(index: FamilyIndex) -> Set<String> {
        var words: [String] = []
        Database.shared.query("SELECT word FROM word_belief WHERE slipping = 1") {
            words.append($0.text(0))
        }
        var out: Set<String> = []
        for word in words {
            for membership in index.families(of: word) { out.insert(membership.stem) }
        }
        return out
    }
}

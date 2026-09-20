import Foundation

/// SPEC 8.1, continued rather than replaced.
///
/// The ranked import did not use 8.1's logit form; `tools/analytics/s4.py` fitted the
/// opportunity-weighted Beta rate instead, and that is the `belief` column the Phase 2
/// queue ranked on. Phase 3 keeps that model, because a second model on the same quantity
/// would make in-app and ranked evidence incomparable and the whole point is to add them:
///
///     belief(w) = (finds + a_L) / (opportunity + a_L + b_L)
///
/// `opportunity` is how likely a *known* word of that length was to be taken on that
/// board -- the board's own find rate for the length class against the rate on the boards
/// where the most was taken, capped at 1. This is the continuous version of 8.1's
/// distinction between "present in a region you covered, not swiped" (evidence) and
/// "present in a region with zero swipe-time" (no inference possible). Without it every
/// 800-word board would look like proof of not knowing 800 words.
///
/// What Phase 3 adds is the second weight, and it is the one the brief is emphatic about:
/// **drill outcomes must not drive belief on their own.** Finding a branch with the stem
/// lit is much weaker evidence than finding it unprompted on a full board. Treating them
/// equally produces a loop where drilling a hook makes it look learned and leave the
/// queue, which is worse than not drilling it.
enum Belief {
    /// Evidence weight by where the observation came from, strongest first. These are
    /// judgements, not measurements -- there is no data yet on how a lit-stem find relates
    /// to an unprompted one, and Phase 3's gate is the experiment that will produce some.
    /// They live here, in one place, so the gate can be re-run against a different set.
    enum Evidence: String {
        /// A word found, or missed, on a full board with nothing pointed at: the warm-up,
        /// a measurement board, and every non-target word on any board. Identical in kind
        /// to a ranked presence, so it carries the ranked weight.
        case unpromptedBoard
        /// A target branch on a family sweep. A full board with no stem lit, but the hook
        /// is one the session is working on, so it is not quite unprompted.
        case familySweep
        /// A target branch on a branch-completion drill. The stem is lit; the player is
        /// being shown where to look.
        case litDrill
        /// An affix-grid judgement. Recognising a word is not finding it.
        case affixGrid

        var weight: Double {
            switch self {
            case .unpromptedBoard: return 1.0
            case .familySweep: return 0.6
            case .litDrill: return 0.25
            case .affixGrid: return 0.1
            }
        }
    }

    /// SPEC 7.5.1's thresholds. Shared with the Phase 2 queue, which used the same two.
    static let unknownBelow = 0.35
    static let ownedAbove = 0.65

    static func status(_ belief: Double) -> String {
        if belief > ownedAbove { return "known" }
        if belief < unknownBelow { return "unknown" }
        return "learning"
    }

    /// The opportunity weight of one presence on one board.
    ///
    /// `foundOfClass / presentOfClass` on this board, against the reference rate for that
    /// (grid, length class). Both halves come from the board's own solve, which the app
    /// has for every board it plays -- that is the whole reason every solved word is
    /// recorded and not just the drilled hook's branches.
    static func opportunity(foundOfClass: Int, presentOfClass: Int, side: Int, length: Int,
                            reference: [String: Double]) -> Double {
        guard presentOfClass > 0 else { return 0 }
        let lc = min(length, 7)
        guard let ref = reference["\(side)x\(side)_\(lc)"], ref > 0 else { return 0 }
        let rate = Double(foundOfClass) / Double(presentOfClass)
        return min(rate / ref, 1.0)
    }

    /// One word's belief from every observation of it, ranked and in-app together.
    ///
    /// `rankedFinds` / `rankedOpportunity` come from the hook record; the in-app pair is
    /// summed out of `presence` and `judgement`, already weighted at write time. Both are
    /// in the same units, which is the only reason they can be added.
    static func belief(length: Int, rankedFinds: Double, rankedOpportunity: Double,
                       inAppFinds: Double, inAppOpportunity: Double,
                       priors: [Int: (a: Double, b: Double)]) -> Double {
        let (a, b) = priors[min(length, 7)] ?? (0.5, 1.5)
        let finds = rankedFinds + inAppFinds
        let opportunity = rankedOpportunity + inAppOpportunity
        let value = (finds + a) / (opportunity + a + b)
        return min(max(value, 0.02), 0.98)  // SPEC 8.1's clamp
    }

    /// What one observation contributes. A find adds `weight` to the numerator and
    /// `weight * opportunity` to the denominator; a miss adds only to the denominator.
    /// Scaling both by `weight` shrinks the observation's influence without distorting
    /// what it says, which is what down-weighting a lit-stem find has to do.
    static func contribution(found: Bool, opportunity: Double, evidence: Evidence)
        -> (finds: Double, opportunity: Double) {
        let w = evidence.weight
        return (found ? w : 0, w * opportunity)
    }
}

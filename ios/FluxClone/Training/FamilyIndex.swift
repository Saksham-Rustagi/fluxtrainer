import Foundation

/// The other direction through the hook record: word -> the families it belongs to.
///
/// Phase 3 only ever asked "what hangs off this stem", because it only ever started from
/// a stem the queue had chosen. Review starts from a board, so every question it asks runs
/// the other way -- which of the 428 words on this board are branches, of what, and which
/// of those did he take. Walking 1,336 hooks per board word would be 570,000 comparisons a
/// board; this is one dictionary lookup.
///
/// Built once, off the main thread, at the same time as the bundle. 32,025 distinct live
/// words across 51,909 (word, stem) pairs.
final class FamilyIndex {
    /// A branch, and the hook it hangs off. A word can be additive on several stems at
    /// once (STRINE is on nine) -- containment is not exclusive, so neither is this.
    struct Membership {
        let stem: String
        let branch: Branch
    }

    /// Built once, beside the bundle, off the main thread. Everything that needs the
    /// reverse index shares this one: building a second would cost another 52,000 entries
    /// for no reason.
    private(set) static var shared: FamilyIndex?

    @discardableResult
    static func build(bundle: HookBundle) -> FamilyIndex {
        if let shared, shared.bundle.generated == bundle.generated { return shared }
        let made = FamilyIndex(bundle: bundle)
        shared = made
        return made
    }

    private var byWord: [String: [Membership]] = [:]
    private var byStem: [String: Hook] = [:]
    let bundle: HookBundle

    init(bundle: HookBundle) {
        self.bundle = bundle
        byWord.reserveCapacity(40_000)
        byStem.reserveCapacity(bundle.hooks.count)
        for hook in bundle.hooks {
            byStem[hook.stem] = hook
            for branch in hook.branches where branch.cls.earnsPoints {
                byWord[branch.word, default: []].append(
                    Membership(stem: hook.stem, branch: branch))
            }
        }
    }

    func families(of word: String) -> [Membership] { byWord[word] ?? [] }
    func hook(_ stem: String) -> Hook? { byStem[stem] }
    var stems: [String] { Array(byStem.keys) }

    /// The single most valuable reason to care about this word, across every family it is
    /// in. Review ranks words by this, which is Phase 2's expected gain and not anything
    /// local to the board -- one board's misses are mostly board luck.
    func bestMembership(of word: String) -> Membership? {
        families(of: word).max { $0.branch.expectedGain < $1.branch.expectedGain }
    }

    /// Every family with at least one member on this board, with what was taken.
    ///
    /// `present` is read off the board's own solve rather than out of the bundle, which is
    /// the same rule `additiveBranchesPresent` follows and the reason the bundle is
    /// allowed to cap its branch lists: containment is checkable on the spot.
    func meetings(on solved: SolvedBoard, found: Set<String>) -> [String: FamilyMeeting] {
        var out: [String: FamilyMeeting] = [:]
        for word in solved.words {
            for membership in families(of: word.word) {
                out[membership.stem, default: FamilyMeeting(stem: membership.stem)]
                    .add(word: word, branch: membership.branch, found: found.contains(word.word))
            }
        }
        return out
    }
}

/// One family's showing on one board: which members were there, which were taken, and what
/// the rest were worth. This is the row `hook_meeting` stores and the unit review ranks.
struct FamilyMeeting {
    let stem: String
    private(set) var present: [SolvedWord] = []
    private(set) var found: [SolvedWord] = []
    private(set) var missed: [SolvedWord] = []
    private(set) var branches: [String: Branch] = [:]

    init(stem: String) { self.stem = stem }

    mutating func add(word: SolvedWord, branch: Branch, found isFound: Bool) {
        guard branches[word.word] == nil else { return }
        branches[word.word] = branch
        present.append(word)
        if isFound { found.append(word) } else { missed.append(word) }
    }

    var pointsPresent: Int { present.reduce(0) { $0 + $1.points } }
    var pointsFound: Int { found.reduce(0) { $0 + $1.points } }
    var pointsMissed: Int { missed.reduce(0) { $0 + $1.points } }

    /// What the queue says the missed members are worth a game, summed. Not the points on
    /// this board: a word he takes 42% of the time is only 58% of a miss.
    var missedExpectedGain: Double {
        missed.reduce(0) { $0 + (branches[$1.word]?.expectedGain ?? 0) }
    }

    /// The stem itself, when it is a word and was on the board. SPEC 7.4's "found the
    /// base, missed 2+ extensions" needs to know whether the base was taken.
    func baseWasFound() -> Bool { found.contains { $0.word == stem } }
    func baseWasPresent() -> Bool { present.contains { $0.word == stem } }
}

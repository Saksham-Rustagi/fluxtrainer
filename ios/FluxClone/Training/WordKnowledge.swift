import Foundation

/// Do you know the word, or can you not see it? Until now the app could not tell.
///
/// Belief (SPEC 8.1, and the `belief` column Phase 2 ranked on) is derived from find rate.
/// That makes "I have never heard of SIREES" and "ERASE was on 243 of my boards and I found
/// it twice" the same number, and they are not remotely the same problem. SPEC 8.1 says so
/// itself and prescribes the fix -- a one-time calibration of stratified valid/invalid
/// judgements, fitting a personal frequency-to-knowledge curve -- and no phase built it.
///
/// This is that step, done per hook instead of once globally, and using the exercise that
/// already exists. Before a hook's board drill, its words go through the affix grid. The
/// answer and the latency sort them:
///
/// | call | latency | verdict | what the drill is then for |
/// | correct | under 1.2 s | `known` | you know it. The drill is a *vision* drill and the number that moves is seconds-to-find. |
/// | correct | over 1.2 s | `shaky` | you got there, but you had to work. Both problems at once. |
/// | wrong | any | `unknown` | genuine vocabulary. The drill is acquisition. |
///
/// The 1.2 s threshold is SPEC 7.3's own target for an affix judgement, so it is not a new
/// constant, and it is the line between recognition and derivation.
enum WordKnowledge {
    static let fastThreshold = 1.2

    enum Verdict: String {
        case known
        case shaky
        case unknown
        /// Never put through the grid. The drill cannot tell which problem it is, so it
        /// treats the word the way it did before this existed.
        case unjudged

        /// A miss on a word you demonstrably know says nothing about your vocabulary. It
        /// is the whole point of sorting first.
        var isVocabulary: Bool { self == .unknown || self == .shaky }
    }

    /// The most recent judgement on this word, whatever stem it was asked under.
    static func verdict(for word: String) -> Verdict {
        var out = Verdict.unjudged
        Database.shared.query("""
            SELECT correct, latency FROM judgement
            WHERE word = ? AND live = 1
            ORDER BY rowid DESC LIMIT 1
            """, [word]) { row in
            out = classify(correct: row.bool(0), latency: row.double(1))
        }
        return out
    }

    /// Every judged word under a stem, in one query, for a drill that is about to run.
    static func verdicts(forStem stem: String) -> [String: Verdict] {
        var out: [String: Verdict] = [:]
        Database.shared.query("""
            SELECT word, correct, latency FROM judgement
            WHERE stem = ? AND live = 1 ORDER BY rowid
            """, [stem]) { row in
            out[row.text(0)] = classify(correct: row.bool(1), latency: row.double(2))
        }
        return out
    }

    /// All of them, for the queue's recompute.
    static func allVerdicts() -> [String: Verdict] {
        var out: [String: Verdict] = [:]
        Database.shared.query("""
            SELECT word, correct, latency FROM judgement
            WHERE live = 1 ORDER BY rowid
            """) { row in
            out[row.text(0)] = classify(correct: row.bool(1), latency: row.double(2))
        }
        return out
    }

    static func classify(correct: Bool, latency: Double) -> Verdict {
        guard correct else { return .unknown }
        return latency <= fastThreshold ? .known : .shaky
    }
}

/// What a word costs you on a board, as against what it would cost someone who sees it.
/// This is the number a vision drill is trying to move, and it is not belief.
struct SightGap {
    let word: String
    let presences: Int
    let finds: Int
    let myRate: Double
    let topQuartileRate: Double
    /// Points a game the queue expects to gain from closing this gap. Ordering the brief
    /// by raw rate difference instead puts ERASES (0% against 28%) above ERASE (1% against
    /// 28%), which is arithmetically bigger and the wrong word to lead with: ERASE is on
    /// three times as many boards and is worth three times as much.
    let expectedGain: Double

    /// "ERASE was on 243 of your boards. You found it twice. The top 25% find it 28%."
    /// One sentence, the player's own numbers, and the reason the drill exists. The hook
    /// record has carried this since Phase 2 and nothing displayed it.
    var sentence: String {
        let found: String
        switch finds {
        case 0: found = "never found it"
        case 1: found = "found it once"
        case 2: found = "found it twice"
        default: found = "found it \(finds) times"
        }
        return "\(word) was on \(presences) of your boards. You \(found). "
            + "The top 25% find it \(Int((topQuartileRate * 100).rounded()))% of the time."
    }

    init?(branch: Branch) {
        guard branch.presences >= 20, let topQ = branch.topQuartileRate, topQ > 0 else {
            return nil
        }
        word = branch.word
        presences = branch.presences
        finds = branch.finds
        myRate = branch.myRate ?? 0
        topQuartileRate = topQ
        expectedGain = branch.expectedGain
    }

    /// The hook's worst offenders first, by what closing the gap is worth a game.
    static func forHook(_ hook: Hook, limit: Int = 2) -> [SightGap] {
        hook.branches
            .filter { $0.cls == .additive }
            .compactMap(SightGap.init(branch:))
            .sorted { $0.expectedGain > $1.expectedGain }
            .prefix(limit)
            .map { $0 }
    }
}

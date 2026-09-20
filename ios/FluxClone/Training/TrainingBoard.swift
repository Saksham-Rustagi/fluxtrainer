import Foundation

/// What a board is allowed to constrain. This is the Phase 3 override of SPEC 11.1, which
/// applied a tier norm check to every training board: realism matters for transfer and for
/// measurement, not for drills.
///
/// | type        | constraint                                   |
/// | drill       | hook present, nothing else                   |
/// | acquisition | hook present, plus a wide density band        |
/// | measurement | full ranked generation, tier and all          |
enum BoardPurpose: String {
    case drill
    case acquisition
    case measurement
    /// One unscored board at the top of the session. Worth about 1,633 points on game 1 of
    /// a session (Build plan, "Warm-up mode"), and it costs a line of code: it is an
    /// ordinary ranked board that is not reviewed and does not feed the drill.
    case warmup

    var constrainsHook: Bool { self == .drill || self == .acquisition }
    var bandsDensity: Bool { self == .acquisition }
}

/// A generated board together with everything the exercise needs to run on it: the solve,
/// the stem's path, and which branches are actually there.
struct HookBoard {
    let purpose: BoardPurpose
    let board: GeneratedBoard
    let solved: SolvedBoard
    let hook: Hook?
    /// The stem path the drill lights. Nil on a sweep, where the point is finding it
    /// yourself, and on a warm-up.
    let litPath: [Int]?
    /// The additive branches on this board that extend `litPath`, or every additive branch
    /// present when nothing is lit. These are the drill's targets.
    let targets: [String]
    let stats: ConstrainedStats?
    /// True when the board was served without meeting its constraints (spec 11.1's
    /// infeasibility fallback). Never silently: the session records it and the summary
    /// says so.
    let degraded: Bool

    var letters: [Character] { board.letters }
    var side: Int { board.side }

    /// The path a branch takes, preferring one that extends the lit stem.
    func path(for word: String) -> [Int]? {
        guard let solvedWord = solved.word(word) else { return nil }
        if let lit = litPath, let extending = solvedWord.paths.first(where: { $0.contains(subpath: lit) }) {
            return extending
        }
        return solvedWord.paths.first
    }
}

enum BoardGeometryUtil {
    /// Every path on the board spelling `word`, up to `cap`. The solver already returns
    /// paths for dictionary words; this exists for the *stem*, which is often not a word
    /// (RAI, NTER) and so never appears in a solve.
    static func paths(of word: String, letters: [Character], side: Int, cap: Int = 64) -> [[Int]] {
        let target = Array(word)
        guard !target.isEmpty, target.count <= letters.count else { return [] }
        var out: [[Int]] = []
        var path: [Int] = []
        var used = [Bool](repeating: false, count: letters.count)

        func neighbours(_ cell: Int) -> [Int] {
            let row = cell / side, col = cell % side
            var n: [Int] = []
            for dr in -1...1 {
                for dc in -1...1 where !(dr == 0 && dc == 0) {
                    let r = row + dr, c = col + dc
                    if r >= 0, r < side, c >= 0, c < side { n.append(r * side + c) }
                }
            }
            return n
        }

        func walk(_ cell: Int, _ depth: Int) {
            guard out.count < cap else { return }
            path.append(cell)
            used[cell] = true
            defer { path.removeLast(); used[cell] = false }
            if depth == target.count - 1 {
                out.append(path)
                return
            }
            for next in neighbours(cell) where !used[next] && letters[next] == target[depth + 1] {
                walk(next, depth + 1)
            }
        }

        for cell in letters.indices where letters[cell] == target[0] { walk(cell, 0) }
        return out
    }
}

extension Array where Element == Int {
    /// Contiguous, in order: exactly SPEC 7.3's path condition. A branch whose path
    /// contains the lit stem path is a branch the player can reach by extending what is
    /// already under his finger.
    func contains(subpath sub: [Int]) -> Bool {
        guard !sub.isEmpty, sub.count <= count else { return false }
        for start in 0...(count - sub.count) {
            var ok = true
            for i in sub.indices where self[start + i] != sub[i] { ok = false; break }
            if ok { return true }
        }
        return false
    }
}

/// Makes the three board types. Everything here runs on the engine's serial queue.
enum TrainingBoards {
    /// The drill wants a board it is possible to clear in 30-45 seconds, and one with
    /// something left to learn on it.
    static let targetRange = 3...6
    /// How many generations to spend looking for a board in `targetRange`. Each costs a
    /// few milliseconds (tools/trainprobe), so this is tens of milliseconds, not seconds.
    static let attempts = 40

    /// SPEC 11.1 says acquisition boards are 60% Casual / 40% Good Casual, no Spam. That
    /// is kept as "no Spam" and dropped as a mix, and the reason is measured: the player's
    /// own current-regime 4x4 boards are 91% Good Casual and 3.5% Casual, so a board drawn
    /// 60% Casual would be identifiable as a training board from the tier alone -- which
    /// is exactly what SPEC 10.2 and this phase's brief forbid. The tier is drawn from the
    /// ruleset's own shares instead, with Spam redrawn.
    static func drawTier(side: Int, engine: FluxEngine, rng: inout SystemRandomNumberGenerator,
                         allowSpam: Bool) -> Tier {
        for _ in 0..<8 {
            let tier = engine.drawTier(side: side, seed: rng.next())
            if allowSpam || tier != .spam { return tier }
        }
        return .goodCasual
    }

    static func drawSide(rng: inout SystemRandomNumberGenerator) -> Int {
        Double.random(in: 0..<1, using: &rng) < FluxEngine.fourByFourShare ? 4 : 5
    }

    /// A drill board: the hook is present, nothing else is constrained, and the board
    /// carries 3 to 6 branches that extend one stem path. Returns nil only if the stem
    /// cannot be laid at all (over the letter cap).
    static func drill(hook: Hook, engine: FluxEngine) -> HookBoard? {
        var rng = SystemRandomNumberGenerator()
        var fallback: HookBoard?
        for _ in 0..<attempts {
            let side = preferredSide(hook: hook, rng: &rng)
            let tier = drawTier(side: side, engine: engine, rng: &rng, allowSpam: false)
            guard let (board, stats) = engine.generateHook(stem: hook.stem, side: side, tier: tier,
                                                           rootSeed: rng.next(), wordBand: nil)
            else { continue }
            let solved = engine.solve(side: side, letters: board.letters)
            guard let lit = bestStemPath(hook: hook, board: board, solved: solved) else { continue }
            let made = HookBoard(purpose: .drill, board: board, solved: solved, hook: hook,
                                 litPath: lit.path, targets: lit.targets, stats: stats,
                                 degraded: false)
            if targetRange.contains(lit.targets.count), hasResidual(hook: hook, targets: lit.targets) {
                return made
            }
            // Keep the closest board seen, so a hook whose branches are hard to co-place
            // still produces a drill rather than nothing.
            if fallback == nil || closer(made, than: fallback!) { fallback = made }
        }
        // Spec 11.1's infeasibility fallback: serve the closest board, flagged. Never
        // silently serve a board that misses its targets.
        guard let f = fallback, !f.targets.isEmpty else { return nil }
        return HookBoard(purpose: .drill, board: f.board, solved: f.solved, hook: hook,
                         litPath: f.litPath, targets: f.targets, stats: f.stats, degraded: true)
    }

    /// An acquisition board: the hook is present, nothing is lit, and the board's word
    /// count sits inside the measured density band for its grid.
    static func acquisition(hook: Hook, engine: FluxEngine, density: [Int: DensityBand])
        -> HookBoard? {
        var rng = SystemRandomNumberGenerator()
        var fallback: (GeneratedBoard, SolvedBoard, ConstrainedStats)?
        for _ in 0..<attempts {
            let side = preferredSide(hook: hook, rng: &rng)
            let tier = drawTier(side: side, engine: engine, rng: &rng, allowSpam: false)
            let band = density[side].map { $0.minWords...$0.maxWords }
            guard let (board, stats) = engine.generateHook(stem: hook.stem, side: side, tier: tier,
                                                           rootSeed: rng.next(), wordBand: band)
            else { continue }
            let solved = engine.solve(side: side, letters: board.letters)
            let targets = additiveBranchesPresent(stem: hook.stem, solved: solved)
            guard !targets.isEmpty else {
                if fallback == nil { fallback = (board, solved, stats) }
                continue
            }
            return HookBoard(purpose: .acquisition, board: board, solved: solved, hook: hook,
                             litPath: nil, targets: targets, stats: stats,
                             degraded: stats.exhausted)
        }
        guard let (board, solved, stats) = fallback else { return nil }
        return HookBoard(purpose: .acquisition, board: board, solved: solved, hook: hook,
                         litPath: nil, targets: additiveBranchesPresent(stem: hook.stem, solved: solved),
                         stats: stats, degraded: true)
    }

    /// A measurement or warm-up board: ordinary ranked generation, tier and all.
    static func ranked(purpose: BoardPurpose, engine: FluxEngine) -> HookBoard? {
        var rng = SystemRandomNumberGenerator()
        let side = drawSide(rng: &rng)
        let tier = engine.drawTier(side: side, seed: rng.next())
        guard let board = engine.generateRanked(side: side, tier: tier, rootSeed: rng.next())
        else { return nil }
        let solved = engine.solve(side: side, letters: board.letters)
        return HookBoard(purpose: purpose, board: board, solved: solved, hook: nil, litPath: nil,
                         targets: [], stats: nil, degraded: false)
    }

    // MARK: Helpers

    /// SPEC 7.3: an additive branch of S is exactly a word containing S contiguously, so
    /// the branches present on a board are read off the board's own solve rather than out
    /// of the bundle. That is why the bundle can cap its branch lists.
    static func additiveBranchesPresent(stem: String, solved: SolvedBoard) -> [String] {
        solved.words.compactMap { w in
            w.word.count > stem.count && w.word.contains(stem) ? w.word : nil
        }
    }

    /// The stem path that the most branches extend, and those branches. Lighting any other
    /// path would ask the player to extend a stem the answers do not run through.
    static func bestStemPath(hook: Hook, board: GeneratedBoard, solved: SolvedBoard)
        -> (path: [Int], targets: [String])? {
        let candidates = BoardGeometryUtil.paths(of: hook.stem, letters: board.letters,
                                                 side: board.side)
        guard !candidates.isEmpty else { return nil }
        let present = additiveBranchesPresent(stem: hook.stem, solved: solved)
        var best: (path: [Int], targets: [String])?
        for path in candidates {
            let reachable = present.filter { word in
                solved.word(word)?.paths.contains { $0.contains(subpath: path) } ?? false
            }
            if best == nil || reachable.count > best!.targets.count {
                best = (path, reachable)
            }
        }
        return best
    }

    /// SPEC 7.5.1: the drill is worth running when something on the board is still to be
    /// learned. A board of six branches he already owns trains the motor pattern and
    /// teaches no vocabulary.
    static func hasResidual(hook: Hook, targets: [String]) -> Bool {
        targets.contains { word in
            guard let b = hook.branch(word) else { return true }  // unseen: not owned
            return b.status != "known"
        }
    }

    private static func closer(_ a: HookBoard, than b: HookBoard) -> Bool {
        func distance(_ n: Int) -> Int {
            n < targetRange.lowerBound ? targetRange.lowerBound - n
                : (n > targetRange.upperBound ? n - targetRange.upperBound : 0)
        }
        return distance(a.targets.count) < distance(b.targets.count)
    }

    /// Prefer the grid where the hook is actually present more often, but keep the ranked
    /// mix visible: a player who only ever drills on 5x5 is training for 38% of his games.
    private static func preferredSide(hook: Hook, rng: inout SystemRandomNumberGenerator) -> Int {
        let four = hook.presenceByTierGrid.filter { $0.key.hasPrefix("4x4") }.values.max() ?? 0
        let five = hook.presenceByTierGrid.filter { $0.key.hasPrefix("5x5") }.values.max() ?? 0
        guard four > 0 || five > 0 else { return drawSide(rng: &rng) }
        // Blend the ranked 62/38 with the hook's own presence, half and half.
        let share = 0.5 * FluxEngine.fourByFourShare + 0.5 * (four / max(four + five, 1e-9))
        return Double.random(in: 0..<1, using: &rng) < share ? 4 : 5
    }
}

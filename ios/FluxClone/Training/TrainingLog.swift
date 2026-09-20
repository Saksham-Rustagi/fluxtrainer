import Foundation

/// Everything Phase 3 records. Phase 4 reads it without a migration: the scheduling it
/// adds hangs off `hook_state`, and the belief model it refines already has its per-word
/// evidence in `presence` and `judgement`.
///
/// The rule that shapes this file is the one about not throwing signal away. Every full
/// board the app plays is already solved, so every word on it is an observed presence with
/// a known outcome -- not just the hook's branches. Recording only the drilled hook would
/// discard 800 observations a board to keep six.
enum TrainingLog {
    static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func now() -> String { iso.string(from: Date()) }

    // MARK: Sessions

    static func startSession(id: String, shape: String, newHook: String?, dueHooks: [String],
                             queueRecomputedAt: Date?) {
        Database.shared.write("session", [
            "session_id": id, "started_wall": now(), "shape": shape,
            "new_hook": newHook, "due_hooks": dueHooks.joined(separator: ","),
            "queue_recomputed_at": queueRecomputedAt.map(iso.string(from:)),
        ])
    }

    static func endSession(id: String, boards: Int, judgements: Int, abandoned: Bool) {
        Database.shared.execute(
            "UPDATE session SET ended_wall = ?, boards = ?, judgements = ?, abandoned = ? "
                + "WHERE session_id = ?",
            [now(), boards, judgements, abandoned ? 1 : 0, id])
    }

    // MARK: Board exercises

    /// Written when the board goes on screen, so an interrupted session still leaves a row
    /// saying what was being attempted.
    static func startExercise(id: String, sessionId: String, seq: Int, kind: GameMode.Kind,
                              board: HookBoard, attemptForHook: Int, duration: Double) {
        Database.shared.write("exercise", [
            "exercise_id": id, "session_id": sessionId, "seq": seq, "kind": kind.rawValue,
            "hook": board.hook?.stem, "attempt_for_hook": attemptForHook,
            "purpose": board.purpose.rawValue,
            "grid": board.side, "tier": board.board.tier.name,
            "letters": String(board.letters), "board_words": board.solved.count,
            "lit_path": board.litPath?.map(String.init).joined(separator: ","),
            "targets": board.targets.joined(separator: ","),
            "duration": duration, "started_wall": now(),
            "degraded": board.degraded ? 1 : 0,
            "constrained_stats": board.stats?.json,
            "abandoned": 1,  // cleared by finishExercise; an interrupted board stays flagged
        ])
    }

    /// The board is over. Writes the exercise's outcome, one `branch_event` per target, and
    /// one `presence` row for every word on the board.
    @discardableResult
    static func finishExercise(id: String, sessionId: String, board: HookBoard,
                               result: GameResult, evidence: Belief.Evidence,
                               attemptForHook: Int) -> (found: [String], missed: [String]) {
        let foundSet = Set(result.found.map(\.word))
        let found = board.targets.filter { foundSet.contains($0) }
        let missed = board.targets.filter { !foundSet.contains($0) }

        Database.shared.execute(
            "UPDATE exercise SET ended_wall = ?, found = ?, missed = ?, abandoned = ?, "
                + "game_id = ? WHERE exercise_id = ?",
            [now(), found.count, missed.count, result.abandoned ? 1 : 0, result.gameId, id])
        Database.shared.execute(
            "UPDATE game SET purpose = ?, session_id = ?, exercise_id = ? WHERE game_id = ?",
            [board.purpose.rawValue, sessionId, id, result.gameId])

        let findTime = Dictionary(result.found.map { ($0.word, $0.t - result.tBoardShown) },
                                  uniquingKeysWith: { a, _ in a })
        let litStem = board.litPath != nil
        Database.shared.writeMany("branch_event", board.targets.map { word in
            [
                "exercise_id": id, "word": word, "hook": board.hook?.stem,
                "cls": board.hook?.branch(word)?.cls.rawValue ?? HookClass.additive.rawValue,
                "found": foundSet.contains(word) ? 1 : 0, "t_found": findTime[word],
                "stem_lit": litStem ? 1 : 0, "game_id": result.gameId,
                "attempt_for_hook": attemptForHook,
                "points": fluxPoints(forLength: word.count),
            ]
        })

        writePresences(board: board, result: result, evidence: evidence, targets: Set(board.targets))
        // Every board played leaves a row per family it carried, this one included, so the
        // per-stem trend covers training boards and ranked games on the same footing. The
        // `purpose` column is what lets the trend exclude the boards that pointed at it.
        if let index = FamilyIndex.shared {
            writeMeetings(gameId: result.gameId, side: board.side,
                          purpose: board.purpose.rawValue, drilled: board.hook?.stem,
                          meetings: index.meetings(on: board.solved, found: foundSet))
        }
        return (found, missed)
    }

    /// One row per solved word. `opportunity` is SPEC 8.1's weight for this board and
    /// length class, and it is computed here, once, from the board's own solve -- the two
    /// `w_` columns are the contribution after the exercise weight, so a later recompute
    /// is a plain SUM and cannot disagree with the weights in force when it was played.
    ///
    /// The drilled hook's own branches carry the exercise's weight; every other word on
    /// the board was found or missed with nothing pointed at it, so it carries the full
    /// unprompted weight whatever exercise it came from.
    static func writePresences(board: HookBoard, result: GameResult,
                               evidence: Belief.Evidence, targets: Set<String>) {
        writePresences(gameId: result.gameId, side: board.side, tier: board.board.tier.name,
                       purpose: board.purpose.rawValue, solved: board.solved, result: result,
                       evidence: evidence, targets: targets)
    }

    /// The same thing for a board that is not a training board. Phase 3 wrote presences
    /// only for boards the session served, which meant a ranked game -- the thing the
    /// player actually does -- fed the belief model nothing at all. Every completed board
    /// goes through here now, which is what makes "the queue moves on its own" true rather
    /// than aspirational.
    static func writePresences(gameId: String, side: Int, tier: String, purpose: String,
                               solved: SolvedBoard, result: GameResult,
                               evidence: Belief.Evidence, targets: Set<String>) {
        let foundAt = Dictionary(result.found.map { ($0.word, $0.t - result.tBoardShown) },
                                 uniquingKeysWith: { a, _ in a })
        let reference = HookBundle.shared?.opportunityRef ?? [:]

        var presentByClass: [Int: Int] = [:]
        var foundByClass: [Int: Int] = [:]
        for w in solved.words {
            let lc = min(w.word.count, 7)
            presentByClass[lc, default: 0] += 1
            if foundAt[w.word] != nil { foundByClass[lc, default: 0] += 1 }
        }

        let free = freeWords(solved: solved, result: result)
        var rows: [[String: Any?]] = []
        rows.reserveCapacity(solved.count)
        for w in solved.words {
            let lc = min(w.word.count, 7)
            let opportunity = Belief.opportunity(
                foundOfClass: foundByClass[lc] ?? 0, presentOfClass: presentByClass[lc] ?? 0,
                side: side, length: w.word.count, reference: reference)
            let isFound = foundAt[w.word] != nil
            let kind: Belief.Evidence = targets.contains(w.word) ? evidence : .unpromptedBoard
            let contribution = Belief.contribution(found: isFound, opportunity: opportunity,
                                                   evidence: kind)
            rows.append([
                "game_id": gameId, "word": w.word, "len": w.word.count,
                "points": w.points, "found": isFound ? 1 : 0, "t_found": foundAt[w.word],
                "grid": side, "tier": tier,
                "board_words": solved.count, "purpose": purpose,
                "path_count": w.pathCount,
                "free": free[w.word] != nil ? 1 : 0, "host": free[w.word],
                "source": "inapp", "opportunity": opportunity, "evidence": kind.rawValue,
                "w_finds": contribution.finds, "w_opportunity": contribution.opportunity,
            ])
        }
        Database.shared.writeMany("presence", rows)
    }

    /// One row per family with a member on the board. Grouping here, at write time, is
    /// what turns "have I got the ones worth having on TORE-" into a single indexed
    /// select instead of a scan over every presence row ever written.
    static func writeMeetings(gameId: String, side: Int, purpose: String, drilled: String?,
                              meetings: [String: FamilyMeeting]) {
        guard !meetings.isEmpty else { return }
        let wall = now()
        let rows = meetings.values.map { m -> [String: Any?] in
            [
                "game_id": gameId, "stem": m.stem,
                "present": m.present.count, "found": m.found.count,
                "points_present": m.pointsPresent, "points_found": m.pointsFound,
                "purpose": purpose, "grid": side,
                "drilled": m.stem == drilled ? 1 : 0, "wall": wall,
            ]
        }
        Database.shared.writeMany("hook_meeting", rows)
    }

    /// Which words were sitting on a path already swiped, and off which find. This is the
    /// 74%-against-1% distinction made concrete: a word whose cells were already under the
    /// finger is a different proposition from one that had to be found cold, and pricing
    /// the two the same is what the whole project is trying to stop doing.
    static func freeWords(board: HookBoard, result: GameResult) -> [String: String] {
        freeWords(solved: board.solved, result: result)
    }

    static func freeWords(solved: SolvedBoard, result: GameResult) -> [String: String] {
        guard !result.found.isEmpty else { return [:] }
        var swiped: [String: String] = [:]   // encoded path -> the word that swiped it
        for f in result.found where f.cells.count >= 3 {
            swiped[encode(f.cells)] = f.word
        }
        guard !swiped.isEmpty else { return [:] }

        var out: [String: String] = [:]
        for w in solved.words where w.word.count >= 4 {
            outer: for path in w.paths {
                guard path.count > 3 else { continue }
                for length in 3...(path.count - 1) {
                    for start in 0...(path.count - length) {
                        let key = encode(Array(path[start..<(start + length)]))
                        if let host = swiped[key], host != w.word {
                            out[w.word] = host
                            break outer
                        }
                    }
                }
            }
        }
        return out
    }

    private static func encode(_ cells: [Int]) -> String {
        cells.map { String(UnicodeScalar(UInt8(65 + $0))) }.joined()
    }

    // MARK: Affix grid

    static func startAffixGrid(id: String, sessionId: String, seq: Int, stem: String) {
        Database.shared.write("exercise", [
            "exercise_id": id, "session_id": sessionId, "seq": seq,
            "kind": GameKind.affixGrid, "hook": stem, "purpose": "affix_grid",
            "started_wall": now(), "abandoned": 1,
        ])
    }

    static func recordJudgement(exerciseId: String, seq: Int, stem: String, item: AffixItem,
                                answeredLive: Bool, latency: Double) {
        Database.shared.write("judgement", [
            "exercise_id": exerciseId, "seq": seq, "stem": stem, "word": item.word,
            "cls": item.cls.rawValue, "live": item.isLive ? 1 : 0,
            "answered_live": answeredLive ? 1 : 0,
            "correct": answeredLive == item.isLive ? 1 : 0,
            "latency": latency, "from_misswipe": item.fromMisswipe ? 1 : 0,
        ])
    }

    static func finishAffixGrid(id: String, correct: Int, total: Int, abandoned: Bool) {
        Database.shared.execute(
            "UPDATE exercise SET ended_wall = ?, found = ?, missed = ?, abandoned = ? "
                + "WHERE exercise_id = ?",
            [now(), correct, total - correct, abandoned ? 1 : 0, id])
    }

    // MARK: Hook state

    /// Phase 3's whole scheduler: exposure counts and a due date. The brief rules out
    /// anything more until Phase 4, and a due date is enough to re-inject a hook into a
    /// later acquisition board unannounced.
    static func recordDrill(stem: String, grid: Int, dueInDays: Int = 7) {
        let due = iso.string(from: Date().addingTimeInterval(Double(dueInDays) * 86400))
        Database.shared.execute("""
            INSERT INTO hook_state(stem, exposures, first_drilled, last_drilled, due_wall, grids_seen)
            VALUES(?, 1, ?, ?, ?, ?)
            ON CONFLICT(stem) DO UPDATE SET
                exposures = exposures + 1,
                last_drilled = excluded.last_drilled,
                due_wall = excluded.due_wall,
                grids_seen = CASE WHEN instr(COALESCE(grids_seen, ''), excluded.grids_seen) > 0
                                  THEN grids_seen ELSE COALESCE(grids_seen, '') || excluded.grids_seen END
            """, [stem, now(), now(), due, "\(grid)"])
    }

    static func recordSweep(stem: String, dueInDays: Int = 14) {
        let due = iso.string(from: Date().addingTimeInterval(Double(dueInDays) * 86400))
        Database.shared.execute("""
            INSERT INTO hook_state(stem, sweeps, due_wall) VALUES(?, 1, ?)
            ON CONFLICT(stem) DO UPDATE SET sweeps = sweeps + 1, due_wall = excluded.due_wall
            """, [stem, due])
    }
}

enum GameKind {
    static let affixGrid = "affix_grid"
}

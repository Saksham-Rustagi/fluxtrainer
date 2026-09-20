import Foundation

/// The one path every finished board goes down, whoever served it.
///
/// Phase 3 solved and recorded only the boards the *session* served. A ranked game -- the
/// thing actually played most -- wrote a `game` row, a pile of `attempt` rows and nothing
/// the player model could read. That made the brief's first mechanism false: `myRate`
/// could not recompute from ranked plus in-app presences, because in-app ranked presences
/// did not exist.
///
/// So: solve the board after the game, write one `presence` row per word and one
/// `hook_meeting` row per family, then build the review off the same solve. One solve, and
/// everything downstream reads it.
enum PlayedBoard {
    struct Context {
        /// "ranked" for an ordinary game, which is what the Play button serves. Phase 1's
        /// tooling reads `COALESCE(purpose, 'ranked')`, so anything else here quietly
        /// removes the board from every ranked query in `tools/clone_report` and from the
        /// percentile this app shows. A first draft defaulted to "measurement" and did
        /// exactly that.
        var purpose: String = "ranked"
        /// The stem the board was built around, when there was one. Recorded on the
        /// meeting rows so the per-stem trend can exclude boards that pointed at it.
        var drilledStem: String?
        /// A family sweep's targets carry the exercise's evidence weight; everything else
        /// on the board was found or missed unprompted whatever the board was for.
        var evidence: Belief.Evidence = .unpromptedBoard
        var targets: Set<String> = []
        /// A drill board's own logging is already done by `TrainingLog.finishExercise`;
        /// this path then only writes the meetings and builds the review.
        var presencesAlreadyWritten = false
        /// Mixed practice: the families the board was seeded with, so review can score
        /// against what was *aimed at* rather than only what happened to be there.
        var mixedStems: [String] = []
    }

    /// Solves, records, and hands back a review. The completion runs on the main thread.
    ///
    /// Abandoned boards are recorded but not reviewed: a board left after nine seconds is
    /// not evidence of anything, and reviewing it would say so at length.
    static func finish(result: GameResult, context: Context, index: FamilyIndex?,
                       engine: FluxEngine = .shared,
                       completion: @escaping (BoardReview?) -> Void) {
        engine.perform({ () -> BoardReview? in
            let solved = engine.solve(side: result.board.side, letters: result.board.letters)
            if !context.presencesAlreadyWritten {
                TrainingLog.writePresences(
                    gameId: result.gameId, side: result.board.side,
                    tier: result.board.tier.name, purpose: context.purpose, solved: solved,
                    result: result, evidence: context.evidence, targets: context.targets)
                // Left NULL for a ranked game, as Phase 1 wrote it, so the column keeps
                // meaning "this board was not an ordinary game".
                if context.purpose != "ranked" {
                    Database.shared.execute("UPDATE game SET purpose = ? WHERE game_id = ?",
                                            [context.purpose, result.gameId])
                }
            }
            guard let index else { return nil }
            let found = Set(result.found.map(\.word))
            let meetings = index.meetings(on: solved, found: found)
            TrainingLog.writeMeetings(gameId: result.gameId, side: result.board.side,
                                      purpose: context.purpose, drilled: context.drilledStem,
                                      meetings: meetings)
            guard !result.abandoned else { return nil }
            return ReviewBuilder.build(result: result, solved: solved, purpose: context.purpose,
                                       index: index,
                                       isWord: { engine.wordId($0) != nil },
                                       meetings: meetings,
                                       drilledStem: context.drilledStem,
                                       mixedStems: context.mixedStems)
        }, then: completion)
    }
}

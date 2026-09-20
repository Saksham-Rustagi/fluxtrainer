import Foundation
import SwiftUI

/// The session. One button starts it; nothing in it asks a question.
///
///     TAP ─── warm-up board (60s, unscored, no review)
///              ├─ new hook: branch completion x 2 boards, then the affix grid
///              ├─ due hooks: family sweep x 2 acquisition boards, unannounced
///              └─ summary: 20 seconds
///
/// Two rules, both from the brief and both load-bearing:
///
///   * **The app chooses the hook**, from the top of the queue filtered to enumerability
///     2-6 and owned >= 2. A queue of 10,594 hooks is a decision that should not be made
///     daily, and a session that opens with a choice is a session that gets skipped.
///   * **Any screen can be left mid-session and resumed.** Real sessions get interrupted.
///     The plan is persisted on every step, so a relaunch picks up at the same place. A
///     board that was on screen is lost, which is correct: it would be a seen board.
@MainActor
final class TrainingSession: ObservableObject {
    enum Step: Equatable, Codable {
        case warmup
        case drill(stem: String, attempt: Int)
        case affixGrid(stem: String)
        case sweep(stem: String, attempt: Int)
        case summary
    }

    enum Screen {
        case preparing(String)
        /// One card before a hook's first drill board, saying what the drill is for in the
        /// player's own numbers. The hook record has carried this line since Phase 2 and
        /// nothing displayed it, which is why the drill read as teaching words he knows.
        case brief(Hook, [SightGap], BoardScreen)
        case board(BoardScreen)
        case verdict(Verdict)
        case affixGrid(Hook, exerciseId: String, seq: Int)
        case summary(Summary)
        case failed(String)
    }

    struct BoardScreen {
        let board: HookBoard
        let mode: GameMode
        let exerciseId: String
        let step: Step
        let attemptForHook: Int
    }

    /// SPEC 9.2: one card, 15 seconds, then straight on. The board half of the review
    /// already happened -- the misses were drawn on the grid.
    struct Verdict {
        let hook: Hook?
        /// Found, with seconds to find and how that compares to the last time this word
        /// was drilled. For a word you already know, seconds is the only thing that can
        /// move, so found/missed alone would look identical in week 1 and week 6.
        let found: [Outcome]
        let missed: [Outcome]
        let stemWasLit: Bool
        let score: Int
        /// The one-tap repeat. The most common action after a drill is doing it again.
        let canRepeat: Bool

        struct Outcome: Identifiable {
            let word: String
            let seconds: Double?
            let previousSeconds: Double?
            let knowledge: WordKnowledge.Verdict
            var id: String { word }

            /// Only meaningful on a word the grid says you know: it is a vision result.
            var improvement: Double? {
                guard let seconds, let previousSeconds, previousSeconds > 0 else { return nil }
                return previousSeconds - seconds
            }
        }
    }

    struct Summary {
        var boards = 0
        /// How the grid sorted this session's words. The headline the player was missing:
        /// most of what the queue teaches is words he knows and does not see.
        var judgedKnown = 0, judgedShaky = 0, judgedUnknown = 0
        /// Seconds to find, on words the grid says he knows.
        var sightTimes: [Double] = []
        var judgements = 0
        var judgementsCorrect = 0
        var medianJudgementLatency: Double?
        var litFound = 0, litTotal = 0
        var unpromptedFound = 0, unpromptedTotal = 0
        var drilledHook: String?
        var sweptHooks: [String] = []
        var tomorrowHook: String?
        var dueTomorrow = 0
        var degradedBoards = 0
    }

    @Published private(set) var screen: Screen = .preparing("Loading the queue")
    @Published private(set) var summary = Summary()

    let queue: TrainingQueue
    private(set) var sessionId: String
    private var plan: [Step]
    private var cursor: Int
    private var seq = 0
    private let engine = FluxEngine.shared
    private let shortDay: Bool

    // MARK: Lifecycle

    init(queue: TrainingQueue, shortDay: Bool) {
        self.queue = queue
        self.shortDay = shortDay
        if let saved = Resume.load(), saved.shortDay == shortDay {
            sessionId = saved.sessionId
            plan = saved.plan
            cursor = saved.cursor
            summary.drilledHook = saved.plan.compactMap(Self.stem(of:)).first
        } else {
            sessionId = UUID().uuidString
            let newHook = queue.nextHook()
            let due = queue.dueHooks(limit: 2)
            plan = Self.buildPlan(newHook: newHook, due: due, shortDay: shortDay)
            cursor = 0
            summary.drilledHook = newHook?.stem
            summary.sweptHooks = due.map(\.stem)
            TrainingLog.startSession(id: sessionId, shape: shortDay ? "short" : "full",
                                     newHook: newHook?.stem, dueHooks: due.map(\.stem),
                                     queueRecomputedAt: queue.lastRecomputed)
        }
        advance(to: cursor)
    }

    /// The shape, built once. A short day is one board plus one affix grid, graded
    /// normally: an earlier draft graded a short day at reduced weight, which penalises
    /// having a life and makes the schedule drift on exactly the days it should not.
    static func buildPlan(newHook: Hook?, due: [Hook], shortDay: Bool) -> [Step] {
        var plan: [Step] = []
        if !shortDay { plan.append(.warmup) }
        if let hook = newHook {
            // The grid goes first, and it is a sorting step before it is a teaching step.
            // It decides, per word, whether the board drill that follows is about seeing
            // or about knowing -- which is the distinction find rate alone cannot make.
            plan.append(.affixGrid(stem: hook.stem))
            plan.append(.drill(stem: hook.stem, attempt: 1))
            if !shortDay { plan.append(.drill(stem: hook.stem, attempt: 2)) }
        }
        if !shortDay {
            // Two acquisition boards for the due hooks, however many there are. The hooks
            // are embedded and not announced: being told which board is a review board
            // makes the review worthless.
            for hook in due.prefix(2) {
                plan.append(.sweep(stem: hook.stem, attempt: 1))
                if due.count == 1 { plan.append(.sweep(stem: hook.stem, attempt: 2)) }
            }
        }
        plan.append(.summary)
        return plan
    }

    static func stem(of step: Step) -> String? {
        switch step {
        case .drill(let s, _): return s
        case .affixGrid(let s): return s
        case .sweep(let s, _): return s
        case .warmup, .summary: return nil
        }
    }

    // MARK: Driving

    func next() { advance(to: cursor + 1) }

    /// Leaves the brief and starts the board it was about.
    func startBriefedBoard(_ state: BoardScreen) { screen = .board(state) }

    /// Repeat the current hook on a fresh board. Stays on the same plan step number, so a
    /// repeat does not consume the second scheduled attempt.
    func repeatBoard() { advance(to: cursor) }

    /// Skip the rest of this hook's boards and move to the next distinct step.
    func skipHook() {
        guard cursor < plan.count, let stem = Self.stem(of: plan[cursor]) else { return next() }
        var i = cursor + 1
        while i < plan.count, case .drill(let s, _) = plan[i], s == stem { i += 1 }
        advance(to: i)
    }

    private func advance(to index: Int) {
        cursor = min(index, plan.count - 1)
        Resume.save(sessionId: sessionId, plan: plan, cursor: cursor, shortDay: shortDay)
        guard cursor < plan.count else { return finish() }

        switch plan[cursor] {
        case .warmup:
            prepare(purpose: .warmup, hook: nil, step: plan[cursor])
        case .drill(let stem, let attempt):
            guard let hook = queue.hook(stem) else { return next() }
            prepare(purpose: .drill, hook: hook, step: plan[cursor], attempt: attempt)
        case .sweep(let stem, let attempt):
            guard let hook = queue.hook(stem) else { return next() }
            prepare(purpose: .acquisition, hook: hook, step: plan[cursor], attempt: attempt)
        case .affixGrid(let stem):
            guard let hook = queue.hook(stem) else { return next() }
            let id = UUID().uuidString
            seq += 1
            TrainingLog.startAffixGrid(id: id, sessionId: sessionId, seq: seq, stem: stem)
            screen = .affixGrid(hook, exerciseId: id, seq: seq)
        case .summary:
            finish()
        }
    }

    private func prepare(purpose: BoardPurpose, hook: Hook?, step: Step, attempt: Int = 1) {
        screen = .preparing(purpose == .warmup ? "Warm-up" : "Making a board")
        let density = queue.bundle.density
        let engine = self.engine
        engine.perform({ () -> HookBoard? in
            switch purpose {
            case .warmup, .measurement:
                return TrainingBoards.ranked(purpose: purpose, engine: engine)
            case .drill:
                return hook.flatMap { TrainingBoards.drill(hook: $0, engine: engine) }
            case .acquisition:
                return hook.flatMap {
                    TrainingBoards.acquisition(hook: $0, engine: engine, density: density)
                }
            }
        }, then: { [weak self] board in
            guard let self else { return }
            guard let board else {
                self.screen = .failed("Could not make a board for \(hook?.stem ?? "the warm-up")")
                return
            }
            self.present(board: board, step: step, attempt: attempt)
        })
    }

    private func present(board: HookBoard, step: Step, attempt: Int) {
        seq += 1
        let id = UUID().uuidString
        var mode = GameMode()
        switch board.purpose {
        case .warmup:
            // 60 seconds, unscored in the sense that nothing is reviewed or drilled off
            // it. The score stays on screen because a warm-up that does not feel like a
            // game does not warm anything up.
            mode = GameMode(kind: .warmup, duration: 60, showsScore: true)
        case .drill:
            // 30 to 45 seconds, scaled to how much is on the board. Stem lit, a counter,
            // the clock, and no other text.
            let seconds = min(45.0, 30.0 + 3.0 * Double(max(0, board.targets.count - 3)))
            var paths: [String: [Int]] = [:]
            for word in board.targets { paths[word] = board.path(for: word) }
            mode = GameMode(kind: .branchCompletion, duration: seconds, showsScore: false,
                            litPath: board.litPath ?? [], targets: Set(board.targets),
                            showsCounter: true, replayMisses: true, targetPaths: paths)
        case .acquisition:
            // 60 seconds, everything scores, so it feels like a game rather than a quiz.
            var paths: [String: [Int]] = [:]
            for word in board.targets { paths[word] = board.path(for: word) }
            mode = GameMode(kind: .familySweep, duration: 60, showsScore: true,
                            targets: Set(board.targets), replayMisses: true, targetPaths: paths)
        case .measurement:
            mode = GameMode(kind: .ranked, duration: GameViewController.duration)
        }
        TrainingLog.startExercise(id: id, sessionId: sessionId, seq: seq, kind: mode.kind,
                                  board: board, attemptForHook: attempt,
                                  duration: mode.duration)
        let screenState = BoardScreen(board: board, mode: mode, exerciseId: id, step: step,
                                      attemptForHook: attempt)
        // Only before the first board for a hook. The repeat is one tap and nothing else.
        if board.purpose == .drill, attempt == 1, let hook = board.hook {
            let gaps = SightGap.forHook(hook)
            if !gaps.isEmpty {
                screen = .brief(hook, gaps, screenState)
                return
            }
        }
        screen = .board(screenState)
    }

    // MARK: Results

    func boardFinished(_ screenState: BoardScreen, result: GameResult) {
        let board = screenState.board
        let evidence: Belief.Evidence
        switch board.purpose {
        case .drill: evidence = .litDrill
        case .acquisition: evidence = .familySweep
        case .warmup, .measurement: evidence = .unpromptedBoard
        }
        let outcome = TrainingLog.finishExercise(
            id: screenState.exerciseId, sessionId: sessionId, board: board, result: result,
            evidence: evidence, attemptForHook: screenState.attemptForHook)

        summary.boards += 1
        if board.degraded { summary.degradedBoards += 1 }
        if board.litPath != nil {
            summary.litFound += outcome.found.count
            summary.litTotal += board.targets.count
        } else if board.hook != nil {
            summary.unpromptedFound += outcome.found.count
            summary.unpromptedTotal += board.targets.count
        }
        if let hook = board.hook {
            switch board.purpose {
            case .drill: TrainingLog.recordDrill(stem: hook.stem, grid: board.side)
            case .acquisition: TrainingLog.recordSweep(stem: hook.stem)
            default: break
            }
        }

        if result.abandoned {
            next()
            return
        }

        // Seconds to find, against the last time the same word was drilled. This is the
        // number a vision drill moves; found/missed is not.
        let times = Dictionary(result.found.map { ($0.word, $0.t - result.tBoardShown) },
                               uniquingKeysWith: { a, _ in a })
        let knowledge = board.hook.map { WordKnowledge.verdicts(forStem: $0.stem) } ?? [:]
        let previous = Self.previousFindTimes(exerciseId: screenState.exerciseId,
                                              words: board.targets)
        func outcomes(_ words: [String]) -> [Verdict.Outcome] {
            words.map { word in
                Verdict.Outcome(word: word, seconds: times[word], previousSeconds: previous[word],
                                knowledge: knowledge[word] ?? .unjudged)
            }
            .sorted { ($0.seconds ?? .greatestFiniteMagnitude) < ($1.seconds ?? .greatestFiniteMagnitude) }
        }
        for word in outcome.found where (knowledge[word] ?? .unjudged) == .known {
            if let t = times[word] { summary.sightTimes.append(t) }
        }

        let canRepeat = board.purpose == .drill
        screen = .verdict(Verdict(hook: board.hook, found: outcomes(outcome.found),
                                  missed: outcomes(outcome.missed),
                                  stemWasLit: board.litPath != nil, score: result.score,
                                  canRepeat: canRepeat))
    }

    /// The last time each of these words was found on an earlier exercise. Excludes the
    /// one just played, so "faster than last time" means what it says.
    private static func previousFindTimes(exerciseId: String, words: [String]) -> [String: Double] {
        guard !words.isEmpty else { return [:] }
        var out: [String: Double] = [:]
        let list = words.map { "'" + $0.replacingOccurrences(of: "'", with: "''") + "'" }
            .joined(separator: ",")
        Database.shared.query("""
            SELECT word, t_found FROM branch_event
            WHERE word IN (\(list)) AND found = 1 AND t_found IS NOT NULL
              AND exercise_id != ?
            ORDER BY rowid
            """, [exerciseId]) { row in
            out[row.text(0)] = row.double(1)   // later rows win: the most recent attempt
        }
        return out
    }

    func affixGridFinished(exerciseId: String, correct: Int, total: Int, abandoned: Bool) {
        summary.judgements += total
        summary.judgementsCorrect += correct
        if let stem = Self.stem(of: plan[min(cursor, plan.count - 1)]) {
            for verdict in WordKnowledge.verdicts(forStem: stem).values {
                switch verdict {
                case .known: summary.judgedKnown += 1
                case .shaky: summary.judgedShaky += 1
                case .unknown: summary.judgedUnknown += 1
                case .unjudged: break
                }
            }
        }
        if abandoned {
            TrainingLog.finishAffixGrid(id: exerciseId, correct: correct, total: total,
                                        abandoned: true)
        }
        next()
    }

    private func finish() {
        // Recompute at session end, which is when the evidence has actually changed.
        queue.recompute()
        summary.medianJudgementLatency = Self.medianLatency(sessionId: sessionId)
        summary.tomorrowHook = queue.nextHook(excluding: Set([summary.drilledHook].compactMap { $0 }))?.stem
        summary.dueTomorrow = queue.dueHooks(limit: 10).count
        TrainingLog.endSession(id: sessionId, boards: summary.boards,
                               judgements: summary.judgements, abandoned: false)
        Resume.clear()
        screen = .summary(summary)
    }

    /// The 1.2 s target in SPEC 7.3 is a per-judgement one, so the median is the honest
    /// summary of it; a mean is dominated by the one card that was looked at for a while.
    private static func medianLatency(sessionId: String) -> Double? {
        var values: [Double] = []
        Database.shared.query("""
            SELECT j.latency FROM judgement j JOIN exercise e ON e.exercise_id = j.exercise_id
            WHERE e.session_id = ? ORDER BY j.latency
            """, [sessionId]) { values.append($0.double(0)) }
        guard !values.isEmpty else { return nil }
        return values[values.count / 2]
    }

    func abandon() {
        TrainingLog.endSession(id: sessionId, boards: summary.boards,
                               judgements: summary.judgements, abandoned: true)
        Resume.clear()
    }

    // MARK: Resume

    /// The plan, on disk, so an interrupted session comes back where it was.
    enum Resume {
        private static let key = "training.session.resume"

        struct State: Codable {
            let sessionId: String
            let plan: [Step]
            let cursor: Int
            let shortDay: Bool
            let savedAt: Date
        }

        static func save(sessionId: String, plan: [Step], cursor: Int, shortDay: Bool) {
            let state = State(sessionId: sessionId, plan: plan, cursor: cursor,
                              shortDay: shortDay, savedAt: Date())
            if let data = try? JSONEncoder().encode(state) {
                UserDefaults.standard.set(data, forKey: key)
            }
        }

        /// A session left overnight is not resumed: it is a new day, the queue has moved,
        /// and picking up yesterday's plan would drill yesterday's hook.
        static func load(maxAge: TimeInterval = 6 * 3600) -> State? {
            guard let data = UserDefaults.standard.data(forKey: key),
                  let state = try? JSONDecoder().decode(State.self, from: data),
                  Date().timeIntervalSince(state.savedAt) < maxAge,
                  state.cursor < state.plan.count else { return nil }
            return state
        }

        static var pending: Bool { load() != nil }

        static func clear() { UserDefaults.standard.removeObject(forKey: key) }
    }
}

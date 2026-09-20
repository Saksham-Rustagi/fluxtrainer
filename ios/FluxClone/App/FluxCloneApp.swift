import SwiftUI
import UIKit

@main
struct FluxCloneApp: App {
    @StateObject private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Exporter.autoExportIfDue() }
        }
    }
}

/// **Playing is the front door and review is what comes back through it.** Phase 3 had it
/// the other way round: the trainer sat above Play and a finished board showed a score and
/// nothing else. That made the app a content engine with a game attached.
///
/// Drilling is still one tap, but it is reached from review or from a family, which is
/// where the decision to drill something actually gets made.
@MainActor
final class AppModel: ObservableObject {
    enum Screen {
        case home
        case preparing(String)
        case failed(String)
        case playing(GeneratedBoard, GameMode, PlayedBoard.Context)
        case reviewing(BoardReview)
        case training(TrainingSession)
    }

    @Published var screen: Screen = .home
    @Published var engineReady = false
    @Published var engineError: String?
    /// Phase 3. Nil until the hook record is parsed, and nil for good if it will not
    /// parse -- the clone still plays, it just cannot teach.
    @Published var queue: TrainingQueue?
    @Published var queueError: String?
    @Published var nextBoard: GeneratedBoard?
    @Published var waitingToPlay = false
    @Published var gridOverride: Int? {
        didSet { if oldValue != gridOverride { regenerate() } }
    }
    @Published var tierOverride: Tier? {
        didSet { if oldValue != tierOverride { regenerate() } }
    }

    private var generation = 0
    private var index: FamilyIndex? { FamilyIndex.shared }

    init() {
        DispatchQueue.global(qos: .userInitiated).async {
            _ = FluxEngine.shared
            _ = Database.shared
            // 13 MB of hook record, parsed once, off the main thread, and the reverse
            // index built beside it -- review asks word -> families on every board.
            let bundle = HookBundle.load()
            if let bundle { FamilyIndex.build(bundle: bundle) }
            DispatchQueue.main.async {
                self.engineReady = true
                if let bundle {
                    self.queue = TrainingQueue(bundle: bundle)
                } else {
                    self.queueError = HookBundle.loadError ?? "the hook record did not load"
                }
                self.regenerate()
                Exporter.autoExportIfDue()
                // Smoke testing: FLUXCLONE_AUTOPLAY=1 starts a game as soon as a board
                // is ready, so a simulator run can reach the board without a tap.
                if ProcessInfo.processInfo.environment["FLUXCLONE_AUTOPLAY"] == "1" { self.play() }
                // The same smoke hatch for the trainer: start a short session as soon as
                // the queue is up, so a simulator run reaches a drill board without a tap.
                // A half-finished session is resumed by design, which is right for a real
                // day and wrong for a test that wants the session from the top, so the
                // reset hatch exists alongside it.
                if ProcessInfo.processInfo.environment["FLUXCLONE_RESET_SESSION"] == "1" {
                    TrainingSession.Resume.clear()
                }
                if ProcessInfo.processInfo.environment["FLUXCLONE_TRAIN"] == "1" {
                    self.train(shortDay: true)
                }
            }
        }
    }

    /// Boards are generated ahead, off the main thread, so Play shows one immediately.
    func regenerate() {
        guard engineReady else { return }
        generation += 1
        let token = generation
        nextBoard = nil
        FluxEngine.shared.generate(sideOverride: gridOverride, tierOverride: tierOverride) { board in
            guard token == self.generation else { return }
            self.nextBoard = board
            if self.waitingToPlay, let board {
                self.waitingToPlay = false
                self.screen = .playing(board, .ranked, PlayedBoard.Context())
            }
        }
    }

    func play() {
        if let board = nextBoard {
            nextBoard = nil
            screen = .playing(board, .ranked, PlayedBoard.Context())
        } else {
            waitingToPlay = true
        }
    }

    /// Section 5: a normal scored board seeded with the families he picked, with nothing
    /// on screen saying they are there. The per-family breakdown arrives in review, which
    /// is the only place it belongs.
    ///
    /// The stems are chosen in the picker, not here. An earlier version chose them off the
    /// top of the queue, which is deterministic, so it served the same five families every
    /// time -- and a practice board that is the same board every time is not practice.
    func playMixed(stems: [String]) {
        guard let queue else { return }
        let hooks = stems.compactMap { queue.hook($0) }
        guard hooks.count >= MixedCandidates.range.lowerBound else { return }
        screen = .preparing("Seeding a board with \(hooks.count) families")
        let engine = FluxEngine.shared
        engine.perform({ TrainingBoards.mixed(hooks: hooks, engine: engine) }) { [weak self] made in
            guard let self else { return }
            guard let made else {
                // Never silently serve a different board. The old code fell back to an
                // ordinary ranked game here, which is why review then showed unrelated
                // families and nothing about the ones that were asked for.
                self.screen = .failed("Could not fit "
                    + hooks.map { "\($0.stem)-" }.joined(separator: ", ")
                    + " onto one board. Try fewer, or swap the longest one out.")
                return
            }
            var context = PlayedBoard.Context()
            context.purpose = BoardPurpose.mixed.rawValue
            context.mixedStems = made.mixedStems
            // No targets and no reduced weight: it is played as an ordinary board with
            // nothing pointed at, so every word on it is unprompted evidence.
            self.screen = .playing(made.board,
                                   GameMode(kind: .ranked, duration: GameViewController.duration),
                                   context)
        }
    }

    /// Every finished board goes through here: solved, recorded, reviewed. A ranked game
    /// used to write a score and nothing the player model could read.
    func finished(_ result: GameResult, context: PlayedBoard.Context) {
        PlayedBoard.finish(result: result, context: context, index: index) { [weak self] review in
            guard let self else { return }
            if let review, !result.abandoned {
                self.screen = .reviewing(review)
            } else {
                self.screen = .home
            }
            self.queue?.recompute()
            self.regenerate()
        }
    }

    /// One tap. No configuration, no menu, no choosing a hook -- unless review has just
    /// made the case for a particular family, in which case that is the hook.
    func train(shortDay: Bool, hook: Hook? = nil) {
        guard let queue else { return }
        screen = .training(TrainingSession(queue: queue, shortDay: shortDay, forcedHook: hook))
    }

    func drill(stem: String) {
        guard let queue, let hook = queue.hook(stem) else { return }
        train(shortDay: true, hook: hook)
    }

    func endTraining() {
        screen = .home
        regenerate()
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        switch model.screen {
        case .home:
            MainTabs()
        case .preparing(let what):
            VStack(spacing: 16) {
                ProgressView().tint(Color(uiColor: FluxTheme.main)).scaleEffect(1.3)
                Text(what).foregroundStyle(.secondary)
                Button("Back") { model.screen = .home }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: FluxTheme.bg))
        case .failed(let message):
            VStack(spacing: 16) {
                Text(message)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Back") { model.screen = .home }
                    .tint(Color(uiColor: FluxTheme.main))
            }
            .padding(30)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: FluxTheme.bg))
        case .playing(let board, let mode, let context):
            GameHost(board: board, mode: mode) { model.finished($0, context: context) }
                .ignoresSafeArea()
                .statusBarHidden(false)
        case .reviewing(let review):
            ReviewView(review: review,
                       again: model.play,
                       home: { model.screen = .home },
                       drill: model.drill(stem:))
        case .training(let session):
            SessionView(session: session, onExit: model.endTraining)
        }
    }
}

struct GameHost: UIViewControllerRepresentable {
    let board: GeneratedBoard
    var mode: GameMode = .ranked
    let onFinish: (GameResult) -> Void

    func makeUIViewController(context: Context) -> GameViewController {
        let recordRaw = Database.shared.rawSampleGameCount() < RawSampling.gameLimit
        return GameViewController(board: board, config: RecognizerSettings.current,
                                  recordRaw: recordRaw, mode: mode, onFinish: onFinish)
    }

    func updateUIViewController(_ vc: GameViewController, context: Context) {}
}

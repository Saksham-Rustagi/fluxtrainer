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

@MainActor
final class AppModel: ObservableObject {
    enum Screen {
        case home
        case playing(GeneratedBoard)
        case results(GameResult)
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

    init() {
        DispatchQueue.global(qos: .userInitiated).async {
            _ = FluxEngine.shared
            _ = Database.shared
            // 13 MB of hook record, parsed once, off the main thread.
            let bundle = HookBundle.load()
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
                self.screen = .playing(board)
            }
        }
    }

    func play() {
        if let board = nextBoard {
            nextBoard = nil
            screen = .playing(board)
        } else {
            waitingToPlay = true
        }
    }

    func finished(_ result: GameResult) {
        screen = result.abandoned ? .home : .results(result)
        regenerate()
    }

    /// One tap. No configuration, no menu, no choosing a hook.
    func train(shortDay: Bool) {
        guard let queue else { return }
        screen = .training(TrainingSession(queue: queue, shortDay: shortDay))
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
            HomeView()
        case .playing(let board):
            GameHost(board: board) { model.finished($0) }
                .ignoresSafeArea()
                .statusBarHidden(false)
        case .results(let result):
            ResultsView(result: result)
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

import AVFoundation
import UIKit

/// Flux's five gameplay haptic slots at their defaults (SettingsManager.swift:277-285),
/// fired as BoardView.triggerHaptic does: impactOccurred(intensity: 0.9) on generators
/// created and prepared once per game and never re-prepared mid-game.
final class Haptics {
    enum Pattern { case none, light, medium, heavy, double }

    static let startChain: Pattern = .none
    static let invalidChain: Pattern = .none
    static let validChain: Pattern = .medium
    static let submitInvalid: Pattern = .none
    static let submitValid: Pattern = .heavy

    private let light = UIImpactFeedbackGenerator(style: .light)
    private let medium = UIImpactFeedbackGenerator(style: .medium)
    private let heavy = UIImpactFeedbackGenerator(style: .heavy)

    func prepare() {
        medium.prepare()
        heavy.prepare()
    }

    func fire(_ pattern: Pattern) {
        switch pattern {
        case .none: return
        case .light: light.impactOccurred(intensity: 0.9)
        case .medium: medium.impactOccurred(intensity: 0.9)
        case .heavy: heavy.impactOccurred(intensity: 0.9)
        case .double:
            medium.impactOccurred(intensity: 0.9)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [medium] in
                medium.impactOccurred(intensity: 0.9)
            }
        }
    }
}

/// Flux's SoundManager in miniature: an AVAudioEngine with a pool of player nodes and
/// preloaded buffers, the .ambient / mixWithOthers session, SFX volume 0.8, and every
/// play dispatched off the main thread after the haptic has fired.
final class Sounds {
    static let shared = Sounds()

    private let engine = AVAudioEngine()
    private var pool: [AVAudioPlayerNode] = []
    private var next = 0
    private var buffers: [String: AVAudioPCMBuffer] = [:]
    private let queue = DispatchQueue(label: "fluxclone.sound", qos: .userInteractive)
    private var started = false
    private static let sfxVolume: Float = 0.8

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "soundEnabled") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "soundEnabled") }
    }

    private init() {}

    func start() {
        queue.async { [self] in
            guard !started else { return }
            try? AVAudioSession.sharedInstance().setCategory(.ambient, mode: .default, options: [.mixWithOthers])
            try? AVAudioSession.sharedInstance().setActive(true)
            // SoundManager.preloadCriticalSounds: logical name -> file.
            let names = [("press", "letter"), ("validDrag", "validDrag"), ("invalidRelease", "invalidRelease")]
                + ((3...10).map { "submit\($0)" } + ["submit_11", "submit_12"]).map { ($0, $0) }
            var format: AVAudioFormat?
            for (name, fileName) in names {
                guard let url = Bundle.main.url(forResource: fileName, withExtension: "wav"),
                      let file = try? AVAudioFile(forReading: url),
                      let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                                    frameCapacity: AVAudioFrameCount(file.length)),
                      (try? file.read(into: buffer)) != nil else { continue }
                buffers[name] = buffer
                format = format ?? file.processingFormat
            }
            guard let format else { return }
            for _ in 0..<8 {
                let node = AVAudioPlayerNode()
                engine.attach(node)
                engine.connect(node, to: engine.mainMixerNode, format: format)
                pool.append(node)
            }
            engine.mainMixerNode.outputVolume = Self.sfxVolume
            engine.prepare()
            started = (try? engine.start()) != nil
            pool.forEach { $0.play() }
        }
    }

    func play(_ name: String, volume: Float = 1.0) {
        guard enabled else { return }
        queue.async { [self] in
            guard started, let buffer = buffers[name], !pool.isEmpty else { return }
            if !engine.isRunning { try? engine.start() }
            let node = pool[next]
            next = (next + 1) % pool.count
            node.volume = volume
            // Buffers with a format different from the pool's are skipped rather
            // than crashing the engine.
            guard buffer.format == node.outputFormat(forBus: 0) else { return }
            node.scheduleBuffer(buffer, at: nil, options: .interrupts)
            if !node.isPlaying { node.play() }
        }
    }

    // BoardView.handleLetterSelected / handleDragEnded sound choices.
    func tilePress() { play("press", volume: 0.8) }
    func validLetter() { play("validDrag") }
    func invalidWord() { play("invalidRelease") }
    func wordComplete(length: Int) {
        switch length {
        case ...3: play("submit3")
        case 4...10: play("submit\(length)")
        case 11: play("submit_11")
        default: play("submit_12")
        }
    }
}

import Foundation

enum Tier: Int, CaseIterable, Codable {
    case casual = 0
    case goodCasual = 1
    case spam = 2

    var name: String {
        switch self {
        case .casual: return "casual"
        case .goodCasual: return "goodCasual"
        case .spam: return "spam"
        }
    }

    var displayName: String {
        switch self {
        case .casual: return "Casual"
        case .goodCasual: return "Good Casual"
        case .spam: return "Spam"
        }
    }
}

/// A generated, solved board. The solution itself is never kept: validity
/// during play is a dictionary lookup, which is equivalent because a swiped
/// path is always a real path on the board.
struct GeneratedBoard {
    let side: Int
    let tier: Tier
    let letters: [Character]
    let rootSeed: UInt64
    let boardSeed: UInt64
    let realizedN: Int
    let seedWord: String?
    let potentialPoints: Int
    let potentialWords: Int
    let potentialWords5p: Int
    let generateMs: Double
    let solveMs: Double
    let gridSource: String  // "drawn" or "override"
    let tierSource: String
}

/// FluxCore v3 behind the C bridge. Generation runs on its own serial queue;
/// lookups only read the DAWG and are safe from the main thread.
final class FluxEngine {
    static let shared: FluxEngine = {
        do { return try FluxEngine() } catch { fatalError("FluxCore failed to load: \(error)") }
    }()

    struct LoadError: Error, CustomStringConvertible {
        let description: String
    }

    let rulesetVersion: Int
    let configHash: UInt64
    let dictionaryHash: UInt64
    let dictionaryWords: Int

    private let dawgData: Data
    private let engine: OpaquePointer
    private let queue = DispatchQueue(label: "fluxclone.engine", qos: .userInitiated)

    private init() throws {
        guard let dawgURL = Bundle.main.url(forResource: "flux_capped", withExtension: "dawg"),
              let configURL = Bundle.main.url(forResource: "ruleset_v3", withExtension: "json") else {
            throw LoadError(description: "bundled DAWG or ruleset missing")
        }
        dawgData = try Data(contentsOf: dawgURL, options: .alwaysMapped)
        let configData = try Data(contentsOf: configURL)
        var err = [CChar](repeating: 0, count: 512)
        let created: OpaquePointer? = dawgData.withUnsafeBytes { dawgBytes in
            configData.withUnsafeBytes { configBytes in
                fc_engine_create(dawgBytes.bindMemory(to: UInt8.self).baseAddress, dawgBytes.count,
                                 configBytes.bindMemory(to: CChar.self).baseAddress, configBytes.count,
                                 &err, err.count)
            }
        }
        guard let created else {
            throw LoadError(description: String(cString: err))
        }
        engine = created
        rulesetVersion = Int(fc_engine_ruleset_version(engine))
        configHash = fc_engine_config_hash(engine)
        dictionaryHash = fc_engine_dictionary_hash(engine)
        dictionaryWords = Int(fc_engine_dictionary_words(engine))
    }

    // MARK: Lookups

    func wordId(_ word: String) -> Int? {
        var utf8 = Array(word.utf8)
        var id: UInt32 = 0
        let found = utf8.withUnsafeMutableBufferPointer { buf in
            buf.baseAddress!.withMemoryRebound(to: CChar.self, capacity: buf.count) {
                fc_engine_word_id(engine, $0, buf.count, &id)
            }
        }
        return found == 1 ? Int(id) : nil
    }

    func isPrefix(_ prefix: String) -> Bool {
        var utf8 = Array(prefix.utf8)
        return utf8.withUnsafeMutableBufferPointer { buf in
            buf.baseAddress!.withMemoryRebound(to: CChar.self, capacity: buf.count) {
                fc_engine_is_prefix(engine, $0, buf.count) == 1
            }
        }
    }

    // MARK: Generation

    /// Ranked mix: about 62% 4x4 (seasons 3-10 in the export run 61-64%),
    /// tier from the ruleset's shares. Either can be overridden for testing.
    static let fourByFourShare = 0.62

    func generate(sideOverride: Int?, tierOverride: Tier?,
                  completion: @escaping (GeneratedBoard?) -> Void) {
        queue.async { [self] in
            var rng = SystemRandomNumberGenerator()
            let side = sideOverride ?? (Double.random(in: 0..<1, using: &rng) < Self.fourByFourShare ? 4 : 5)
            let tier = tierOverride
                ?? Tier(rawValue: Int(fc_engine_draw_tier(engine, UInt8(side), rng.next())))
                ?? .goodCasual
            let rootSeed = rng.next()
            var out = FCBoard()
            let ok = fc_engine_generate(engine, UInt8(side), UInt8(tier.rawValue), rootSeed, &out)
            guard ok == 1 else {
                DispatchQueue.main.async { completion(nil) }
                return
            }
            let letters = withUnsafeBytes(of: &out.letters) { raw in
                String(decoding: raw.prefix(side * side), as: UTF8.self)
            }
            let seedWord = withUnsafeBytes(of: &out.seedWord) { raw -> String in
                let bytes = raw.prefix { $0 != 0 }
                return String(decoding: bytes, as: UTF8.self)
            }
            let board = GeneratedBoard(
                side: side, tier: tier, letters: Array(letters),
                rootSeed: rootSeed, boardSeed: out.boardSeed, realizedN: Int(out.realizedN),
                seedWord: out.seeded == 1 ? seedWord : nil,
                potentialPoints: Int(out.potentialPoints), potentialWords: Int(out.potentialWords),
                potentialWords5p: Int(out.potentialWords5p),
                generateMs: out.generateMs, solveMs: out.solveMs,
                gridSource: sideOverride == nil ? "drawn" : "override",
                tierSource: tierOverride == nil ? "drawn" : "override")
            DispatchQueue.main.async { completion(board) }
        }
    }
}

// MARK: - Phase 3: training boards and full solves

/// One word on a solved board: its distinct paths (up to the solver's store cap) and the
/// true number of them. Every word here is an observed presence with a known outcome once
/// the board has been played, which is what the training log records.
struct SolvedWord {
    let word: String
    let paths: [[Int]]
    let pathCount: Int

    var points: Int { fluxPoints(forLength: word.count) }
}

struct SolvedBoard {
    let words: [SolvedWord]
    let totalPoints: Int
    let words5p: Int
    let solveMs: Double
    private let index: [String: Int]

    init(words: [SolvedWord], totalPoints: Int, words5p: Int, solveMs: Double) {
        self.words = words
        self.totalPoints = totalPoints
        self.words5p = words5p
        self.solveMs = solveMs
        var index: [String: Int] = [:]
        index.reserveCapacity(words.count)
        for (i, w) in words.enumerated() { index[w.word] = i }
        self.index = index
    }

    func word(_ s: String) -> SolvedWord? { index[s].map { words[$0] } }
    var count: Int { words.count }
}

/// What a constrained generation cost (spec 11.1). Recorded per training board so the
/// fallback ladder is visible in the log rather than inferred.
struct ConstrainedStats {
    let candidatesBuilt: Int
    let candidatesAccepted: Int
    let solves: Int
    let placementFailures: Int
    let normRejects: Int
    let wordRejects: Int
    /// The budget ran out before the tier's full best-of-N. A board still came back; it
    /// simply had fewer candidates to win against, so it is a slightly weaker board.
    let exhausted: Bool
    let generateMs: Double

    var json: String {
        "{\"builds\":\(candidatesBuilt),\"accepted\":\(candidatesAccepted),\"solves\":\(solves),"
            + "\"placementFailures\":\(placementFailures),\"normRejects\":\(normRejects),"
            + "\"wordRejects\":\(wordRejects),\"exhausted\":\(exhausted),"
            + "\"ms\":\(String(format: "%.1f", generateMs))}"
    }
}

extension FluxEngine {
    /// Run `body` on the engine's serial queue and hand the result back on the main
    /// thread. Generation is not thread-safe and the solve result lives inside the
    /// engine, so everything in the training layer goes through here.
    func perform<T>(_ body: @escaping () -> T, then: @escaping (T) -> Void) {
        queue.async {
            let value = body()
            DispatchQueue.main.async { then(value) }
        }
    }

    /// The ruleset's tier draw for a grid. Synchronous; call it on the engine queue.
    func drawTier(side: Int, seed: UInt64) -> Tier {
        Tier(rawValue: Int(fc_engine_draw_tier(engine, UInt8(side), seed))) ?? .goodCasual
    }

    /// Ordinary ranked generation, synchronously. `generate(sideOverride:tierOverride:)` is
    /// the same thing with the draw and the hop back to the main thread built in; the
    /// training layer already knows its grid and tier and is already on the queue.
    func generateRanked(side: Int, tier: Tier, rootSeed: UInt64) -> GeneratedBoard? {
        var out = FCBoard()
        guard fc_engine_generate(engine, UInt8(side), UInt8(tier.rawValue), rootSeed, &out) == 1
        else { return nil }
        let letters = withUnsafeBytes(of: &out.letters) { raw in
            String(decoding: raw.prefix(side * side), as: UTF8.self)
        }
        let seedWord = withUnsafeBytes(of: &out.seedWord) { raw -> String in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
        return GeneratedBoard(
            side: side, tier: tier, letters: Array(letters), rootSeed: rootSeed,
            boardSeed: out.boardSeed, realizedN: Int(out.realizedN),
            seedWord: out.seeded == 1 ? seedWord : nil,
            potentialPoints: Int(out.potentialPoints), potentialWords: Int(out.potentialWords),
            potentialWords5p: Int(out.potentialWords5p), generateMs: out.generateMs,
            solveMs: out.solveMs, gridSource: "drawn", tierSource: "drawn")
    }

    /// A board carrying `stem` as a path, optionally banded on distinct word count.
    /// Synchronous: call it on `work`, which is the engine's own serial queue.
    func generateHook(stem: String, side: Int, tier: Tier, rootSeed: UInt64,
                      wordBand: ClosedRange<Int>?, budget: Int = 20000)
        -> (board: GeneratedBoard, stats: ConstrainedStats)? {
        var out = FCBoard()
        var raw = FCConstrainedStats()
        var target = Array(stem.utf8)
        let ok: Int32 = target.withUnsafeMutableBufferPointer { buf in
            buf.baseAddress!.withMemoryRebound(to: CChar.self, capacity: buf.count) { p in
                fc_engine_generate_hook(engine, UInt8(side), UInt8(tier.rawValue), p,
                                        buf.count, rootSeed, 0, UInt64.max,
                                        UInt32(wordBand?.lowerBound ?? 0),
                                        UInt32(wordBand?.upperBound ?? 0), UInt32(budget),
                                        &out, &raw)
            }
        }
        let stats = ConstrainedStats(
            candidatesBuilt: Int(raw.candidatesBuilt), candidatesAccepted: Int(raw.candidatesAccepted),
            solves: Int(raw.solves), placementFailures: Int(raw.placementFailures),
            normRejects: Int(raw.normRejects), wordRejects: Int(raw.wordRejects),
            exhausted: raw.exhausted == 1, generateMs: raw.generateMs)
        guard ok == 1 else { return nil }

        let letters = withUnsafeBytes(of: &out.letters) { raw in
            String(decoding: raw.prefix(side * side), as: UTF8.self)
        }
        let seedWord = withUnsafeBytes(of: &out.seedWord) { raw -> String in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
        let board = GeneratedBoard(
            side: side, tier: tier, letters: Array(letters), rootSeed: rootSeed,
            boardSeed: out.boardSeed, realizedN: Int(out.realizedN),
            seedWord: out.seeded == 1 ? seedWord : nil,
            potentialPoints: Int(out.potentialPoints), potentialWords: Int(out.potentialWords),
            potentialWords5p: Int(out.potentialWords5p), generateMs: out.generateMs,
            solveMs: out.solveMs, gridSource: "training", tierSource: "training")
        return (board, stats)
    }

    /// Every word on the board, with its paths. Synchronous; call it on `work`.
    func solve(side: Int, letters: [Character]) -> SolvedBoard {
        var summary = FCSolveSummary()
        var bytes = Array(String(letters).utf8).map { CChar(bitPattern: $0) }
        let count = bytes.withUnsafeMutableBufferPointer { buf in
            fc_engine_solve(engine, UInt8(side), buf.baseAddress, &summary)
        }
        var words: [SolvedWord] = []
        words.reserveCapacity(Int(count))
        var nameBuffer = [CChar](repeating: 0, count: 32)
        var cellBuffer = [UInt8](repeating: 0, count: 32)
        for i in 0..<count {
            let len = nameBuffer.withUnsafeMutableBufferPointer {
                fc_engine_solved_word(engine, i, $0.baseAddress, $0.count)
            }
            guard len > 0 else { continue }
            let word = String(cString: nameBuffer)
            let stored = fc_engine_solved_paths_stored(engine, i)
            var paths: [[Int]] = []
            paths.reserveCapacity(Int(stored))
            for j in 0..<stored {
                let n = cellBuffer.withUnsafeMutableBufferPointer {
                    fc_engine_solved_path(engine, i, j, $0.baseAddress, $0.count)
                }
                if n > 0 { paths.append(cellBuffer.prefix(Int(n)).map(Int.init)) }
            }
            words.append(SolvedWord(word: word, paths: paths,
                                    pathCount: Int(fc_engine_solved_path_count(engine, i))))
        }
        return SolvedBoard(words: words, totalPoints: Int(summary.totalPoints),
                           words5p: Int(summary.words5p), solveMs: summary.solveMs)
    }
}

/// SPEC 2.2: 3 -> 100, 4 -> 400, 5 -> 800, then 400(n-3) + 200 from 6.
/// The ruleset carries the same table; this is the closed form of it.
func fluxPoints(forLength n: Int) -> Int {
    switch n {
    case ..<3: return 0
    case 3: return 100
    case 4: return 400
    case 5: return 800
    default: return 400 * (n - 3) + 200
    }
}

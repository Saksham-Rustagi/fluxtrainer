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

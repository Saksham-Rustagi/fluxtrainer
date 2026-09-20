import Foundation

/// The Phase 2 -> Phase 3 contract, decoded. The writer is `tools/queue/hookrecord.py`;
/// its `SCHEMA_VERSION`, `HOOK_FIELDS` and `BRANCH_FIELDS` are the same lists as the
/// `CodingKeys` here, and a mismatch is a load failure rather than a silent shift.
///
/// The bundle is columnar for branches -- `{"fields": [...], "rows": [[...]]}` -- because
/// repeating seventeen JSON keys for each of a hundred thousand branches was a third of
/// the file. It is decoded by index against the declared field list, so reordering the
/// Python side cannot quietly misread here: the order is read from the file.
enum HookClass: String, Codable {
    case additive
    case cellmate
    case mutating_ = "mutating"
    case dead

    /// SPEC 7.3: only `additive` and `cellmate` can earn points. The other two are
    /// misswipe prevention, which is worth drilling and worth no points.
    var earnsPoints: Bool { self == .additive || self == .cellmate }
}

struct Branch {
    let word: String
    let cls: HookClass
    /// How the branch reads against the stem: "-ERS", "PRE-", "anagram of PRATES".
    let ext: String
    let points: Int
    /// SPEC 7.5.1's P(reachable | stem present), from Phase 2. Nothing on device
    /// recomputes it: it is measured over 2,865 ranked boards or fitted, and a handful of
    /// in-app boards would make it worse, not better.
    let reachability: Double
    let reachSource: String
    let myRate: Double?
    let topQuartileRate: Double?
    let nTopQuartile: Int
    /// How often the whole field takes this word. Schema 2.
    ///
    /// rank.py splits the queue on it: below 10% the word is **alpha** -- vocabulary
    /// almost nobody has, where finding it at all is the win -- and at or above it the
    /// word is **par**, something you are expected to take and are not taking. That is
    /// the know-against-see distinction again, measured on other players rather than on
    /// him, and it is the difference between "learn this word" and "start seeing this
    /// word". Nil for a branch the ranked import could not price.
    let fieldRate: Double?
    /// Ranked presences and finds on current-regime boards. The app adds its own to these
    /// rather than replacing them, which is why the record carries the counts and not
    /// just the ratio.
    let presences: Int
    let finds: Int
    /// The ranked opportunity sum for those presences (SPEC 8.1, continuous form). An
    /// in-app presence adds to this on the same scale, which is what lets the two be
    /// added rather than blended by hand.
    let opportunity: Double
    let presencesPerGame: Double
    let belief: Double?
    let status: String
    let expectedGain: Double
    let earns: Bool
    /// Times this exact string appears in the player's own invalid attempts. The affix
    /// grid draws its dead branches from here first: a string he has actually tried is
    /// better teaching material than one the dictionary merely fails to contain.
    let misswiped: Int

    /// rank.py's line: the field takes it less than one time in ten.
    static let alphaBelow = 0.10
    /// Vocabulary almost nobody has. Finding it at all is the win.
    var isAlpha: Bool { (fieldRate ?? 1) < Branch.alphaBelow }
    var track: String { isAlpha ? "alpha" : "par" }
}

struct Hook {
    let stem: String
    let stemLen: Int
    let isWord: Bool
    let rank: Int
    let track: String
    let score: Double
    let expectedGain: Double
    let residual: Double
    /// SPEC 7.5 condition 1, in the 2-to-6 band's units.
    let enumerability: Double
    let enumerabilitySource: String
    let cueable: Bool
    let owned: Int
    let learning: Int
    let unknown: Int
    let studyItems: Int
    let familySize: Int
    let branchCount: Int
    let presentShare: Double
    let presentGames: Int
    /// A *lower* bound on P(stem path present), per "4x4_goodCasual" and friends. Used to
    /// pick a grid that actually carries the stem, never as a probability.
    let presenceByTierGrid: [String: Double]
    let deadBranches: Int
    /// What the dead half of the affix grid is worth in avoided misswipes, at Phase 2's
    /// weight. Carried, never recomputed: nothing on device measures what drilling a dead
    /// affix removes, and rank.py says so.
    let deadPoints: Double
    let why: String
    let branches: [Branch]

    var liveBranches: [Branch] { branches.filter { $0.cls == .additive || $0.cls == .cellmate } }
    var deadAndMutating: [Branch] { branches.filter { $0.cls == .dead || $0.cls == .mutating_ } }

    func branch(_ word: String) -> Branch? { branches.first { $0.word == word } }
}

struct MinedAffix {
    let side: String  // "front" or "back"
    let letters: String

    func applied(to stem: String) -> String { side == "back" ? stem + letters : letters + stem }
    var display: String { side == "back" ? "-" + letters : letters + "-" }
}

/// The board's distinct word count band for an acquisition board, per grid. p10 to p95 of
/// the player's own current-regime boards: wide, measured, and with a floor that means
/// something. See hookrecord.py's `board_density`.
struct DensityBand {
    let minWords: Int
    let maxWords: Int
    let medianWords: Int
}

struct HookBundle {
    let schema: Int
    let generated: String
    let player: String
    let queueTotal: Int
    let hooks: [Hook]
    let density: [Int: DensityBand]
    let minedAffixes: [MinedAffix]
    /// "4x4_5" -> the find rate for 5-letter words on the boards where he took the most.
    /// A board's own rate against this is that board's opportunity weight.
    let opportunityRef: [String: Double]
    /// Length class -> the Beta(a, b) prior the ranked belief was smoothed with.
    let beliefPriors: [Int: (a: Double, b: Double)]
    /// Every string the player has swiped and had rejected, with how many times. The
    /// affix grid's dead half comes from here and from the app's own invalid attempts,
    /// and from nowhere else.
    let misswipes: [String: Int]

    static let expectedSchema = 2

    private(set) static var shared: HookBundle?
    private(set) static var loadError: String?

    /// Parsed off the main thread at launch. 12 MB of JSON, once.
    @discardableResult
    static func load() -> HookBundle? {
        if let shared { return shared }
        do {
            let bundle = try parse()
            shared = bundle
            return bundle
        } catch {
            loadError = "\(error)"
            return nil
        }
    }

    struct LoadError: Error, CustomStringConvertible { let description: String }

    static func parse(url: URL? = nil) throws -> HookBundle {
        guard let url = url ?? Bundle.main.url(forResource: "training_hooks", withExtension: "json")
        else { throw LoadError(description: "training_hooks.json is not in the app bundle") }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw LoadError(description: "training_hooks.json is not an object")
        }
        let schema = root["schema"] as? Int ?? -1
        guard schema == expectedSchema else {
            throw LoadError(description: "hook record schema \(schema), this build reads \(expectedSchema)")
        }
        guard let rawHooks = root["hooks"] as? [[String: Any]] else {
            throw LoadError(description: "no hooks")
        }

        var density: [Int: DensityBand] = [:]
        for (key, value) in (root["boardDensity"] as? [String: [String: Int]] ?? [:]) {
            guard let side = Int(key) else { continue }
            density[side] = DensityBand(minWords: value["minWords"] ?? 0,
                                        maxWords: value["maxWords"] ?? 0,
                                        medianWords: value["medianWords"] ?? 0)
        }
        let affixes = (root["minedAffixes"] as? [[String: String]] ?? [])
            .compactMap { entry -> MinedAffix? in
                guard let side = entry["side"], let letters = entry["letters"] else { return nil }
                return MinedAffix(side: side, letters: letters)
            }

        var priors: [Int: (a: Double, b: Double)] = [:]
        for (key, value) in (root["beliefPriors"] as? [String: [Double]] ?? [:]) {
            if let lc = Int(key), value.count == 2 { priors[lc] = (value[0], value[1]) }
        }

        let hooks = try rawHooks.map { try hook(from: $0) }
        return HookBundle(schema: schema,
                          generated: root["generated"] as? String ?? "",
                          player: root["player"] as? String ?? "",
                          queueTotal: root["queueTotal"] as? Int ?? hooks.count,
                          hooks: hooks, density: density, minedAffixes: affixes,
                          opportunityRef: root["opportunityRef"] as? [String: Double] ?? [:],
                          beliefPriors: priors,
                          misswipes: root["misswipes"] as? [String: Int] ?? [:])
    }

    private static func hook(from d: [String: Any]) throws -> Hook {
        guard let stem = d["stem"] as? String else { throw LoadError(description: "hook has no stem") }
        return Hook(
            stem: stem,
            stemLen: d["stemLen"] as? Int ?? stem.count,
            isWord: d["isWord"] as? Bool ?? false,
            rank: d["rank"] as? Int ?? 0,
            track: d["track"] as? String ?? "",
            score: num(d["score"]),
            expectedGain: num(d["expectedGain"]),
            residual: num(d["residual"]),
            enumerability: num(d["enumerability"]),
            enumerabilitySource: d["enumerabilitySource"] as? String ?? "",
            cueable: d["cueable"] as? Bool ?? false,
            owned: d["owned"] as? Int ?? 0,
            learning: d["learning"] as? Int ?? 0,
            unknown: d["unknown"] as? Int ?? 0,
            studyItems: d["studyItems"] as? Int ?? 0,
            familySize: d["familySize"] as? Int ?? 0,
            branchCount: d["branchCount"] as? Int ?? 0,
            presentShare: num(d["presentShare"]),
            presentGames: d["presentGames"] as? Int ?? 0,
            presenceByTierGrid: (d["presenceByTierGrid"] as? [String: Any] ?? [:])
                .mapValues { num($0) },
            deadBranches: d["deadBranches"] as? Int ?? 0,
            deadPoints: num(d["deadPoints"]),
            why: d["why"] as? String ?? "",
            branches: try branches(from: d["branches"]))
    }

    private static func branches(from any: Any?) throws -> [Branch] {
        guard let table = any as? [String: Any],
              let fields = table["fields"] as? [String],
              let rows = table["rows"] as? [[Any]] else { return [] }
        var index: [String: Int] = [:]
        for (i, f) in fields.enumerated() { index[f] = i }
        // Every field the struct needs must be present. A field the file has and this
        // build does not know about is ignored, which is what lets the Python side add
        // one without a coordinated release; a field it drops is a load failure.
        for required in ["word", "cls", "points", "reachability", "fieldRate"]
        where index[required] == nil {
            throw LoadError(description: "branch field '\(required)' missing from the record")
        }
        return rows.compactMap { row -> Branch? in
            func at(_ name: String) -> Any? {
                guard let i = index[name], i < row.count else { return nil }
                return row[i] is NSNull ? nil : row[i]
            }
            guard let word = at("word") as? String,
                  let cls = HookClass(rawValue: at("cls") as? String ?? "") else { return nil }
            return Branch(
                word: word, cls: cls, ext: at("ext") as? String ?? "",
                points: at("points") as? Int ?? 0,
                reachability: num(at("reachability")),
                reachSource: at("reachSource") as? String ?? "",
                myRate: at("myRate").map(num), topQuartileRate: at("topQuartileRate").map(num),
                nTopQuartile: at("nTopQuartile") as? Int ?? 0,
                fieldRate: at("fieldRate").map(num),
                presences: at("presences") as? Int ?? 0, finds: at("finds") as? Int ?? 0,
                opportunity: num(at("opportunity")),
                presencesPerGame: num(at("presencesPerGame")),
                belief: at("belief").map(num), status: at("status") as? String ?? "unseen",
                expectedGain: num(at("expectedGain")),
                earns: at("earns") as? Bool ?? false,
                misswiped: at("misswiped") as? Int ?? 0)
        }
    }

    private static func num(_ any: Any?) -> Double {
        (any as? NSNumber)?.doubleValue ?? 0
    }
}

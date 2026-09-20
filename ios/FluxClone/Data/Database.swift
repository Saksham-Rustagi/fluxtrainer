import Foundation
import SQLite3

/// The play log. One SQLite file in Application Support, written on a serial queue so a
/// submit never waits on disk. Every timestamp column (t_*, per_cell_entry_timestamps,
/// touch_sample.t) is in the CACurrentMediaTime / UITouch.timestamp timebase: seconds of
/// system uptime, monotonic, unaffected by clock changes. Subtract t_board_shown to get
/// game time.
final class Database {
    static let shared = Database()
    static let schemaVersion = 1

    let url: URL
    private var db: OpaquePointer?
    private let queue = DispatchQueue(label: "fluxclone.db", qos: .utility)
    private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private init() {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        url = dir.appendingPathComponent("fluxclone.sqlite")
        queue.sync {
            guard sqlite3_open(url.path, &db) == SQLITE_OK else { fatalError("cannot open database") }
            exec("PRAGMA journal_mode=WAL")
            exec("PRAGMA synchronous=NORMAL")
            migrate()
        }
    }

    private func migrate() {
        exec("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS game(
            game_id TEXT PRIMARY KEY,
            started_wall TEXT,
            grid INTEGER, tier TEXT, grid_source TEXT, tier_source TEXT,
            letters TEXT,
            ruleset_version INTEGER, config_hash TEXT, dictionary_hash TEXT,
            root_seed TEXT, board_seed TEXT, realized_n INTEGER, seed_word TEXT,
            potential_points INTEGER, potential_words INTEGER, potential_words_5p INTEGER,
            generate_ms REAL, solve_ms REAL,
            score INTEGER, word_count INTEGER,
            t_board_shown REAL, t_first_submit REAL, t_end REAL,
            end_reason TEXT, interrupted INTEGER DEFAULT 0,
            app_version TEXT, device TEXT, os_version TEXT, screen_max_fps INTEGER,
            tile_size REAL, spacing REAL, grid_origin_x REAL, grid_origin_y REAL,
            screen_w REAL, screen_h REAL,
            recognizer_config TEXT, raw_samples INTEGER
        );
        CREATE TABLE IF NOT EXISTS attempt(
            game_id TEXT, seq INTEGER,
            cell_sequence TEXT, letters TEXT, per_cell_entry_timestamps TEXT,
            t_touch_down REAL, t_first_cell REAL, t_submit REAL,
            result TEXT, reason TEXT, word_id INTEGER, points INTEGER,
            gap_since_previous_submit REAL, submit_cause TEXT,
            n_samples INTEGER, n_deliveries INTEGER, max_step_pt REAL, max_sample_dt REAL,
            shadow_cells TEXT, shadow_letters TEXT, shadow_valid INTEGER,
            affix TEXT, stem TEXT, is_prefix INTEGER,
            PRIMARY KEY(game_id, seq)
        );
        CREATE TABLE IF NOT EXISTS touch_sample(
            game_id TEXT, seq INTEGER, i INTEGER, t REAL, x REAL, y REAL,
            phase TEXT, delivered INTEGER
        );
        CREATE INDEX IF NOT EXISTS touch_sample_game ON touch_sample(game_id, seq);
        """)
        exec("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '\(Self.schemaVersion)')")
    }

    // MARK: Writes

    func insertGame(_ row: [String: Any?]) {
        queue.async { self.insert(table: "game", row: row, replace: true) }
    }

    func updateGame(id: String, _ fields: [String: Any?]) {
        queue.async {
            let keys = fields.keys.sorted()
            let sql = "UPDATE game SET " + keys.map { "\($0) = ?" }.joined(separator: ", ") + " WHERE game_id = ?"
            self.run(sql, keys.map { fields[$0] ?? nil } + [id])
        }
    }

    func insertAttempt(_ row: [String: Any?]) {
        queue.async { self.insert(table: "attempt", row: row, replace: false) }
    }

    /// (seq, t, x, y, phase, delivered) in grid-local points.
    func insertSamples(gameId: String, _ samples: [(Int, Double, Double, Double, String, Bool)]) {
        queue.async {
            self.exec("BEGIN")
            var stmt: OpaquePointer?
            sqlite3_prepare_v2(self.db, "INSERT INTO touch_sample VALUES(?,?,?,?,?,?,?,?)", -1, &stmt, nil)
            for (i, s) in samples.enumerated() {
                sqlite3_reset(stmt)
                self.bind(stmt, [gameId, s.0, i, s.1, s.2, s.3, s.4, s.5 ? 1 : 0])
                sqlite3_step(stmt)
            }
            sqlite3_finalize(stmt)
            self.exec("COMMIT")
        }
    }

    // MARK: Reads (synchronous, small)

    func rawSampleGameCount() -> Int {
        queue.sync { scalarInt("SELECT COUNT(*) FROM game WHERE raw_samples = 1") }
    }

    struct GameSummary: Identifiable {
        let id: String
        let startedWall: String
        let grid: Int
        let tier: String
        let tierSource: String
        let score: Int
        let words: Int
        let potential: Int
        let invalid: Int
        let duplicate: Int
        let interrupted: Bool
    }

    func recentGames(limit: Int = 50) -> [GameSummary] {
        queue.sync {
            let sql = """
            SELECT g.game_id, g.started_wall, g.grid, g.tier, g.tier_source, g.score, g.word_count,
                   g.potential_points,
                   (SELECT COUNT(*) FROM attempt a WHERE a.game_id = g.game_id AND a.result = 'invalid' AND a.reason = 'not_word'),
                   (SELECT COUNT(*) FROM attempt a WHERE a.game_id = g.game_id AND a.result = 'duplicate'),
                   g.interrupted
            FROM game g WHERE g.t_end IS NOT NULL ORDER BY g.started_wall DESC LIMIT \(limit)
            """
            var out: [GameSummary] = []
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return out }
            defer { sqlite3_finalize(stmt) }
            while sqlite3_step(stmt) == SQLITE_ROW {
                out.append(GameSummary(
                    id: text(stmt, 0), startedWall: text(stmt, 1), grid: Int(sqlite3_column_int(stmt, 2)),
                    tier: text(stmt, 3), tierSource: text(stmt, 4), score: Int(sqlite3_column_int(stmt, 5)),
                    words: Int(sqlite3_column_int(stmt, 6)), potential: Int(sqlite3_column_int64(stmt, 7)),
                    invalid: Int(sqlite3_column_int(stmt, 8)), duplicate: Int(sqlite3_column_int(stmt, 9)),
                    interrupted: sqlite3_column_int(stmt, 10) != 0))
            }
            return out
        }
    }

    func completedGameCount() -> Int {
        queue.sync { scalarInt("SELECT COUNT(*) FROM game WHERE t_end IS NOT NULL") }
    }

    // MARK: Export

    /// A consistent single-file snapshot (VACUUM INTO folds the WAL in). Runs after every
    /// queued write has landed.
    func snapshot(to destination: URL) throws {
        try? FileManager.default.removeItem(at: destination)
        var rc: Int32 = SQLITE_ERROR
        queue.sync {
            let escaped = destination.path.replacingOccurrences(of: "'", with: "''")
            rc = sqlite3_exec(db, "VACUUM INTO '\(escaped)'", nil, nil, nil)
        }
        if rc != SQLITE_OK {
            throw NSError(domain: "Database", code: Int(rc),
                          userInfo: [NSLocalizedDescriptionKey: "snapshot failed (\(rc))"])
        }
    }

    // MARK: Plumbing (queue only)

    private func insert(table: String, row: [String: Any?], replace: Bool) {
        let keys = row.keys.sorted()
        let sql = "INSERT \(replace ? "OR REPLACE " : "")INTO \(table)(" + keys.joined(separator: ",")
            + ") VALUES(" + keys.map { _ in "?" }.joined(separator: ",") + ")"
        run(sql, keys.map { row[$0] ?? nil })
    }

    private func run(_ sql: String, _ values: [Any?]) {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            print("SQL prepare failed: \(String(cString: sqlite3_errmsg(db))) in \(sql)")
            return
        }
        bind(stmt, values)
        if sqlite3_step(stmt) != SQLITE_DONE {
            print("SQL step failed: \(String(cString: sqlite3_errmsg(db))) in \(sql)")
        }
        sqlite3_finalize(stmt)
    }

    private func bind(_ stmt: OpaquePointer?, _ values: [Any?]) {
        for (i, value) in values.enumerated() {
            let idx = Int32(i + 1)
            switch value {
            case nil: sqlite3_bind_null(stmt, idx)
            case let v as Int: sqlite3_bind_int64(stmt, idx, Int64(v))
            case let v as Int64: sqlite3_bind_int64(stmt, idx, v)
            case let v as Bool: sqlite3_bind_int(stmt, idx, v ? 1 : 0)
            case let v as Double: sqlite3_bind_double(stmt, idx, v)
            case let v as CGFloat: sqlite3_bind_double(stmt, idx, Double(v))
            case let v as String: sqlite3_bind_text(stmt, idx, v, -1, SQLITE_TRANSIENT)
            default: sqlite3_bind_text(stmt, idx, "\(value!)", -1, SQLITE_TRANSIENT)
            }
        }
    }

    private func exec(_ sql: String) {
        if sqlite3_exec(db, sql, nil, nil, nil) != SQLITE_OK {
            print("SQL exec failed: \(String(cString: sqlite3_errmsg(db)))")
        }
    }

    private func scalarInt(_ sql: String) -> Int {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return 0 }
        defer { sqlite3_finalize(stmt) }
        return sqlite3_step(stmt) == SQLITE_ROW ? Int(sqlite3_column_int64(stmt, 0)) : 0
    }

    private func text(_ stmt: OpaquePointer?, _ col: Int32) -> String {
        guard let c = sqlite3_column_text(stmt, col) else { return "" }
        return String(cString: c)
    }
}

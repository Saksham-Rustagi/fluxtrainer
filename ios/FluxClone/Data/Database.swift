import Foundation
import SQLite3

/// The play log. One SQLite file in Application Support, written on a serial queue so a
/// submit never waits on disk. Every timestamp column (t_*, per_cell_entry_timestamps,
/// touch_sample.t) is in the CACurrentMediaTime / UITouch.timestamp timebase: seconds of
/// system uptime, monotonic, unaffected by clock changes. Subtract t_board_shown to get
/// game time.
final class Database {
    static let shared = Database()
    /// 1: Phase 1, the play log. 2: Phase 3, the training log. 3: Phase 3.5, review --
    /// `hook_meeting` and two status columns on `word_belief`. The Phase 1 tables are
    /// untouched by any of them -- a training board writes an ordinary `game` and
    /// `attempt` row, so `tools/clone_report` keeps working, with `game.purpose` telling
    /// the two apart.
    static let schemaVersion = 3

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
        migrateTraining()
        exec("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '\(Self.schemaVersion)')")
    }

    /// Schema 2. Designed so Phase 4 does not need a migration: the scheduling it adds
    /// (stability, difficulty, a real interval) are columns on `hook_state`, and the
    /// belief model it refines already has its per-word row and its event log.
    private func migrateTraining() {
        // Phase 1 databases predate these three columns on `game`. ALTER TABLE ADD COLUMN
        // errors harmlessly once they exist, which is the cheapest correct migration here.
        for column in ["purpose TEXT", "session_id TEXT", "exercise_id TEXT"] {
            sqlite3_exec(db, "ALTER TABLE game ADD COLUMN \(column)", nil, nil, nil)
        }
        exec("""
        CREATE TABLE IF NOT EXISTS session(
            session_id TEXT PRIMARY KEY,
            started_wall TEXT, ended_wall TEXT,
            shape TEXT,                 -- full | short
            new_hook TEXT, due_hooks TEXT,
            queue_recomputed_at TEXT,
            boards INTEGER DEFAULT 0, judgements INTEGER DEFAULT 0,
            abandoned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS exercise(
            exercise_id TEXT PRIMARY KEY, session_id TEXT, seq INTEGER,
            kind TEXT,                  -- warmup | branch_completion | family_sweep | affix_grid
            hook TEXT, attempt_for_hook INTEGER,
            game_id TEXT, purpose TEXT,
            grid INTEGER, tier TEXT, letters TEXT, board_words INTEGER,
            lit_path TEXT, targets TEXT,
            duration REAL, started_wall TEXT, ended_wall TEXT,
            found INTEGER, missed INTEGER,
            degraded INTEGER DEFAULT 0, constrained_stats TEXT,
            abandoned INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS exercise_session ON exercise(session_id, seq);
        CREATE INDEX IF NOT EXISTS exercise_hook ON exercise(hook, started_wall);

        -- One row per branch the exercise asked for. `stem_lit` is the difference between
        -- the two drills and is why belief cannot be updated from drill outcomes alone.
        CREATE TABLE IF NOT EXISTS branch_event(
            exercise_id TEXT, word TEXT, hook TEXT, cls TEXT,
            found INTEGER, t_found REAL, stem_lit INTEGER,
            game_id TEXT, attempt_for_hook INTEGER, points INTEGER,
            PRIMARY KEY(exercise_id, word)
        );
        CREATE INDEX IF NOT EXISTS branch_event_word ON branch_event(word);

        -- Every solved word on every full board played in the app. The board is already
        -- solved, so each of these is an observed presence with a known outcome; keeping
        -- only the drilled hook's branches would throw most of the signal away for free.
        CREATE TABLE IF NOT EXISTS presence(
            game_id TEXT, word TEXT, len INTEGER, points INTEGER,
            found INTEGER, t_found REAL,
            grid INTEGER, tier TEXT, board_words INTEGER, purpose TEXT,
            path_count INTEGER,
            free INTEGER,               -- reachable as an extension of an earlier find
            host TEXT,                  -- that earlier find, when free
            source TEXT DEFAULT 'inapp',
            -- The belief input. `opportunity` is SPEC 8.1's weight for this board and
            -- length class; `evidence` says which exercise it came from; the two w_
            -- columns are the contribution after the exercise weight, so the recompute
            -- is a plain SUM and cannot drift from the weights used at write time.
            opportunity REAL, evidence TEXT, w_finds REAL, w_opportunity REAL,
            PRIMARY KEY(game_id, word)
        );
        CREATE INDEX IF NOT EXISTS presence_word ON presence(word);

        CREATE TABLE IF NOT EXISTS judgement(
            exercise_id TEXT, seq INTEGER, stem TEXT, word TEXT, cls TEXT,
            live INTEGER, answered_live INTEGER, correct INTEGER, latency REAL,
            from_misswipe INTEGER,
            PRIMARY KEY(exercise_id, seq)
        );
        CREATE INDEX IF NOT EXISTS judgement_word ON judgement(word);

        CREATE TABLE IF NOT EXISTS hook_state(
            stem TEXT PRIMARY KEY,
            exposures INTEGER DEFAULT 0, sweeps INTEGER DEFAULT 0,
            first_drilled TEXT, last_drilled TEXT, due_wall TEXT,
            grids_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS word_belief(
            word TEXT PRIMARY KEY,
            logit REAL, belief REAL,
            inapp_presences INTEGER DEFAULT 0, inapp_finds INTEGER DEFAULT 0,
            inapp_weight REAL DEFAULT 0, inapp_find_weight REAL DEFAULT 0,
            my_rate REAL, updated_wall TEXT
        );

        -- Schema 3. One row per (board, family) for every board played, ranked included.
        -- Written from the board's own solve, so "how often do I meet this stem and how
        -- much of it do I take" is a grouped select rather than a scan over every word on
        -- every board. This is what My Stems and the per-stem trend read.
        CREATE TABLE IF NOT EXISTS hook_meeting(
            game_id TEXT, stem TEXT,
            present INTEGER, found INTEGER,
            points_present INTEGER, points_found INTEGER,
            purpose TEXT, grid INTEGER, drilled INTEGER DEFAULT 0,
            wall TEXT,
            PRIMARY KEY(game_id, stem)
        );
        CREATE INDEX IF NOT EXISTS hook_meeting_stem ON hook_meeting(stem, wall);

        -- What review actually put on screen, per board. The phase's gate is a human
        -- question -- did it tell me something I did not know and would act on -- and it
        -- cannot be asked offline unless what was shown is recorded. Also the fastest way
        -- to catch a stuck ranker: the same stem leading five boards running.
        CREATE TABLE IF NOT EXISTS review_item(
            game_id TEXT, rank INTEGER,
            kind TEXT,                  -- family | word
            stem TEXT, word TEXT,
            priority INTEGER, value REAL,
            covered INTEGER, missed INTEGER,
            wall TEXT,
            PRIMARY KEY(game_id, rank)
        );
        CREATE INDEX IF NOT EXISTS review_item_stem ON review_item(stem);

        CREATE TABLE IF NOT EXISTS queue_state(key TEXT PRIMARY KEY, value TEXT);
        """)
        // Schema 3 adds two columns to a table schema 2 already created. `status` is what
        // the recompute decided; `announced_status` is what the player has been told. A
        // transition is surfaced exactly once, which is the difference between the two.
        for column in ["status TEXT", "announced_status TEXT", "slipping INTEGER DEFAULT 0"] {
            sqlite3_exec(db, "ALTER TABLE word_belief ADD COLUMN \(column)", nil, nil, nil)
        }
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

    // MARK: Generic access (the training log; Phase 1's writes keep their own methods)

    /// Queued, like the Phase 1 writes: a submit never waits on disk.
    func write(_ table: String, _ row: [String: Any?], replace: Bool = true) {
        queue.async { self.insert(table: table, row: row, replace: replace) }
    }

    func writeMany(_ table: String, _ rows: [[String: Any?]], replace: Bool = true) {
        guard !rows.isEmpty else { return }
        queue.async {
            self.exec("BEGIN")
            for row in rows { self.insert(table: table, row: row, replace: replace) }
            self.exec("COMMIT")
        }
    }

    func execute(_ sql: String, _ values: [Any?] = []) {
        queue.async { self.run(sql, values) }
    }

    /// One prepared statement over many rows, in a transaction. `writeMany` builds an
    /// INSERT OR REPLACE from the row's keys, which is wrong wherever a column has to
    /// survive the write -- `word_belief.announced_status` is the case that forced this.
    func executeMany(_ sql: String, _ rows: [[Any?]]) {
        guard !rows.isEmpty else { return }
        queue.async {
            self.exec("BEGIN")
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(self.db, sql, -1, &stmt, nil) == SQLITE_OK else {
                print("SQL prepare failed: \(String(cString: sqlite3_errmsg(self.db))) in \(sql)")
                self.exec("COMMIT")
                return
            }
            for row in rows {
                sqlite3_reset(stmt)
                sqlite3_clear_bindings(stmt)
                self.bind(stmt, row)
                if sqlite3_step(stmt) != SQLITE_DONE {
                    print("SQL step failed: \(String(cString: sqlite3_errmsg(self.db)))")
                }
            }
            sqlite3_finalize(stmt)
            self.exec("COMMIT")
        }
    }

    /// Synchronous read. `body` sees one prepared statement positioned on each row; use
    /// the `Row` helpers rather than sqlite3_column_* directly.
    struct Row {
        fileprivate let stmt: OpaquePointer?
        func int(_ i: Int32) -> Int { Int(sqlite3_column_int64(stmt, i)) }
        func double(_ i: Int32) -> Double { sqlite3_column_double(stmt, i) }
        func bool(_ i: Int32) -> Bool { sqlite3_column_int(stmt, i) != 0 }
        func isNull(_ i: Int32) -> Bool { sqlite3_column_type(stmt, i) == SQLITE_NULL }
        func text(_ i: Int32) -> String {
            guard let c = sqlite3_column_text(stmt, i) else { return "" }
            return String(cString: c)
        }
        func optionalText(_ i: Int32) -> String? { isNull(i) ? nil : text(i) }
        func optionalDouble(_ i: Int32) -> Double? { isNull(i) ? nil : double(i) }
    }

    func query(_ sql: String, _ values: [Any?] = [], _ body: (Row) -> Void) {
        queue.sync {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
                print("SQL prepare failed: \(String(cString: sqlite3_errmsg(db))) in \(sql)")
                return
            }
            defer { sqlite3_finalize(stmt) }
            bind(stmt, values)
            while sqlite3_step(stmt) == SQLITE_ROW { body(Row(stmt: stmt)) }
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

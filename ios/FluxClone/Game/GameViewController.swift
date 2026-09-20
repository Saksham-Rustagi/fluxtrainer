import QuartzCore
import UIKit

struct GameResult {
    let gameId: String
    let board: GeneratedBoard
    let score: Int
    let words: Int
    let invalid: Int
    let duplicates: Int
    let abandoned: Bool
}

/// The whole game screen, in UIKit so nothing between the digitizer and the tiles goes
/// through SwiftUI. Layout, colours, feedback and rules follow flux-ios BoardView.swift;
/// docs/CLONE_RECON.md has the source for each.
final class GameViewController: UIViewController {
    static let duration: Double = 80

    private let board: GeneratedBoard
    private let config: RecognizerConfig
    private let recordRaw: Bool
    private let onFinish: (GameResult) -> Void
    private let gameId = UUID().uuidString
    private let engine = FluxEngine.shared
    private let haptics = Haptics()
    private let sounds = Sounds.shared

    // Layout
    private var geometry: GridGeometry!
    private var gridOrigin = CGPoint.zero  // in boardArea coordinates
    private let backButton = UIButton(type: .system)
    private let scoreLabel = UILabel()
    private let wordsLabel = UILabel()
    private let timeLabel = UILabel()
    private let boardArea = UIView()
    private let touchView = TouchOverlayView()
    private var tileViews: [TileView] = []
    private let pathLayer = CAShapeLayer()
    private let bubble = WordBubble()
    private var laidOut = false

    // Game state
    private var recognizer: Recognizer!
    private var shadow: Recognizer!
    private var found = Set<String>()
    private var score = 0
    private var wordState: WordState = .invalid
    private var tBoardShown: Double?
    private var tFirstSubmit: Double?
    private var lastSubmit: Double?
    private var seq = 0
    private var isOver = false
    private var interrupted = false
    private var invalidCount = 0
    private var duplicateCount = 0
    private var displayLink: CADisplayLink?
    private var lastShownRemaining = -1
    private var warningDim = false
    private var displayedScore = 0
    private var scoreAnimation: (from: Int, to: Int, start: Double)?

    // The swipe in progress
    private struct Attempt {
        var tDown: Double
        var cells: [Int] = []
        var times: [Double] = []
        var nSamples = 0
        var nDeliveries = 0
        var maxStep: Double = 0
        var maxDt: Double = 0
        var last: (t: Double, p: CGPoint)
    }
    private var attempt: Attempt?
    private var rawSamples: [(Int, Double, Double, Double, String, Bool)] = []

    init(board: GeneratedBoard, config: RecognizerConfig, recordRaw: Bool,
         onFinish: @escaping (GameResult) -> Void) {
        self.board = board
        self.config = config
        self.recordRaw = recordRaw
        self.onFinish = onFinish
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError() }

    // MARK: Setup

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = FluxTheme.bg

        backButton.setImage(UIImage(systemName: "chevron.left",
                                    withConfiguration: UIImage.SymbolConfiguration(pointSize: 24, weight: .medium)),
                            for: .normal)
        backButton.tintColor = FluxTheme.main.withAlphaComponent(0.8)
        backButton.addTarget(self, action: #selector(backTapped), for: .touchUpInside)

        let compact = UIScreen.main.bounds.height < 700
        scoreLabel.font = FluxFont.bold(compact ? 54 : 68)
        scoreLabel.textColor = FluxTheme.bgContrast
        scoreLabel.textAlignment = .center
        scoreLabel.text = "0"
        for label in [wordsLabel, timeLabel] {
            label.font = .systemFont(ofSize: 18, weight: .medium)
            label.textColor = FluxTheme.bgContrast
            label.alpha = 0.8
        }
        wordsLabel.text = "0 words"
        timeLabel.text = Self.format(remaining: Int(Self.duration))
        timeLabel.font = .monospacedDigitSystemFont(ofSize: 18, weight: .medium)

        [backButton, scoreLabel, wordsLabel, timeLabel, boardArea].forEach(view.addSubview)
        haptics.prepare()
        sounds.start()

        NotificationCenter.default.addObserver(self, selector: #selector(resignedActive),
                                               name: UIApplication.willResignActiveNotification, object: nil)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        guard !laidOut, view.bounds.width > 0 else { return }
        laidOut = true
        layout()
    }

    private func layout() {
        let safe = view.safeAreaLayoutGuide.layoutFrame
        let width = view.bounds.width

        // Header row (back button), then hudTopGap, then GameStats.
        backButton.frame = CGRect(x: safe.minX + 16, y: safe.minY + 8, width: 32, height: 32)
        var y = safe.minY + 8 + 32 + 4
        y += UIScreen.main.bounds.height >= 700 ? 16 : 2
        scoreLabel.sizeToFit()
        scoreLabel.frame = CGRect(x: 0, y: y, width: width, height: scoreLabel.bounds.height)
        y = scoreLabel.frame.maxY - 5
        wordsLabel.text = "000 words"
        wordsLabel.sizeToFit()
        timeLabel.sizeToFit()
        let rowWidth = wordsLabel.bounds.width + 16 + timeLabel.bounds.width
        wordsLabel.frame = CGRect(x: (width - rowWidth) / 2, y: y, width: wordsLabel.bounds.width,
                                  height: wordsLabel.bounds.height)
        wordsLabel.textAlignment = .right
        wordsLabel.text = "0 words"
        timeLabel.frame = CGRect(x: wordsLabel.frame.maxX + 16, y: y, width: timeLabel.bounds.width,
                                 height: timeLabel.bounds.height)
        y = timeLabel.frame.maxY

        // BoardView.swift:1904-1933: grid size from getLetterSize, container of
        // 24 (top pad) + 64 (word slot) + 20 (gap) + grid, leftover split by the vertical
        // position setting (0.5), with a 24 pt home-indicator guard below.
        boardArea.frame = CGRect(x: 0, y: y, width: width, height: safe.maxY - y)
        let settings = BoardSettings.flux
        let tile = settings.tileSize(side: board.side, screenWidth: UIScreen.main.bounds.width)
        geometry = GridGeometry(side: board.side, tileSize: tile, spacing: settings.spacing)
        let gridSize = geometry.totalSize
        let wordDisplayHeight: CGFloat = 64, wordDisplaySpacing: CGFloat = 20, wordDisplayTop: CGFloat = 24
        let bottomGuard: CGFloat = 24
        let containerHeight = gridSize + wordDisplayHeight + wordDisplaySpacing + wordDisplayTop
        let extra = max(0, boardArea.bounds.height - containerHeight - bottomGuard)
        let containerTop = extra * settings.verticalPosition
        gridOrigin = CGPoint(x: (width - gridSize) / 2,
                             y: containerTop + wordDisplayTop + wordDisplayHeight + wordDisplaySpacing)

        for cell in 0..<(board.side * board.side) {
            let frame = geometry.cellFrame(cell).offsetBy(dx: gridOrigin.x, dy: gridOrigin.y)
            let tv = TileView(frame: frame, letter: board.letters[cell], tileSize: tile)
            boardArea.addSubview(tv)
            tileViews.append(tv)
        }

        // The touch overlay covers the padded grid, as in Flux: from the container's
        // top-left (word slot and left margin included) to the grid's bottom-right.
        touchView.frame = CGRect(x: 0, y: containerTop, width: gridOrigin.x + gridSize,
                                 height: gridOrigin.y + gridSize - containerTop)
        touchView.controller = self
        boardArea.addSubview(touchView)

        pathLayer.frame = boardArea.bounds
        pathLayer.fillColor = nil
        pathLayer.strokeColor = FluxTheme.path.cgColor
        pathLayer.lineWidth = BoardSettings.flux.pathWidth
        pathLayer.lineCap = .round
        pathLayer.lineJoin = .round
        pathLayer.actions = ["path": NSNull()]
        boardArea.layer.addSublayer(pathLayer)

        bubble.slot = CGRect(x: 0, y: gridOrigin.y - wordDisplaySpacing - wordDisplayHeight,
                             width: width, height: wordDisplayHeight)
        boardArea.addSubview(bubble)
        bubble.isUserInteractionEnabled = false

        recognizer = Recognizer(geometry: geometry, config: config)
        shadow = Recognizer(geometry: geometry, config: .shadow)
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard displayLink == nil else { return }
        let link = CADisplayLink(target: self, selector: #selector(tick))
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 120, preferred: 120)
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    // MARK: Clock

    @objc private func tick(_ link: CADisplayLink) {
        let now = CACurrentMediaTime()
        guard let t0 = tBoardShown else {
            // The first frame after the board is on screen starts the clock
            // (Flux: gameStartDate = Date() in the board's onAppear).
            tBoardShown = now
            insertGameRow()
            return
        }
        let elapsed = now - t0
        let remaining = max(0, Int(Self.duration) - Int(elapsed))
        if remaining != lastShownRemaining {
            lastShownRemaining = remaining
            timeLabel.text = Self.format(remaining: remaining)
            // BoardView.handleTimeUpdate: toggle the warning each tick in the last 10 s.
            if remaining <= 10 && remaining > 0 {
                warningDim.toggle()
                UIView.animate(withDuration: 0.5, delay: 0, options: [.curveEaseInOut, .allowUserInteraction]) {
                    self.timeLabel.alpha = self.warningDim ? 0.4 : 0.8
                }
            }
        }
        if let anim = scoreAnimation {
            // AnimatedCounter: 0.8 s count-up.
            let p = min(1, (now - anim.start) / 0.8)
            let eased = 1 - pow(1 - p, 3)
            displayedScore = anim.from + Int(Double(anim.to - anim.from) * eased)
            scoreLabel.text = "\(displayedScore)"
            if p >= 1 { scoreAnimation = nil }
        }
        if elapsed >= Self.duration {
            // An in-progress swipe is submitted, and scores if valid, before the game ends.
            if attempt != nil { submit(cause: "timeout", at: now) }
            endGame(reason: "timeout", at: now)
        }
    }

    private static func format(remaining: Int) -> String {
        String(format: "%02d:%02d", remaining / 60, remaining % 60)
    }

    // MARK: Touches

    fileprivate func touchBegan(_ touch: UITouch) {
        guard !isOver, tBoardShown != nil else { return }
        let p = gridPoint(touch.location(in: boardArea))
        let t = touch.timestamp
        attempt = Attempt(tDown: t, last: (t, p))
        recordSample(p, t: t, phase: "began", delivered: true)
        shadow.begin(at: p)
        for cell in recognizer.begin(at: p) { select(cell, at: t) }
    }

    fileprivate func touchMoved(_ touch: UITouch, event: UIEvent?) {
        guard !isOver, attempt != nil else { return }
        let coalesced = event?.coalescedTouches(for: touch) ?? []
        let samples = coalesced.isEmpty ? [touch] : coalesced
        attempt!.nDeliveries += 1
        for (i, s) in samples.enumerated() {
            let p = gridPoint(s.location(in: boardArea))
            recordSample(p, t: s.timestamp, phase: "moved", delivered: i == samples.count - 1)
            shadow.move(to: p)
            if config.sampleMode == .coalesced {
                for cell in recognizer.move(to: p) { select(cell, at: s.timestamp) }
            }
        }
        if config.sampleMode == .perDelivery {
            // Flux before a2f3523: one hit test per touchesMoved, at the touch's location.
            let p = gridPoint(touch.location(in: boardArea))
            for cell in recognizer.move(to: p) { select(cell, at: touch.timestamp) }
        }
    }

    fileprivate func touchEnded(_ touch: UITouch, cancelled: Bool) {
        guard !isOver, attempt != nil else { return }
        let p = gridPoint(touch.location(in: boardArea))
        recordSample(p, t: touch.timestamp, phase: cancelled ? "cancelled" : "ended", delivered: true)
        // Lift always submits; so does a system cancel (Flux handleTouchCancelled).
        submit(cause: cancelled ? "cancel" : "lift", at: touch.timestamp)
    }

    private func gridPoint(_ p: CGPoint) -> CGPoint {
        CGPoint(x: p.x - gridOrigin.x, y: p.y - gridOrigin.y)
    }

    private func recordSample(_ p: CGPoint, t: Double, phase: String, delivered: Bool) {
        guard var a = attempt else { return }
        a.nSamples += 1
        if phase == "moved" {
            let step = hypot(p.x - a.last.p.x, p.y - a.last.p.y)
            a.maxStep = max(a.maxStep, Double(step))
            a.maxDt = max(a.maxDt, t - a.last.t)
        }
        a.last = (t, p)
        attempt = a
        if recordRaw {
            rawSamples.append((seq, t, Double(p.x), Double(p.y), phase, delivered))
        }
    }

    // MARK: Selection (BoardView.handleLetterSelected + BoardState.selectLetter)

    private var currentLetters: String {
        String(recognizer.path.map { board.letters[$0] })
    }

    private func classify(_ word: String) -> WordState {
        guard word.count >= 3, engine.wordId(word) != nil else { return .invalid }
        return found.contains(word) ? .validButFound : .validAndAvailable
    }

    private func select(_ cell: Int, at t: Double) {
        attempt?.cells.append(cell)
        attempt?.times.append(t)
        let isFirst = recognizer.path.count == 1
        let word = currentLetters
        wordState = classify(word)

        for c in recognizer.path { tileViews[c].setSelected(true, state: wordState, animated: c == cell) }
        updatePath()
        bubble.show(word: word, state: wordState)

        // Haptic first, then sound (Flux orders them for latency).
        if isFirst {
            haptics.fire(Haptics.startChain)
            sounds.tilePress()
        } else if wordState == .validAndAvailable {
            haptics.fire(Haptics.validChain)
            sounds.validLetter()
        } else {
            haptics.fire(Haptics.invalidChain)
            sounds.tilePress()
        }
    }

    private func updatePath() {
        let points = recognizer.path.map { c -> CGPoint in
            let p = geometry.center(c)
            return CGPoint(x: p.x + gridOrigin.x, y: p.y + gridOrigin.y)
        }
        let path = UIBezierPath()
        if points.count > 1 {
            path.move(to: points[0])
            points.dropFirst().forEach { path.addLine(to: $0) }
        }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        pathLayer.path = path.cgPath
        CATransaction.commit()
    }

    private func clearSelection() {
        for c in recognizer.path { tileViews[c].setSelected(false, state: .invalid, animated: false) }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        pathLayer.path = nil
        CATransaction.commit()
        bubble.hide()
    }

    // MARK: Submit (BoardView.handleDragEnded)

    private func submit(cause: String, at t: Double) {
        guard let a = attempt else { return }
        attempt = nil
        let cells = recognizer.path
        let word = currentLetters
        let state = classify(word)
        clearSelection()

        let result: String
        var reason: String?
        var wordId: Int?
        var points = 0
        switch state {
        case .validAndAvailable:
            result = "valid"
            wordId = engine.wordId(word)
            points = fluxPoints(forLength: word.count)
            haptics.fire(Haptics.submitValid)
            sounds.wordComplete(length: word.count)
            found.insert(word)
            let from = displayedScore
            score += points
            scoreAnimation = (from, score, CACurrentMediaTime())
            wordsLabel.text = "\(found.count) \(found.count == 1 ? "word" : "words")"
            bubble.fly(word: word, points: points)
        case .validButFound:
            result = "duplicate"
            wordId = engine.wordId(word)
            duplicateCount += 1
            haptics.fire(Haptics.submitInvalid)
            sounds.invalidWord()
        case .invalid:
            result = "invalid"
            reason = cells.isEmpty ? "empty" : (word.count < 3 ? "too_short" : "not_word")
            if reason == "not_word" { invalidCount += 1 }
            haptics.fire(Haptics.submitInvalid)
            sounds.invalidWord()
        }

        let t0 = tBoardShown ?? t
        let gap = t - (lastSubmit ?? t0)
        if !cells.isEmpty {
            lastSubmit = t
            if tFirstSubmit == nil { tFirstSubmit = t }
        }

        var row: [String: Any?] = [
            "game_id": gameId, "seq": seq,
            "cell_sequence": cells.map(String.init).joined(separator: ","),
            "letters": word,
            "per_cell_entry_timestamps": a.times.map { String(format: "%.6f", $0) }.joined(separator: ","),
            "t_touch_down": a.tDown, "t_first_cell": a.times.first, "t_submit": t,
            "result": result, "reason": reason, "word_id": wordId, "points": points,
            "gap_since_previous_submit": cells.isEmpty ? nil : gap,
            "submit_cause": cause,
            "n_samples": a.nSamples, "n_deliveries": a.nDeliveries,
            "max_step_pt": a.maxStep, "max_sample_dt": a.maxDt,
        ]
        if shadow.path != cells {
            let shadowWord = String(shadow.path.map { board.letters[$0] })
            row["shadow_cells"] = shadow.path.map(String.init).joined(separator: ",")
            row["shadow_letters"] = shadowWord
            row["shadow_valid"] = shadowWord.count >= 3 && engine.wordId(shadowWord) != nil
        }
        if reason == "not_word" {
            if let affix = AffixClassifier.classify(word, isWord: { self.engine.wordId($0) != nil }) {
                row["affix"] = affix.affix
                row["stem"] = affix.stem
            }
            row["is_prefix"] = engine.isPrefix(word)
        }
        Database.shared.insertAttempt(row)
        // Written per attempt, not at the end of the game, so a crash or a forced quit
        // cannot take the raw samples with it.
        if recordRaw, !rawSamples.isEmpty {
            Database.shared.insertSamples(gameId: gameId, rawSamples)
            rawSamples.removeAll(keepingCapacity: true)
        }
        seq += 1
    }

    // MARK: End

    private func insertGameRow() {
        Database.shared.insertGame([
            "game_id": gameId,
            "started_wall": ISO8601DateFormatter().string(from: Date()),
            "grid": board.side, "tier": board.tier.name,
            "grid_source": board.gridSource, "tier_source": board.tierSource,
            "letters": String(board.letters),
            "ruleset_version": engine.rulesetVersion,
            "config_hash": String(format: "0x%016llx", engine.configHash),
            "dictionary_hash": String(format: "0x%016llx", engine.dictionaryHash),
            "root_seed": String(board.rootSeed), "board_seed": String(board.boardSeed),
            "realized_n": board.realizedN, "seed_word": board.seedWord,
            "potential_points": board.potentialPoints, "potential_words": board.potentialWords,
            "potential_words_5p": board.potentialWords5p,
            "generate_ms": board.generateMs, "solve_ms": board.solveMs,
            "t_board_shown": tBoardShown,
            "app_version": AppInfo.version, "device": AppInfo.deviceModel, "os_version": AppInfo.osVersion,
            "screen_max_fps": UIScreen.main.maximumFramesPerSecond,
            "tile_size": geometry.tileSize, "spacing": geometry.spacing,
            "grid_origin_x": gridOrigin.x + boardArea.frame.minX,
            "grid_origin_y": gridOrigin.y + boardArea.frame.minY,
            "screen_w": UIScreen.main.bounds.width, "screen_h": UIScreen.main.bounds.height,
            "recognizer_config": config.json, "raw_samples": recordRaw,
        ])
    }

    private func endGame(reason: String, at t: Double) {
        guard !isOver else { return }
        isOver = true
        displayLink?.invalidate()
        displayLink = nil
        if attempt != nil {
            attempt = nil
            clearSelection()
        }
        if tBoardShown != nil {
            Database.shared.updateGame(id: gameId, [
                "score": score, "word_count": found.count,
                "t_first_submit": tFirstSubmit, "t_end": t,
                "end_reason": reason, "interrupted": interrupted,
            ])
            if recordRaw, !rawSamples.isEmpty {
                Database.shared.insertSamples(gameId: gameId, rawSamples)
                rawSamples.removeAll(keepingCapacity: true)
            }
        }
        let result = GameResult(gameId: gameId, board: board, score: score, words: found.count,
                                invalid: invalidCount, duplicates: duplicateCount,
                                abandoned: reason != "timeout")
        // Let the last word's animation land before leaving the board.
        DispatchQueue.main.asyncAfter(deadline: .now() + (reason == "timeout" ? 0.6 : 0)) {
            self.onFinish(result)
        }
    }

    @objc private func backTapped() {
        let alert = UIAlertController(title: "Abandon game?", message: "It is logged as abandoned.",
                                      preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Keep playing", style: .cancel))
        alert.addAction(UIAlertAction(title: "Abandon", style: .destructive) { _ in
            self.interrupted = true
            self.endGame(reason: "abandoned", at: CACurrentMediaTime())
        })
        present(alert, animated: true)
    }

    @objc private func resignedActive() {
        if !isOver { interrupted = true }
    }
}

// MARK: - Views

/// Receives the touches for the board: a plain UIView, single touch, no gesture
/// recognizers, so UIKit delivers every event directly (OptimizedTouchHandler).
final class TouchOverlayView: UIView {
    weak var controller: GameViewController?

    override init(frame: CGRect) {
        super.init(frame: frame)
        isMultipleTouchEnabled = false
        backgroundColor = .clear
    }

    required init?(coder: NSCoder) { fatalError() }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let touch = touches.first else { return }
        controller?.touchBegan(touch)
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let touch = touches.first else { return }
        controller?.touchMoved(touch, event: event)
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let touch = touches.first else { return }
        controller?.touchEnded(touch, cancelled: false)
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let touch = touches.first else { return }
        controller?.touchEnded(touch, cancelled: true)
    }
}

/// OptimizedLetterTile / LetterVisual: a 0.86 rounded tile (radius 6, 1 pt border) in a
/// full-cell frame; selected tiles scale to 1.1 on spring(response 0.15, damping 0.4),
/// deselect snaps back; colour changes are not animated.
final class TileView: UIView {
    private let visual = UIView()
    private let label = UILabel()

    init(frame: CGRect, letter: Character, tileSize: CGFloat) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        let v = tileSize * 0.86
        visual.frame = CGRect(x: (tileSize - v) / 2, y: (tileSize - v) / 2, width: v, height: v)
        visual.layer.cornerRadius = 6
        visual.layer.borderWidth = 1
        addSubview(visual)
        label.frame = visual.bounds
        label.textAlignment = .center
        label.font = FluxFont.bold(tileSize * 0.6)
        label.text = String(letter)
        visual.addSubview(label)
        apply(selected: false, state: .invalid)
    }

    required init?(coder: NSCoder) { fatalError() }

    func setSelected(_ selected: Bool, state: WordState, animated: Bool) {
        apply(selected: selected, state: state)
        if selected {
            if animated {
                transform = .identity
                UIView.animate(springDuration: 0.15, bounce: 0.6, options: [.allowUserInteraction]) {
                    self.transform = CGAffineTransform(scaleX: 1.1, y: 1.1)
                }
            }
        } else {
            layer.removeAllAnimations()
            transform = .identity
        }
    }

    private func apply(selected: Bool, state: WordState) {
        UIView.performWithoutAnimation {
            visual.backgroundColor = TileColors.fill(selected: selected, state: state)
            visual.layer.borderColor = TileColors.border(selected: selected, state: state).cgColor
            label.textColor = TileColors.foreground(selected: selected, state: state)
        }
    }
}

/// FormedWordBubble in the 64 pt slot above the grid: FiraSans-Bold 25, 10 pt padding,
/// 50 pt tall, radius 10, 1.5 pt border, "(+pts)" only for a new valid word.
final class WordBubble: UIView {
    var slot: CGRect = .zero {
        didSet { frame = slot }
    }
    private let label = PaddedLabel()

    override init(frame: CGRect) {
        super.init(frame: frame)
        addSubview(label)
        isHidden = true
    }

    required init?(coder: NSCoder) { fatalError() }

    func show(word: String, state: WordState) {
        let text = state == .validAndAvailable ? "\(word) (+\(fluxPoints(forLength: word.count)))" : word
        WordBubble.style(label, text: text, state: state)
        place(label)
        isHidden = false
    }

    func hide() { isHidden = true }

    /// AnimatingWordWithRarityView: rise 25 pt and scale 1.1 on spring(0.5, 0.7), fade
    /// out from 0.3 s over 0.2 s.
    func fly(word: String, points: Int) {
        guard let parent = superview else { return }
        let flyer = PaddedLabel()
        WordBubble.style(flyer, text: "\(word) (+\(points))", state: .validAndAvailable)
        let container = UIView(frame: frame)
        container.isUserInteractionEnabled = false
        container.addSubview(flyer)
        place(flyer, in: container)
        parent.addSubview(container)
        UIView.animate(springDuration: 0.5, bounce: 0.3, options: [.allowUserInteraction]) {
            flyer.transform = CGAffineTransform(translationX: 0, y: -25).scaledBy(x: 1.1, y: 1.1)
        }
        UIView.animate(withDuration: 0.2, delay: 0.3, options: [.curveEaseOut, .allowUserInteraction]) {
            flyer.alpha = 0
        } completion: { _ in
            container.removeFromSuperview()
        }
    }

    private func place(_ l: PaddedLabel, in container: UIView? = nil) {
        let bounds = (container ?? self).bounds
        let maxWidth = bounds.width - 32
        var size = l.sizeThatFits(CGSize(width: maxWidth, height: 50))
        size.width = min(size.width, maxWidth)
        l.frame = CGRect(x: (bounds.width - size.width) / 2, y: bounds.height - 50, width: size.width, height: 50)
    }

    private static func style(_ l: PaddedLabel, text: String, state: WordState) {
        l.text = text
        l.font = FluxFont.bold(25)
        l.adjustsFontSizeToFitWidth = true
        l.minimumScaleFactor = 0.5
        l.textAlignment = .center
        l.textColor = TileColors.foreground(selected: true, state: state)
        l.backgroundColor = TileColors.fill(selected: true, state: state)
        l.layer.cornerRadius = 10
        l.layer.masksToBounds = true
        l.layer.borderWidth = 1.5
        l.layer.borderColor = TileColors.bubbleBorder(state: state).cgColor
    }
}

final class PaddedLabel: UILabel {
    let inset: CGFloat = 10

    override func drawText(in rect: CGRect) {
        super.drawText(in: rect.insetBy(dx: inset, dy: 0))
    }

    override func sizeThatFits(_ size: CGSize) -> CGSize {
        let s = super.sizeThatFits(CGSize(width: size.width - 2 * inset, height: size.height))
        return CGSize(width: s.width + 2 * inset, height: size.height)
    }
}

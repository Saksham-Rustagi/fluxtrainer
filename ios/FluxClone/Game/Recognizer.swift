import CoreGraphics
import Foundation

// Port of flux-ios HighPerformanceTouchHandlerOptimized.swift (OptimizedTouchHandler +
// TileGridCache) at 40e6ed7. See docs/CLONE_RECON.md for the line-by-line source. Every
// knob the port exposes defaults to what Flux does; the alternatives exist so the
// recognizer can be tuned against the Phase 1 gate, and each game records which it used.

enum HitShape: String, Codable, CaseIterable {
    case circle    // Flux default: inscribed circle, |d| <= ratio/2 * tileSize
    case diamond   // Flux option (picker commented out): |dx| + |dy| <= ratio/2 * tileSize
    case rect      // full cell rect, for comparison only
}

enum Interpolation: String, Codable, CaseIterable {
    case none      // Flux: only the sampled points are hit-tested
    case segment   // walk the segment between samples at 1 pt steps
}

enum SampleMode: String, Codable, CaseIterable {
    case perDelivery  // Flux before a2f3523 (the whole ranked baseline): one sample per touchesMoved
    case coalesced    // Flux from a2f3523 (2026-09-19): every coalesced digitizer sample
}

struct RecognizerConfig: Codable, Equatable {
    var hitShape: HitShape = .circle
    /// Hit target size as a fraction of tileSize: the circle's diameter, the diamond's
    /// width. Flux: Constants.dragHitboxRatio = 0.86.
    var hitRatio: Double = 0.86
    /// Flux tests the first tile of a swipe against the full cell rect (tileAt), and
    /// only later tiles against the shape (tileAtShape).
    var firstTileFullRect: Bool = true
    var interpolation: Interpolation = .none
    var sampleMode: SampleMode = .perDelivery

    static let flux = RecognizerConfig()

    /// The diagnostic shadow: what a recognizer that never skips would have selected.
    static let shadow = RecognizerConfig(interpolation: .segment, sampleMode: .coalesced)

    var json: String {
        let data = (try? JSONEncoder.sorted.encode(self)) ?? Data()
        return String(decoding: data, as: UTF8.self)
    }
}

extension JSONEncoder {
    static let sorted: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys]
        return e
    }()
}

/// Grid-local geometry: (0, 0) is the top-left of the top-left tile's cell.
struct GridGeometry: Equatable {
    let side: Int
    let tileSize: CGFloat
    let spacing: CGFloat

    var pitch: CGFloat { tileSize + spacing }
    var totalSize: CGFloat { CGFloat(side) * tileSize + CGFloat(side - 1) * spacing }

    func cellFrame(_ cell: Int) -> CGRect {
        let row = cell / side, col = cell % side
        return CGRect(x: CGFloat(col) * pitch, y: CGFloat(row) * pitch, width: tileSize, height: tileSize)
    }

    func center(_ cell: Int) -> CGPoint {
        let f = cellFrame(cell)
        return CGPoint(x: f.midX, y: f.midY)
    }

    func adjacent(_ a: Int, _ b: Int) -> Bool {
        let dr = abs(a / side - b / side), dc = abs(a % side - b % side)
        return dr <= 1 && dc <= 1 && !(dr == 0 && dc == 0)
    }

    /// The cell whose pitch box contains `p` (TileGridCache's integer division), or nil
    /// off-grid. Note the bounds check is inclusive at totalSize, as in Flux.
    private func pitchCell(_ p: CGPoint) -> Int? {
        guard p.x >= 0, p.y >= 0, p.x <= totalSize, p.y <= totalSize else { return nil }
        let col = Int(p.x / pitch), row = Int(p.y / pitch)
        guard row >= 0, row < side, col >= 0, col < side else { return nil }
        return row * side + col
    }

    /// Flux tileAt: the full cell rect, excluding the spacing gap.
    func cellInRect(_ p: CGPoint) -> Int? {
        guard let cell = pitchCell(p) else { return nil }
        return cellFrame(cell).contains(p) ? cell : nil
    }

    /// Flux tileAtShape: the shape of the pitch cell containing `p` only.
    func cellInShape(_ p: CGPoint, shape: HitShape, ratio: Double) -> Int? {
        guard let cell = pitchCell(p) else { return nil }
        let c = center(cell)
        let dx = abs(p.x - c.x), dy = abs(p.y - c.y)
        let half = tileSize * CGFloat(ratio) * 0.5
        switch shape {
        case .circle: return (dx * dx + dy * dy).squareRoot() <= half ? cell : nil
        case .diamond: return dx + dy <= half ? cell : nil
        case .rect: return cellFrame(cell).contains(p) ? cell : nil
        }
    }
}

/// One swipe's selection logic. Pure: points in, cells out.
final class Recognizer {
    let geometry: GridGeometry
    let config: RecognizerConfig

    private(set) var path: [Int] = []
    private var lastPoint: CGPoint?

    init(geometry: GridGeometry, config: RecognizerConfig) {
        self.geometry = geometry
        self.config = config
    }

    /// touchesBegan. Returns the cells added (at most one).
    @discardableResult
    func begin(at p: CGPoint) -> [Int] {
        path.removeAll()
        lastPoint = p
        let hit = config.firstTileFullRect
            ? geometry.cellInRect(p)
            : geometry.cellInShape(p, shape: config.hitShape, ratio: config.hitRatio)
        if let hit {
            path.append(hit)
            return [hit]
        }
        return []
    }

    /// One touchesMoved sample (Flux processMove). Returns the cells added, in order.
    @discardableResult
    func move(to p: CGPoint) -> [Int] {
        var added: [Int] = []
        if config.interpolation == .segment, let a = lastPoint {
            let dx = p.x - a.x, dy = p.y - a.y
            let steps = max(1, Int((dx * dx + dy * dy).squareRoot().rounded(.up)))
            for i in 1..<steps {
                let t = CGFloat(i) / CGFloat(steps)
                if let cell = consider(CGPoint(x: a.x + dx * t, y: a.y + dy * t)) { added.append(cell) }
            }
        }
        if let cell = consider(p) { added.append(cell) }
        lastPoint = p
        return added
    }

    private func consider(_ p: CGPoint) -> Int? {
        guard let cell = geometry.cellInShape(p, shape: config.hitShape, ratio: config.hitRatio) else {
            return nil
        }
        // Retrace onto any selected tile, including the previous one, is a no-op.
        if path.contains(cell) { return nil }
        // Non-adjacent: ignored, and the path continues from its last tile.
        if let last = path.last, !geometry.adjacent(last, cell) { return nil }
        path.append(cell)
        return cell
    }
}

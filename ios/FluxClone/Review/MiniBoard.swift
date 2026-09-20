import SwiftUI

/// The board, small, with one path drawn on it.
///
/// SPEC 9.1's first design rule: **board first for spatial leaks, list first for study
/// material.** A missed family is a spatial leak -- the answer to "why did I not see
/// STORED" is a shape, not a string -- so review draws it where it was, along the path it
/// takes.
///
/// It used to walk the path a cell at a time and cycle through the misses. That is out:
/// the answer is already known by the time the animation starts, and waiting for it is
/// the cost of looking at a card. One path, drawn, held, and changed by tapping a word in
/// the list beside it -- which also means the shape can be looked at for as long as it is
/// wanted instead of for 0.32 seconds a cell.
///
/// This is deliberately not the game's `GameViewController`: nothing here is touchable,
/// nothing is timed, and it has to sit inside a scrolling review card.
struct MiniBoard: View {
    let letters: [Character]
    let side: Int
    /// Lit for as long as the card is on screen: the stem the family hangs off.
    var stemPath: [Int] = []
    /// The one path drawn over it.
    var path: [Int] = []
    var tileSize: CGFloat = 34
    var spacing: CGFloat = 4

    var body: some View {
        let width = CGFloat(side) * tileSize + CGFloat(side - 1) * spacing
        // Three layers, and the order matters: the swipe line goes over the tiles and
        // under the letters. Drawing it last -- which is what the game does, where the
        // line is the thing being watched -- covers the letters on a board this small,
        // and an unreadable board is not a review of anything.
        ZStack(alignment: .topLeading) {
            layer { fill($0) }
            if stemPath.count > 1 {
                shape(stemPath)
                    .stroke(Color(uiColor: FluxTheme.sub),
                            style: .init(lineWidth: 8, lineCap: .round, lineJoin: .round))
            }
            if path.count > 1 {
                shape(path)
                    .stroke(Color(uiColor: FluxTheme.main).opacity(0.85),
                            style: .init(lineWidth: 5, lineCap: .round, lineJoin: .round))
            }
            layer { letter($0) }
        }
        .frame(width: width, height: width)
        .animation(.easeOut(duration: 0.18), value: path)
    }

    /// One pass over the grid, laid out identically whichever layer is being drawn, so
    /// the fills and the letters cannot drift apart.
    private func layer<Content: View>(@ViewBuilder _ cell: @escaping (Int) -> Content)
        -> some View {
        VStack(spacing: spacing) {
            ForEach(0..<side, id: \.self) { row in
                HStack(spacing: spacing) {
                    ForEach(0..<side, id: \.self) { col in
                        cell(row * side + col).frame(width: tileSize, height: tileSize)
                    }
                }
            }
        }
    }

    private func fill(_ cell: Int) -> some View {
        RoundedRectangle(cornerRadius: 6)
            .fill(Color(uiColor: path.contains(cell) ? FluxTheme.main
                                                     : (stemPath.contains(cell) ? FluxTheme.sub
                                                                                : FluxTheme.subAlt)))
    }

    private func letter(_ cell: Int) -> some View {
        Text(cell < letters.count ? String(letters[cell]) : " ")
            .font(Font(FluxFont.bold(tileSize * 0.52)))
            .foregroundStyle(Color(uiColor: path.contains(cell) ? FluxTheme.mainContrast
                                                                : FluxTheme.text))
    }

    private func centre(_ cell: Int) -> CGPoint {
        let row = CGFloat(cell / side), col = CGFloat(cell % side)
        return CGPoint(x: col * (tileSize + spacing) + tileSize / 2,
                       y: row * (tileSize + spacing) + tileSize / 2)
    }

    private func shape(_ cells: [Int]) -> Path {
        var out = Path()
        guard cells.count > 1 else { return out }
        out.move(to: centre(cells[0]))
        for cell in cells.dropFirst() { out.addLine(to: centre(cell)) }
        return out
    }
}

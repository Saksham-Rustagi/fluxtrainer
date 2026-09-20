import UIKit

/// The "arch" theme (flux-ios GeneratedThemes.swift, themes/arch.css) with the derived
/// contrast colours resolved the way Theme.init resolves them (highest WCAG contrast
/// ratio among the candidates), and the "classic" board colour scheme
/// (BoardView.swift getBoardLetter*Color).
enum FluxTheme {
    static let bg = UIColor(hex: 0x0C0D11)
    static let main = UIColor(hex: 0x7EBAB5)
    static let sub = UIColor(hex: 0x454864)
    static let subAlt = UIColor(hex: 0x171A25)
    static let text = UIColor(hex: 0xF6F5F5)
    static let colorfulError = UIColor(hex: 0xFF4754)

    // Highest-contrast candidate, as Theme.init picks them for arch.
    static let bgContrast = text        // of [main, sub, text] against bg: 17.85
    static let subAltContrast = text    // of [main, sub, text] against subAlt: 15.94
    static let mainContrast = bg        // of [sub, text, bg] against main: 8.86
    static let subContrast = text       // of [main, text, bg] against sub: 8.16

    static let path = colorfulError     // pathColorReference default: colorfulErrorColor
}

enum WordState {
    case invalid
    case validButFound
    case validAndAvailable
}

/// The classic scheme with tile borders on. It differs from contrast only for an invalid
/// word: the tile keeps the unselected fill and foreground (subAlt / subAltContrast)
/// rather than dropping to sub / subContrast, so only the red border marks it.
enum TileColors {
    static func fill(selected: Bool, state: WordState) -> UIColor {
        guard selected else { return FluxTheme.subAlt }
        switch state {
        case .validAndAvailable: return FluxTheme.main
        case .validButFound: return FluxTheme.main.withAlphaComponent(0.7)
        case .invalid: return FluxTheme.subAlt
        }
    }

    static func foreground(selected: Bool, state: WordState) -> UIColor {
        guard selected else { return FluxTheme.subAltContrast }
        switch state {
        case .validAndAvailable: return FluxTheme.mainContrast
        case .validButFound: return FluxTheme.mainContrast.withAlphaComponent(0.7)
        case .invalid: return FluxTheme.subAltContrast
        }
    }

    static func border(selected: Bool, state: WordState) -> UIColor {
        guard selected else { return FluxTheme.subAltContrast.withAlphaComponent(0.7) }
        switch state {
        case .validAndAvailable: return FluxTheme.mainContrast
        case .validButFound: return FluxTheme.mainContrast.withAlphaComponent(0.7)
        case .invalid: return FluxTheme.colorfulError
        }
    }

    /// FormedWordBubble border: a valid word gets subColor at 0.35, otherwise the tile rule.
    static func bubbleBorder(state: WordState) -> UIColor {
        state == .validAndAvailable ? FluxTheme.sub.withAlphaComponent(0.35) : border(selected: true, state: state)
    }
}

enum FluxFont {
    static func bold(_ size: CGFloat) -> UIFont {
        UIFont(name: "FiraSans-Bold", size: size) ?? .systemFont(ofSize: size, weight: .heavy)
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

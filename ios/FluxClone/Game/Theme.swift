import UIKit

/// Flux's default theme ("aurora", flux-ios SimpleTheme.swift:222, GeneratedThemes.swift)
/// with the derived contrast colours resolved the way Theme.init resolves them, and the
/// default "contrast" board colour scheme (BoardView.swift getBoardLetter*Color).
enum FluxTheme {
    static let bg = UIColor(hex: 0x011926)
    static let main = UIColor(hex: 0x00E980)
    static let sub = UIColor(hex: 0x245C69)
    static let subAlt = UIColor(hex: 0x000C13)
    static let text = UIColor(hex: 0xFFFFFF)
    static let colorfulError = UIColor(hex: 0xB94DA1)

    // Highest-contrast candidate, as Theme.init picks them for aurora.
    static let bgContrast = text        // of [main, sub, text] against bg
    static let subAltContrast = text    // of [main, sub, text] against subAlt
    static let mainContrast = bg        // of [sub, text, bg] against main
    static let subContrast = text       // of [main, text, bg] against sub

    static let path = colorfulError     // pathColorReference default: colorfulErrorColor
}

enum WordState {
    case invalid
    case validButFound
    case validAndAvailable
}

/// The contrast scheme with tile borders on (the defaults).
enum TileColors {
    static func fill(selected: Bool, state: WordState) -> UIColor {
        guard selected else { return FluxTheme.subAlt }
        switch state {
        case .validAndAvailable: return FluxTheme.main
        case .validButFound: return FluxTheme.main.withAlphaComponent(0.7)
        case .invalid: return FluxTheme.sub
        }
    }

    static func foreground(selected: Bool, state: WordState) -> UIColor {
        guard selected else { return FluxTheme.subAltContrast }
        switch state {
        case .validAndAvailable: return FluxTheme.mainContrast
        case .validButFound: return FluxTheme.mainContrast.withAlphaComponent(0.7)
        case .invalid: return FluxTheme.subContrast
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

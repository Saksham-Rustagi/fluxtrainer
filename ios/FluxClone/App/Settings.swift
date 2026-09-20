import UIKit

/// Flux board settings at their defaults (SettingsManager.swift:253-269) and the tile-size
/// formula (BoardView.getUniformLetterSize / getLetterSize / getMaxLetterSize).
struct BoardSettings {
    var universalTileSize: CGFloat = 1.0   // 0.6...1.6
    var spacing: CGFloat = 0               // 0...10
    var verticalPosition: CGFloat = 0.5    // 0...1
    var pathWidth: CGFloat = 4.0           // 1...10

    static let flux = BoardSettings()

    func tileSize(side n: Int, screenWidth: CGFloat) -> CGFloat {
        let base = min(72, (screenWidth - 12) / CGFloat(n))
        let scaled = base * universalTileSize
        let maxSize = (screenWidth - 40 - spacing * CGFloat(n - 1)) / CGFloat(n)
        return min(scaled, maxSize)
    }
}

/// Recognizer settings, persisted. Defaults are Flux's; changes apply from the next game
/// and every game records the config it ran with.
enum RecognizerSettings {
    private static let key = "recognizerConfig"

    static var current: RecognizerConfig {
        get {
            guard let data = UserDefaults.standard.data(forKey: key),
                  let config = try? JSONDecoder().decode(RecognizerConfig.self, from: data) else { return .flux }
            return config
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: key) }
    }
}

enum AppInfo {
    static var version: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return "\(v) (\(b))"
    }

    static var deviceModel: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    static var osVersion: String { "iOS \(UIDevice.current.systemVersion)" }
}

/// Raw touch samples are kept for the first 30 games only (they get large fast).
enum RawSampling {
    static let gameLimit = 30
}

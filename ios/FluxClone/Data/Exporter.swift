import Foundation

/// Two ways the play log leaves the app container:
///  - manual: a snapshot handed to the system "Save to Files" picker (HomeView).
///  - automatic, weekly: a snapshot written into Documents/Exports, which the Files app
///    shows under On My iPhone > FluxClone (UIFileSharingEnabled +
///    LSSupportsOpeningDocumentsInPlace). It survives the free-profile expiry as long as
///    the app is re-signed rather than deleted, and it is one tap to copy elsewhere.
enum Exporter {
    static let autoInterval: TimeInterval = 7 * 24 * 3600
    static let autoKeep = 8

    static var lastManualExport: Date? {
        get { UserDefaults.standard.object(forKey: "lastManualExport") as? Date }
        set { UserDefaults.standard.set(newValue, forKey: "lastManualExport") }
    }

    static var lastAutoExport: Date? {
        get { UserDefaults.standard.object(forKey: "lastAutoExport") as? Date }
        set { UserDefaults.standard.set(newValue, forKey: "lastAutoExport") }
    }

    static var lastAnyExport: Date? {
        [lastManualExport, lastAutoExport].compactMap { $0 }.max()
    }

    private static func stamp(_ date: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: date)
    }

    /// A fresh snapshot in tmp, for the Files picker.
    static func manualSnapshot() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("fluxclone-\(stamp()).sqlite")
        try Database.shared.snapshot(to: url)
        return url
    }

    static var exportsDirectory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Exports", isDirectory: true)
    }

    /// Called on every launch and foreground. Cheap when not due.
    static func autoExportIfDue() {
        if let last = lastAutoExport, Date().timeIntervalSince(last) < autoInterval { return }
        guard Database.shared.completedGameCount() > 0 else { return }
        DispatchQueue.global(qos: .utility).async {
            do {
                try FileManager.default.createDirectory(at: exportsDirectory, withIntermediateDirectories: true)
                let url = exportsDirectory.appendingPathComponent("fluxclone-auto-\(stamp()).sqlite")
                try Database.shared.snapshot(to: url)
                DispatchQueue.main.async { lastAutoExport = Date() }
                prune()
            } catch {
                print("auto export failed: \(error)")
            }
        }
    }

    private static func prune() {
        let fm = FileManager.default
        guard let files = try? fm.contentsOfDirectory(at: exportsDirectory, includingPropertiesForKeys: nil) else { return }
        let autos = files.filter { $0.lastPathComponent.hasPrefix("fluxclone-auto-") }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
        for old in autos.dropFirst(autoKeep) { try? fm.removeItem(at: old) }
    }
}

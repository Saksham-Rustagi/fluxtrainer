import SwiftUI
import UIKit

private let fluxAccent = Color(uiColor: FluxTheme.main)
private let fluxBackground = Color(uiColor: FluxTheme.bg)

struct HomeView: View {
    @EnvironmentObject var model: AppModel
    @State private var games: [Database.GameSummary] = []
    @State private var exportURL: URL?
    @State private var exportError: String?
    @State private var showSettings = false
    @State private var lastExport = Exporter.lastAnyExport

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button(action: model.play) {
                        HStack {
                            Spacer()
                            if model.waitingToPlay || (!model.engineReady) {
                                ProgressView()
                            } else {
                                Text("Play").font(.system(size: 28, weight: .heavy))
                            }
                            Spacer()
                        }
                        .padding(.vertical, 14)
                    }
                    .disabled(!model.engineReady)
                    .listRowBackground(fluxAccent.opacity(0.25))

                    Picker("Grid", selection: $model.gridOverride) {
                        Text("Ranked mix").tag(Int?.none)
                        Text("4x4").tag(Int?.some(4))
                        Text("5x5").tag(Int?.some(5))
                    }
                    Picker("Tier", selection: $model.tierOverride) {
                        Text("Ranked mix").tag(Tier?.none)
                        ForEach(Tier.allCases, id: \.self) { Text($0.displayName).tag(Tier?.some($0)) }
                    }
                } footer: {
                    Text("Overrides are for testing; games played with one are flagged in the log.")
                }

                Section("Data") {
                    Button("Export database to Files") { exportNow() }
                    HStack {
                        Text("Last export")
                        Spacer()
                        Text(lastExportText).foregroundStyle(exportOverdue ? .red : .secondary)
                    }
                    if let exportError { Text(exportError).foregroundStyle(.red) }
                }

                Section("Games (\(games.count) shown)") {
                    if games.isEmpty { Text("No games yet").foregroundStyle(.secondary) }
                    ForEach(games) { g in GameRow(game: g) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(fluxBackground)
            .navigationTitle("Flux Clone")
            .toolbar {
                Button { showSettings = true } label: { Image(systemName: "slider.horizontal.3") }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(item: $exportURL) { url in
                ExportPicker(url: url) { saved in
                    if saved {
                        Exporter.lastManualExport = Date()
                        lastExport = Exporter.lastAnyExport
                    }
                    exportURL = nil
                }
            }
            .onAppear(perform: reload)
        }
    }

    private var exportOverdue: Bool {
        guard !games.isEmpty else { return false }
        guard let lastExport else { return true }
        return Date().timeIntervalSince(lastExport) > 7 * 24 * 3600
    }

    private var lastExportText: String {
        guard let lastExport else { return "never" }
        return RelativeDateTimeFormatter().localizedString(for: lastExport, relativeTo: Date())
    }

    private func reload() {
        DispatchQueue.global(qos: .userInitiated).async {
            let rows = Database.shared.recentGames(limit: 200)
            DispatchQueue.main.async {
                games = rows
                lastExport = Exporter.lastAnyExport
            }
        }
    }

    private func exportNow() {
        do {
            exportURL = try Exporter.manualSnapshot()
            exportError = nil
        } catch {
            exportError = error.localizedDescription
        }
    }
}

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}

private struct GameRow: View {
    let game: Database.GameSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text("\(game.score)").font(.headline.monospacedDigit())
                Text("· \(game.words) words").foregroundStyle(.secondary)
                Spacer()
                Text("\(game.grid)x\(game.grid) \(game.tier)\(game.tierSource == "override" ? "*" : "")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Text("potential \(game.potential)")
                Text("invalid \(game.invalid)")
                Text("dup \(game.duplicate)")
                if game.interrupted { Text("interrupted").foregroundStyle(.orange) }
                Spacer()
                Text(game.startedWall.prefix(16).replacingOccurrences(of: "T", with: " "))
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }
}

struct ExportPicker: UIViewControllerRepresentable {
    let url: URL
    let done: (Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(done: done) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ vc: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let done: (Bool) -> Void
        init(done: @escaping (Bool) -> Void) { self.done = done }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) { done(true) }
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { done(false) }
    }
}

struct ResultsView: View {
    @EnvironmentObject var model: AppModel
    let result: GameResult

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Text("\(result.score)")
                .font(Font(FluxFont.bold(68)))
                .foregroundStyle(.white)
            Text("\(result.words) words").font(.title3).foregroundStyle(.white.opacity(0.8))
            VStack(alignment: .leading, spacing: 6) {
                row("Board", "\(result.board.side)x\(result.board.side) \(result.board.tier.displayName)")
                row("Potential", "\(result.board.potentialPoints) pts · \(result.board.potentialWords) words")
                row("Invalid attempts", "\(result.invalid)")
                row("Duplicate re-swipes", "\(result.duplicates)")
            }
            .font(.body.monospacedDigit())
            .padding()
            .background(RoundedRectangle(cornerRadius: 12).fill(Color(uiColor: FluxTheme.subAlt)))
            Spacer()
            Button(action: model.play) {
                Text("Next game").font(.title2.weight(.heavy)).frame(maxWidth: .infinity).padding()
            }
            .buttonStyle(.borderedProminent)
            .tint(fluxAccent)
            .foregroundStyle(Color(uiColor: FluxTheme.bg))
            .disabled(model.nextBoard == nil && model.waitingToPlay)
            Button("Home") { model.screen = .home }
                .padding(.bottom)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(fluxBackground)
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).foregroundStyle(.secondary)
            Spacer()
            Text(v).foregroundStyle(.white)
        }
    }
}

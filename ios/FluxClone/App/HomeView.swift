import SwiftUI
import UIKit

private let fluxAccent = Color(uiColor: FluxTheme.main)
private let fluxBackground = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)

/// The home tab, and the front door. **Playing a board is one tap from launch with no
/// configuration.** Everything that used to sit above it -- the trainer, the overrides --
/// is either below it or in another tab.
struct PlayView: View {
    @EnvironmentObject var model: AppModel
    @State private var games: [Database.GameSummary] = []
    @State private var showSettings = false
    @State private var mixedCandidates: [MixedCandidate] = []
    @State private var mixedSelection: Set<String> = []
    @State private var showMixed = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    playButton
                    mixedButton
                    trainRow
                    recent
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 30)
            }
            .background(fluxBackground)
            .navigationTitle("Flux")
            .toolbar {
                NavigationLink { DataView() } label: { Image(systemName: "tray.and.arrow.up") }
                Button { showSettings = true } label: { Image(systemName: "slider.horizontal.3") }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(isPresented: $showMixed) {
                MixedPickerView(candidates: mixedCandidates, selection: $mixedSelection,
                                play: {
                                    showMixed = false
                                    model.playMixed(stems: Array(mixedSelection))
                                },
                                cancel: { showMixed = false })
            }
            .onAppear(perform: reload)
        }
    }

    private var playButton: some View {
        Button(action: model.play) {
            HStack {
                Spacer()
                if model.waitingToPlay || !model.engineReady {
                    ProgressView().tint(Color(uiColor: FluxTheme.bg))
                } else {
                    Text("Play").font(.system(size: 34, weight: .heavy))
                }
                Spacer()
            }
            .padding(.vertical, 24)
            .background(RoundedRectangle(cornerRadius: 16).fill(fluxAccent))
            .foregroundStyle(Color(uiColor: FluxTheme.bg))
        }
        .disabled(!model.engineReady)
        .padding(.top, 8)
    }

    /// Section 5. A normal board with the families you pick quietly seeded into it,
    /// scored per family afterwards.
    private var mixedButton: some View {
        Button(action: openMixed) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Mixed practice").font(.headline)
                    Text(mixedSubtitle)
                        .font(.caption).foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(.tertiary)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 12).fill(panel))
            .foregroundStyle(.white)
        }
        .disabled(model.queue == nil)
    }

    /// The last set is remembered and shown, so repeating a mix is one tap and changing
    /// it is two.
    private var mixedSubtitle: String {
        guard !mixedSelection.isEmpty else {
            return "Pick families and hide them in an ordinary board"
        }
        return mixedSelection.sorted().map { "\($0)-" }.joined(separator: " ")
    }

    private func openMixed() {
        guard let queue = model.queue else { return }
        let ranked = queue.ranked
        let index = FamilyIndex.shared
        DispatchQueue.global(qos: .userInitiated).async {
            let found = MixedCandidates.load(queue: ranked, index: index)
            DispatchQueue.main.async {
                mixedCandidates = found
                // Shuffled within the top of the list on first open, so two sessions in a
                // row are not the same board.
                if mixedSelection.isEmpty || !mixedSelection.isSubset(
                    of: Set(found.map(\.hook.stem))) {
                    mixedSelection = MixedCandidates.defaultSelection(from: found)
                }
                showMixed = true
            }
        }
    }

    /// Demoted on purpose. The drill is reached from review or from a family, which is
    /// where the case for drilling a particular stem actually gets made -- but a daily
    /// session is still one tap for the days he just wants to be told what to do.
    @ViewBuilder
    private var trainRow: some View {
        if let queue = model.queue {
            TrainCard(queue: queue) { shortDay in model.train(shortDay: shortDay) }
                .padding(14)
                .frame(maxWidth: .infinity)
                .background(RoundedRectangle(cornerRadius: 12).fill(panel))
        } else if let error = model.queueError {
            Text("Training is off: \(error)")
                .font(.footnote).foregroundStyle(.orange)
        }
    }

    private var recent: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Recent").font(.headline).foregroundStyle(.white)
                Spacer()
                Text("\(games.count)").font(.caption).foregroundStyle(.tertiary)
            }
            .padding(.top, 10)
            if games.isEmpty {
                Text("No games yet").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(games.prefix(25)) { g in
                GameRow(game: g)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8).fill(panel))
            }
        }
    }

    private func reload() {
        DispatchQueue.global(qos: .userInitiated).async {
            let rows = Database.shared.recentGames(limit: 200)
            DispatchQueue.main.async { games = rows }
        }
    }
}

/// Export, the board overrides, and the counts. Off the front door because none of it is
/// part of playing.
struct DataView: View {
    @EnvironmentObject var model: AppModel
    @State private var exportURL: URL?
    @State private var exportError: String?
    @State private var lastExport = Exporter.lastAnyExport
    @State private var games = 0

    var body: some View {
        List {
            Section {
                Picker("Grid", selection: $model.gridOverride) {
                    Text("Ranked mix").tag(Int?.none)
                    Text("4x4").tag(Int?.some(4))
                    Text("5x5").tag(Int?.some(5))
                }
                Picker("Tier", selection: $model.tierOverride) {
                    Text("Ranked mix").tag(Tier?.none)
                    ForEach(Tier.allCases, id: \.self) { Text($0.displayName).tag(Tier?.some($0)) }
                }
            } header: {
                Text("Board overrides")
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
                HStack {
                    Text("Games logged")
                    Spacer()
                    Text("\(games)").foregroundStyle(.secondary)
                }
                if let exportError { Text(exportError).foregroundStyle(.red) }
            }
        }
        .scrollContentBackground(.hidden)
        .background(fluxBackground)
        .navigationTitle("Data")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $exportURL) { url in
            ExportPicker(url: url) { saved in
                if saved {
                    Exporter.lastManualExport = Date()
                    lastExport = Exporter.lastAnyExport
                }
                exportURL = nil
            }
        }
        .onAppear { games = Database.shared.completedGameCount() }
    }

    private var exportOverdue: Bool {
        guard games > 0 else { return false }
        guard let lastExport else { return true }
        return Date().timeIntervalSince(lastExport) > 7 * 24 * 3600
    }

    private var lastExportText: String {
        guard let lastExport else { return "never" }
        return RelativeDateTimeFormatter().localizedString(for: lastExport, relativeTo: Date())
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

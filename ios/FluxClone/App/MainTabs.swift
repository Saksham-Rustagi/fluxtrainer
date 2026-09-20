import SwiftUI

private let accent = Color(uiColor: FluxTheme.main)
private let bg = Color(uiColor: FluxTheme.bg)
private let panel = Color(uiColor: FluxTheme.subAlt)

/// The shape of the app, after the structural change.
///
/// | tab | what it is |
/// | Play | the front door: a board in one tap, or mixed practice |
/// | My stems | everything drilled or met, with completion and trend |
/// | Queue | demoted to a reference tab |
///
/// Review is not a tab. It is what a finished board returns to, which is the point: it is
/// in the path rather than somewhere to go and look. The drill is not a tab either -- it
/// is reached from review or from a family, where the case for drilling a particular stem
/// has just been made.
struct MainTabs: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        TabView {
            PlayView()
                .tabItem { Label("Play", systemImage: "square.grid.3x3.fill") }
            StemsView(drill: model.drill(stem:))
                .tabItem { Label("My stems", systemImage: "list.bullet.rectangle") }
            QueueView()
                .tabItem { Label("Queue", systemImage: "arrow.down.right.circle") }
        }
        .tint(accent)
    }
}

/// The queue, as reference. It is not where the day starts any more -- the app picks the
/// hook and review sends him to a family -- but 10,594 ranked hooks are worth being able
/// to look at, and the recompute's own numbers are worth being able to check.
struct QueueView: View {
    @EnvironmentObject var model: AppModel
    @State private var search = ""

    var body: some View {
        NavigationStack {
            Group {
                if let queue = model.queue {
                    List {
                        Section {
                            Text(queue.recomputedText)
                                .font(.caption).foregroundStyle(.secondary)
                            if queue.promotable.myRateMoved > 0 {
                                Text("\(queue.promotable.myRateMoved) words the queue could "
                                     + "not price have moved on your own rate; their "
                                     + "top-quartile reference stays untrusted until the "
                                     + "next ranked export.")
                                    .font(.caption2).foregroundStyle(.tertiary)
                            }
                        }
                        Section("\(shown(queue).count) of \(queue.bundle.queueTotal) hooks") {
                            ForEach(shown(queue).prefix(200)) { ranked in
                                NavigationLink(value: ranked.hook.stem) {
                                    QueueRow(ranked: ranked)
                                }
                                .listRowBackground(Color.clear)
                            }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .searchable(text: $search, prompt: "Stem")
                } else {
                    Text(model.queueError ?? "Loading the queue")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .background(bg)
            .navigationTitle("Queue")
            .navigationDestination(for: String.self) {
                FamilyPageView(stem: $0, drill: model.drill(stem:))
            }
        }
    }

    private func shown(_ queue: TrainingQueue) -> [TrainingQueue.Ranked] {
        let query = search.uppercased()
        guard !query.isEmpty else { return queue.ranked }
        return queue.ranked.filter { $0.hook.stem.contains(query) }
    }
}

private struct QueueRow: View {
    let ranked: TrainingQueue.Ranked

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(ranked.hook.stem)-")
                    .font(.body.monospaced().weight(.bold))
                    .foregroundStyle(ranked.eligible ? accent : .secondary)
                Text(ranked.hook.track).font(.caption2).foregroundStyle(.tertiary)
                Spacer()
                Text(String(format: "%.1f/game", ranked.expectedGain))
                    .font(.caption.monospacedDigit()).foregroundStyle(.white)
            }
            Text("\(ranked.owned) owned · \(ranked.learning) learning · \(ranked.unknown) unknown")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}

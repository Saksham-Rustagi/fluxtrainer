import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var config = RecognizerSettings.current
    @State private var soundOn = Sounds.shared.enabled
    @State private var rawGames = 0

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Hit shape", selection: $config.hitShape) {
                        ForEach(HitShape.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    Stepper(value: $config.hitRatio, in: 0.5...1.0, step: 0.01) {
                        Text("Hit size \(config.hitRatio, specifier: "%.2f") × tile")
                    }
                    Toggle("First tile: full cell rect", isOn: $config.firstTileFullRect)
                    Picker("Interpolation", selection: $config.interpolation) {
                        ForEach(Interpolation.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    Picker("Hit-tested samples", selection: $config.sampleMode) {
                        ForEach(SampleMode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    Button("Reset to Flux") { config = .flux }
                        .disabled(config == .flux)
                } header: {
                    Text("Recognizer")
                } footer: {
                    Text(config == .flux
                         ? "Matches Flux: circle 0.86, full rect for the first tile, no interpolation, one sample per touch delivery."
                         : "Differs from Flux. Every game records the config it used.")
                }

                Section("Feedback") {
                    Toggle("Sound", isOn: $soundOn)
                }

                Section("Diagnostics") {
                    LabeledContent("Device", value: AppInfo.deviceModel)
                    LabeledContent("Max frame rate", value: "\(UIScreen.main.maximumFramesPerSecond) Hz")
                    LabeledContent("Raw-sample games", value: "\(rawGames) / \(RawSampling.gameLimit)")
                    LabeledContent("Ruleset", value: "v\(FluxEngine.shared.rulesetVersion)")
                    LabeledContent("Config hash", value: String(format: "0x%016llx", FluxEngine.shared.configHash))
                    LabeledContent("Dictionary", value: "\(FluxEngine.shared.dictionaryWords) words")
                    LabeledContent("App", value: AppInfo.version)
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                Button("Done") {
                    RecognizerSettings.current = config
                    Sounds.shared.enabled = soundOn
                    dismiss()
                }
            }
            .onAppear { rawGames = Database.shared.rawSampleGameCount() }
        }
    }
}

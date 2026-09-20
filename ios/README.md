# Flux Clone (Phases 1 and 3)

An iOS app that plays like Flux ranked and logs every swipe (Phase 1), and trains board
vision off the Phase 2 queue (Phase 3).

- **Play** is the clone: an 80-second ranked board, nothing constrained, everything logged.
- **Train** is the teaching loop: a warm-up board, branch-completion drills on a hook the
  app picks, an affix grid, and family sweeps of hooks that are due. Ten to fifteen minutes,
  one tap, no configuration. `docs/PHASE3_NOTES.md` covers what it does and why.

- The input layer is ported from flux-ios at `40e6ed7`. `docs/CLONE_RECON.md` gives the source
  file and line for each rule.
- Boards and solving come from FluxCore v3: `config/ruleset_v3.json` and
  `data/dict/flux_capped.dawg`, built from the same C++ as the simulator.
- Every attempt goes into a local SQLite database.
- `tools/clone_report/clone_report.py` turns an export into the Phase 1 gate numbers.

## Build and install (free Apple ID)

One-time setup:

1. Install the iOS platform: Xcode > Settings > Components > iOS, or run
   `xcodebuild -downloadPlatform iOS`.
2. Install XcodeGen with `brew install xcodegen`.
3. The DAWG must exist at `data/dict/flux_capped.dawg`. It is gitignored. Rebuild it with:
   `build_dawg bogwords.txt flux_capped.dawg --exclude data/flux_removed_words.txt --max-letter-repeat 2`.
   `FluxClone/Resources/training_hooks.json` is committed; `sh tools/queue/run_all.sh`
   rewrites it alongside the queue.
4. On the phone, turn on Settings > Privacy & Security > Developer Mode (this needs a restart).

Then build and run:

```sh
cd ios
xcodegen                    # generates FluxClone.xcodeproj (not committed)
open FluxClone.xcodeproj
```

In Xcode:

1. Go to the FluxClone target > Signing & Capabilities.
2. Set Team to your Personal Team (your Apple ID).
3. If Xcode says the bundle ID is taken, change it.
4. Pick your iPhone as the run destination and press Run.

The first launch is blocked until you trust the certificate. On the phone, go to Settings >
General > VPN & Device Management > your Apple ID > Trust.

Use a **Release** build for real games: Product > Scheme > Edit Scheme > Run > Build
Configuration > Release. The C++ is optimized in Debug as well, but Swift in Debug is slower and
adds debugger overhead to the touch path.

## Tests

```sh
cd ios
xcodebuild -project FluxClone.xcodeproj -scheme FluxClone \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath /tmp/fluxclone-dd test
```

That runs the recognizer rules (hit target, retrace, adjacency, off-grid, diagonals,
interpolation), the affix classifier, the engine (pinned ruleset, generation timing) and a
UI test that swipes across the board. Keep `-derivedDataPath` outside the repo: this repo
sits in an iCloud-synced folder, and thousands of build files inside it push iCloud into
evicting source files.

Launching with `FLUXCLONE_AUTOPLAY=1` starts a game immediately, and `FLUXCLONE_TRAIN=1`
starts a short training session, which is how the UI test and any screenshot run reach a
board without a tap. On the simulator these go through `SIMCTL_CHILD_`:

```sh
SIMCTL_CHILD_FLUXCLONE_TRAIN=1 xcrun simctl launch booted com.sakshamrustagi.fluxclone
```

## The 7-day re-signing routine

A free provisioning profile expires **7 days** after install, and the app then refuses to launch.
**Your data is not deleted.** It stays in the app container. Re-signing restores it, and
deleting the app destroys it.

Once a week, before the week is up:

1. **Export first.** In the app, tap Data > Export database to Files and save it to iCloud Drive
   or your Mac. If the app has already expired, skip this step. The data is still there, and
   step 3 brings it back.
2. Connect the phone, open `ios/FluxClone.xcodeproj` and press **Run**. Installing over the
   existing app renews the profile for another 7 days and keeps the database.
   - Never delete the app from the phone to "fix" an install. That erases the database.
   - Do not change the bundle ID between installs. A new bundle ID is a new app with an empty
     container.
3. Launch once and check that the game count on the home screen is unchanged.

A calendar reminder every 6 days is the cheapest insurance.

## Data safety

- **Manual export:** tap Data > Export database to Files. This writes a consistent single-file
  snapshot (`VACUUM INTO`) and opens the system "Save to Files" picker.
- **Automatic weekly export:** on launch or return to foreground, if 7 days have passed since
  the last automatic export, a snapshot goes to `Documents/Exports/fluxclone-auto-*.sqlite`.
  The newest 8 are kept. You can see them in the Files app under **On My iPhone > Flux Clone**.
  They live in the same container as the database: they protect against a corrupted database
  or a bad migration, **not** against deleting the app. Copy one off the phone now and then.
- The home screen shows the time since the last export, in red once it passes 7 days.

## What is logged

**`game`**: one row per game.

- The board: letters, grid, tier, and whether each was drawn or overridden. Games with an
  override are flagged, and the report leaves them out by default.
- Ruleset version, config hash, dictionary hash, seeds, realized best-of-N, and the seed word.
- Solved potential (points, words, 5+ words).
- Score, word count, `t_board_shown`, `t_first_submit`, `t_end`, `end_reason`, and
  `interrupted` (the app lost focus mid-game).
- App version, device model, max frame rate, and exact geometry (tile size, grid origin,
  screen).
- The recognizer config the game ran with.

**`attempt`**: one row per finger lift, including empty and too-short lifts, which are flagged
by `reason`.

- `cell_sequence` and `per_cell_entry_timestamps`.
- `t_touch_down`, `t_first_cell` and `t_submit`.
- `result` is valid, invalid or duplicate. `reason` is not_word, too_short or empty.
- `word_id`, `points`, `gap_since_previous_submit`, and `submit_cause` (lift, cancel or
  timeout).
- Per-attempt sampling stats: samples, deliveries, largest step, largest interval.
- Invalid attempts also get `affix`, `stem` and `is_prefix`.
- When a segment-interpolating recognizer fed every coalesced sample would have picked a
  different path, that path is stored in `shadow_cells`, `shadow_letters` and `shadow_valid`.
  This is the direct measure of letters dropped by the lack of interpolation.

**`touch_sample`**: raw `(t, x, y)` for every digitizer sample, in grid-local points, for the
first 30 games only. After that, only the per-attempt stats are kept.

All times are `CACurrentMediaTime` / `UITouch.timestamp` seconds, which are monotonic.
Subtract `t_board_shown` to get game time.

## Recognizer settings

The slider icon on the home screen opens the recognizer settings. The defaults are Flux's:

- circle target, diameter 0.86 × tile
- full cell rect for the first tile
- no interpolation
- one hit test per touch delivery

You can change the target shape and size, the first-tile rule, interpolation (none or segment)
and which samples are hit-tested (per delivery or every coalesced sample). A change applies
from the next game, and each game records its config.

## Training tables (schema 2)

A schema 1 database migrates on first launch: three columns are added to `game`
(`purpose`, `session_id`, `exercise_id`) and the tables below are created. A training board
writes an ordinary `game` and `attempt` row as well, so `tools/clone_report` keeps working;
`game.purpose` is what tells a ranked game from a drill.

- **`session`**: one row per training session. Shape (full or short), the hook drilled, the
  hooks swept, and when the queue was last recomputed.
- **`exercise`**: one row per board or affix grid. The board's letters, grid, tier and word
  count, the lit stem path, the targets, the constrained-generation stats, and whether the
  board was served short of its constraints.
- **`branch_event`**: one row per branch the exercise asked for — found or missed, time to
  find, whether the stem was lit, and which attempt for that hook it was.
- **`presence`**: **one row per solved word on every full board played**, not just the
  drilled hook's branches. Found or not, time of find, the board's density, whether the word
  was reachable off a path already swiped and off which find, and the SPEC 8.1 opportunity
  weight for that board and length class.
- **`judgement`**: one row per affix-grid call — live or dead, the answer, whether it was
  right, and the latency.
- **`hook_state`**: exposures, first and last drill, grids seen, and a due date.
- **`word_belief`**, **`queue_state`**: the recompute's output and its timestamp.

## Report

```sh
build-analytics/venv/bin/python tools/clone_report/clone_report.py ~/Downloads/fluxclone-*.sqlite --out reports/clone_gate.md

# Phase 3's gate: does a hook drilled this week get found unprompted next week?
build-analytics/venv/bin/python tools/train_report/gate.py ~/Downloads/fluxclone-*.sqlite --out reports/phase3_gate.md
```

The report covers:

- the potential-matched score and word comparison against the 9,034 ranked games
- swipe_a and swipe_b
- misswipes by affix pattern
- duplicates
- baseline_gap
- opening latency and first-10 length
- touch sampling, including the interpolation shadow

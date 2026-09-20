# Clone recon: the Flux input layer

Phase 1, step 1. Read-only recon of `github.com/AStout75/flux-ios` at **`40e6ed7`** (2026-09-19),
input layer only. Citations are `file:line` at that commit. Nothing was committed or pushed; the
clone lives in the session scratchpad with push disabled.

The live board is `flux/Board/BoardView.swift` (SwiftUI) with a UIKit touch overlay,
`flux/HighPerformanceTouchHandlerOptimized.swift`. Tiles are drawn by
`flux/OptimizedLetterTile.swift`. `flux/Letter.swift` and its `DragGesture` are dead code
(`Letter.swift:123-124`, "DISABLED: Old gesture system"). `fluxAppClip/` has an older copy and is
not the app you play.

## Two findings that change the build

1. **There is no interpolation.** The recognizer hit-tests only the sampled points. Nothing walks
   the segment between samples (item c).
2. **Coalesced touches were only added today.** Commit `a2f3523` (2026-09-19 01:29 UTC) made
   `touchesMoved` hit-test `event.coalescedTouches(for:)`. Every game in the 9,034-game baseline was
   played on the older recognizer, which tested **one sample per `touchesMoved`**. On a ProMotion
   (120 Hz) phone this makes no difference, because UIKit already delivers about one sample per
   frame. On a 60 Hz phone the old recognizer tested half the digitizer's samples. **So "match
   Flux" depends on your device**, and the clone needs this as a switch (see "Build decisions").

## a) Geometry

**Tile size** (`BoardView.swift:2346-2381`):

```
base      = min(72, (screenWidth - 12) / n)                     // getUniformLetterSize
scaled    = base * universalTileSize
maxSize   = (screenWidth - 40 - spacing*(n-1)) / n              // getMaxLetterSize
tileSize  = min(scaled, maxSize)                                 // getLetterSize
pitch     = tileSize + spacing
```

`tileSize` is the full cell. The visible tile is a rounded rectangle at **0.86 × tileSize** with
corner radius 6, centred in the cell (`OptimizedLetterTile.swift:158-162`,
`Constants.swift:12`). With spacing 0 there is still a 0.14 × tileSize visual gap between tiles,
and it lies inside the hit grid.

Worked values at the defaults on a 393 pt wide phone (iPhone 15 Pro; the 16 Pro is 402 pt, see below):
4x4 has tileSize 72, visual 61.9, grid 288 pt. 5x5 has tileSize 70.6 (capped by `maxSize`),
visual 60.7, grid 353 pt.

**User settings** (`SettingsManager.swift:253-255`, ranges in `SettingsView.swift:157-182`):

| Setting | Default | Range |
| --- | --- | --- |
| `universalTileSize` | 1.0 | 0.6 to 1.6, step 0.1 |
| `tileSpacing` | 0 pt | 0 to 10, step 1 ("0 recommended") |
| `boardVerticalPosition` | 0.5 | 0 to 1, step 0.01; presets Top 0, Center 0.5, Bottom 1 |

**Vertical position** (`BoardView.swift:1906-1933`). Below the HUD, a container holds a 24 pt top
pad, a 64 pt word bubble slot, a 20 pt gap and then the grid. The leftover height
`extra = available - (gridHeight + 64 + 20 + 24) - 24` (the last 24 guards the home-indicator
gesture) is split: `boardVerticalPosition × extra` above and the rest below. The grid is centred
horizontally.

The touch overlay is attached to the padded grid, so it also covers the word bubble slot above
the grid and the left margin (`BoardView.swift:2019-2026`). It does not extend below or to the
right of the grid.

## b) Hit target

There are two different tests:

- **First tile, on touch-down: the full cell rect** (`tileAt`, `HighPerformanceTouchHandlerOptimized.swift:226-260`,
  `frame.contains` at 255). The rect is `tileSize` square (the pitch minus spacing), so it is
  larger than the visible tile.
- **Every later tile, during the move: an inscribed circle of diameter 0.86 × tileSize**, so the
  radius is **0.43 × tileSize** (`tileAtShape`, 264-319; the radius is at 300;
  `Constants.dragHitboxRatio = 0.86`, `Constants.swift:13`). That circle is inscribed in the
  visible tile. At 72 pt the radius is 31.0 pt.

The circle has been 0.43 since at least `25e4eb0` (2025-12-10). On 2026-01-13 it was briefly
changed to 0.94444 and reverted 30 minutes later (`cb68a0a`, `0a66f99`), so the whole baseline
period used 0.43. A diamond shape (`|dx|+|dy| ≤ 0.43·tileSize`) exists, but its settings picker
is commented out (`SettingsView.swift:381`) and the default is circle (`SettingsManager.swift:289`).

The move test first picks the cell by integer division of the point by the pitch, then checks the
circle of **that cell only** (`tileAtShape` 278-305). The circles don't overlap, so this is
equivalent to testing every circle.

What this means for feel: a diagonal swipe through the shared corner of four cells passes
0.707 × pitch (50.9 pt) from every centre, well outside the 31 pt radius, so it never picks up
the orthogonal neighbours. Between two orthogonal neighbours there is a 0.14 × tileSize dead band
(10 pt).

A touch-down that hits no tile (in the gap, the bubble slot or the margin) still starts a drag
(`isDragging = true` at 53). The first circle the finger then enters becomes the first tile,
because the adjacency check is skipped while the path is empty (111).

## c) Interpolation

**None.** `processMove` (89-128) hit-tests the single point it is given. Consecutive samples are
never joined. A finger that crosses a circle between two samples does not select it.

- At `40e6ed7` every coalesced sample is tested (78-85).
- Before `a2f3523`, which covers the whole baseline, only `touch.location(in:)` was tested, once
  per `touchesMoved` delivery.

Once a tile is skipped the damage continues past that tile. The next tile the finger enters is
usually not adjacent to the last one selected, so it is **silently ignored** (adjacency check,
111-120). The recognizer then waits for a tile that is adjacent to the stale last tile. A dropped
letter therefore shows up as a truncated or garbled word, not as a word missing one letter.

How fast is too fast: the chord through a 31 pt circle at perpendicular offset d is
2·√(31² − d²). A sample step s misses a tile whenever that chord is shorter than s. Through the
centre that needs s > 62 pt, which is 7,400 pt/s at 120 Hz or 3,700 pt/s at 60 Hz. For a path
that clips a tile 5 pt inside its edge, s > 24 pt is enough, which is 1,400 pt/s at 60 Hz. So on
a 60 Hz phone before today, drops on clipped corners were plausible at fast swipe speeds.
Section 4.6 of the gate measures this directly.

## d) Path rules against SPEC §2.1

| Rule | Code | Agrees with spec? |
| --- | --- | --- |
| 8-way adjacency | `rowDiff ≤ 1 && colDiff ≤ 1`, not both zero (111-120) | Yes |
| No tile reuse | `selectedLetters.contains` → return (106-108) | Yes |
| Retrace is a no-op and does not undo | the same check. Returning to the previous tile does nothing, and there is no backtrack path anywhere | Yes |
| Non-adjacent tile | ignored, and the path continues from the last selected tile (117-119) | Not in spec; see below |
| Leaving the grid does not cancel | `tileAtShape` returns nil off-grid (274-276), and UIKit keeps delivering moves to the view that got `touchesBegan` | Yes |
| Lift always submits | `touchesEnded` → `handleTouchEnded` → `handleDragEnded` (130-134; `BoardView.swift:2539-2558`) | Yes |
| A system cancel also submits | `touchesCancelled` → `handleTouchCancelled` → `handleDragEnded` (136-140; `BoardView.swift:2560-2563`) | **Not in spec, and the code wins** |
| Minimum length 3 | `count < minWordLength` → `.invalid` (`BoardView.swift:647-649`) | Yes |
| Duplicate | `foundWordSet.contains` → `.validButFound` (`BoardView.swift:652-655`) | Yes |

**Flags:**

1. **A cancelled touch submits.** An incoming call or a system gesture that cancels the touch
   submits the current path. Worth matching.
2. **A lift with fewer than 3 tiles, or with no tiles, is still a "submission".** `handleDragEnded`
   runs on every lift. An empty or 1 to 2 tile path goes down the invalid branch and plays the
   invalid sound (2332-2337). The clone logs these but flags them (`too_short`, `empty`) so they
   don't inflate the misswipe count.
3. **Validity shows live during the swipe.** This is the finding that matters most for behaviour.
   After every tile, `selectLetter` classifies the current prefix as valid-and-new, valid-but-found
   or invalid (`BoardView.swift:630-661`). The tiles are recoloured, the bubble above the board
   shows the word with "(+points)" when it is new, and a new valid prefix fires a medium haptic
   and the `validDrag` sound. You therefore know a word is valid, or already found, **before you
   lift**. Any analysis of misswipes and duplicates has to account for this: a duplicate you
   submit is one you swiped past the "found" styling. The clone must reproduce it or it will
   elicit different behaviour.

## e) Feedback: haptics and sound

Five slots, each with a pattern of none, light, medium, heavy or double. Defaults are from
`SettingsManager.swift:277-285`, the event wiring from `BoardView.swift:2434-2487` and
`2296-2337`, the firing from `triggerHaptic` at 2514-2537.

| Event | Setting | Default | Sound (async, after the haptic) |
| --- | --- | --- | --- |
| First tile of a swipe | Initial Touch | **none** | `press` at 0.8 |
| New tile, prefix is valid **and new** | Drag to Letter (valid) | **medium** | `validDrag` at 1.0 |
| New tile, prefix invalid **or already found** | Drag to Letter (invalid) | **none** | `press` at 0.8 |
| Lift, word valid and new | Release word (valid) | **heavy** | `submit3` … `submit10`, `submit_11`, `submit_12` by length |
| Lift, invalid, duplicate, too short or empty | Release word (invalid) | **none** | `invalidRelease` at 1.0 |

- **Intensity:** every impact is `impactOccurred(intensity: 0.9)` on a `UIImpactFeedbackGenerator`
  of the matching style. "Double" is two medium impacts 80 ms apart. The global
  `hapticIntensity` setting (default medium) is **not** used on the board; only menus use it.
- Generators are created and prepared once in `onAppear` (1555-1558, 2489-2512). They are never
  re-prepared mid-game, because that exhausted the haptic engine's channels (comment at 2515-2521).
- **A duplicate and an invalid word get identical feedback at release.** They differ only in the
  live styling during the drag.
- The sound assets are `flux/Audio/FX/*.wav`. `masterSoundEnabled` defaults to true
  (`SettingsManager.swift:248`) and SFX volume to 0.8.

## f) Rendering

- **Path:** the default style is `snapToCenter` (`SettingsManager.swift:270`). A polyline joins the
  **centres of the selected tiles** (`LetterPath`, `SharedRevealComponents.swift:108-122`, drawn at
  `BoardView.swift:2076-2078`). It does not follow the finger and has no segment to the finger.
  The stroke is **4 pt** (range 1 to 10, step 0.5), with round caps and joins. The colour is the
  theme's `colorfulErrorColor` (`SettingsManager.swift:267`). There are 178 selectable themes, so
  the actual colour depends on which one you use. The optional "Finger Painter" style draws the
  raw finger trail and an 8 pt dot instead.
- **Tile selection:** the selected tile scales to **1.1** with
  `.spring(response: 0.15, dampingFraction: 0.4)`, a quick overshoot (`OptimizedLetterTile.swift:196-197`).
  Deselection snaps back with no animation. Colour changes are unanimated (`transaction.animation = nil`, 192-194).
- **Live tile colours by state** (`BoardView.swift:54-229`; the default scheme is `contrast`,
  `SettingsManager.swift:258`):
  - valid and new: fill `mainColor`
  - valid but found: fill `mainColor` at 0.7 opacity
  - invalid: fill `subColor`
  - unselected: fill `subAltColor`
  - borders on by default: the invalid border is `colorfulErrorColor`
- **Frame timing:** `onLetterSelected` runs synchronously inside `touchesMoved` and mutates the
  `@Observable` board state in place. SwiftUI re-renders in the same run-loop turn's commit. There
  is no deliberate one-frame delay, but the selection pays a SwiftUI diff and the spring animation.
  A clone that updates `CALayer`s directly in `touchesMoved` is at least as fast, and never slower.

## g) Timer and end of game

- **Clock start:** `gameStartDate = Date()` in the board's `onAppear` (`BoardView.swift:1505`).
  The ranked pre-game screen never shows the letters (it builds its preview with `letters: nil`),
  so the clock starts when the board appears. The hit grid is built one run-loop turn later. The
  navigation push animation (about 0.35 s) runs on the clock.
- **Display:** a `TimelineView(.periodic(from: gameStartDate, by: 1.0))` shows `MM:SS` of
  `80 - floor(elapsed)`, so it starts at `01:20` (`BoardView.swift:806-819`, 1647). It is 18 pt
  medium text at 0.8 opacity. In the last 10 seconds the opacity toggles between 0.8 and 0.4 each
  second with a 0.5 s ease (2242-2246).
- **At 0:00:** on the tick where remaining reaches 0, **an in-progress swipe is submitted**, and
  scores if it is valid, before `endGame()` (2247-2252). After that, `isGameOver` blocks further
  input. The end lands on the 1 s timeline tick, so the game lasts 80 s plus the tick latency.
- The score is an `AnimatedCounter` (0.8 s count-up, FiraSans-Bold 68 pt, or 54 pt on screens under
  700 pt tall) above an "N words · MM:SS" row (2891-2931).
- Ranked hides the seed: ranked boards are built with `seedPhrase: ""`
  (`AnimatedRankedMatchPreviewView.swift:684-690`), so seed tiles are not highlighted. The clone
  must not highlight them either.

## h) Validation feedback at release

The selection clears **immediately** on lift (`clearSelectionAtomically`, 2289), before any
feedback.

- **Valid:** a heavy haptic, the length-graded submit sound, the score added, and the word bubble
  "WORD (+pts)" animated upward: offset −25 pt and scale 1.1 with
  `.spring(response: 0.5, dampingFraction: 0.7)`, fade-out starting at 0.3 s over 0.2 s, removed at
  about 0.5 s (`AnimatingWordWithRarityView`, 493-538). Rarity crests are cosmetic.
- **Invalid:** the `invalidRelease` sound only. There is no visual and, by default, no haptic.
- **Duplicate:** exactly like invalid at release (the `else` branch, 2332-2337). Its only visual
  signal comes earlier, as the dimmed "found" styling during the drag.
- None of this blocks input. The next swipe can start on the next frame.

## Build decisions this implies

Recommended defaults; all of them are runtime-configurable in the clone's debug settings.

| Parameter | Default | Why |
| --- | --- | --- |
| Hit test | first tile: full cell rect; later tiles: circle of radius 0.43·tileSize | exact port |
| Interpolation | **off** | Flux has none; "segment" (geometric segment–circle intersection) is available as a diagnostic |
| Hit-test samples | **per delivery**, or all coalesced samples | must match the phone the baseline was played on (question 1) |
| Raw logging | always every coalesced sample | timing data needs all of them, whichever set is hit-tested |
| Geometry | the Flux formulas with your own Flux settings | question 2 |
| Haptics and sound | the defaults above | question 3 |

For diagnosis, every attempt also records the cells that interpolation *would* have added: the
segment–circle crossings between consecutive samples that the recognizer did not register. That
answers gate item 6 directly, without waiting for raw samples.

## Answers and what they fixed (2026-09-19)

- **Device:** iPhone 16 Pro, 120 Hz ProMotion, 402 pt wide. At the defaults both grids get
  72 pt tiles: 4x4 is capped by the 72 pt target and 5x5 by the width. That gives a 61.9 pt
  visual tile and a 31.0 pt hit radius.
- **Settings:** all Flux defaults: tile size 1.0, spacing 0, vertical 0.5, path snap-to-centre
  at 4 pt, contrast scheme, borders on, the aurora theme, and the five haptic slots as above.
  Sound is on.
- **Assets:** the Fira Sans Bold font (under the OFL licence) and the 13 gameplay `.wav` files
  are copied into `ios/FluxClone/Resources/FluxAssets`. The flux-ios clone was only read from.
- **Sampling default:** the clone hit-tests **one sample per `touchesMoved` delivery**, as the
  recognizer did for the whole baseline. Every coalesced sample is still logged. A shadow
  recognizer with segment interpolation over all coalesced samples runs alongside, and each
  attempt records whether it would have chosen a different path. If ProMotion delivers one
  sample per event, as the `a2f3523` commit message claims, the two sample modes are identical
  and the log will show it: samples per delivery will be about 1.0.

The implementation is in `ios/`; `ios/README.md` covers building, re-signing, the log schema
and the report.

## Questions asked before building

1. **Which iPhone did you play the ranked games on?** Specifically, is it ProMotion (a 120 Hz
   Pro model)? If it is, coalescing makes no difference and the clone matches both Flux versions.
   If it is 60 Hz, the baseline was played with per-delivery hit testing, and I will default to
   that.
2. **Your Flux settings:** Tile Size, Tile Spacing, Board Vertical Alignment, Path Width and Style,
   and board colour scheme and theme name. Screenshots of the Board and Visual settings tabs are
   enough. If they aren't at the defaults, the geometry has to use your values.
3. **Your five haptic slots and whether sound is on.** Same screenshots.
4. **Sounds and font:** Fira Sans is OFL, so it can be bundled. For the Flux `.wav` files, I plan a
   build step that copies them from your local flux-ios clone into the app bundle, with no copy
   committed to this repo. Is that acceptable, or do you want synthesized placeholders?

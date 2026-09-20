# Flux Clone: Phase 1 gate report

Source: `fluxclone-20260920-004740.sqlite`. Games counted: **8** (finished, excl. interrupted, excl. grid/tier overrides).
Devices: {'iPhone17,1 @ 120 Hz': 8}. Recognizer configs: 1 (all Flux default).
Grid mix: {4: 5, 5: 3}. Tier mix: {'casual': 2, 'goodCasual': 5, 'spam': 1}.

## Gate: score and words against board potential

| grid | games | mean potential | mean score (95% CI) | mean words (95% CI) |
| --- | --- | --- | --- | --- |
| 4x4 | 5 | 164,940 | 41,560 ± 10,974 | 82.6 ± 16.0 |
| 5x5 | 3 | 487,367 | 52,500 ± 2,927 | 112.3 ± 14.9 |
| all | 8 | 285,850 | 45,662 ± 7,702 | 93.8 ± 15.1 |

Ranked baseline, headline: mean score 51,900, 94.4 words per game over 9,034 games.

Potential-matched: a per-grid OLS of your ranked score and words on board potential (9,034 ranked games) predicts each clone game from its own potential. Mean clone minus prediction: **score 775 ± 6,646**, **words 7.0 ± 10.7** (95% CI).
A clearly negative residual means the clone yields fewer words or points than Flux at the same potential: the recognizer is the first suspect. Ranked potential comes from the export's solutions, which may credit a handful of words the capped Flux dictionary does not (spec 2.1), so a small positive offset in the clone is expected.
- 4x4 baseline: score = 23,510 + 0.0906·potential; words = 66.9 + 0.000071·potential (n=6,811).
- 5x5 baseline: score = 28,376 + 0.0559·potential; words = 78.9 + 0.000044·potential (n=2,223).

## 1. swipe_a and swipe_b

Entry duration = lift time minus the time the first cell was entered, regressed on path length.
| pool | n | swipe_a (s) | swipe_b (s/letter) | R² |
| --- | --- | --- | --- | --- |
| valid words | 750 | -0.085 ± 0.028 | 0.086 ± 0.007 | 0.467 |
| all attempts of 3+ cells | 1236 | -0.041 ± 0.026 | 0.079 ± 0.006 | 0.355 |

SPEC §3.2 placeholder: 0.30 + 0.08n.
| length | n | median (s) | p25 | p75 |
| --- | --- | --- | --- | --- |
| 3 | 239 | 0.163 | 0.138 | 0.196 |
| 4 | 275 | 0.238 | 0.204 | 0.288 |
| 5 | 173 | 0.321 | 0.288 | 0.363 |
| 6 | 53 | 0.404 | 0.338 | 0.504 |
| 7 | 8 | 0.546 | 0.469 | 0.592 |

Median time between consecutive cell entries, valid words: 0.063 s.

## 2. Misswipes (invalid attempts)

- Invalid attempts per game (3+ letters, not a word): **47.75 ± 11.01**
- Seconds lost per game, all-in (gap since previous submit, i.e. decision + swipe): **27.1 ± 6.5 s = 33.9% of the clock**
- Seconds lost per game, swipe only (touch-down to lift): 17.0 ± 4.2 s
SPEC §3.6 claim to test: 12 to 15 per game, 15 to 20 s (15 to 20% of the clock).
- Not counted above (per game): too short 13.50, empty lifts 0.00.

**By affix pattern** (attempt = real stem + affix):
| pattern | count | share | seconds lost (all-in) |
| --- | --- | --- | --- |
| (no affix pattern) | 305 | 79.8% | 175.8 |
| -ER | 19 | 5.0% | 10.3 |
| -S | 17 | 4.5% | 7.8 |
| -ERS | 9 | 2.4% | 5.1 |
| -ES | 9 | 2.4% | 4.5 |
| -AL | 4 | 1.0% | 2.3 |
| RE- | 4 | 1.0% | 2.7 |
| -IER | 3 | 0.8% | 1.4 |
| -ED | 3 | 0.8% | 2.0 |
| -Y | 2 | 0.5% | 1.0 |
| -EST | 2 | 0.5% | 0.7 |
| -EN | 2 | 0.5% | 1.3 |
| -IEST | 1 | 0.3% | 0.7 |
| -IERS | 1 | 0.3% | 0.7 |
| -ISE | 1 | 0.3% | 0.7 |

**By length:** 3: 62, 4: 100, 5: 122, 6: 75, 7: 21, 8: 2

- 139 of 382 (36%) are a prefix of some word (lifted early, or a letter dropped at the end).
- 0 of 382 would have been a **valid word under segment interpolation** (the recognizer, not the player, made these invalid).

**Most repeated invalid strings:**
| attempt | times | affix | stem |
| --- | --- | --- | --- |
| RALL | 5 |  |  |
| SOLT | 3 |  |  |
| NILER | 2 | -ER | NIL |
| CUER | 2 | -ER | CUE |
| CUL | 2 |  |  |
| LINNE | 2 |  |  |
| LEIN | 2 |  |  |
| TUR | 2 |  |  |
| TURE | 2 |  |  |
| REA | 2 |  |  |
| LUCER | 2 | -ER | LUCE |
| LIO | 2 |  |  |
| REL | 2 |  |  |
| RAL | 2 |  |  |
| HOLERS | 2 | -ERS | HOLE |
| NAL | 2 |  |  |
| DAR | 2 |  |  |
| MITS | 2 |  |  |
| ALLARS | 2 |  |  |
| TOSR | 2 |  |  |


## 3. Duplicate re-swipes

- Duplicates per game: **13.00 ± 2.99**
- Seconds lost per game, all-in: **6.3 ± 1.6 s**; swipe only 3.8 s
- By length: 3: 52, 4: 33, 5: 17, 6: 2

## 4. Dead time: gaps between submissions

|  | n | p10 | p25 | **p40 = baseline_gap** | p50 | p75 | p90 | p99 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all gaps | 1344 | 0.275 | 0.333 | 0.392 | 0.425 | 0.558 | 0.725 | 1.259 |
| excluding the opening gap | 1336 | 0.275 | 0.333 | 0.383 | 0.425 | 0.558 | 0.717 | 1.200 |

- 4x4 baseline_gap (p40, excluding opening): 0.383 s
- 5x5 baseline_gap (p40, excluding opening): 0.383 s
- casual baseline_gap: 0.408 s
- goodCasual baseline_gap: 0.383 s
- spam baseline_gap: 0.358 s

## 5. Opening latency

- Board shown to first submission: median 1.22 s, mean 1.25 s
- Board shown to first valid word: median 1.42 s
- Mean length of the k-th valid word: #1: 4.00, #2: 3.88, #3: 4.38, #4: 3.88, #5: 4.38
- **First-10 mean length: 3.94** (ranked: 3.93). If these differ materially, the clone is not eliciting your real opening.

## 6. Touch sampling

- Samples per touchesMoved delivery (all games): median 1.97, mean 1.99. Above 1 means coalesced samples exist that per-delivery hit testing (the ranked baseline's recognizer) never sees.
- Raw samples (1344 swipes with raw data): digitizer interval median 4.17 ms (**240 Hz**), delivery interval median 8.33 ms (120 Hz). p99 digitizer interval 8.3 ms.
- Attempts with a sample step longer than the hit-circle diameter (0.86·tile): 0 of 1344 (0.00%).
- Attempts where a segment-interpolating recognizer on every coalesced sample would have selected a different path: **1 of 1344 (0.07%)**.
| actual result | interpolated path | count |
| --- | --- | --- |
| invalid | not valid | 1 |

| actual | interpolated |
| --- | --- |
| TAFES | TAFEES |


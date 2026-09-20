# FluxCore Phase 1 — report

**Written for:** the person deciding whether Phases 3 and 4 get built as specified.

> **Part A is the current report.** Phase 1 was rerun on 2026-09-18 under **ruleset v3**, the
> generator as the Flux client implements it (SPEC §2.3, read from flux-ios), with the Flux
> dictionary. Part B is the original report under ruleset v1, kept for comparison, with its dead
> findings marked **RETRACTED** where they appear. Where the two disagree, Part A wins.

---

# Part A — Rerun under ruleset v3

## A0. What changed, and what it did

| | ruleset v1 (Part B) | ruleset v3 (Part A) | source |
| --- | --- | --- | --- |
| Letter table | CSW21 word-list letter frequency (E 11.3%, T 6.5%) | client `letterFrequencies`, running-text English (E 12.02, T 9.10, A 8.12 … Z 0.07) | SPEC §2.3, flux-ios@fa8fb2d |
| Letter cap | none (a triple on 80% of 4x4, 99.9% of 5x5 boards) | **at most 2 of any letter**, applied while filling, random fill order; seeds over the cap never drawn | all 9,034 real boards |
| Seed | drawn per candidate | **drawn once per board, before best-of-N**, shared by all N candidates, laid by the client's random walk | SinglePlayerHomeView → BoggleGenerator |
| Best-of-N count | N uniform over [144, 625] | quality q uniform over [12, 25], **N = floor(q²)** (provisional reading of the published squares) | BoggleGenerator.generateBoard |
| Dictionary | CSW21, 279,496 words | CSW21 − 419 Flux removals = 279,077, then − 55,584 words needing 3+ of one letter = **223,493** | SPEC §2.1 |

`config/ruleset_v3.json` (config hash `0xaa2566169b8b50d9`), pinned to DAWG source hash
`0xfa4bad1daff9c8d6`. v1 is untouched: its file hash is unchanged (`0x22448ec0ab243759`) and its
outputs reproduce byte for byte from the new code (checked on simulate and measure).

**The dictionary.** Pruning to the cap removes **55,584 words, 19.9% of CSW21**, far more than the
419 removals. It is almost entirely long words: 0.1% of 3-letter words, 1% of 5s, 6% of 7s, 30%
of 11s, 50% of 13s. It is lossless: a v3 simulation against the pruned DAWG and against the
unpruned 279,077-word DAWG is **byte-identical** in board norms, and not one of the 100,951 distinct
solution words on the real boards, nor one of the 35,560 distinct words either player found, has
a letter three times. New DAWG: 67,627 states, 164,814 edges, **1.14 MB** (was 79,807 / 191,740 /
1.34 MB).

**The dictionary is now enforced.** A v3 ruleset names its DAWG; every tool (simulate, measure,
genprobe, genboards, solve_boards, bench, genbench) hard-errors on any other. v1/v2 pin nothing and
the tools say so on every run.

**Where the potential drop comes from.** Board potential fell 6–19% (A5). Decomposed at 20,000
boards per cell: removing the 419 words moves simulated potential by 0.2% or less; pruning the
over-cap words moves it by exactly zero; **the generator corrections account for all of the rest.**
The 419 were not inflating simulated potentials to any degree that matters (on the real boards they
move mean potential 237.9k → 237.6k). They matter for word lists, not for norms.

## A1. The gate

Spec §15: if reachability implies **about 2 extra words a game rather than 10 or more**, the
family curriculum is the wrong product.

**It is still not 2. Under the corrected generator the gate quantity falls by 6–15%, not "a lot",
and it is nowhere near the kill line. But the old figure it was passed on was not the right number
for two reasons unrelated to the regime change, and both have to be stated.**

1. **The old headline (5.5 extensions per found stem) was a sampling artifact.** M1's stems were
   the first ~500 words of each length in dictionary order: an early-alphabet set (the 4-letter
   slice ends in the B's) that happens to be unusually extensible. Measured over **every** stem,
   the same v1 boards give **2.52**, not 5.5. Under v3 the alphabetical sample gives 4.48 (−19%) and
   all stems give **2.20 (−13%)**. Part A uses all stems (`--m1-sample all`).
2. **Extensions per stem is a per-stem availability number; the gate is about words per game.**
   Part B compared the one against the other. The rerun computes the gate quantity directly: for a
   player who finds F of a board's n findable words, the expected number of free words collected —
   words that are reachable extensions of a found word's path, and were not themselves found.
   Under a uniformly random found set this is exact:
   P(w collected) = C(n−1, F)/C(n, F) − C(n−1−k, F)/C(n, F), k = findable stems reaching w.
   F = 100 (spec §3.1; the real export averages 91 words found on 4x4 and 102 on 5x5 in seasons
   7–10).

| cell | ext/found stem, v1 → **v3** | free words on board | free fraction of findable | **extra words a game at F = 100**, v1 → v3 |
| --- | --- | --- | --- | --- |
| 4x4 Casual | 2.05 → **1.87** | 203 → 197 | 71.0% → 68.4% | 76.7 → **72.3** |
| 4x4 Good Casual | 2.27 → **2.05** | 257 → 240 | 74.0% → 71.1% | 97.6 → **88.3** |
| 4x4 Spam | 2.78 → **2.50** | 402 → 363 | 79.2% → 76.5% | 143.3 → **127.5** |
| 5x5 Casual | 2.33 → **1.98** | 384 → 345 | 73.9% → 69.3% | 122.6 → **106.4** |
| 5x5 Good Casual | 2.69 → **2.26** | 525 → 459 | 77.8% → 73.1% | 155.4 → **132.1** |
| 5x5 Spam | 3.00 → **2.51** | 665 → 576 | 80.5% → 75.9% | 181.8 → **154.2** |

(`runs/v1-gate`, `runs/v3-gate`, 5,000 boards per cell, all stems. Part B's own v1 column, from
the alphabetical sample, read 4.04–6.95 extensions per stem and 108–375 free words per board.)

**Verdict: the thesis survives the correction, but on weaker ground than Part B claimed.** The
corrected availability is 72–154 free words a game, an order of magnitude above the kill line and
6–15% below v1. The direction and size of the move are what the cap predicts for -S and -ES and
the opposite of what it predicts for -D and -T (A2): the cap took away third and fourth S's and
E's, and the running-text table put back T, D and H.

What this number is **not**: realized play. It assumes the player knows every free word and has
time to swipe it, which is exactly what Phases 3 and 4 would train, and it assumes a uniformly
random found set, which undercounts (real players find the short stems more readily than the long
extensions, raising both terms). The gate cannot be closed by simulation alone; it needs P(know)
from Phase 2 play. What the simulation settles is that the failure mode the gate guards against — a
board structure that offers only ~2 free words — is not the structure Flux boards have. **No
redesign of the family curriculum is implied by this rerun.**

## A2. M1 — reachability by affix

P(extension has a path extending the stem's path | stem path present), 4x4 Good Casual. The change
column is like for like: v1 and v3 both over all stems, same boards per cell, same seed.

| affix | Part B (v1, alphabetical sample) | v1, all stems | **v3, all stems** | regime change |
| --- | --- | --- | --- | --- |
| `-E` | 0.526 | 0.518 | **0.466** | −10% |
| `R-` | 0.419 | 0.399 | **0.374** | −6% |
| `-S` | 0.490 | 0.439 | **0.372** | **−15%** |
| `S-` | 0.463 | 0.440 | **0.367** | −16% |
| `-T` | 0.347 | 0.324 | **0.362** | +12% |
| `T-` | 0.352 | 0.329 | **0.360** | +9% |
| `-D` | 0.187 | 0.176 | **0.223** | +27% |
| `D-` | 0.178 | 0.165 | **0.205** | +24% |
| `-ES` | 0.281 | 0.253 | **0.195** | **−23%** |
| `C-` | 0.162 | 0.153 | **0.147** | −4% |
| `-ED` | 0.115 | 0.094 | **0.107** | +14% |
| `-ING` | 0.028 | 0.024 | **0.021** | −12% |

The expectation that reachability would fall a lot is half right. The S and E affixes fell, -ES
hardest (−23%), -S and S- by about 15%, as the cap predicts: an additive -S needs an S next to the
stem's last cell, and uncapped boards routinely carried three or four. But the affixes built on T
and D *rose* 9–27%, because the client table has far more T (9.1% against 6.5%), D and H than the
CSW21 placeholder. The two effects largely cancel in aggregate, which is why the gate moved only
6–15%. **The design consequence changes:** -S no longer stands out as the second affix; -E, R-,
-S, S-, -T and T- sit together at 0.36–0.47, and -D/D- now beat -ES. "Order the grid by measured
reachability" still holds; the order moved. -ING stays near worthless.

## A3. M2 — cellmate pathability

P(anagram has a valid path | word has one), 4x4 Good Casual.

| length | v1 | **v3** | change | | length | v1 | **v3** | change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | 0.808 | **0.784** | −3% | | 7 | 0.176 | **0.135** | −23% |
| 4 | 0.600 | **0.547** | −9% | | 8 | 0.117 | **0.084** | −28% |
| 5 | 0.414 | **0.356** | −14% | | 9 | 0.107 | **0.057** | −47% |
| 6 | 0.281 | **0.223** | −21% | | 10 | 0.107 | **0.039** | −63% |

Down at every length, more at every added letter, as expected: an anagram of a long word needs the
same repeated letters in a different arrangement, and the cap removed the spare copies. **The
conclusion is unchanged and stronger:** only 3s and 4s clear §7.6's 0.5 threshold; 5-letter
anagrams, the first length worth real points, now land 36% of the time.

Drop-terminal against drop-interior over the dictionary: **1,269,705 against 56,017, 23 to 1**
(was 1,731,818 against 62,667, 28 to 1). The guaranteed relation still dominates.

## A4. M3 — stem enumerability, re-derived

E[other family members findable | stem present], stem itself excluded, range across the six cells,
30,000 boards per cell (`runs/v3-m3-curated`):

| stem length | broad | curated | curatedTight | curatedWord |
| --- | --- | --- | --- | --- |
| 2 | 12.14–20.09 (was 17.10–36.93) | 15.12–26.96 | 15.33–27.17 | 23.17–41.85 |
| **3** | **1.91–3.25** (was 2.83–5.63) | **4.02–6.78** (was 4.46–8.93) | 6.10–10.78 (was 6.65–13.76) | **4.58–7.50** (was 5.26–10.29) |
| **4** | 0.66–1.09 (was 0.82–1.50) | **1.68–2.95** (was 1.85–3.70) | **2.27–4.21** (was 2.44–5.11) | **1.80–2.88** (was 2.03–3.68) |
| 5 | 0.33–0.54 | 0.82–1.46 | 1.10–2.07 | 0.93–1.47 |
| 6 | 0.19–0.30 | 0.48–0.86 | 0.61–1.17 | 0.65–1.00 |
| 7 | 0.18–0.27 | 0.35–0.65 | 0.44–0.88 | 0.53–0.75 |

Re-derived from these numbers, not adjusted from Part B's:

- **3-letter stems are in the band, and curated ones now straddle its top edge.** Broad 3-letter
  stems fall into the band in five cells and just under it in one (4x4 Casual, 1.91). Curated word
  stems run 4.58–7.50: over 6 on both Spam cells and 5x5 Good Casual. `curatedTight` is over the top
  edge in every cell, as before.
- **4-letter stems are in, with less margin.** `curatedTight` clears 2 in every cell (min 2.27).
  `curatedWord` — the pedagogically natural population — clears 2 in five cells of six; it misses in
  **4x4 Casual (1.80)**, the most common board in ranked (0.6 × 0.3 of all boards).
- **5-letter stems remain Spam-only material.** Only 5x5 Spam under `curatedTight` clears 2 (2.07).
- **6 and 7 remain dead.**

**The band is 3 to 4 letters, as Part B found — but 4-letter word stems now sit on the band's
lower edge on Casual 4x4 boards, and 3-letter curated stems on its upper edge on Spam.** §7.5's
cutoff should stay at 3–4, and the curriculum should expect 4-letter word stems to be a thin cue on
the weakest boards.

Secondary findings: curation depth is still a gradient (`curatedTight` > `curated` at every length
≥ 3 in every cell). "Word-stems beat fragment-stems at every length ≥ 4" was already one cell
short of true in v1; under v3 it fails in two cells, both 4-letter on 5x5, both effectively ties
(2.47 vs 2.48, 2.88 vs 2.95). Read it as "word-stems are as good as fragment-stems", not better.

Section 4's broad table (stem counted), v1 → v3: 3-letter 3.13 → 2.14 (4x4 Casual), 3.82 → 2.49
(Good Casual), 5.70 → 3.50 (4x4 Spam), 5.97 → 3.42 (5x5 Spam); 4-letter 0.99 → 0.84, 1.19 → 0.94,
1.65 → 1.29, 1.65 → 1.28; 5-letter 0.42 → 0.42, 0.49 → 0.48, 0.69 → 0.63, 0.74 → 0.64; 2-letter
17.12 → 12.15, 20.56 → 14.12, 29.84 → 20.23, 36.88 → 20.12. The full grid is in
`reports/phase1_rerun_tables.md`.

**The N-quartile split still finds little.** 4x4 Spam, 5-letter broad stems, stem counted:
0.68 / 0.68 / 0.71 / 0.69 → **0.58 / 0.64 / 0.64 / 0.66**; `curatedTight` ex-stem 1.78–1.90 →
1.55–1.66 across the quartiles. A mild gradient, not a cue that switches on and off with N.
Quartiles are now equal in probability under the quality draw (Part B's split was equal in N, which
coincided under uniform N).

## A5. The full simulation

`runs/v3-full`: 5.2M boards, same cell sizes and root seed (20260917) as Part B, 1,228 s on 14
threads.

| cell | total points, mean [p10–p90] | words | 5+ words | seeded | mean N |
| --- | --- | --- | --- | --- | --- |
| 4x4 Casual | 194,148 [116,900–285,400] → **181,496** [101,300–278,700] | 287 → **287** | 129 → **120** | 68.3% → **50.1%** | 5.0 → **5.0** |
| 4x4 Good Casual | 252,258 [174,600–342,500] → **227,579** [144,200–328,000] | 348 → **338** | 171 → **153** | 74.6% → **50.0%** | 15.0 → **14.2** |
| 4x4 Spam | 423,476 [347,700–509,400] → **364,889** [274,100–473,900] | 508 → **473** | 288 → **249** | 86.5% → **50.0%** | 384.6 → **355.9** |
| 5x5 Casual | 394,397 [233,600–582,600] → **338,067** [194,200–506,900] | 517 → **498** | 261 → **222** | 62.6% → **50.0%** | 3.0 → **3.0** |
| 5x5 Good Casual | 569,607 [414,300–748,300] → **467,699** [320,700–639,800] | 675 → **628** | 379 → **311** | 72.8% → **50.1%** | 15.0 → **14.2** |
| 5x5 Spam | 754,387 [611,200–921,000] → **611,933** [463,500–789,800] | 827 → **759** | 499 → **409** | 80.7% → **50.0%** | 81.0 → **81.0** |

- **Potential is down 6% (4x4 Casual) to 19% (5x5 Spam)**, words down 0–8%, 5+ words down 7–18%.
  The loss is concentrated where Part B's boards were richest: long words on dense Spam boards,
  which is where the cap bites and where the pruned words lived.
- **Seeded boards: 50.0% in every cell**, by construction of the per-board seed. See the
  retraction in A7.
- **Mean N under the quality draw: 355.9** for 4x4 Spam (the analytic value is 355.8), not 384.5;
  58.6% of Spam boards draw N ≤ 384. Good Casual's mean is 14.2, since floor(q²) on
  [√10, √20] almost never reaches 20.
- **Spam is still a spread.** 4x4 Spam by quartile of realized N: 340,585 (N 144–232),
  359,038 (232–342), 373,866 (342–473), 386,123 (473–624), a 13.4% spread with shrinking
  increments (18k, 15k, 12k). Part B: 394,693 → 446,239, also 13%. See A8 on what this is evidence
  of.
- **Retention at 1e-5**: 212,004 distinct words, **94.9% of the v3 dictionary** (Part B: 221,430,
  79% of CSW21). The threshold filters even less than before; §5.3's "set worth showing a human"
  still needs a different cut.
- **Reproducibility**: byte-identical `word_stats`, `board_norms` and `board_norms_by_n` at 14 and 6
  threads (`runs/v3-verify14`, `runs/v3-verify6`, 20,000 boards per cell; the full 5.2M run was
  not repeated).

## A6. Validation against the real boards

The bar from the client-code session: letter-frequency TVD 0.010 (4x4) and 0.014 (5x5) against
the real boards; letters appearing twice per board 4.56 and 9.37, distinct letters 11.44 and 15.63.
Simulated boards from `genboards` (20,000 per cell, reweighted to the 20/50/30 tier mix); real
potentials from `solve_boards` under the same ruleset and dictionary
(`runs/v3-validate/validation_v3.json`, `tools/analytics/validate_generator.py`).

| | 4x4 real | 4x4 **v3** | 4x4 v1 | 5x5 real | 5x5 **v3** | 5x5 v1 |
| --- | --- | --- | --- | --- | --- | --- |
| letter TVD, all seasons | — | **0.0098** | 0.0868 | — | **0.0146** | 0.1477 |
| letter TVD, seasons 7–10 (noise95) | — | 0.0126 (0.0101) | 0.0930 | — | 0.0107 (0.0084) | 0.1459 |
| letters doubled per board (S7–10) | 4.56 | 4.65 | 2.90 | 9.37 | 9.51 | 3.64 |
| distinct letters per board (S7–10) | 11.44 | 11.35 | 10.50 | 15.63 | 15.49 | 13.00 |
| boards with a letter 3+ times | 0% | 0% | 80.3% | 0% | 0% | 99.95% |

**The letters clear the bar.** v3 matches the real marginal at 0.0098 and 0.0146, against 0.087 and
0.148 for Part B's generator. In seasons 7–10 the TVD sits slightly above a same-size noise floor
on both grids, and the simulation doubles slightly more letters than the real boards (4.65 vs 4.56,
9.51 vs 9.37). Both are what a letter-variety setting above 0.5 on some tiers would produce, and
variety per tier is server data (SPEC §2.4). Nothing here says the pipeline is wrong.

**Potential, seasons 7–10 only** (4x4 n = 1,787, 5x5 n = 1,078; real 95% bootstrap interval in
brackets):

| quantile | 4x4 real | 4x4 **v3** | 5x5 real | 5x5 **v3** |
| --- | --- | --- | --- | --- |
| p10 | 136,860 [131,936–140,200] | **128,800** below | 300,040 [291,840–308,712] | **261,900** below |
| p25 | 169,900 [166,500–173,950] | 166,300 | 358,400 [350,200–365,725] | 342,200 below |
| p50 | 223,900 [218,300–229,300] | **223,600** | 440,400 [429,796–453,605] | **444,900** |
| p75 | 288,850 [282,600–297,400] | 303,400 above | 535,800 [523,725–552,402] | 555,200 above |
| p90 | 361,940 [348,460–373,420] | 379,000 above | 647,600 [631,000–667,200] | 666,700 |
| mean | 237,603 | 241,243 | 461,146 | 457,034 |

**The centre matches and the spread does not.** Medians and means agree on both grids (Part B's
generator's medians were 9% high on 4x4 and 24% high on 5x5). But the simulated distribution is too wide: its weak boards
are too weak and its strong boards too strong, most visibly on 5x5 where the simulated p10 is 38k
below the real interval. With the letters confirmed, that is the tier mix or the candidate counts —
too many near-random Casual boards (5x5 Casual is best-of-3) and too long a Spam tail — and those
are server-side settings the client does not show. **They were not tuned to fit.** Until the
`boardConfigPool` is known, per-tier statistics carry this error; pooled statistics near the centre
of the distribution are sound.

## A7. Retractions

**RETRACTED — "63–87% of winning boards carry a seed, rising to 86.5% at Spam"** (Part B §5, §8).
Produced by drawing a seed per candidate: with N independent seed draws, best-of-N selects seeded
candidates. The client draws one seed per board before best-of-N, so the seeded share of winners is
the base rate, **50% at every tier** (v3: 50.0–50.1% in all six cells). The accompanying
interpretation — "the seed table … is most of what makes the tier" — is retracted with it. The
spec §5.3 sentence that invited this reading has been rewritten.

**RETRACTED as evidence — "Mean realized N is 384.6 against the 384.5 a uniform draw predicts"**
(Part B §5). This checked the simulator's RNG against the simulator's own assumption. It said
nothing about Flux and never could. The number itself was also based on the wrong draw: under
N = floor(q²) the mean is 355.9.

## A8. Self-confirmation audit

Every place in Part B where a simulated output was checked against the assumption that produced
it, whether or not the number came out right:

1. **Seeded-winner overrepresentation** — retracted (A7). It confirmed the per-candidate seed
   assumption, then presented the confirmation as a finding.
2. **Mean N 384.6 against 384.5** — retracted (A7).
3. **"Tier ordering holds on every metric" (listed under Supported).** Best-of-larger-N over the
   same candidate distribution dominates best-of-smaller-N by construction; the ordering could not
   have failed. It is a check that the simulator implements its tier table, not evidence about
   Flux's tiers. Still true in v3, still not a finding. The real export has no tier labels, so
   nothing external checks it.
4. **"Spam is a spread, and N moves it" (Supported).** The direction is by construction (more
   candidates, higher maximum). Only the size of the spread is informative, and it is conditional
   on the assumed N range, which is unconfirmed. v3 changed the draw and the spread stayed at 13%;
   that is a property of best-of-N, not a measurement of Flux.
5. **§11.1 "constrained Spam is infeasible" (0.6% in band, 96% exhaust).** The norm band is the
   p10–p90 of the same simulator's unconstrained boards, so the probe measures the generator
   against itself. As a cost number for this generator it is legitimate; as a statement about real
   Spam boards it inherits the unconfirmed tier table, and A6 shows the simulated spread is wider
   than the real one. Rerun: 4x4 Spam 1.0% accepted, **75% of boards exhaust** the budget (v1
   rerun on today's code: 0.4% / 97.5%; 5x5 Spam 1.9% / 0%, was 1.4% / 7.5%). The conclusion —
   the fallback ladder is not an edge case for Spam — stands.
6. **The inverse-fitted distribution (`ruleset_v2.json`, analytics session, not this report).** It
   was fitted to the observed marginal and then shown to reproduce the observed marginal. The fit
   absorbed a missing mechanism (the cap) into implausible weights (E 3.5%, H 8.1%). Superseded
   by v3, whose letter table comes from code and was checked against the boards afterwards — the
   only non-circular order.

Not self-confirming, but found in the same audit:

7. **The M1 stem sample was alphabetical** (A1). The 5.5 headline came from it; over all stems the
   same boards give 2.52.
8. **The gate compared a per-stem availability number with a per-game threshold** (A1).
9. **Transcription error:** Part B's §5 table gives 5x5 Good Casual mean N as 81.0; the run
   recorded 15.0 (`runs/full/board_norms.tsv`). Corrected in place.
10. **Mixed sources in §4.1:** its N-quartile series (0.68 / 0.68 / 0.71 / 0.69) is from
    `runs/m-full`, broad sample, stem counted, while the rest of §4.1 is `runs/m3-curated`, ex-stem.
11. **The seeded generator tests did not run under ctest** (they needed a word list on the command
    line). They now run when `FLUX_WORDLIST` is set, as do the full-dictionary halves of the other
    four suites.

Checked and legitimate: byte-identical reproducibility (an engineering property, tested as one);
the LetterCounter oracle agreement (an independent implementation, and about the solver, not the
generator); the unit tests that assert the generator implements its config (that is their job).

## A9. What survives, what moved, what is gone

**Survives unchanged**
- Only 3- and 4-letter anagrams clear §7.6's 0.5 threshold; the cellmate curriculum above 4 letters
  does not survive its own rule. Drop-terminal dominates drop-interior (23 : 1).
- The usable stem band is 3 to 4 letters, with 5 as Spam-only material; 6 and 7 are dead.
- Curation depth is a gradient.
- Enumerability is insensitive to the N draw.
- Solver and generation performance comfortably inside target.
- The 1e-5 retention threshold does not filter.

**Moved**
- Gate: 72–154 free words a game at F = 100 (v1: 77–182), measured directly for the first time;
  extensions per found stem 1.87–2.51 over all stems. Still an order of magnitude above the kill
  line.
- Affix ordering, like for like: -S −15%, S- −16%, -ES −23%; -D/D- +24–27%, -T/T- +9–12%; -S no
  longer stands out.
- Anagram pathability down 3% (3s) to 63% (10s).
- 4-letter word stems now miss the band on 4x4 Casual (1.80); 3-letter curated word stems overshoot
  it on Spam.
- Board potential down 6–19%, 5+ words down 7–18%; the simulated centre now matches real boards,
  the spread does not.
- Mean N 355.9 under the quality draw.

**Gone**
- Seeded-board overrepresentation, and "the seed table is most of what makes Spam".
- The N-mean check as evidence of anything.
- "Tier ordering" and "Spam is a spread" as evidence about Flux (they remain properties of the
  model).
- "5.5 reachable extensions per found stem".
- "The letter distribution is the thing everything is provisional on" — it is confirmed; what is
  provisional now is the tier table, the candidate counts and letter variety per tier.

## A10. Benchmarks, v3

Solve time on generated boards, single-threaded, release, p50 / p95 µs, today's machine
(`runs/v3-bench.txt`; `runs/v1-bench.txt` is v1 on the same machine, same day):

| cell | Count mode | Full mode | words | v1 Count p50, same day |
| --- | --- | --- | --- | --- |
| 4x4 Casual | 55.8 / 78.7 | 59.2 / 84.1 | 284 | 63.0 |
| 4x4 Good Casual | 63.8 / 90.0 | 68.4 / 98.1 | 338 | 72.6 |
| 4x4 Spam | 81.2 / 104.4 | 88.5 / 114.0 | 472 | 96.9 |
| 5x5 Casual | 100.7 / 136.3 | 108.3 / 150.0 | 503 | 128.0 |
| 5x5 Good Casual | 118.9 / 154.4 | 127.6 / 165.1 | 623 | 153.5 |
| 5x5 Spam | 140.9 / 182.0 | 152.7 / 196.7 | 761 | 182.0 |

Generation cost per final board, single-threaded, tier-weighted: **3.9 ms (4x4), 2.3 ms (5x5),
3.3 ms grid-weighted** (v1 measured the same way today: 4.7 / 2.8 / 4.0 ms; Part B's 5.3 / 3.6 /
4.6 ms came from a different measurement). Simulator scaling, 4x4 Spam: 58 / 116 / 232 / 411 / 652
boards/s at 1 / 2 / 4 / 8 / 14 threads (efficiency 100 / 100 / 100 / 89 / 80%).

Test suite: **1,785,963 checks across six suites** with the word list (test_dawg 853,551,
test_solver 550,819, test_generator 380,304, test_oracle 1,159, test_affix 61, test_ruleset 69),
including new tests for the letter table, the cap (every tier, seeded and not, plus a dominant-letter
config where the cap must bind at exactly 2 and land anywhere on the board), the per-board seed
(shared across candidates, independent of N, 51% of best-of-60 winners against 85% under the old
per-candidate draw), the quality draw (mean 355.98, equal-probability quartiles) and the dictionary
pin.

## A11. Reproducing

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DFLUX_WORDLIST=<bogwords.txt>
cmake --build build -j 14 && ctest --test-dir build --output-on-failure

./build/tools/build_dawg/build_dawg <bogwords.txt> data/dict/flux_capped.dawg \
    --exclude data/flux_removed_words.txt --max-letter-repeat 2
./build/tools/simulate/simulate --config config/ruleset_v3.json --dawg data/dict/flux_capped.dawg \
    --out runs/v3-full --boards-per-cell 1000000 --boards 4x4:spam=200000 --threads 14 --seed 20260917
./build/tools/measure/measure --config config/ruleset_v3.json --dawg data/dict/flux_capped.dawg \
    --out runs/v3-gate --boards-per-cell 5000 --m1-sample all --threads 14 --seed 20260917
./build/tools/measure/measure --config config/ruleset_v3.json --dawg data/dict/flux_capped.dawg \
    --out runs/v3-m3-curated --boards-per-cell 30000 --stems 3000 --curated-per-len 2000 \
    --curated-tight 500 --threads 14 --seed 20260917
python tools/analytics/compare_phase1.py > reports/phase1_rerun_tables.md
```

Every step is in `runs/v3-batch.sh`. **These runs were made on an uncommitted tree** (manifests say
`gitDirty: true`); the exact source is `runs/v3-tree/` (base SHA, tracked-file patch, untracked
sources), so they are reproducible from that snapshot but not from a SHA alone until the code is
committed.

---

# Part B — Original Phase 1 report (ruleset v1), superseded by Part A

All numbers are **provisional on the letter distribution**, which is a placeholder (spec §2.4 item 1).
If Flux turns out to use Boggle-style dice, the distribution changes materially and everything here
has to be recomputed. Every artifact records its config hash (`22448ec0ab243759`) and dictionary hash
so a stale number is detectable rather than silently wrong.

Dictionary: CSW21, 279,496 words, recovered from the LetterCounter repo. Three runs back these
numbers, each with its own manifest:

| run | what | size |
| --- | --- | --- |
| `runs/m-full` | M1 / M2 / M3, broad stem sample | 5,000 boards per cell × 6 cells, 18s |
| `runs/m3-curated` | M3 remeasured under curation (§4.1) | 30,000 boards per cell × 6 cells, 710s |
| `runs/full` | the full simulation — `word_stats`, `board_norms` (§5) | 5.2M boards, 1,859s |

---

## 1. The gate: does the family curriculum survive?

Spec §15 sets the kill condition plainly: if the reachability number implies **2 extra words a game
rather than 10 or more**, the family curriculum is the wrong product and Phases 3 and 4 should be
redesigned before they are built.

**It is not 2. The thesis survives, decisively.**

> **Superseded by A1.** The 5.5 below came from an alphabetical stem sample (all stems: 2.52 on these
> same boards), and it is a per-stem availability number compared against a per-game threshold. The
> gate measured directly, under v3, is 72–154 free words a game: still not 2.

| cell | reachable extensions per found stem | distinct free words per board | findable words that are free |
| --- | --- | --- | --- |
| 4x4 Casual | 4.04 | 108 | 37.8% |
| 4x4 Good Casual | 4.76 | 142 | 40.8% |
| 4x4 Spam | 6.56 | 235 | 46.3% |
| 5x5 Casual | 4.69 | 205 | 39.5% |
| 5x5 Good Casual | 5.90 | 290 | 43.0% |
| 5x5 Spam | 6.95 | 375 | 45.4% |

A word you have found has on average **5.5 additive extensions that are also present and reachable**
on the same board. Between 38% and 46% of everything findable on a board is reachable as an additive
extension of something else findable there.

**The honest caveat:** this measures *availability*, not realized play. It assumes perfect vocabulary
and unlimited time. The real number is availability × P(you know the word) × P(you have time), and
the last two are what Phases 3 and 4 exist to improve. But the ceiling is ~100–375 free words per
board, not 2, so the gate is not close.

---

## 2. M1 — Reachability, by affix

`P(extension has a valid path that extends the stem's path | stem path present)`, 4x4 Good Casual.
Affixes are the **mined** alphabet (§7.3), not a hand-written list, so this is not conditioned on a
guess about which affixes matter.

| affix | P(reachable) | affix | P(reachable) |
| --- | --- | --- | --- |
| `-E` | 0.526 | `-T` | 0.347 |
| `-S` | 0.490 | `-ES` | 0.281 |
| `S-` | 0.463 | `-D` | 0.187 |
| `R-` | 0.419 | `D-` | 0.178 |
| `T-` | 0.352 | `C-` | 0.162 |
| | | `-ED` | 0.115 |
| | | `-ING` | 0.028 |

The shape is physical rather than linguistic: a one-cell extension needs one adjacent free cell
carrying the right letter, so the probability tracks **letter frequency and affix length**, not
morphology. `-S` at 0.49 and `-ING` at 0.028 differ by a factor of 17 purely because `-ING` needs
three specific adjacent cells.

**Design consequence:** an affix grid should be ordered by measured reachability, not by
morphological tidiness. Teaching `-ING` as a free-points item is close to worthless; teaching `-S`
pays about half the time.

Two conditionings are reported in `reachability.tsv` because the spec does not disambiguate them:
per-stem-path (your finger is on *that* path) and per-board (some path of the stem admits it). They
differ by roughly 10% relative, per-board being the upper bound.

---

## 3. M2 — Cellmate pathability

`P(anagram has a valid path | word has a valid path)`, by length, 4x4 Good Casual.

| length | P | length | P |
| --- | --- | --- | --- |
| 3 | 0.808 | 7 | 0.176 |
| 4 | 0.600 | 8 | 0.117 |
| 5 | 0.414 | 9 | 0.107 |
| 6 | 0.281 | 10 | 0.107 |

**This contradicts the spec.** §7.6 expects the rate to be "high for 5s and to fall off for 7+", and
sets a teaching threshold of about 0.5. Measured, **5-letter anagrams are 0.414 — already below the
threshold**. Only 3s and 4s clear 0.5, and those are the lengths worth the least in points.

The practical reading: the anagram cellmate mechanic is weak exactly where it would pay. A 7-letter
anagram pair is worth 1,800 points and lands 18% of the time. §7.6's "only pairs above about 0.5 are
worth teaching" rule, applied to this data, deletes nearly the whole cellmate curriculum above
4 letters.

**The guaranteed relation dominates instead.** Over CSW21 the split between the two drop relations
is **1,731,818 drop-terminal pairs against 62,667 drop-interior — 28 to 1**, and drop-terminal is
P = 1.0 by construction. The cellmate track's value is overwhelmingly in the relation that needs no
probability estimate at all, which is why splitting the old "drop-one" relation mattered for more
than correctness.

---

## 4. M3 — Stem enumerability

`E[distinct family members findable | stem present]`, by stem length. §7.5 wants the band **2 to 6**,
which is what a player can run through in a couple of seconds.

| stem length | 4x4 Casual | 4x4 Good Casual | 4x4 Spam | 5x5 Spam |
| --- | --- | --- | --- | --- |
| 2 | 17.12 | 20.56 | 29.84 | 36.88 |
| **3** | **3.13** | **3.82** | **5.70** | **5.97** |
| 4 | 0.99 | 1.19 | 1.65 | 1.65 |
| 5 | 0.42 | 0.49 | 0.69 | 0.74 |
| 6 | 0.26 | 0.29 | 0.42 | 0.40 |
| 7 | 0.31 | 0.30 | 0.43 | 0.45 |

**This also contradicts the spec.** §7.5.1 predicts "roughly the 4-to-6-letter band" survives
(`-LLERS`, `-NTERS`, `-EATER`, `-ANTED`). Measured, the 2-to-6 target band is hit by **3-letter stems
only**. Four-letter stems yield about one findable member; five- and six-letter stems yield well
under one, meaning that on most boards where the stem is present, *nothing* in its family is findable.

Two-letter stems behave as §7.5 predicts — 17 to 37 members findable, far too many to act on, which
confirms the reason `-RS` is useless as a hunting cue.

**Sampling caveat:** family stems were sampled broadly across the index rather than weighted toward
productive stems. A curated curriculum would pick better stems, so these are a lower bound.

The table above counts a word-stem as a member of its own family; §4.1 does not, which is why its
`broad` column reads slightly lower (2.83 against 3.13 at 3 letters). §4.1 is the comparable one.

### 4.1 Under curation — and the caveat above was half wrong

The broad sample is what produced "4-to-6 letter stems are useless", and that finding reshapes the
curriculum, so it was remeasured against the population a curriculum would actually draw from.
Stems were ranked by **productivity**: distinct valid completions in CSW21, weighted by what those
completions score, so a family of six 7-letter words outranks a family of six 3-letter ones. Top N
per stem length. Four samples, all tallied on the **same boards in one pass**, so the only thing
that varies across the columns is curation. 30,000 boards per cell, six cells (`runs/m3-curated`).

| sample | what it is |
| --- | --- |
| `broad` | stride through the family index — the §4 numbers above |
| `curated` | top 2,000 per length by weighted productivity |
| `curatedTight` | top 500 per length — is curation depth a gradient? |
| `curatedWord` | top 2,000 per length among stems that are **themselves valid words** |

`curatedWord` exists because the unrestricted ranking selects morphological tails — `TION`, `NESS`,
`ATIO`, `SSES`, `ISATIO` — which are real hunting cues but are not what §7.5 means by a stem to
teach. Restricted to words, the same ranking gives `GRAPH`, `INTER`, `UNDER`, `RATION`, `NATION`,
`ABILITY`, `COUNTER`.

**One correction before the numbers.** A stem that is itself a word belongs to its own family and is
found whenever it has a path, contributing a guaranteed 1 that a fragment stem can never score.
Counting it would credit curation with a floor it did not earn — 5-letter `curatedWord` reads 2.04
with the stem counted and 0.99 without. Everything below **excludes the stem itself**, which is what
§7.5 is asking anyway: what *else* does this stem get you.

Range across the six cells, poorest (4x4 Casual) to richest (5x5 Spam):

| stem length | broad | curated | curatedTight | curatedWord |
| --- | --- | --- | --- | --- |
| 2 | 17.10–36.93 | 17.20–37.68 | 17.44–38.13 | 26.30–58.72 |
| **3** | **2.83–5.63** | **4.46–8.93** | 6.65–13.76 | **5.26–10.29** |
| **4** | 0.82–1.50 | **1.85–3.70** | **2.44–5.11** | **2.03–3.68** |
| 5 | 0.33–0.64 | 0.86–1.70 | 1.13–2.41 | 1.04–1.84 |
| 6 | 0.20–0.36 | 0.49–0.98 | 0.55–1.25 | 0.74–1.24 |
| 7 | 0.24–0.39 | 0.33–0.74 | 0.39–1.00 | 0.58–0.90 |

**The answer to the narrow question: 4-letter stems reach the band, 5-letter stems do not.**

- **4-letter stems clear 2 in every cell** under both `curatedTight` (min 2.44) and `curatedWord`
  (min 2.03). Against the broad sample's 0.99 this is a 2.5–3.4× lift. My earlier claim that
  "plausible curation will not close a 7× gap" was wrong for this length — curation closes it.
- **5-letter stems roughly triple but stay short.** Only one cell of six clears 2 (5x5 Spam under
  `curatedTight`, 2.41); `curatedWord` peaks at 1.84. They are not a hunting cue outside Spam.
- **6- and 7-letter stems stay dead.** Best case 1.25. Curation lifts them proportionally but from
  a base so low it does not matter.
- **3-letter stems are the strongest, and can be over-curated.** `curatedTight` pushes 5x5 Spam to
  13.76 — out the *top* of the 2-to-6 band. The band has two edges, and the tightest 3-letter stems
  cross the upper one.

**So §7.5.1's "roughly the 4-to-6-letter band" is half right.** Four is in, five is marginal and
Spam-only, six is out. The usable band is **3 to 4 letters**, with 5 available as Spam-tier material.
§7.5's cutoff should be set there.

**Two secondary findings the curriculum can use.** Curation depth is a **gradient**, not a
threshold: `curatedTight` beats `curated` at every length ≥ 3, in every cell. A shorter stem list
is a better stem list, so the curriculum can trade coverage for quality rather than needing a large
one. And at equal list size, **word-stems beat fragment-stems at every length ≥ 4** (`curatedWord`
above `curated` throughout) — the stems that are pedagogically natural are also the better cues, so
teachability and measured quality do not pull against each other here.

**The N-quartile split found nothing here.** Splitting Spam at the quartiles of realized N gives
0.68 / 0.68 / 0.71 / 0.69 for 5-letter stems — flat. The same split *does* move board potential
(400,831 at N=146–252 against 442,730 at N=507–625), so the machinery was worth building, but
enumerability is insensitive to the N draw.

---

## 5. The full simulation run

`runs/full`: **5.2M boards** — 1M per cell, 200k for 4x4 Spam per §5.3's stratification, since that
cell draws N from [144, 625] and costs roughly 7× a Casual board. 31 minutes on 14 threads, root
seed 20260917.

`board_norms`, means with p10–p90 in brackets:

| cell | total points | words | 5+ words | seeded | mean N |
| --- | --- | --- | --- | --- | --- |
| 4x4 Casual | 194,148 [116,900–285,400] | 287 | 129 | 68.4% | 5.0 |
| 4x4 Good Casual | 252,258 [174,600–342,500] | 348 | 171 | 74.6% | 15.0 |
| 4x4 Spam | 423,476 [347,700–509,400] | 508 | 288 | 86.5% | 384.6 |
| 5x5 Casual | 394,397 [233,600–582,600] | 517 | 261 | 62.6% | 3.0 |
| 5x5 Good Casual | 569,607 [414,300–748,300] | 675 | 379 | 72.8% | 15.0 *(printed as 81.0 in the original; the run recorded 15.0)* |
| 5x5 Spam | 754,387 [611,200–921,000] | 827 | 499 | 80.7% | 81.0 |

Tier ordering holds on every metric on both grids *(by construction of best-of-N; see A8)*.
~~4x4 Spam's mean realized N is **384.6** against the 384.5 a uniform draw over [144, 625]
predicts — the draw is doing what §2.3 says.~~ **RETRACTED as evidence (A7):** this checked the
simulator's RNG against its own assumption. The seeded column above is also an artifact (below).

**Reproducibility: verified at scale.** The same run at **6 threads** produced `word_stats.tsv`
(1,039,718 lines), `board_norms.tsv` and `board_norms_by_n.tsv` **byte-identical** to the 14-thread
run. The manifests differ only in `threads`, `wallSeconds`, `outputDir` and the timestamp. This is
the property the board-index RNG streams were chosen for over per-thread streams, now confirmed on
5.2M boards rather than the pilot's 1,800.

**Two findings §5.3 asked for by name.**

> **RETRACTED (A7).** The paragraph below is an artifact of drawing a seed per candidate. Flux draws
> one seed per board before best-of-N; the seeded share of winners is 50% at every tier.

~~*Seeded boards dominate the winners.*~~ The base seed rate is 50% (`probabilityPerMille: 500`), and
each of the N candidates draws its own seed independently — but **63% to 87% of boards that win
their best-of-N carry one**, rising monotonically with tier to 86.5% at 4x4 Spam. §5.3 said that if
seeded boards dominate Spam far beyond the 50% base rate, it is "a real finding about what Spam
boards *are*, not a generator bug". It is the finding: at Spam tier, a high-potential board is
mostly a *seeded* board, so the seed table is not a garnish on the generator, it is most of what
makes the tier.

*Spam is a spread, and N moves it.* Splitting 4x4 Spam at the quartiles of realized N:

| quartile | N range | mean points | boards |
| --- | --- | --- | --- |
| Q1 | 144–264 | 394,693 | 50,242 |
| Q2 | 264–385 | 418,810 | 50,513 |
| Q3 | 385–505 | 434,247 | 50,236 |
| Q4 | 505–625 | 446,239 | 50,242 |

A 13% spread in mean potential across the draw, with the increments shrinking (24k, 15k, 12k) — the
familiar diminishing return of best-of-N. Averaging over the draw would have hidden it, which is why
§5.3 requires the split.

**One number the spec got wrong in the other direction.** §5.3 expects the 1e-5 retention threshold
to leave "60k to 120k surviving words". It leaves **221,430** — 79% of CSW21. At 1M boards per cell
the resolution is fine enough that almost everything clears 1e-5, so the threshold is not doing the
filtering §5.3 assumed. If the intent was "the set worth showing a human", that set has to be cut by
something else — points, or P(appear) at a threshold two orders of magnitude higher.

**A manifest caveat for these three runs.** The `startedUtc` field was being written when the
manifest was written, i.e. at run *end*, so in `runs/full`, `runs/full-verify` and `runs/m3-curated`
it records the finish time; the true start is `startedUtc − wallSeconds`. Fixed in the tools, but the
existing artifacts were not regenerated for a timestamp label — nothing about reproducing a run
depends on it, since that needs the seed, config hash, dictionary hash and git SHA, all of which are
correct.

---

## 6. Benchmarks

Solve time on generated boards, single-threaded, release, p50 / p95 microseconds:

| cell | Count mode | Full mode | words |
| --- | --- | --- | --- |
| 4x4 Casual | 60.5 / 83.2 | 64.6 / 91.4 | 287 |
| 4x4 Good Casual | 69.0 / 92.0 | 74.5 / 100.1 | 346 |
| 4x4 Spam | 91.3 / 113.5 | 101.5 / 124.0 | 511 |
| 5x5 Casual | 124.2 / 171.2 | 136.7 / 187.0 | 520 |
| 5x5 Good Casual | 149.5 / 203.7 | 164.5 / 226.7 | 685 |
| 5x5 Spam | 181.9 / 238.0 | 197.1 / 269.2 | 822 |

Targets were 300 µs (4x4) and 3 ms (5x5). **Met with 3.3× and 16× of margin.** Full path enumeration
costs 8–12% over count mode, not the multiple that would have forced the simulator to give up paths.

Generation cost per final board: 5.3 ms (4x4), 3.6 ms (5x5), **4.6 ms tier-weighted** against the
30 ms §5.3 assumed — about 6.5× cheaper, so 1M boards per cell is roughly 1.3 CPU-hours, not 8.

Simulator throughput scaling, 4x4 Spam:

| threads | boards/s | speedup | efficiency |
| --- | --- | --- | --- |
| 1 | 55 | 1.00× | 100% |
| 2 | 106 | 1.93× | 96% |
| 4 | 204 | 3.71× | 93% |
| 8 | 393 | 7.15× | 89% |
| 14 | 545 | 9.91× | 71% |

The drop at 14 is the efficiency cores on this machine, not contention.

DAWG: 79,807 states, 191,740 edges, **1.34 MB**, ~120 ms to build.

---

## 7. Recon verdict on LetterCounter

`bogwords.txt` is Collins 21 — 279,496 words, sorted, deduped, and containing the CSW21-only short
words (ZA, QI, EW, OK, ZAS, QIS) that distinguish it from TWL. Not provisional.

The review in the build prompt was accurate. Ported: self-avoiding seed placement (with the per-node
vector allocation removed), `embed_word` including overlap mode, canonical form under the 8 dihedral
symmetries. Not ported: the trie, `compute_letter_weights` (a vowel/ERSTAIN heuristic that would have
biased every statistic), global mutable state, the `BOARD_SIDE` macro, clock seeding, and the
annealing.

Its value turned out to be as an **oracle**, as the review predicted. On its best recorded board
(`SEMCNAPAGIRSSELC`) the new solver independently computes the identical **834,200** total and finds
all 50 of the long words it logged. Two unrelated implementations agreeing exactly on a 934-word
board is stronger evidence than any invariant test.

The saved artifacts were less useful than hoped: `boards.pk` is 47 raw board strings with no scores,
and `sim_summary.json`'s word list is truncated to 50, so neither is a ground-truth fixture.

---

## 8. What the data supports, and what it does not

**Supported:**

- **The free-vocabulary thesis (§3.5).** 5.5 reachable extensions per found stem, 38–46% of findable
  words free. Nowhere near the 2-per-game kill threshold. *(Survives on different numbers: see A1.)*
- **Tier ordering.** Spam > Good Casual > Casual on every metric, both grids. *(By construction, not
  evidence about Flux: A8 item 3.)*
- ~~**Seeded-board overrepresentation (§2.3).** 50% of candidates carry a seed; **63–87% of *winners*
  do**, rising monotonically with tier to 86.5% at 4x4 Spam (§5, 5.2M boards). Selection after
  seeding does what the ruling predicted, and more strongly than expected.~~ **RETRACTED (A7).**
- **Spam is a spread, not a point.** Mean potential moves 394,693 → 446,239 across the quartiles of
  realized N, with diminishing increments (§5). *(Direction by construction; A8 item 4.)*
- **Solver and generation performance.** Both comfortably inside target; the simulator is ~6.5×
  cheaper than the spec's compute budget assumed.

**Not supported — these need spec changes:**

- **§7.6's cellmate expectation is wrong.** 5-letter anagrams are 0.414, below the spec's own 0.5
  teaching threshold, not "high". The cellmate curriculum above 4 letters mostly does not survive its
  own rule.
- **§7.5.1's 4-to-6-letter stem band is half wrong** (§4.1). Under curation by weighted productivity,
  4-letter stems *do* reach the 2-to-6 target (2.03–5.11 against the broad sample's 0.99), but
  5-letter stems clear it in only one cell of six and 6-letter stems stay under 1.25. The usable band
  is **3 to 4 letters**, with 5 as Spam-tier material — not 4 to 6.
- **§5.3's word-retention estimate.** The 1e-5 threshold was expected to leave 60k–120k words; it
  leaves **221,430**, 79% of CSW21. The threshold is not the filter §5.3 assumed it was, so "the set
  worth showing a human" needs a different cut.
- **§14.4's "under 1 MB" for the DAWG.** Measured 1.34 MB. Already corrected in the spec; irrelevant
  in a 100 MB bundle.
- **§11.1's constrained Spam generation.** Effectively infeasible as written: 0.6% of constrained
  candidates land in the tier's own norm band, so 96% of boards exhaust a 20,000-attempt budget. This
  does not block anything, because §11.1 already says acquisition boards are Casual and Good Casual
  only, and those cost 0.7–14 ms with no infeasibility. But the fallback ladder is not an edge case
  if anything ever targets Spam.

**Still unverified:**

- The letter distribution (§2.4). Everything above is provisional on it. *(Resolved: read from the
  Flux client and validated against 9,034 real boards; Part A.)* §16.2's suggestion of
  recording 50 real ranked boards by hand remains the cheapest way to detect a badly wrong one, and
  is worth doing before Phase 3.
- Which *specific* stems the curriculum ships. §4.1 establishes that curation by weighted
  productivity lifts 4-letter stems into the band, but it ranks the whole dictionary mechanically; a
  hand-checked list would differ at the margins. The measurement says the population is viable, not
  that any particular stem is.

---

## 9. Reproducing

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j 14
ctest --test-dir build --output-on-failure

./build/tools/build_dawg/build_dawg <csw21-wordlist> csw21.dawg
./build/tools/simulate/simulate --config config/ruleset_v1.json --dawg csw21.dawg \
    --out runs/full --boards-per-cell 1000000 --boards 4x4:spam=200000 --threads 14
./build/tools/measure/measure  --config config/ruleset_v1.json --dawg csw21.dawg \
    --out runs/m3-curated --boards-per-cell 30000 --stems 3000 \
    --curated-per-len 2000 --curated-tight 500 --threads 14 --seed 20260917
```

Every run writes `manifest.json` with config hash, dictionary hash, git SHA (with a dirty flag),
root seed, per-cell counts, thread count and wall time. Output is byte-identical at any thread count
for the same root seed — verified on the full 5.2M-board run at 14 and 6 threads across all three
simulator data files (§5), and earlier at 1 and 14 threads on the pilot.

Test suite: 1,425,935 checks across five suites, including a brute-force differential oracle that
enumerates 62.5M paths with no DAWG and agrees with the solver exactly.

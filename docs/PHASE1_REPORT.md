# FluxCore Phase 1 — report

**Written for:** the person deciding whether Phases 3 and 4 get built as specified.

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
| 5x5 Good Casual | 569,607 [414,300–748,300] | 675 | 379 | 72.8% | 81.0 |
| 5x5 Spam | 754,387 [611,200–921,000] | 827 | 499 | 80.7% | 81.0 |

Tier ordering holds on every metric on both grids, and 4x4 Spam's mean realized N is **384.6**
against the 384.5 a uniform draw over [144, 625] predicts — the draw is doing what §2.3 says.

**Reproducibility: verified at scale.** The same run at **6 threads** produced `word_stats.tsv`
(1,039,718 lines), `board_norms.tsv` and `board_norms_by_n.tsv` **byte-identical** to the 14-thread
run. The manifests differ only in `threads`, `wallSeconds`, `outputDir` and the timestamp. This is
the property the board-index RNG streams were chosen for over per-thread streams, now confirmed on
5.2M boards rather than the pilot's 1,800.

**Two findings §5.3 asked for by name.**

*Seeded boards dominate the winners.* The base seed rate is 50% (`probabilityPerMille: 500`), and
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
  words free. Nowhere near the 2-per-game kill threshold.
- **Tier ordering.** Spam > Good Casual > Casual on every metric, both grids.
- **Seeded-board overrepresentation (§2.3).** 50% of candidates carry a seed; **63–87% of *winners*
  do**, rising monotonically with tier to 86.5% at 4x4 Spam (§5, 5.2M boards). Selection after
  seeding does what the ruling predicted, and more strongly than expected.
- **Spam is a spread, not a point.** Mean potential moves 394,693 → 446,239 across the quartiles of
  realized N, with diminishing increments (§5).
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

- The letter distribution (§2.4). Everything above is provisional on it. §16.2's suggestion of
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

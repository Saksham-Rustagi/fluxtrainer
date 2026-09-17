# FluxCore Phase 1 — report

**Written for:** the person deciding whether Phases 3 and 4 get built as specified.

All numbers are **provisional on the letter distribution**, which is a placeholder (spec §2.4 item 1).
If Flux turns out to use Boggle-style dice, the distribution changes materially and everything here
has to be recomputed. Every artifact records its config hash (`22448ec0ab243759`) and dictionary hash
so a stale number is detectable rather than silently wrong.

Dictionary: CSW21, 279,496 words, recovered from the LetterCounter repo. Measurement run:
5,000 boards per cell × 6 cells, 3,000 M1 stems, 3,000 family stems, 18s on 14 threads.

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

**Sampling caveat, and it cuts toward optimism being wrong:** family stems were sampled broadly
across the index rather than weighted toward common stems. A curated curriculum would pick the
productive stems, which have higher enumerability than this average. So treat the 4–6 letter numbers
as a lower bound — but the gap to the target band is large (0.29 against a target of 2), and
plausible curation will not close a 7× gap.

**The N-quartile split found nothing here.** Splitting Spam at the quartiles of realized N gives
0.68 / 0.68 / 0.71 / 0.69 for 5-letter stems — flat. The same split *does* move board potential
(400,831 at N=146–252 against 442,730 at N=507–625), so the machinery was worth building, but
enumerability is insensitive to the N draw.

---

## 5. Benchmarks

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

## 6. Recon verdict on LetterCounter

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

## 7. What the data supports, and what it does not

**Supported:**

- **The free-vocabulary thesis (§3.5).** 5.5 reachable extensions per found stem, 38–46% of findable
  words free. Nowhere near the 2-per-game kill threshold.
- **Tier ordering.** Spam > Good Casual > Casual on every metric, both grids.
- **Seeded-board overrepresentation (§2.3).** 50.1% of candidates carry a seed; 66–89% of *winners*
  do, rising with tier. Selection after seeding does what the ruling predicted.
- **Spam is a spread, not a point.** Mean potential moves 400,831 → 442,730 across the quartiles of N.
- **Solver and generation performance.** Both comfortably inside target; the simulator is ~6.5×
  cheaper than the spec's compute budget assumed.

**Not supported — these need spec changes:**

- **§7.6's cellmate expectation is wrong.** 5-letter anagrams are 0.414, below the spec's own 0.5
  teaching threshold, not "high". The cellmate curriculum above 4 letters mostly does not survive its
  own rule.
- **§7.5.1's 4-to-6-letter stem band is wrong.** Only 3-letter stems land in the 2-to-6 enumerability
  target. Four-letter stems give ~1 findable member, five- and six-letter stems well under 1.
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
- Whether a curated stem set lifts M3's 4–6 letter enumerability into the target band. The broad
  sample says no by a factor of 7, but the sample is not the curriculum.

---

## 8. Reproducing

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j 14
ctest --test-dir build --output-on-failure

./build/tools/build_dawg/build_dawg <csw21-wordlist> csw21.dawg
./build/tools/simulate/simulate --config config/ruleset_v1.json --dawg csw21.dawg \
    --out runs/full --boards-per-cell 1000000 --boards 4x4:spam=200000 --threads 14
./build/tools/measure/measure  --config config/ruleset_v1.json --dawg csw21.dawg \
    --out runs/measure --boards-per-cell 5000 --stems 3000 --threads 14
```

Every run writes `manifest.json` with config hash, dictionary hash, git SHA (with a dirty flag),
root seed, per-cell counts, thread count and wall time. Output is byte-identical at any thread count
for the same root seed — verified at 1 and 14 threads across all three simulator data files.

Test suite: 1,425,935 checks across five suites, including a brute-force differential oracle that
enumerates 62.5M paths with no DAWG and agrees with the solver exactly.

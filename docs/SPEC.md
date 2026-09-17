# Flux Trainer — Technical Specification

2026-09-17 · @Someone

## 1. Scope and product thesis

Flux Trainer is a standalone iOS app that a top-tier Flux player uses **instead of** ranked Flux for part of their daily practice. It contains its own playable Boggle engine that reproduces Flux's ranked board distribution, solves every board against Collins 21, records what the player does at the swipe level, and turns that into targeted study.

The app has to contain the game because there is currently no way to get data out of Flux. Every signal the trainer needs (which words you found, in what order, where on the board you were looking, what you swiped that was not a word, how long you hesitated) only exists if the swipes happen inside this app.

### Thesis

A top-50 Flux player does not lose points mainly because they lack vocabulary. They lose points because in 80 seconds they can physically enter roughly 100 words, boards routinely contain 200 to 1000+, and so every game is a selection problem under a hard time budget. The trainer improves three things, in priority order:

1. **Family completion.** Knowing every valid word reachable from a stem you are already swiping, and knowing with certainty which ones are not valid. This is vocabulary, but it is the specific slice of vocabulary that costs no search time and eliminates misswipes.
2. **Selection.** Spending your \~100 swipes on the highest-value words available, instead of on whatever the eye lands on first.
3. **Board vision.** Seeing a word or family that is present, in a region the eye never visited.

These are not independent, and the dependency runs one way. Complete word knowledge makes vision and selection better as a byproduct: you cannot see a family you don't know, and you decide faster when you are certain rather than guessing. Selection and vision also improve on their own with volume of play. Vocabulary does not.

So vocabulary is the axis the app trains directly, and the other two are trained implicitly by playing real boards built around the vocabulary being learned. That is the main loop, specified in Section 10.

### Non-goals

- No beginner strategy or tutorial content. The target user is top 100 ranked.
- No multiplayer, accounts, or cloud sync in v1. Solo, local, offline.
- No attempt to scrape data out of Flux (screenshots, OCR, network interception). If the developer later exposes an export, that becomes an import path, not a rewrite.
- Not a solver you consult mid-game. This is for practice, not for cheating in ranked.

### What done looks like

You open the app, play three to five boards drawn from the real ranked distribution, and after each one get a review that says, in board terms rather than word-list terms, where the points went. Once a week you can see whether your long-word share and your points per second on good boards are actually moving.

## 2. Game model

Everything here is implemented as data in a versioned `RulesetConfig`, not as constants in code. The generation parameters are partly guesswork and will change when the Flux developer confirms them, and when they change every derived statistic has to be recomputed.

### 2.1 Confirmed rules

| Rule | Value |
| --- | --- |
| Dictionary | Collins 21 (CSW21) |
| Game length | 80 seconds |
| Grids | 4x4 and 5x5 |
| Adjacency | 8-way |
| Tile reuse | Not allowed within a word |
| Q tile | Plain Q, U is a separate tile |
| Board | Static for the whole game |
| Duplicates | Words found by both players still score for both |

The duplicate rule matters more than it looks. Because there is no unique-word bonus, obscure words have no premium over common ones. A word is worth exactly its points, and the only question is what it costs you in time. That pushes the whole app toward throughput and selection rather than toward rare-word hoarding.

### 2.2 Scoring

| Length | Points | Points per letter |
| --- | --- | --- |
| 3 | 100 | 33 |
| 4 | 400 | 100 |
| 5 | 800 | 160 |
| 6 | 1,400 | 233 |
| 7 | 1,800 | 257 |
| 8 | 2,200 | 275 |
| 9 | 2,600 | 289 |
| n ≥ 7 | 1400 + 400(n−6) | — |

The marginal jump flattens after 6. Going from 5 to 6 letters is worth 600 points; every letter after that is worth 400. So 6-letter words are the highest-leverage length in the game, and 7s and 8s are worth chasing mostly when they are extensions of a 6 you already have on screen.

### 2.3 Ranked generation (as published, treated as spec)

- **Grid split:** 60% 4x4, 40% 5x5.
- **Seeding:** 50% of boards contain a secret seed word.
- **Seed lengths:** 4x4 uses 8, 9, 10, or 11. 5x5 uses 9, 10, 11, 12, or 13.
- **Longest seeds** (11 on 4x4, 13 on 5x5) only appear on Spam boards.
- **Quality tiers**, implemented as best-of-N over generated candidates:

| Tier | Share | 4x4 candidates | 5x5 candidates |
| --- | --- | --- | --- |
| Spam | 20% | 144–625 | 81 |
| Good Casual | 50% | 10–20 | 10–20 |
| Casual | 30% | 5 | 3 |

**Where N is a range, it is drawn uniformly at random per board.** For 4x4 Spam that is a uniform draw over [144, 625]. Best-of-144 and best-of-625 produce measurably different boards, so the Spam tier is a spread rather than a point, and the simulator records the realized N on every Spam board (5.3).

**Candidates in the best-of-N are ranked by total available points on the board.** Confirmed, not assumed. This is the single most consequential generation parameter, because it determines what a Spam board looks like: selecting on point mass favours boards with dense long-word clusters and heavy stem reuse, rather than boards with many distinct short words. The simulator ranks candidates the same way, and `board_norms` is built from that ranking.

**A word contributes to total available points exactly once, however many distinct paths spell it.** Duplicate words do not score twice in play, so per-path counting would rank boards by points no player can capture, and best-of-N would select for dense repeated-letter boards on the strength of value that does not exist. This is settled and hardcoded in the potential metric, not a configurable option. It constrains the scoring metric only: the solver still enumerates and stores every distinct path per word, because reachability, cellmate and enumerability analysis all depend on paths.

**Seeding happens before the best-of-N, not after it.** The tier is drawn first (it is what sets N, and what the 20/50/30 shares above are a distribution over), then each candidate is seeded, then the tier's best-of-N runs over already-seeded candidates. Reading "before tier selection" as "before the tier is known" would make the Spam-only restriction on the longest seed lengths unimplementable, since that rule is conditional on the tier. Each of the N candidates draws its own seed word and placement independently, rather than all N sharing one seed word with different fills — candidates are independent everywhere else and this keeps them so. A consequence worth remembering when reading simulation output: because selection happens after seeding, a selected board's potential comes partly from its seed, so seeded boards are overrepresented at the top of every best-of-N.

### 2.4 Parameters that are assumptions

These are flagged in the config as `provisional` and are the first thing to confirm with the developer:

1. **Letter distribution.** Placeholder is English letter frequency weighted by frequency in words (not in running text), which is the sane default. Flux may use Boggle-style dice, which produce a meaningfully different distribution because dice guarantee vowel spread. If it turns out to be dice, the simulation output changes a lot and has to be rerun.
2. **Letter variety adjustment.** The note that variety is "probably increased in casual/good casual" is modeled as a tunable bias toward distinct letters, off by default until confirmed.
3. **Seed placement mechanism.** Assumed to be: pick a word of the target length, lay its path on the grid as a self-avoiding walk, then fill the remaining cells from the letter distribution. Whether Flux lays seeds this way is unconfirmed. The *ordering* around tier selection is not an assumption — seeding happens first, per 2.3.

Until these are confirmed, every number the app derives from simulation carries a `ruleset_version` and the UI shows a quiet "stats v3" marker, so you never get confused about why a word's seen percentage moved.

## 3. Training thesis: what actually limits a strong player

This section is the reason the app looks the way it does. It is built from the player's own description of their play, and if the diagnosis is wrong the feature set is wrong.

### 3.1 The constraint is swipes, not words

80 seconds, roughly 96 words on average, best game 161. Call it a budget of 100 to 160 swipes. A good 4x4 can hold 1000+ words. You are never going to run out of things to swipe on a good board, which means **the total word list on the board is almost irrelevant as a target.** The game is: pick the best 100 of them, in an order your hands can keep up with.

This immediately kills percent-of-available-points as a metric, which matches the player's own objection to it. On a 1000-word board, 10% capture can be an excellent game. On a 200-word board, 40% can be mediocre.

### 3.2 The two costs, and why shorts are a trap that sometimes isn't

Every word costs **search time plus swipe time**.

Swipe time is roughly linear in path length and is small: call it 0.3s of fixed cost plus 0.08s per letter, so about 0.55s for a 3 and 0.8s for a 6. On swipe cost alone, longer words are strictly better per second at every length. A 6 is worth 1,687 points per second of swiping; a 3 is worth 182.

Search time is where the whole game lives, and it is wildly asymmetric:

- A short word that is a subpath or anagram of a word you just swiped costs **almost no search time.** You are already looking at it. This is exactly the described behavior: swipe TILLERS, then pick up TIES, TIS, SIT, SITE on the way out.
- A long word in a region you have not looked at costs **a lot** of search time, and the cost rises as the game goes on because you have already harvested the easy ones.

So the correct framing is not "shorts are bad." It is:

> **Your hunting rate decays over the course of a game. Your filler rate is roughly flat. Play hunting until your hunting rate drops below your filler rate, then play filler.**

That single sentence explains every tier strategy in the original brainstorm without needing separate rules:

- **Spam boards:** hunting rate stays enormous for the full 80 seconds, so the crossover never arrives and filler is always wrong.
- **Casual boards:** the long words run out fast, the crossover comes early (maybe 25 to 35 seconds in), and after that filler is not a leak, it is correct play.
- **Good Casual:** the crossover lands somewhere in the middle, which is exactly why the player describes it as hard to gauge.

Selection is worth measuring, but it cannot be measured the obvious way. Once you switch to filler you stop generating hunt observations, so your hunt-rate curve is censored exactly where the counterfactual lives: a game where you quit hunting at 0:24 contains no evidence about what your hunt rate would have been at 0:35. The optimal crossover is therefore not estimable from ordinary play. Review shows the descriptive rate curve and where you actually switched, which is honest and cheap. The counterfactual comes only from longs-only drills run deliberately as a measurement instrument (10.4), one per tier per week.

Selection also improves on its own with volume of play. Vocabulary does not. That asymmetry, not importance, is why vocabulary is the axis the app trains directly.

### 3.3 The vision failure is structural, not regional

A 4x4 is sixteen cells. It is not big enough to have neighbourhoods you never visit, and in practice you take points from anywhere the letters are useful. So region-level blindness is mostly not the problem, and an earlier draft of this spec overweighted it badly.

The real failure is **pattern-level**. You are on the right cells, working the right stem, and you miss one branch off it: you took PRATE, PRATER, PRATERS and never registered that the -IEST was sitting there. Or the family is one you have never learned exists at all, in which case there was nothing to notice.

That splits cleanly in two, and the two need different fixes:

| Failure | What happened | Fix |
| --- | --- | --- |
| **Family blindness** | You touched the stem and missed a branch you know | Drill the affix grid until the branch set comes as one unit |
| **Family ignorance** | The family was never in your vocabulary | Learn it, which requires knowing which families are worth learning |

The second is the one that makes simulation load-bearing rather than decorative. There is no way to know which families are common enough to be worth your time without solving a large sample of ranked-distribution boards and counting. That is the primary job of the pipeline in 5.3, and `family_stats` is its most important output, not `word_stats`.

Consequence for review: the unit of analysis is the **family on the board**, not the word and not the region. For every family present, did you find none of it, some of it, or all of it? Three very different diagnoses, and only the middle one is a vision problem.

Cell coverage is still tracked, but its job is narrow: it tells the player model when to make no inference at all, because a word whose cells you never touched is not evidence that you don't know it. It is a guard, not a diagnosis.

### 3.4 Where the points actually are

Given the scoring curve, 6-letter words are the sweet spot, and 5s are the volume play. The player's stated gap against better players on good boards is precisely this: they find more 5s and 6s while he is either over-reaching for 8s or filling with 3s. So the target behavioral change is narrow and specific:

> On Good Casual and Spam boards, raise the count of 5- and 6-letter words found, at the expense of 3-letter words, without lowering total word count much.

That is a measurable target with a number attached, and it is the headline of the progress dashboard.

### 3.5 Vocabulary: free and expensive

Vocabulary is not one thing, and lumping it together is what makes people rank it wrong. There are two kinds and they behave completely differently under the cost model in 3.2.

**Free vocabulary: additive affixes.** A word whose path is your stem's path plus extra cells, with the stem's own cells untouched. PATERS → EPATERS is one cell on the front. PRATE → PRATER → PRATERS is one and two cells on the back. Search cost is near zero because your finger is already on the stem, swipe cost is about 0.8 seconds, and a 7 pays 1,800. This is the highest points-per-second action available in the game.

It is conditional on **reachability**: the extra cell has to be adjacent to the right end of the stem path and not already consumed by it. How often that holds is unknown and is the single most important unverified number in this spec. It is computable from the simulator (5.3) and has to be computed before the curriculum is built, because if the answer is 2 extra words a game rather than 12, the batch system is the wrong product.

**Cheap vocabulary: mutating affixes.** PRATE + ING is PRATING, not PRATEING. The E is consumed, so PRATING does not run along PRATE's path and you have to find it as a separate word. Same for consonant doubling and Y → I changes. These are **not** free points, and the earlier draft of this spec was wrong to lump them in.

Their value is entirely negative knowledge: knowing that PRATING is valid and PRATIER is not stops you spending swipes on nothing. So mutating affixes are trained, but they belong to the misswipe track (3.6), not the free-points track, and they are worth much less per item.

**Expensive vocabulary** is an isolated word needing its own search. Here the earlier argument holds: it only pays on sparse boards where you had spare capacity, and on dense boards it is nearly worthless because you had 800 other words and no time.

Every family member is tagged `drop-terminal`, `additive`, `cellmate`, `mutating`, or `independent` at extraction time, and each is valued, scheduled, and displayed differently. `drop-terminal` (7.6) leads the ordering because it is the one class whose points are guaranteed rather than probable.

So the study list has to separate these explicitly. They are not ranked on the same scale, and Section 6 gives them different value formulas.

### 3.6 Negative knowledge is worth as much as positive knowledge

The other half of family completion is knowing what is **not** a word. Suffix ambiguity is the main offender: some stems take -IER, -IEST, -IERS and structurally similar ones do not, and there is no rule that predicts it.

Every invalid attempt costs the swipe time plus the decision time in front of it, and it scores nothing. Call it 1.0 to 1.5 seconds all-in. If a game contains 12 to 15 of these, that is 15 to 20 seconds of an 80-second game, which is 20% of the clock spent on zero points. That estimate is a guess until the app measures it, and **measuring it accurately in the first session is one of the highest-value things the trainer does**, because if it is real it is the single largest recoverable block of time in the player's game.

This means the ending set for a stem has to be taught as a complete object: which endings are live and which are dead, learned together. Teaching only the valid words leaves the misswipes in place. Section 7.3 specifies this, and Section 10 has a drill for it.

## 4. Core metrics

One metric is the spine of the app. Everything else is a breakdown of it.

### 4.1 Par

Percent of available points is rejected for the reasons in 3.1. But the replacement should not be a modeled quantity in v1, because a modeled denominator that is wrong is worse than no denominator at all.

**v1 headline: tier percentile.** Your score on this board, as a percentile of your own last 50 boards of the same tier and grid size. No cost model, no optimizer, no calibration, and it cannot drift. It answers the only question that matters day to day: was that good for me, on this kind of board.

**v2, experimental: Par.** The score a strong player with your vocabulary could realistically have achieved on this specific board in 80 seconds. Defined as a time-budget path-selection problem:

```
cost(w | already_taken) = swipe_cost(len(w)) + search_cost(w | already_taken)

swipe_cost(n)  = a + b·n           a, b measured per player in Phase 0
search_cost(w) = s0 · (1 − overlap(w)) · region_factor(w)

overlap(w)      = longest shared subpath with any taken word, / len(w)   ∈ [0,1]
region_factor(w)= 1.0 if a taken word already passes through w's 3x3 neighbourhood,
                  else r  (r ≈ 2.5, fitted)
s0              = your median observed time-to-find for an isolated 5-letter word
```

Note that `cost` depends on what has already been taken, so **this is not a knapsack.** It is prize-collecting orienteering with a time budget, and calling it a knapsack would get you a solver that is wrong in a way that looks fine. Implementation: greedy by points-per-marginal-cost, then 2-opt swaps over the selected sequence, fixed seed, capped at 200 iterations so it is deterministic and reproducible.

**Par is frozen at play time.** It is computed once, written to the `game` row with the `player_model_version` used, and never recomputed. The earlier draft had Par rising as your vocabulary grew, which would make your headline efficiency fall every time you learned something. If a moving reference is wanted later it goes in a separate shadow column.

Calibration gate: Par must be compared against the distribution of your scores on that tier, not against your personal best. If median Par is more than about 1.6x your median score, the cost model is too generous and `s0` and `r` need refitting before any metric built on Par is shown to you.

### 4.2 Headline numbers

| Metric | Definition | Status |
| --- | --- | --- |
| **Tier percentile** | score vs your own last 50 boards of the same tier and grid | v1 headline |
| **Family capture** | share of present families where you found at least one member, and mean share of members found | v1, the vision metric |
| **Rate** | points per second, whole game | v1 |
| **Rate curve** | points per second, rolling 10s window | v1, descriptive only |
| **Long share** | share of points from 5+ words | v1, the direct target from 3.4 |
| **Wasted seconds** | time on invalid attempts plus dead time | v1 |
| **Board Efficiency** | score / frozen Par | v2, gated on the calibration check |

Family capture is the number to watch. Finding one member of a family and missing three is a completely different failure from never touching the family at all, and a single word-count or coverage figure hides both.

### 4.3 The leak decomposition

The gap between your score and what was reachable is split into buckets. The buckets are in two different currencies and the earlier draft wrongly claimed they all sum to one gap. They do not, and forcing them to would double-count: the seconds lost to an invalid swipe are the same seconds the allocation bucket says you could have spent on a 6, and that 6 may also be sitting in the vision bucket.

So they are reported as two separate accounts.

**Account A — points you never had a chance at.** Each missed word is assigned to exactly one bucket, tested in this order:

| Bucket | Test | Meaning |
| --- | --- | --- |
| **Untouched** | none of the word's cells were used all game | No inference. Rare on a small grid, but it is what stops the model concluding you don't know 800 words. |
| **Vocabulary** | belief below 0.35 | You would never have found it |
| **Family blindness** | you swiped another member of its family | You were on the stem and missed the branch. The expensive one, and the one the curriculum targets. |
| **Vision** | known, cells touched, no family member found | You passed over it |

**Account B — time you spent badly.** Measured directly from timestamps, in seconds, and converted to points exactly once, at a rate defined below:

| Bucket | Measurement |
| --- | --- |
| **Invalid attempts** | total seconds on rejected sequences |
| **Dead time** | inter-word gaps exceeding your `baseline_gap` |
| **Allocation** | seconds spent on ≤4-letter words in regions where a known 5+ word was available |

**The conversion rate** is your median points per second across your last 20 games on that tier, and nothing else. Not the theoretical rate of a 6, not the whole-game average of the current board. One definition, used everywhere, shown in the UI as "at your Casual rate of 680/sec." The earlier draft used three different implied rates and the flagship number varied by 3x depending on which.

Review reports the two accounts separately and never adds them together. The single sentence at the top of review names the largest bucket from whichever account is bigger.

### 4.4 What is deliberately not measured

Word count is displayed but never framed as a goal, because the player's known failure mode is optimizing it. Accuracy percentage is not shown as a headline, since misswipes are cheap and a fear of misswiping makes people slow.

## 5. Data layer: dictionary, solver, simulation

### 5.1 Dictionary encoding

CSW21 is about 280,000 words. Only words of length 3 to 16 (4x4) or 3 to 25 (5x5) can appear, which is nearly all of it.

Encode as a **DAWG** (minimal deterministic acyclic word graph) built offline:

- Edge = 32-bit packed record: child index (25 bits), letter (5 bits), end-of-word flag, end-of-list flag.
- Built by incremental minimization (Daciuk-style) from a sorted word list. Measured on CSW21: 79,807 states, 191,740 edges, 1.34 MB. Trivially fits in the app bundle and stays memory-resident.
- Ship as a flat little-endian binary loaded with `mmap`, no parse step, instant cold start.
- **Numbered (perfect-hash) DAWG:** each state stores the count of words reachable through it, so any terminal maps to a dense integer word ID computed during the walk itself. There is no parallel word-index array and no side table; the ID falls out of the traversal that was happening anyway.

Every downstream artifact — stats tables, family tables, player model — keys on that ID, so three invariants are load-bearing:

- **IDs are dense and contiguous**, covering exactly `[0, word_count)`.
- **IDs are stable across rebuilds** from the same sorted input. The builder is deterministic and produces byte-identical output.
- **IDs change when the dictionary changes.** Every derived artifact therefore records the hash of the dictionary it was built against. Reading a stats table whose dictionary hash does not match the loaded DAWG is a **hard error, not a warning** — the IDs silently mean different words, which would corrupt every number in the app without any visible symptom.

### 5.2 Solver

Standard DFS from each cell with DAWG-guided pruning, plus a visited bitmask (16 or 25 bits, fits in a `uint32`).

For each board the solver produces, for every findable word:

- word ID, length, points
- **every distinct path** that spells it (needed for family and region analysis; a word can appear in three places on the board and that is three different learning opportunities)
- the canonical shortest path for display

Performance target: a 4x4 solve in 100–300 µs, a 5x5 in 1–3 ms single-threaded. In-app this means solving happens instantly at board load, before the timer starts.

The same C++ core is used in three places: the offline simulator, the in-app board solve, and the Par optimizer. One implementation, one set of bugs.

### 5.3 Offline simulation pipeline

A separate C++ CLI, multithreaded, run on a desktop. It generates boards exactly as ranked does (Section 2.3), solves them, and aggregates.

**Compute budget.** Best-of-N means each final board requires solving N candidates, and the averages differ by grid size, so they cannot be pooled:

```
4x4:  0.20·384 + 0.50·15 + 0.30·5  ≈  86 candidates,  ~0.2 ms each  →  17 ms per final board
5x5:  0.20·81  + 0.50·15 + 0.30·3  ≈  25 candidates,  ~2.0 ms each  →  49 ms per final board

weighted (60/40):  ~30 ms per final board
```

So 1M final boards is roughly 8 CPU-hours, about an hour on 8 cores. That gives seen-percentage resolution near 1e-5, far finer than needed, and it is cheap enough to rerun whenever a ruleset parameter changes, which is the property that actually matters.

Two optimizations if it gets tight:

1. **Cheap candidate scoring.** Candidates that lose the best-of-N never need a full word list, only a potential score. Run a truncated solve that counts 5+ words and exits early once a candidate is clearly behind the current leader.
2. **Stratify by tier.** Simulate each (grid size, tier) cell independently with its own board count, since Casual boards are cheap and Spam boards are expensive. 1M per cell for the cheap cells, 200k for Spam, then reweight at aggregation time.

**Outputs** (one directory per `ruleset_version`):

| Artifact | Contents |
| --- | --- |
| `family_stats` | The primary output. Per stem × (grid, tier): P(stem path present), **E\[members findable \| present\]** (the enumerability test in 7.5), expected points, member count. For Spam, also split at the quartiles of realized N (see below) |
| `word_stats` | Per word × (grid, tier): P(appears), E\[paths per board\] |
| `reachability` | Per stem × affix: P(additive extension present and reachable \| stem path present). The number the free-vocabulary thesis rests on (3.5) |
| `cellmate_stats` | Per pair × relation × length: P(cellmate has a valid path \| word has a valid path). Decides which pairs are worth teaching (7.6). Also reports the count of `drop-terminal` words implied by a typical board's found-set, which needs no probability estimate at all |
| `board_norms` | Distribution of total points, word count, 5+ count per tier. Classifies tiers at runtime, sanity-checks Par. |

**Per-board fields recorded during simulation**, because two generation parameters are spreads rather than points and averaging over them destroys information the curriculum needs:

- **Realized N.** 4x4 Spam draws N uniformly from [144, 625] (2.3), so `board_norms` for Spam aggregates over that draw exactly as ranked does. But every per-tier statistic that feeds the curriculum — enumerability above all — is **also reported split at the quartiles of N**. If a stem's enumerability sits in the usable 2-to-6 band at N=144 and blows past it at N=625, that stem is a hunting cue on only half of Spam boards, and the curriculum has to know that rather than average it away.
- **Seed presence and identity.** Whether the board carried a seed and which word it was. Because selection happens after seeding (2.3), seeded boards are expected to be overrepresented at the top of every best-of-N. If they dominate the Spam tier far beyond the 50% base rate, that is a real finding about what Spam boards *are*, not a generator bug.

Only words with P(appear) above about 1e-5 in any cell are retained. Expect 60k to 120k surviving words, which is the set actually worth showing a human.

Note that three of these five artifacts exist to answer questions the spec cannot answer from the armchair: is an extension reachable, is an anagram pathable, is a stem enumerable. If the pipeline only produced seen percentages it would not be worth building.

Only words with P(appear) above about 1e-5 in any cell are retained. Expect on the order of 60k to 120k surviving words, which is the set actually worth showing a human.

### 5.4 On-device generation

The app generates its own boards at runtime using the same generator code. It does not ship a fixed board library, except for the benchmark set in 11.3. Spam-tier generation needs up to 625 candidate solves, which at 4x4 speeds is well under a second on an iPhone, but it runs off the main thread with a brief "generating" state to be safe.

## 6. Commonality and study value

### 6.1 Seen percentage is an input, not an answer

The simulation gives P(word appears) per grid size and tier. Ranking study material by that alone produces a list of words you already know, since common words are common precisely because you have seen them a thousand times. Seen percentage is one factor among five.

### 6.2 Study value

Study value is deliberately a simple product of quantities that are all directly measurable. The earlier draft included a findability term and a learning-cost denominator; both are cut, because neither can be fitted from data the app collects, and a denominator described as "near zero" makes the whole expression explode.

```
StudyValue(w) = Σ_tier  P(tier) · P(appear | tier) · P(capacity | tier) · points(w) · (1 − belief(w))

P(capacity | tier) = 1 − min(1, words_on_board(tier) / your_word_count(tier))
```

| Term | Meaning | Source |
| --- | --- | --- |
| `P(appear \| tier)` | Seen percentage | Simulation (5.3) |
| `P(capacity \| tier)` | Would you have had a spare swipe for it? | Board density vs your word count. About 0.6 on sparse Casual, near 0 on Spam. |
| `points(w)` | From the scoring table | Fixed |
| `belief(w)` | Your known-word belief | Player model (8.1) |

The `P(capacity)` term is what makes this different from a frequency-ranked word list, and it encodes 3.5: a word that only ever appears on Spam boards is nearly worthless to learn, because on a Spam board you had 900 words and no time. A word that shows up on sparse Casual boards converts to real points, because there every word you know gets used.

This systematically shifts the list toward words that appear on bad boards, which is exactly the stated need.

**Additive family members bypass this ranking entirely.** An additive extension of a stem you already own is ranked by `P(reachable) · points`, with no capacity term, because it costs no search and therefore competes with nothing. These sit at the top of the queue by construction.

### 6.3 Unfriendly words

The brainstorm correctly identifies unfriendly words: common, worth points, but isolated, so hard to spot in play. Define friendliness as the inverse of `isolation` from 4.1, averaged over simulated appearances.

Unfriendly words are handled differently rather than demoted:

- They are never taught as isolated flashcards, because that does not transfer. They are taught in a **shape context**: "CONTE, MONTE, RONTE-family, look for -ONTE with a loose first letter."
- They get more aggressive board-based reinforcement (Section 11), because for these the bottleneck is recognition speed, not knowledge.
- If a word is both unfriendly and appears mostly on dense boards, it is dropped from study entirely. It will never pay for itself.

### 6.4 Inflection handling

A word's study value is shared with, not duplicated across, its inflections. ELATE, ELATES, ELATED, ELATER, ELATERS should not occupy five slots in a study queue. They collapse into one family entry (Section 7) with a single scheduling slot, and the app teaches the **stem plus the live endings** rather than five strings.

The exception is when an inflection is materially harder than its base (ELATER is not obvious from ELATE), in which case it gets its own entry inside the family and can be scheduled separately.

## 7. Word families

### 7.1 Two kinds of family, and why both are needed

The brainstorm defines a family as words sharing a common set of letters, anywhere in the word. That is right, but it is an orthographic definition, and the reason families are valuable in play is **motor**: you swipe the shared part once and vary the ends. So the app carries two definitions.

**Lexical families** are board-independent and computed offline. A family is a set of words sharing a contiguous substring (the stem), where the stem is long enough relative to the words. ELATE / ELATER / ELATERS / GELATES / DELATES all contain ELATE. This is what the browse and study UI is organized around.

**Board-path families** are computed per board at solve time, and this is the version that matters for review and drills. Two words are in the same board family if their paths share a contiguous sub-path of length ≥ 3. This catches things lexical families miss entirely: two unrelated words that happen to run through the same four cells are, in play, one motor pattern and one look.

Board-path families are strictly better for post-game review, because they describe what your hand actually had to do. Lexical families are better for study lists, because they survive across boards. The app uses each where it belongs.

### 7.2 Family strength

```
strength(F) = coherence(F) · log2(1 + |F|) · value(F) / 2200

coherence(F) = mean over members of  len(stem) / len(w)
value(F)     = mean over members of  max(points(w), 800)
```

Dividing by 2200 (the points of an 8) normalizes strength to roughly \[0, 3\]. **High-strength means ≥ 1.2**, and that threshold is used everywhere the phrase appears.

A family is only surfaced if all of these hold:

1. `|F| ≥ 3`, or `|F| = 2` with both members 6+ letters.
2. `coherence ≥ 0.65` **and** `len(stem) ≥ 4`. The absolute floor matters: coherence alone admits a 3-letter stem inside a 5-letter word, which is the noise this filter exists to remove.
3. At least two members are 5+ letters.
4. The stem appears on at least 0.5% of boards in some tier. This is the ECCHYMOSIS filter: perfectly coherent family, stem almost never on a board, never shown.
5. At least one member is `additive`. A family made entirely of mutating forms has no free-points value and belongs in the misswipe track instead.

### 7.3 Affix grids

For each stem, precompute which affixes produce valid CSW21 words and which do not. Both halves are stored: the valid half is points, the invalid half prevents misswipes.

**Affix application is a string operation, not concatenation.** This has to be specified or the whole block is unimplementable. Generation rule, applied in order, with the result checked against the DAWG:

```
stem ends in E,  affix starts with a vowel   → drop the E      PRATE + ING → PRATING
stem ends in Y,  affix is ER/EST/ES/ED       → Y becomes I     SANTY  + ER  → SANTIER
stem ends in CVC, affix starts with a vowel  → double the C     BAT    + ING → BATTING
otherwise                                    → concatenate     PRATE  + R   → PRATER
```

Each generated form is then classified by comparing its path requirements against the stem's path:

| Class | Condition | Value |
| --- | --- | --- |
| `drop-terminal` | a contiguous sub-path of the word's own path, trimmed from either end (see 7.6) | **Guaranteed** free points. Pathable by construction, P = 1.0. Ranks above everything below. |
| `additive` | stem's cells all used, in order, plus new cells | Free points *if reachable*. Extends the path. |
| `cellmate` | same cells, different path (see 7.6) | Free points *if pathable*. Reuses the path. |
| `mutating` | stem's cells not preserved (letter dropped or changed) | Misswipe prevention only |
| `dead` | not a valid word | Misswipe prevention only |

`drop-terminal` is the only class whose value is unconditional. `additive` and `cellmate` are both contingent on a probability that has to be measured, and everything below them is worth nothing in points.

**Affix set:** -S, -ES, -ED, -ER, -ERS, -EST, -ING, -IER, -IEST, -IERS, -Y, -AL, -IC, -OUS, plus single-letter and common multi-letter front extensions (A-, BE-, DE-, EN-, OUT-, OVER-, RE-, UN-). The set is config, not code, and should be revised once real data shows which affixes actually generate misswipes for you.

Display leads with the shared part, since the pattern is the thing being learned. Additive forms are shown in the points colour, mutating and dead forms in the warning colour, because they are different skills:

> **PRATE-** · R ✓ · RS ✓ · S ✓ · D ✓ · ~~IER~~ · ~~IEST~~ *mutating:* PRATING ✓
>
> **-PATERS** · E ✓ · S ✓ · ~~O~~ · ~~A~~

### 7.3.1 Which grids are worth drilling

Rank by two things only, both of which come from data the app has:

1. **Personal misswipe history.** A stem you have actually guessed wrong goes to the front, immediately. This is the strongest possible signal and it needs no model.
2. **Additive yield.** Number of additive forms weighted by `P(reachable)` and points. Grids with three additive extensions are worth far more than grids with one.

The earlier draft proposed ranking by deviation from a predicted-validity model fitted on stem shape and part of speech. That is cut. CSW21 ships no part-of-speech data, "stem shape" was never defined, and it put an unspecified classifier in charge of ordering the entire curriculum. Until there are enough personal misswipes to rank on, seed the queue by additive yield alone.

### 7.5 Choosing the level: which stem is the teaching unit

Stems nest. Every word ending in -LLERS also ends in -ERS, which also ends in -RS. Showing you every word on the board ending in -RS is useless; showing you the -LLERS set is useful. The spec needs a rule that produces the second and never the first, and length alone is not it.

The test is what the pattern tells you **when you spot it on a board**, and it comes out of simulation directly:

**Condition 1 — conditional enumerability.** `E[members findable | stem path present]`, measured per tier. For -RS on a good board this is 30 or more: you cannot check them all, so noticing -RS gives you nothing to act on. For -LLERS it is typically 2 to 5, which you can run through in a couple of seconds. Target range 2 to 6.

**This condition governs whether a stem works as a hunting cue, and nothing else.** It decides what the app tells you to scan for on a board. It does not decide what is worth studying, and the earlier hard cap of 10 members was wrong for exactly the reason that a 40-member family where you know all but two is one of the best study items in the app: you need two words, not forty.

**Condition 2 — path share.** `len(stem) / mean len(member) ≥ 0.65`, already in 7.2. A 2-letter stem inside a 7-letter word is 0.29 and fails, which kills -RS a second time.

**Condition 3 — closure.** Over the stem containment lattice, if a longer stem has the same member set as a shorter one, keep only the longer: it is more specific and shares more path. This is closed-itemset mining over stems and it collapses chains like -ATERS / -EATERS where nothing is gained by the shorter form.

### 7.5.1 Residual, not size, gates study

What makes a family worth drilling is what is left in it **for you**. That is a personal, moving quantity:

```
unknown(F)  = { w ∈ F : belief(w) < 0.35 }
owned(F)    = { w ∈ F : belief(w) > 0.65 }

residual(F) = Σ_{w ∈ unknown(F)}  points(w) · P(reachable | stem present)

drillable(F) ⟺  1 ≤ |unknown(F)| ≤ 8  AND  |owned(F)| ≥ 2
```

No ceiling on `|F|`. A 40-member family with two unknowns is drillable and ranks high, because `residual` is large relative to the effort of learning two words. The `|owned| ≥ 2` condition is what makes the item cheap: you already have the stem, the motor pattern, and the habit of looking there.

The drill shows the **residual, not the family**. You are not re-reading 38 words you know to get to the two you don't.

This makes drillability dynamic in a useful way. A large family starts undrillable because everything in it is unknown, becomes a sequence of study items as you chip at it, and then converts into a high-value residual item once you own most of it. Families move in and out of the queue as belief updates, which is correct: the thing worth your time this month is not the thing worth your time next month.

The `|unknown| ≤ 8` bound stays, but it is a bound on one sitting's work, not on the family. A family with 30 unknowns is not rejected; it is split into batches of up to 8 and worked across sessions, ordered so the highest-value members come first.

What survives is roughly the 4-to-6-letter band: -LLERS, -NTERS, -EATER, -ANTED. What does not survive is -S, -ED, -ERS, -ING as standalone units. Those still exist as affixes inside an affix grid (7.3), where they are attached to a specific stem and the member set is bounded by construction. The distinction is that -ERS is a question you ask about PRATE, never a pattern you hunt for on its own.

**In the browser** (12.2), stems still nest and the chain is shown as a breadcrumb, so you can walk from -LLERS up to -ERS to see the wider set when you are exploring. But drills and scheduling only ever operate on units that pass the enumerability test. Broad stems are navigation, not material.

### 7.6 Cellmates: same letters, different path

SEATERS and SAETERS sit on the same seven cells. Once you have found one, the cells are already located and the only open question is whether a second path through them exists. That is nearly free, and it is free on a **different axis** from additive affixes: additives extend the path, cellmates reuse it.

Four relations, all precomputed over the dictionary:

| Relation | Example | Notes |
| --- | --- | --- |
| **Anagram** | SEATERS / SAETERS / TEASERS / EASTERS | Identical letter multiset. The strongest measured case. |
| **Drop-terminal** | CANTERED → CANTER | Letters removed from either end. The result is a contiguous sub-path of the original path, so it is **always pathable**, P = 1.0 by construction. No measurement needed. |
| **Drop-interior** | CANTERED → CANTRED | A letter removed from the middle. Requires adjacency the original path never needed — CANTRED needs T adjacent to R, which CANTERED's own path (T→E→R) does not provide. Not guaranteed; measured. |
| **Add-one** | CANTER → CANTRED | Needs one adjacent free cell, same condition as an additive affix. |

An earlier draft of this table had a single "drop-one" relation claiming it was always available if the longer word was. That is true only for the terminal case, and the example given was the interior one. The split above is the fix, and it matters for more than correctness.

**Drop-terminal is the only guaranteed-free relation in the whole spec.** If you have the long word, the short one is already on the board, with no probability attached and no risk. It is therefore its own study class (7.3), ranked above both `additive` and `cellmate`, and `cellmate_stats` reports how many drop-terminal words a typical board's found-set implies — a count, not an estimate.

**For every other relation the value condition is not automatic.** An anagram's letters are present, but adjacency constrains order, so a valid path may not exist. `P(cellmate has a valid path | word has a valid path)` has to be measured in simulation, per relation and per length. Expect it to be high for 5s and to fall off for 7+, where path constraints bite. Only pairs above about 0.5 are worth teaching.

**They are stored and taught as directed trigger pairs**, because that is how they are used in play: the common word is the trigger, the rarer one is the response. SEATERS → check SAETERS, not an undirected set. Direction is assigned by seen percentage.

This is a distinct study object from the affix grid and gets its own drill (10.4, cellmate check) and its own review line: a cellmate you missed on a word you found is the cheapest miss in the whole game, cheaper even than a missed additive extension, because you had already done the hard part.

### 7.4 The family gap, done carefully

The brainstorm asks for: if you got SANTERO and SANTERA but missed SANTERIA, show that. This is right and it is the highest-signal moment in review, because you demonstrably found the family and just didn't finish it.

Priority ordering for family gaps after a game:

| Priority | Pattern | Rationale |
| --- | --- | --- |
| 1 | Found ≥ 2 of a family, missed a 5+ member | You were there. Cheapest possible points. |
| 2 | Missed an entire high-strength family in a region you covered | Vision leak on a valuable pattern |
| 3 | Found the base, missed 2+ extensions | Ending-set blindness, very trainable |
| 4 | Missed an entire high-strength family in a region you never touched | Coverage problem, shown but framed differently |
| — | Missed 3- and 4-letter-only families | Suppressed unless the board was sparse and filler was correct |

That last row implements the brainstorm's instinct: do not nag about missed 3s on a good board, because skipping them was the right call. The suppression is conditional on tier, not absolute, so on a Casual board where filler was correct, missed short families do get shown.

## 8. Player model

Four sub-models, all fed by in-app play. They are the reason the app has to contain the game.

### 8.1 Known-word belief

A per-word belief in \[0,1\], updated as a logistic score. All constants live in `RulesetConfig` so they are tunable without a code change.

```
logit(belief) += weight(event)
belief = sigmoid(logit), clamped to [0.02, 0.98]
```

| Event | Weight |
| --- | --- |
| Swiped in a live game | +2.5 |
| Swiped faster than your median for that length | +1.0 additional |
| Present, in a region you covered, not swiped | −0.8 |
| Present, in a region with zero swipe-time | 0. No inference possible. |
| Found in a drill | +1.2 |
| Shown in review, acknowledged | +0.4 |
| Dismissed as 'I know this' in review | +1.5 |
| Invalid attempt on this string | −3.0 (belief that it is a word) |

Decay: the logit decays 3% per week toward the prior, doubled for words whose only positive evidence came from review rather than live play.

**Initial prior.** Fitted from length and corpus frequency, but that is weakest exactly where it matters for a top-50 player, since above a certain frequency threshold everything is known and below it frequency stops predicting much. So the app runs a **one-time 10-minute calibration** on first launch: roughly 200 stratified valid/invalid judgments sampled across frequency bands and lengths, fitting a personal frequency-to-knowledge curve. Worth ten minutes, because every StudyValue and every Vocabulary attribution leans on the prior for months before live play accumulates enough evidence to override it.

The distinction between rows 3 and 4 is why coverage tracking is load-bearing. Without it, every board would look like evidence that you don't know 800 words.

### 8.2 Throughput model

Fitted continuously from swipe timestamps:

- `swipe_a`, `swipe_b`: linear fit of entry duration against path length. **Measured in Phase 0**, before anything downstream uses them, because they feed Par, the misswipe pricing and the allocation bucket. The placeholder 0.30 + 0.08n in 3.2 is a guess and is probably wrong: a 161-word game in 80 seconds is 0.50s per word including search, which the placeholder cannot produce.
- `baseline_gap`: the 40th percentile of your inter-word gaps across the last 20 games on that tier. Gaps beyond it count as dead time. Defining it off a percentile rather than an undefined 'productive streak' makes it computable.
- `hunt_decay(t, tier)`: points per second while hunting. Fitted only from longs-only drills, for the censoring reason in 3.2.
- `filler_rate(tier)`: points per second while harvesting off already-swiped paths.

**Filler classification.** A find is filler if its path overlaps a path you swiped in the previous 8 seconds by at least 3 cells, **regardless of its length**. The earlier draft restricted this to words of 4 letters or fewer, which mislabels a 5 harvested off a path you just swiped as a hunt find, and biases the picture in the direction that flatters you. Length and filler status are independent dimensions and are reported separately.

This classification is a heuristic and is shown in review so you can check whether it describes your play correctly.

### 8.3 Touch model

Demoted from its own diagnostic layer to a guard, for the reason in 3.3: on a grid this small, region-level blindness is mostly not real.

Per game, record which cells each swipe used and when. Time is attributed to a cell by entry timestamp, each cell credited the interval until the next cell is entered. That gives one thing the model needs:

- **Touched or not.** A word whose cells were never used all game produces no evidence about your vocabulary, and the belief update in 8.1 has to skip it. Without this guard every board would look like proof you don't know 800 words.

Two secondary uses, both cheap and neither load-bearing:

- **Dwell distribution.** Where your time actually went, shown in review as context for the family-capture number rather than as a finding of its own.
- **Hand-position check.** Rotate the board 180 degrees on a random 25% of games. If a persistent cold corner turns out to follow the hand rather than the grid, it is a thumb-reach problem and the fix is grip or device position, not training. Worth the near-zero cost of implementing, and worth nothing more than a line in the diagnostics screen.

The region-sweep drill and the cumulative blind-spot map that earlier drafts built on this are cut.

### 8.4 Misswipe log

Every rejected sequence is recorded with its letters, path, and timestamp. Aggregated:

- Sequences attempted 3+ times across games are surfaced as **"not a word"** items, with the nearest valid neighbors shown so the correction sticks ("REATION is not valid; you're thinking of REATTAIN / CREATION").
- Systematic patterns are detected and named, since these are more useful than individual words: over-applying -ERS, assuming -ING on verbs that don't take it, inventing plurals of mass nouns.
- Misswipes are also a **positive** signal: a misswipe usually means you saw a shape, which is evidence of board vision even when the word was wrong.

## 9. Post-game review

Review runs at two levels. The earlier draft put a seven-card review after every board, which would mean 5 to 7 minutes of reading against 4 to 7 minutes of playing, and the player-model updates would all live inside the part people skip. Split it instead.

### 9.1 Design rules

1. **Board first for spatial leaks** (coverage, vision), **list first for study material.** Studying is not a spatial task, which is why the family browser in Section 12 is a list.
2. **Per-board review is 15 seconds.** Session review is the long one.
3. **Hard cap of 3 items per board, 8 per session.** A board can have 900 words; showing 40 of them is the same as showing none.
4. **Every item is an action:** add to study, or dismiss as known. Dismissal is a real signal worth +1.5 in the player model.

### 9.2 Per-board verdict (15 seconds, after every board)

One card. Score, tier percentile, and one sentence naming the largest bucket with its cost. Up to three tappable items underneath, then straight into the next board.

> **47,300 · 62nd percentile on Good Casual** *Biggest leak: 8,400 points in additive extensions of stems you already swiped.* EPATERS · SANTERIA · PRATERS

That is the whole per-board experience. Anything longer gets skipped, and a skipped review teaches nothing.

### 9.3 Session review (once, after all boards)

Aggregated across the session's boards, which also reduces the single-board variance the dashboard already has to fight.

**Card 1 — free points.** Additive extensions you missed on stems you demonstrably swiped. Highest priority in the app. Shown as the stem's path on the board with the extra cell lit.

**Card 2 — invalid attempts.** Grouped by affix pattern rather than listed individually. Total seconds, converted at your tier rate. Links to the affected affix grids.

> 11 invalid attempts · 13.4 seconds · 9,100 points at your Good Casual rate of 680/sec Pattern: -IER on stems that don't take it (3 stems)

**Card 3 — families you never opened.** High-strength families that were present on the session's boards where you found nothing at all. These are vocabulary items, not vision items, and they are the direct output of the family-ignorance failure in 3.3. Ranked by `strength` and seen percentage, capped at four, each one addable to the queue in a tap.

**Card 4 — rate curves.** Points per second across each board, with filler shading. Descriptive only. No optimal-crossover line, for the censoring reason in 3.2.

**Card 5 — vision misses.** Up to four known words in regions you covered, as paths, with the timestamp you were last in that region.

**Card 6 — length distribution.** Your word lengths against the session's board potential. The clearest single picture of the 3-letter habit.

Full solutions stay one tap away via the board explorer (12.3) but are not part of the flow.

### 9.4 What enters the study queue

| Source | Item | Priority |
| --- | --- | --- |
| Missed additive extension | Affix grid for that stem | Highest |
| Repeated invalid attempt | Affix grid, dead affixes emphasized | Highest |
| Missed high-strength family (strength ≥ 1.2) in a covered region | Family card | High |
| Vision miss on a known word | Board drill, not a word card | Medium |
| Expensive vocabulary miss | Word card, only above the StudyValue threshold | Low |
| Coverage miss | Nothing. This is a scanning drill. | — |

That last row matters: a coverage problem is not fixed by learning the words you missed, and generating word cards from it would flood the queue with noise.

## 10. The main loop

The app is organized around **family batches**. A batch is a small set of related word families the player is currently learning. Everything else in the app serves the batch you are on.

### 10.1 The cycle

The session opens with play, not with reading. Acquisition happens in drills, where throughput is high; boards are for conversion, where throughput is low but transfer is real. The earlier draft had this backwards, using the expensive channel (boards, \~6 families a week) for the cheap task (learning which affixes are valid).

```
  MIN 0   ─ open the app, you are swiping. No intro screen, no batch screen.
            Board 1 at whatever tier is scheduled.

  MIN 2   ─ 15-second verdict. Straight into board 2. Then board 3.

  MIN 5   ─ three boards played, three verdicts seen. The app now has this
            session's misswipe log, coverage maps and latencies. It has said
            nothing about curriculum yet.

  MIN 5-10 ─ ONE drill block, chosen from this session's evidence.
             Misswiped -IER twice → affix grid block: 60-100 valid/invalid
             judgments at ~1.2s each. This is where vocabulary throughput
             actually lives. New stems enter here, not on a reading screen.

  MIN 10-14 ─ optional: two more boards carrying the stems you just drilled,
              plus scheduled retired families. The conversion step, and the
              smaller half of the session.

  END      ─ one session review (9.3), once.
```

**Short-day policy.** A 4-minute day is one board plus one grid block, graded normally. The earlier draft's card-review fallback graded at reduced weight, which penalizes you for having a life and makes the schedule drift on exactly the days you most need it to hold.

Throughput at this shape is roughly 40 to 80 stems a week rather than 6, and the affix grid does the work that the reading screen used to pretend to do.

Retired families do not disappear. They are re-injected into later boards at spaced intervals (11.2), so a family learned in week one shows up in week three inside a board about something else.

### 10.2 Why boards, not flashcards

A flashcard teaches you that EPATERS is a word. It does not teach you to see EPATERS while your finger is already on PATERS with 40 seconds left and 600 other words on the board. The second skill is the one that scores points, and it only trains under time pressure on a real grid.

So the batch's boards are **real ranked-distribution boards that happen to contain the target families**, not contrived puzzles. The player should not be able to tell, mid-game, which board is a training board. If the target family is obvious, the transfer to ranked play is worthless.

### 10.3 Batch composition

A batch is 4 to 6 families, selected to be:

- **Coherent but not identical.** Families that share a pattern (all -ER/-EST ambiguity, all front-extension families, all one letter-cluster) so the batch teaches a generalizable shape, not six unrelated facts.
- **Mixed difficulty.** One or two families you partly know already, so the batch starts with wins and the completion instinct has something to attach to.
- **High `StudyValue`** per Section 6, with the ambiguity score from 7.3.1 pushing misswipe-heavy stems forward.
- **Board-compatible.** Families whose stems can actually be co-embedded on a 4x4 or 5x5 without distorting the board. Some family pairs cannot share a grid and the batch builder has to check this at composition time, not at generation time.

### 10.4 Drills

Drills are short, 2 to 4 minutes, and are prescribed by what the review found. They are not a menu the player browses, though all of them are available manually.

| Drill | Trains | Trigger |
| --- | --- | --- |
| **Affix grid** | Live and dead affixes for a stem, timed. Valid/not-valid under 1.2s. | Misswipe leak, or a new stem entering the queue |
| **Branch completion** | A stem is shown lit on a board. Find every additive extension before the timer. | Family blindness: took the stem, missed branches |
| **Cellmate check** | A word is shown found on the grid. What else do those same cells make? | Missed an anagram of a word you found |
| **Family sweep** | A board with a target family present. Find every member. | Missed family members across a session |
| **Front extension** | Given a stem on a grid, find the extended forms. | Missed a front-extended word like EPATERS |
| **Longs only** | Full 80s board, words under 5 letters rejected | Allocation leak, and the only uncensored estimator of hunt-rate decay (3.2) |
| **Swipe budget** | 80s board, capped at 60 submissions | Filler habit |
| **Tier read** | 8 seconds to look at a board, then call its tier | Judging early whether to hunt or farm |
| **Misswipe autopsy** | Your own repeated invalid attempts mixed with real words, forced binary call | 3+ repeats of a sequence |

The first five carry the curriculum. Longs-only doubles as a measurement instrument and should be scheduled weekly per tier whether or not a leak triggers it.

The first four carry the curriculum. Longs-only doubles as a measurement instrument and should be scheduled weekly per tier whether or not a leak triggers it.

The first three carry the batch. The rest fire only when their leak shows up, and the app should be willing to prescribe nothing on a clean day rather than inventing work.

## 11. Board generation and scheduling

### 11.1 Constrained generation

Training boards must contain target families while remaining indistinguishable from ranked boards. The algorithm:

1. Pick the target families for this board (1 to 3 from the active batch, plus 0 to 2 spaced-review families from retired batches).
2. Lay each family's stem as a self-avoiding path on the grid, chosen so the required extension cells stay free. If two stems can share cells, prefer that: overlapping stems produce the dense family clusters that real good boards have.
3. Fill remaining cells from the ruleset's letter distribution.
4. Solve. Verify every target word is actually present and reachable.
5. Check the board's total points against `board_norms` for the intended tier. If it lands outside the tier's middle 80%, reject and retry.
6. Run the tier's best-of-N on top, over candidates that all satisfy steps 1 through 5.

Step 5 keeps these boards honest. Embedding a family raises density, so without the norm check every training board drifts toward Spam and you stop learning how Casual boards feel.

**Infeasibility fallback**, applied in order, because constrained Spam generation can fail outright: drop to one target family, then relax the norm check to the middle 95%, then drop the tier requirement and serve the board at whatever tier it lands in, labelled honestly. Never silently serve a board that misses its targets.

**Acquisition boards and measurement boards are different.** The earlier draft mirrored ranked (20/50/30) for everything, which contradicts 6.2: `P(capacity)` is near zero on Spam, so injecting a family into a Spam board teaches something the model itself says is worthless there.

| Purpose | Tier mix |
| --- | --- |
| Acquisition (carrying target families) | 60% Casual, 40% Good Casual. No Spam. |
| Measurement (benchmarks, dashboard feed) | Mirrors ranked, 20/50/30 |

Never use one board for both. A board that is teaching you something is not a board you can measure yourself on.

**Constrained Spam generation must be benchmarked in Phase 1, not Phase 4.** Up to 625 candidates, each passing a 60 to 90% rejection filter, is potentially thousands of generate-solve cycles, and the "under 1 second" figure in 14.4 is the unconstrained number. If it turns out to cost 10 seconds, the fallback ladder above is the product, not an edge case.

### 11.2 Spaced repetition over boards

Scheduling is FSRS-style but the review event is **a live board containing the family**, not a card.

- Each family carries FSRS stability and difficulty. Initial stability is 1.5 days for a family with any prior positive evidence, 0.5 days otherwise; initial difficulty 5.0 on the standard 1–10 scale.
- On the due date, the family is injected into the next acquisition board as a background family. You are not told it is there.
- Grading comes from play, with explicit latency thresholds:

| Outcome | Grade |
| --- | --- |
| All members found, each within 2.0s of the previous family member | Easy |
| Most members found, any latency | Good |
| Base found, extensions missed | Hard |
| Family missed entirely, region covered | Again |
| Family missed, region never covered | No grade. Reschedule at the same interval. |

**Graduation is a positive test, not the absence of one.** The earlier draft retired a family when it was found "with no misswipe on its dead affixes," which graduates on a non-event: if you never attempt PRATIER, no evidence exists either way. Replace with two conditions that both have to be observed:

1. The affix grid answered correctly, live and dead affixes both, under 1.2s per judgment.
2. At least one live find of an additive member on a board you had not seen.

Card-based review still exists for days with no play time, and it grades normally per the short-day policy in 10.1.

### 11.3 Benchmark boards

Because the board is identical, score differences are pure skill signal with no board-luck variance. Memorization is a real risk over a long enough horizon, so:

A fixed set of **14 boards** (7 per grid size, spread across tiers) played on a **2-week rotation**, two or three per sitting. Never used for training. The earlier draft's 6 boards every 3 to 4 weeks gives about 17 data points a year, which is far too sparse to see anything.

Because the board is identical, score differences carry no board-luck variance, which makes this the only trustworthy progress signal in the app.

Benchmark results are the only numbers in the app that are trustworthy for "am I actually getting better," and the progress dashboard treats them differently from ordinary game stats.

### 11.4 Anti-memorization

Ordinary training boards are never repeated. The generator keeps a hash of every board served and rejects collisions. Similar-but-different is the goal: the same family, a different grid, a different position, different surrounding letters. Repeating a grid teaches the grid, which is worth nothing in ranked.

## 12. Search and browse

The structured loop covers daily practice. This section covers the other mode: sitting down and digging through words directly, which a strong player will want and should not have to leave the app for.

### 12.1 Word search

Query model, all combinable:

| Filter | Example |
| --- | --- |
| Length | exactly 6, or 5–7 |
| Starts with | `PRAT-` |
| Ends with | `-ATERS` |
| Contains | `-LAT-` |
| Pattern | `P?AT??S` |
| Anagram of | letters of PRATES, any order |
| Subword of | words findable inside PRATERS |
| Seen % | above 2% on Casual 4x4 |
| Points | 1,400+ |
| My status | unknown / learning / known / leaked recently |
| Family | members of a given stem |

Sort by seen percentage (per tier and grid size, selectable), length, points, alphabetical, study value, or your own miss rate.

Implementation: SQLite FTS5 for the text side, plus precomputed sorted-letter keys for anagram lookup and a suffix index for ends-with. All local, all instant.

### 12.2 Family browser

The main browse surface, and the one that should feel best to use. Organized by stem, showing the ending grid with live and dead endings, the family's strength and seen percentage, and your personal status per member.

Entry points into it:

- **Common families I'm missing.** Ranked by `StudyValue`, the default landing view.
- **Families I've leaked.** Families where I missed a member in a real game in the last 30 days.
- **High-ambiguity stems.** Where the dead affixes are surprising. The misswipe prevention list.
- **Cellmate pairs.** Anagram and drop-interior pairs above the path-probability threshold, shown as trigger → response. Drop-terminal pairs are listed unconditionally, since they carry no threshold to clear.
- **Adjacent to what I know.** Families sharing a stem shape with families already graduated, the cheapest possible expansion.

Within a family, the breadcrumb shows where the stem sits in the containment chain (-LLERS under -ERS under -RS), so you can widen the view when exploring. The enumerable level is what the app tells you to hunt for; drills target your residual in the family, whatever its size (7.5.1).

Any family can be pushed into the next batch manually, or drilled on the spot with a generated board.

### 12.3 The board explorer

Given any past board, the full solution with all the filters above applied to that board's words only, plus the ability to toggle any word's path onto the grid. Used after a game when the player wants to go deeper than the six review cards.

This is also where a board can be re-run as a drill, or sent to the generator as a "more like this" seed.

## 13. Progress dashboard

One screen, checked weekly rather than daily. Daily numbers on an 80-second game are mostly board variance and looking at them teaches bad lessons.

### 13.1 The four headline numbers

| Number | Definition | Direction |
| --- | --- | --- |
| **Tier percentile trend** | Rolling mean of your per-board percentile, by tier | Up |
| **Long share** | Share of points from 5+ words, by tier | Up on Good Casual and Spam |
| **Wasted seconds** | Invalid attempts plus dead time, per game | Down |
| **Affix grids owned** | Count graduated, and additive members per grid | Up |

Split by tier everywhere. A mean across tiers hides exactly the effect being trained, and improvement on Casual and improvement on Spam are different skills.

**Session position is recorded on every game** and shown as a covariate. Board 5 of a session and board 1 are not comparable, and a rolling mean that pools them will read as noise. If a fatigue effect shows up, the session-length policy should change rather than the numbers being explained away.

### 13.2 Benchmark track

A separate panel, updated only when a benchmark board is played. Shows score on each of the 6 fixed boards over time. This is the honest progress signal and should be visually distinct from the noisy rolling stats.

### 13.3 Diagnostics

Second screen, for when the player wants to know why:

- **Leak breakdown over time.** Stacked area of the six buckets from 4.3, as a share of the gap to Par. The story this tells over months is the app working or not working.
- **Length distribution vs Par's.** Two histograms overlaid. The clearest single picture of the 3-letter habit, and the one most likely to actually change behavior.
- **Blind-spot map.** Cumulative coverage heatmap across all games, normalized. Persistent cold zones are a real finding.
- **Crossover chart.** Your actual hunt-to-filler switch time versus optimal, per tier, over time.
- **Misswipe patterns.** Ranked list of systematic errors with counts and estimated time cost.

### 13.4 What is not on the dashboard

No streaks, no XP, no daily goal rings. The user is a top-50 player with a specific technical problem, and gamification would add noise and pressure to play when tired, which is worse than not playing. Word count appears only inside the length distribution, never as a standalone number.

## 14. Architecture

### 14.1 Modules

```
┌─────────────────────────────────────────────────┐
│  SwiftUI app                                    │
│  Play · Review · Batch · Browse · Stats         │
├─────────────────────────────────────────────────┤
│  Swift domain layer                             │
│  batch scheduler · player model · leak analysis │
│  FSRS · study queue                             │
├─────────────────────────────────────────────────┤
│  FluxCore  (C++17, static lib, C shim header)   │
│  DAWG · solver · generator · Par optimizer      │
│  family extraction                              │
├─────────────────────────────────────────────────┤
│  Storage                                        │
│  bundled: dawg.bin, stats.sqlite (read-only)    │
│  user: player.sqlite (GRDB)                     │
└─────────────────────────────────────────────────┘

offline, not shipped:
  simulator (same C++ core) → aggregation (Python) → stats.sqlite
```

The C++ core is deliberately the same code offline and on-device. A divergence between the simulator's generator and the app's generator would silently invalidate every statistic in the app, and that class of bug is very hard to notice.

Bridging: a thin C shim header, imported into Swift via a module map. No Objective-C++ layer needed. Data crosses the boundary as flat structs and index arrays, never as strings.

### 14.2 Swipe capture

The game view needs to record more than the final word. Per attempt:

- cell sequence, with a timestamp per cell entered
- submission time and result (valid, invalid, duplicate)
- time since previous submission
- whether the path was reversed or backtracked mid-swipe

Backtracking is worth capturing because it distinguishes 'I was unsure of the word' from 'I was unsure of the path', which are different problems with different fixes.

Sample at the cell-entry level, not at touch-move resolution. Storage stays small and nothing downstream needs finer granularity.

### 14.3 Schema sketch

**Bundled, read-only:**

```sql
word(id, text, len, points, sorted_key, family_id)
word_stat(word_id, grid, tier, p_appear, e_paths, p_capacity)
family(id, stem, coherence, strength, ambiguity)
family_member(family_id, word_id, affix, affix_type)
family_dead_affix(family_id, affix, affix_type)   -- the misswipe preventers
board_norm(grid, tier, pct, total_points, word_count, count_5plus)
```

**User, read-write:**

```sql
game(id, played_at, grid, tier, seed_word, board_letters,
     score, par, efficiency, ruleset_version)
attempt(game_id, seq, path, word_id, valid, t_start, t_submit)
leak(game_id, bucket, points, detail_json)
word_belief(word_id, belief, last_confirmed_at, source)
family_sched(family_id, stability, difficulty, due_at, state)
batch(id, started_at, graduated_at, family_ids)
misswipe(text, path, count, last_seen_at, resolved)
throughput(fitted_at, swipe_a, swipe_b, baseline_gap,
           hunt_decay_json, filler_rate_json)
coverage(game_id, cell_index, time_weight)
```

Boards are stored as their letter string plus the generator seed, not as solved word lists. Re-solving is sub-millisecond, so storing solutions would waste space for no gain.

### 14.4 Sizes and performance

| Item | Estimate |
| --- | --- |
| `dawg.bin` | 1.34 MB (measured, CSW21: 79,807 states / 191,740 edges) |
| `stats.sqlite` | 30–60 MB, dominated by `word_stat` |
| App bundle | under 100 MB |
| Board generation, Spam tier | under 1 second, off main thread |
| Solve at board load | under 5 ms |
| Par computation | under 50 ms, runs during the results animation |
| Full review generation | under 200 ms |

### 14.5 Platform notes

- iOS 17+, SwiftUI, no external dependencies except GRDB.
- Everything works offline. There is no server in v1.
- Swipe input needs a custom gesture recognizer over the grid, tuned for speed rather than accuracy: a player entering 120 words in 80 seconds is moving fast and sloppily, and the recognizer must tolerate that. This is worth prototyping first, because if the input feel is worse than Flux's you will not use the app, and every other feature depends on you using it.

## 15. Build order

Sequenced so that each phase is usable on its own and the riskiest unknowns get tested first.

### Phase 0 — Prove the input feel (1 week)

### Phase 1 — Core engine (1–2 weeks)

### Phase 2 — Playable with real review (2 weeks)

### Phase 3 — Family system (2–3 weeks)

### Phase 4 — The loop (2–3 weeks)

### Phase 5 — Par and leaks (2 weeks)

### Phase 6 — Polish

---

A SwiftUI grid with the custom swipe recognizer, a DAWG, and a timer. No scoring, no stats, no persistence. Play twenty 80-second games.

**Gates:** does it feel as good as Flux to swipe on? And measure `swipe_a` and `swipe_b` here, from those twenty games, before anything downstream consumes them. Also record 50 real ranked boards by hand while you are prototyping anyway, for the distribution check in 16.2 that the Phase 1 generator depends on.

### Phase 1 — Core engine (1–2 weeks)

C++ DAWG, solver, generator matching 2.3, all tested. Ruleset config as data. The offline simulator CLI. Affix generation with the mutation rules from 7.3.

**Gates:** solve a known board against a reference solver exactly. **Compute the reachability number** from 3.5: across simulated boards, given a stem path is present, how often is an additive extension both present and reachable? If that number implies 2 extra words a game rather than 10 or more, the family curriculum is the wrong product and Phases 3 and 4 should be redesigned before they are built. Also benchmark constrained Spam generation here.

### Phase 2 — Playable with real review (2 weeks)

Full game loop, swipe capture, scoring, persistence, tier percentile, the 15-second per-board verdict, and the invalid-attempt card. Plus the 10-minute knowledge calibration from 8.1, and board rotation on 25% of games from 8.3.

**Gate:** the misswipe number. This is where the 3.6 estimate is tested for real. Also compute your hit rate on speculative attempts and the break-even line from 16.6. The finding may be that you are not gambling enough, which is worth knowing before three drills are built on the opposite assumption.

### Phase 3 — Affix grids and families (2–3 weeks)

Full simulation run. Family extraction with additive/mutating classification, affix grids, the browser and word search, the free-points review card.

**Gate:** open the family browser and read the top 50 by StudyValue. Junk or useful? Only you can judge this, and it is the main quality risk in the project.

### Phase 4 — The loop (2–3 weeks)

Constrained acquisition boards, the grid drill at throughput, FSRS over families, graduation on the positive test, the session review.

**Gate:** run one full cycle. Does a stem drilled this week get found on a live board next week?

### Phase 5 — Optional, experimental

Par, Board Efficiency, the leak accounts, the crossover measurement via longs-only drills. All gated on the calibration check in 4.1, and none of it blocks a usable app.

### Phase 6 — Polish

Blind-spot map (once rotation data supports it), board explorer, diagnostics.

---

Phases 0 through 2 are about 5 weeks and produce something useful standing alone: a Flux clone that tells you what you misswiped, where you didn't look, and whether that game was good for you. Four load-bearing claims get tested inside those 5 weeks (swipe constants, letter distribution, reachability, misswipe cost), which is the point of ordering them this way.

## 16. Risks and open questions

### 16.1 Collins 21 licensing

CSW21 is copyrighted by Collins. Shipping the full word list inside an App Store app is a licensing question, not just a technical one. Options, roughly in order of preference:

1. Keep it personal: build with a development profile, sideload to your own device, never submit to the App Store. Removes the problem entirely and costs nothing given this is a solo tool.
2. License it, if Collins offers terms for small apps.
3. Use a permissively licensed list for any public release and accept that it does not match ranked exactly. This degrades the product meaningfully, since a trainer that disagrees with the game's dictionary teaches wrong answers.

Worth deciding early only because it determines whether the app can ever be shared with other Flux players.

### 16.2 The simulation is only as good as the generator

If the letter distribution is wrong, every seen percentage is wrong, and seen percentage feeds StudyValue, which orders the entire curriculum. The failure mode is quiet: the app will confidently teach a well-ordered list of the wrong words.

Mitigations: keep `ruleset_version` on every derived number, make the pipeline a single command to rerun, and sanity-check simulated board norms against real Flux boards you can record by hand. Fifty hand-recorded ranked boards would be enough to detect a badly wrong distribution, and that is worth doing before Phase 3.

### 16.3 Questions for the Flux developer

1. Exact letter distribution or dice configuration.
2. Whether the letter-variety adjustment on Casual and Good Casual is real.
3. Exact Collins 21 edition and any house additions or removals.
4. **Does re-swiping an already-found word cost time?** Not captured anywhere in this spec, and in fast play it is a real source of waste.
5. Whether an end-of-game export of board plus found words could ever exist. Even a copyable text blob would let the trainer ingest real ranked games.

Two questions previously on this list have been settled and removed: multi-path words count once toward board potential, and seeding happens before tier selection. Both are specified in 2.3 and neither is configurable.

### 16.4 Product risks

| Risk | Mitigation |
| --- | --- |
| Family quality is junk and the curriculum teaches nothing useful | Phase 3 gate is a manual read of the top 50. Be willing to throw out the scoring and hand-tune. |
| Par is miscalibrated and Board Efficiency becomes meaningless | Phase 5 gate. Fall back to raw rate by tier, which needs no model. |
| Training-board families become obvious and stop transferring | Norm check in 11.1, plus injecting retired families as background noise so no single family stands out |
| Time spent building exceeds time saved training | Phases 0–2 are self-justifying. Reassess before Phase 4. |
| The app becomes a replacement for playing ranked | Cap daily training boards. Ranked play is still the thing being trained for. |

### 16.5 Things deliberately left out of v1

Opponent modelling, ELO simulation, multiplayer, sharing family sets, and any hint system during live play.

One of these deserves a note rather than a dismissal. Flux is head-to-head with duplicates scored, so the win condition is score **difference**, and on Casual boards where both players clear most of the value the game turns on a handful of words, while on Spam it is a pure throughput race. Knowing which tiers you lose close games on would properly drive where practice time goes. That is unbuildable without a Flux export, which is why it is question 7 above rather than a v1 feature.

### 16.6 Misswipes may be correct play

The spec prices every invalid attempt as pure loss, and that framing may be wrong. A speculative swipe costs about 0.9 seconds and pays 1,800 if it hits. Against a filler rate of roughly 700 points per second, the break-even hit rate is about 35%. Above that, gambling on an uncertain suffix is correct.

So the app computes your actual hit rate on uncertain attempts and shows the break-even line rather than treating every misswipe as waste. The finding may be that you should attempt more, not fewer, and an app that cannot report that is structurally biased.

### 16.7 Data survival

The sideloaded-build option in 16.1 has a real cost the earlier draft ignored: a free developer profile expires every 7 days, a paid one annually, and months of play history would be sitting in a local SQLite file on a build that can stop launching.

Required from Phase 2: a one-tap export of `player.sqlite` to Files or iCloud Drive, an automatic weekly export, and a documented re-signing routine. Cheap to build, and the alternative is losing the only dataset that makes the app worth anything.

### 16.8 Migration

`ruleset_version` covers derived statistics, but nothing currently covers what happens to the FSRS schedule and the player model when a ruleset changes. Decide the policy before the first rerun: word beliefs carry over unchanged, family schedules carry over, and StudyValue simply recomputes. Any family that drops below the surfacing filters under the new ruleset is retired rather than deleted, so its history survives.

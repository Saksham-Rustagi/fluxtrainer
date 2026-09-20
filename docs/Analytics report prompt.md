# Analytics report prompt

One session, run in the FluxCore repo after Phase 1. It ingests the ranked export, measures against the spec, and produces the report. Paste into Claude Code.

---

## Goal

A single self-contained HTML report with embedded charts, plus the TSVs behind every figure. Audience is one person: a top-50 Flux player deciding what to train and whether `docs/SPEC.md` describes his actual game. Every chart must answer a question he would ask. Do not produce a chart because the data allows it.

Use both parts of the ranked export (9,034 games). Deduplicate on `createdAt` + `opponent.username` in case the parts overlap, and report how many rows overlapped.

### Grounding: read the sources, do not trust this prompt's restatements

Read `docs/SPEC.md` and `PHASE1_REPORT.md` before planning, and refer back to them rather than relying on what is quoted here.

- Where this prompt cites a spec section or a Phase 1 number, **the source is authoritative.** If they disagree, the source wins and you flag it. This prompt was written from memory of those documents and may be stale.
- The part-2 figures quoted throughout (the 3.97-to-4.34 length curve, the 0.643 family rate, the 62.6/37.4 grid split, the 18,005 missed words) are from a quick pass over part 2 only. **Recompute every one of them on the merged set** and report yours, not mine. Where they differ, yours is right.
- Refer to spec sections by number in the report rather than reproducing their prose. The reader has the spec.
- **Reuse the ingest artifacts and Phase 1 outputs. Do not re-derive them.** `data/ranked/` has the solved boards, presence table and belief estimates from the previous session; `runs/full` and `runs/m3-curated` have the simulation results. Solving 9,034 boards twice is wasted time.
- Where an analysis here duplicates something Phase 1 already measured by simulation, put the two side by side in the report. The whole value of this data is that it replaces simulated availability with observed play, and that comparison is the finding.

### The data

`ranked_data_MiningMath_part*.json`. Part 2 is 16.6 MB, 4,517 games, Feb to Sep 2026, seasons 3 to 10. **Get part 1 from the developer**; the export is 9,034 games total and everything below should run on the merged set.

```
{ username, totalGames: 9034, wins, losses, fetchedAt, part, partsTotal, gamesInThisPart,
  games: [ {
    season, wentFirst, createdAt, completedAt,
    yourScore, yourWordsFound: [str], wordsFoundCount,
    eloAtStart, eloChange, didWin,          // null on ties
    opponent: { username, score, wordsFound: [str] },
    board: { letters: "OVTSUNEAASOGTIEI", boardSize: 4|5, duration: 80 }
  } ] }
```

`letters` is row-major, 16 or 25 chars. `yourWordsFound` and `opponent.wordsFound` are in find order. Both claims are verified in section 0 before anything depends on them.

## 0. Verification, before any analysis

Report each of these explicitly. Several are already confirmed on part 2 but must be rechecked on the merged set.

1. **Board orientation.** Solve each board and confirm every word in `yourWordsFound` has a valid path under row-major. Report the unsolvable rate. If it is non-zero, try column-major and the eight dihedral transforms before concluding. A small residue may be dictionary drift (Flux may not be exactly CSW21) rather than orientation, so list the unsolvable words themselves, since that list is interesting in its own right.
2. **Scoring table.** Summing `1400+400(n-6)` over finds reproduced `yourScore` on 4,517 of 4,517 in part 2. Confirm on the merged set.
3. **Find order.** `yourWordsFound` is neither alphabetical nor length-sorted, and mean word length varies monotonically with position, so it is almost certainly chronological find order. Confirm it is not some board-position ordering: check correlation between list position and the board index of each word's first cell. **Everything in section 2 depends on this**, so if it fails, say so loudly and skip that section rather than producing wrong charts.
4. **`wordsFoundCount` equals `len(yourWordsFound)`** on all rows, so no truncation. Recheck.
5. **`didWin` is null exactly on ties** (12 in part 2). Confirm and treat ties as their own outcome, not as losses.

## 1. Time series (by season and by month)

Every series gets both groupings, with n per bucket shown and bootstrap confidence bands. Part 2 alone covers seasons 3 through 10 across Feb to Sep 2026.

**Series to plot:** mean score, word count, capture rate against solved board potential, Elo, win rate, length mix (3/4/5/6/7+ as shares, stacked area), distinct words found per game, cumulative distinct vocabulary, new-word rate.

**The confound, and it is serious.** Mean score rose from 49,507 to 54,474 across the four time quartiles of part 2 *while Elo fell from 1698 to 1525*. Those move in opposite directions, so at least one of three things is happening: the boards got richer, the opponents got weaker, or scoring changed between seasons. Any "I improved" conclusion is unsupported until board potential and opponent strength are controlled for.

So: plot every headline series **twice**, raw and residualized against solved board potential and opponent Elo. If the improvement survives the controls, that is a real finding. If it does not, that is a more important one.

**Recovering opponent Elo.** The export gives `eloAtStart` and `eloChange` but not the opponent's rating. Standard Elo inverts: `change = K(S - E)` with `E = 1/(1+10^((R_opp - R)/400))`. Fit K from the distribution of `eloChange` (it is likely a small integer set, possibly rating-banded), then solve for `R_opp` per game. Validate by checking that recovered ratings for repeat opponents are stable across games. If the fit is poor, fall back to opponent score as a strength proxy and say so.

**Season caveat.** Seasons may differ in rules, board generation or the player pool. Before pooling across them, test whether board potential and opponent Elo distributions differ by season. If they do, seasons are not comparable units and the monthly series is the trustworthy one.

## 2. Sequence analysis (the centrepiece)

Find order recovers most of what timestamps would have given. This section is the most valuable in the report.

**2.1 The length-by-position curve.** Mean word length against normalized position in the find sequence (deciles, and also absolute position for the first 25 finds, which is where the action is). Plot four curves on one axis: the player, all opponents, opponents who beat him by 10k+, and opponents who lost by 10k+.

Part 2 shows the player rising monotonically 3.97 to 4.34 while opponents peak early and taper (4.25 to 4.37 to 4.29) and strong opponents do it harder (4.45 to 4.62 to 4.47). Confirm on the merged set, then break it out by grid size, by tier, and by season. **The season split answers whether this is fixable**: if the opening curve has flattened over seven months, the habit moves; if it is identical in season 3 and season 10, it does not move on its own.

**2.2 Cost of the opening.** Quantify the gap in points. For each game, compute the player's actual points from the first N finds (N = 10, 15, 20, 25) and compare against a counterfactual where those N finds have the length distribution of strong opponents' first N, drawn from words actually present on that board. Report mean points forgone per game, and the share of losses where that gap exceeds the final margin. That last number is the headline: **how many games were lost in the first fifteen seconds.**

**2.3 Crossover.** Classify each find as family-continuation (shares a 3+ character substring with a find in the previous 5 positions) or fresh. Plot the fresh-find rate against position for player and opponents. This is the observable shadow of the hunt-to-filler transition from §3.2 and it needs no timing data. Report where each curve crosses.

**2.4 Run structure.** Distribution of family-run lengths (consecutive finds sharing a stem). Player against opponents. The consecutive-family rate is 0.643 against 0.629 in part 2, nearly identical, so the difference between him and stronger players is probably not scanning style. Confirm that, because it rules out a whole class of drills.

**2.5 Length transitions.** A Markov matrix over length classes (3, 4, 5, 6, 7+) for consecutive finds, player against strong opponents. Specifically: after a 6, what comes next? If the player follows long finds with shorts more often than strong players do, that is the filler habit at the transition level, which is a different and more trainable thing than the aggregate mix.

## 3. Spatial analysis

Requires solved boards and path assignment. Words with multiple valid paths are ambiguous; resolve by choosing the path assignment that minimizes total travel from the previous find's endpoint, and **report the ambiguity rate** so the reader knows how much is inference.

- Board coverage against find position: how much of the grid has been touched by find 10, 25, 50.
- Travel distance between consecutive finds, player against opponents. Low travel means working a region; high means jumping.
- Region revisit rate: does he return to a region after leaving it, and does the second visit yield anything?
- Cumulative heatmap of cell usage across all games, normalized by cell. §8.3 predicts this shows little, since the grid is small. Verify that rather than assuming it.
- Do missed high-value words cluster spatially, or sit inside regions he demonstrably worked? This is the §3.3 structural-versus-regional question, answered on real play.

## 4. Vocabulary and families

**4.1 Belief.** `found / present` per word, Beta-smoothed, using solved boards for presence. Report coverage (how many words have enough presence events), the belief distribution by word length, and how it shifts between the first and last quartile of the data.

**Weight presence by opportunity.** A word present on a 900-word board where he found 96 was never realistically available. Compute belief both raw and weighted by board density, and show how much the two disagree. The raw version systematically understates knowledge and should not be the one that ships.

**4.2 Pure vocabulary holes.** Words present many times and never once found, ranked by cumulative points forgone. Split by whether the word belongs to a family he does find (a branch miss) or stands alone (a true gap). These are two different curriculum items.

**4.3 Fragile knowledge.** Words found once or twice and then missed on later presences. If a word's find rate does not rise after its first find, nothing is being retained, which is direct evidence about whether a spaced-repetition system is even needed.

**4.4 Family completion.** For each board, group present words by stem. Given he found at least one member, what share of the family did he take? By family size, stem length, and tier. This is the §3.3 family-blindness number measured on real play rather than simulated availability.

**4.5 Affix-level misses.** Which affixes does he systematically fail to take when the extension was present and reachable? Rank by points forgone. §3.6 predicts suffix ambiguity is a major leak; this is the closest test available without misswipe data, since a systematically unclaimed affix is either not known or not trusted.

**4.6 Anagram sets.** For each letter multiset, how many members present, how many found. The top of the opponent-missed list in part 2 is almost entirely one cluster (STARE, TARES, ASTER, TASER, STEAR, REAST, NITES, NITER, RITES, TIRES, STIRE, RINES), so report anagram-set completion as its own metric and list the worst sets by forgone points.

**4.7 Learning curve.** For words first found in season 3, what is the find rate on subsequent presences through season 10? A rising curve means vocabulary sticks once acquired, which is the premise the whole curriculum rests on.

**4.8 Realized versions of the Phase 1 proxies.** Phase 1 measured *availability* by simulation and said so. These are the observed versions, and each must be reported beside its Phase 1 counterpart.

- **M1-real, the gate number.** Of the words present on a board that the player missed, what share were additive extensions of words he found on that same board? By extension length and by affix. This is what §15's gate actually wanted and it needs no player model, because the finds are observed. Phase 1's proxy said 5.5 extensions per found stem and 38 to 46% of findable words free; if the realized number is far lower, the family curriculum is worth less than Phase 1 concluded.
- **M2-real.** How often did he find one anagram of a letter set and miss another, by length? Compare against Phase 1's 0.414 pathability for 5s.
- **Drop-terminal-real.** How often did he take a long word and miss a shorter word contained in it as a contiguous subpath? These are guaranteed present, so every miss is pure vocabulary or pure inattention, with no probability term.
- **M3-real.** Given a stem present on the board, how many of its members did he actually find? Against the curated simulation figures in the Phase 1 report §4.1, which set the 3-to-4 letter usable band.

## 5. Boards and generation

- Real board potential distribution against `runs/full` simulated norms, per grid.
- Tier mixture fit and recovered weights against the stated 20/50/30.
- Real grid split (62.6/37.4 in part 2) against the stated 60/40, with a significance test.
- Seed detection: longest words present per board against the §2.3 seed tables, implied seed rate against the stated 50%.
- Capture rate against board potential, scatter with a fitted curve. **This directly tests §3.1's claim** that on rich boards capture percentage is meaningless. If capture falls steeply with potential, the claim holds and tier percentile is the right metric.

### 5.1 The letter distribution

This is §2.4 item 1, the assumption every Phase 1 number is provisional on, and this data resolves it. Observed marginal over part 2's 87,473 cells:

```
E 9.37  S 8.30  A 7.88  T 7.83  R 7.27  I 7.25  N 6.77  O 6.67  L 4.88  D 4.79
H 4.58  C 3.38  U 3.12  M 3.02  G 2.55  P 2.45  Y 1.94  F 1.93  B 1.82  W 1.71
V 0.99  K 0.87  X 0.20  Z 0.18  J 0.11  Q 0.11
```

**Do not paste this into the config as the generator's base distribution.** It is a post-selection marginal: every board here won a best-of-N ranked by total points, and that selection favours high-scoring letters, so the observed frequencies are biased away from the base distribution the generator samples from.

Fit it as an inverse problem: find the base distribution which, after the full generation pipeline including tier selection and seeding, produces a simulated marginal matching the observed one. Iterative proportional fitting or a gradient step on the 26 probabilities with the simulator in the loop. Report both distributions and the gap. **The size of that gap is itself a finding**, since it quantifies how much best-of-N distorts boards, which nothing has measured.

Then check for structure the config cannot express: are vowels spread more evenly across the grid than independent sampling predicts? If so Flux uses dice or a positional constraint and §2.4's dice hypothesis is live.

Finally, rerun the simulation under the fitted distribution and report which Phase 1 numbers move. Keep the old `ruleset_version` intact so both sets remain comparable.

## 6. Competitive analysis

- Win rate against board potential, grid, tier, opponent Elo, and time of day.
- Margin distribution. 2,590 of 4,512 games were decided by under 8,000 points at a 50.2% win rate, so most games are close and small improvements convert.
- **Marginal value regression.** Predict win probability from word count, long share, capture rate, board potential and opponent Elo. Report the marginal effect of one additional 5-letter word against one additional 3-letter word. This turns the curriculum into expected wins and tells him what a drill is actually worth.
- Repeat opponents: head-to-head records, and whether he does worse against specific players in a way that suggests a style matchup.
- Words opponents found that he missed, ranked by frequency and points, cross-referenced against anagram sets and families. Weight by opponent strength.
- **Overlap ratio**: share of his finds that the opponent also found. Low overlap on a board means they searched differently; high means the same words were obvious to both. Plot overlap against margin.

## 7. Session and fatigue

The export has `createdAt` and `completedAt`, so this is available and §13.1 explicitly wants it.

- Define sessions by gaps between `createdAt` (a gap over \~20 minutes starts a new session). Report the session-length distribution.
- Performance against position within session: score, word count, long share. If game 8 is worse than game 1, the session-length policy in §10.1 needs a number attached.
- Time of day and day of week against performance.
- Wall-clock duration is 114s median against an 80s game, so there is \~34s of overhead per game. Check whether unusually long gaps before a game (a fresh start) correlate with better or worse openings, which bears directly on section 2.2.
- `wentFirst` means the player sent the challenge out and an opponent accepted it later. It cannot mechanically affect the outcome, so treat the observed gap as a natural experiment rather than a game-mechanic effect. In part 2 it splits 2456/2061 and shows a 53.8% win rate against 50.1%, roughly 2.5 sigma, so it is borderline and worth resolving rather than assuming. Note that mean score was slightly LOWER on sent games (51,786 against 52,246) while the win rate was higher, which means the difference is on the opponent's side, not the player's. Two competing explanations, and recovered opponent Elo separates them cleanly: (a) opponent selection, where weaker players accept open challenges, which would show up as lower recovered opponent Elo on sent games and is the duller and more likely answer; or (b) readiness, where the player plays a game he initiated when he is warmed up and plays an accepted challenge cold. Test (b) directly against the section 2 opening curve: compare mean length of the first 10 finds on sent against accepted games, controlling for opponent Elo. If the opening curve differs, cold starts cost real points and warming up before ranked is worth something. If only opponent Elo differs, it is selection and nothing more, and say so plainly.

## 8. Statistical discipline

- Every chart shows n and uncertainty. No point estimates without bands.
- **Hold out a time-split validation set.** Mining 18,005 missed words and 26 letters and dozens of affixes will produce spurious patterns. Fit on seasons 3 to 8, validate on 9 to 10, and report which findings survive. Any curriculum recommendation that does not survive the split is not a finding.
- Correct for multiple comparisons on the per-word and per-affix rankings.
- State effect sizes in points and in win probability, not just significance.

## 9. Output

- `reports/analytics.html`: self-contained, charts embedded as inline SVG or base64 PNG, no external assets, readable top to bottom in one sitting. Structure it as: headline findings first (no more than five, each one sentence plus one chart), then sections in the order above, then an appendix of everything else.
- `reports/figures/*.tsv`: the data behind every chart, one file per figure, named to match.
- `reports/manifest.json`: input hashes, game counts, git SHA, generation timestamp.
- matplotlib is fine. Prefer clarity over decoration, label axes with units, and never use a dual y-axis.

Also write the reusable derived data to `data/ranked/`, since later phases consume it and nothing should have to re-solve 9,034 boards:

| artifact | contents |
| --- | --- |
| `games.parquet` | one row per game: board, grid, solved potential, tier posterior, score, capture, word count, length mix, opening length, Elo, recovered opponent Elo, session id, timestamps |
| `presence.parquet` | word x game presence and found flags, partitioned by grid. The base for belief and every miss analysis. |
| `belief.tsv` | per word: present count, found count, raw and density-weighted belief, time-sliced variants |
| `missed_by_opponent.tsv` | words opponents found that he did not, with counts, points, anagram-set and family membership |
| `fitted_distribution.json` | the inverse-fitted base distribution, the observed marginal, and the gap |
| `board_norms_real.tsv` | real board potential distributions for comparison against `runs/full` |

## 10. What is not in this data

State this plainly in the report so nobody builds on sand: no misswipes, no within-game timestamps, no paths. So §4.3's Account B (dead time, invalid attempts, allocation) and §3.6's claim that suffix ambiguity costs 15 to 20% of the clock remain entirely unmeasured, and still require Phase 0 and Phase 2. Find order is a strong substitute for timing in sequence analysis, but it gives ordinal position, not seconds, so no rate in points per second can be computed from it.

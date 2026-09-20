# Build plan

Replaces §15 of the spec. That version was written before any measurement, and three things have changed since.

**The game's client source is available.** Recreating the board, the swipe recognizer and the timing no longer carries the risk §15 built Phase 0 around. The hard part is now a porting job, not a design gamble.

**FluxCore v3 reproduces real boards.** Median potential within 2% on both grids, letter marginal at TV 0.020, no triples. Board generation is solved.

**The diagnosis is measured, not assumed.** Two interventions are priced and holdout-validated. The curriculum that the old plan spent five weeks on is the *least* certain part of the value, not the most.

---

## Principles this ordering follows

1. **The curriculum is why this app exists.** The two highest-value measured interventions barely need software: a warm-up board is one practice game before you open Flux, and the opening fix is mostly knowledge you already have. Deciding *which* words are worth learning, and teaching you to see them on a board, is the part that cannot be done by hand. It goes first.
2. **Vision is taught through the words, on live boards.** Not as a separate drill and not on flashcards. You take a 5+ letter word 74% of the time when it extends something you already found and about 1% otherwise, so a word learned in isolation is a word you will not find. The unit of teaching is a hook plus its branches, shown on a real board under time pressure.
3. **Logging comes free with the clone.** Misswipes, dead time and duplicate re-swipes exist in no export, and §3.6's claim that suffix ambiguity costs 15 to 20% of the clock is still untested. Every hour the app is in use collects that, whatever phase the curriculum is in.
4. **Don't teach on the weakest numbers.** The alpha list's payoff rests on an achievable-rate assumption that needs repricing before anything is built on it.
5. **Personal tool.** The client source is someone else's work. Sideloaded, private, not distributed.

---

## Phase 0 — Already done

For the record, so nothing gets rebuilt:

- FluxCore: DAWG, solver, generator at ruleset v3, offline simulator, all tested against a brute-force oracle.
- Real board norms, letter distribution, tier posteriors, seed behaviour.
- 9,034 games of the player's ranked history plus 7,133 of Nicole's, solved, with presence tables, belief estimates, hook stems and family structure.
- The diagnosis: the opening, the 74x chaining ratio, the top-quartile gaps on family completion and free-extension take, the warm-up cost.

---

## Phase 1 — The clone (1 to 2 weeks)

**Goal:** an iOS app that plays exactly like Flux and records everything the export could not.

**Build**

- Port the input layer from the client source: grid rendering, the swipe gesture recognizer, tile hit targets, path drawing, timing. Match the real feel rather than reimplementing from scratch; a recognizer that is 10% less forgiving will make every measurement below wrong.
- Rules exactly as confirmed: 80 seconds, 8-way adjacency, no tile reuse, retracing onto a selected tile is a no-op, **lifting the finger always submits**, re-swiping a found word scores nothing and costs the time. Minimum length 3.
- Wire FluxCore v3 for generation and solving. Board on screen in under a second including Spam-tier best-of-N.
- Full attempt logging: cell sequence with a timestamp per cell entered, submission timestamp, result (valid, invalid, duplicate), time since previous submission.
- Local SQLite, plus one-tap export of the database to Files. A build signed with a free profile expires every 7 days, so an unexported month of data is a month you can lose.

**Gate:** play twenty 80-second games. Does it feel like Flux? Then fit `swipe_a` and `swipe_b`, and report the first real misswipe numbers: invalid attempts per game, seconds lost, duplicate re-swipes per game. **That answers §3.6, which nine thousand games of export data could not.**

---

## Phase 2 — The selection engine (1 to 2 weeks)

**Goal:** answer "what should I learn next, and why" defensibly. This is the brain of the app and no board is shown until it works.

**Build**

- Import the derived tables from the ranked analysis: opportunity-weighted belief per word, hook stems, family membership, presence rates by tier and grid, top-quartile holes, alpha candidates.
- **Reprice the alpha list first.** Replace the uniform 74% achievable rate with the per-word top-quartile rate, floored at your own current rate. Words where you already beat the top quartile drop out entirely; roughly a quarter of the current top 200 are words you find more often than the field does. Expect the list to shrink a lot and to get much better.
- Two distinct study pools, kept separate because they answer different questions:
  - **Par words**, the top-quartile holes. Words the strongest players take and you don't. Learning these closes a gap, about 582 points a game.
  - **Alpha words**, which almost nobody takes. Learning these opens one.
- Rank by expected points per unit of learning effort, with effort discounted by hook membership: the sixth branch off a hook you already own is nearly free.
- Group everything by hook. A study item is `RAI-` with its branches, not SERAI as a string.
- A browser to read the queue: hook, branches, your rate, the top-quartile rate, presence, points, why it is ranked where it is.

**Gate:** read the top 100 hooks and the top 200 words. Are these worth learning? That judgment is yours and cannot be automated, and it is the main quality risk in the project.

---

## Phase 3 — The teaching loop (2 to 3 weeks)

**Goal:** turn the queue into board vision. This is the core product.

**Build**

- **Constrained board generation.** Real ranked-distribution boards that happen to contain the target hooks, using FluxCore v3 with the embedding and norm checks. The board must not look like a puzzle; if you can tell which hook it was built around, nothing transfers.
- **Branch completion**, the central drill. The hook is lit on a board and you find every extension before the timer. This is where the 1%-to-74% gap gets trained: the point is not knowing SERAI, it is seeing `RAI` and reaching for it.
- **Family sweep.** A board with a target family present, no hint given. Find every member. Harder than branch completion and the real test of transfer.
- **Affix grids** per hook, live and dead branches both. The dead ones are what prevent misswipes, and they train at high throughput: 60 to 100 valid/invalid judgments in five minutes, against a handful of words per board.
- Review after every board, board-first: the hook lit, what you found, what you missed on the same path.
- Session shape: a few boards, one drill block chosen from what the boards exposed, one review. New hooks enter through the drill block, not through a reading screen.

**Gate:** a hook drilled this week gets found unprompted on a fresh board next week.

---

## Phase 4 — Retention (1 week)

**Goal:** make learned words stay learned, which the data says does not happen on its own.

A word is taken 25.2% of the time when the previous presence was taken and 10.3% when it was missed, and 4,320 words were found once or twice then missed on five or more later presences. Acquisition sticks weakly; it does not compound.

**Build**

- FSRS over hooks, graded from live play rather than self-report, with the §11.2 grading table.
- Spaced re-injection: a due hook is embedded in the next acquisition board as background, unannounced.
- Graduation on a positive test (the affix grid answered at speed, plus one live find on an unseen board), never on the absence of a misswipe.

---

## Phase 5 — Measurement (1 week)

**Goal:** know whether the curriculum is working, separately from whether you are having a good week.

**Build**

- Free-extension take rate against the top-quartile reference, which is the metric the curriculum is trying to move. Currently 34.4% against their 37.4%.
- Hooks owned, branches per hook, and find rate on graduated hooks over time.
- Tier percentile as the per-board headline. Not Par, not capture rate; capture elasticity to potential is about -0.4, so capture mostly measures the board.
- 14 fixed benchmark boards on a two-week rotation, never used for training.
- **Report progress as score against the field at your rating, not as win rate.** On a rated ladder win rate returns to about 50% whatever you do, and your own history shows it: you gained 1,111 points a month, opponents gained 1,005, win rate flat.

---

## Phase 6 — Drills and session shell (1 week, whenever)

Cheap to add and deliberately last, because none of it needs the curriculum and two of them barely need the app.

- **Warm-up mode.** One unranked board before ranked. Worth about 1,633 points on the first game of a session. **Do this by hand today**; it needs no software at all.
- **Longs only.** Words under 5 letters rejected. Trains the 1% regime.
- **Swipe budget.** 60 submissions in 80 seconds. Trains selection.
- **Opening focus.** Only the first 15 finds are scored.
- Opening-length tracking with its two guards: total word count must not fall by more than about 3 a game, and board-controlled score must rise.

---

## Phase 7 — Optional

Full word and family browser with the §12 filters, board explorer, Par and the leak decomposition as an experiment, Nicole as a second player for validation.

---

## Cross-cutting

**Where the value is, by confidence**

| Intervention | Value | Confidence | Needs the app? | Phase |
| --- | --- | --- | --- | --- |
| Warm-up board | \~1,633 points on game 1 of a session | Measured, survives holdout | No | 6, or today |
| Opening fix | 1,600 to 2,400 points a game | Measured, volume cost measured | Barely | 6 |
| Free-extension gap to top quartile | Gap is 2.8 pp and holdout-validated; payoff needs repricing on a like-for-like basis | Gap measured, payoff extrapolated | **Yes** | 2, 3 |
| Alpha words, past the field | Unknown until repriced | Ranking measured, payoff extrapolated | **Yes** | 2, 3 |
| Misswipe reduction | Unknown | Unmeasured until Phase 1 ships | **Yes** | 1 |

The last three are the reason to build anything. The first two are worth more per unit of confidence, but you can capture them with a habit change and a practice game, which is why they moved to Phase 6.

**Total: roughly 8 to 12 weeks**, with the selection engine readable after 4 and the teaching loop running by 7. The warm-up habit costs nothing and starts today.

**Risks**

- The recognizer feels wrong and the data is biased. Mitigated by porting rather than reimplementing, and by the Phase 1 gate.
- Phase 3 fails its gate, meaning the opening counterfactual did not transfer. That is a real result, cheaply obtained, and it would redirect everything after it.
- Ranked generation changes again on the server, as it did around 7 June 2026. Keep the ruleset versioned and re-export periodically.
- Training in the app displaces ranked play. Cap daily training boards; ranked is what is being trained for.

**Not building:** multiplayer, accounts, sync, hints during live play, opponent modelling, anything social, and any public distribution.

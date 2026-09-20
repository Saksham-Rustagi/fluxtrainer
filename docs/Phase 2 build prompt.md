# Phase 2 build prompt: the selection engine

Paste into Claude Code in the trainer repo. Phase 1 is done and the clone feels right.

---

## What this phase is, and why it comes first

You are building the **selection engine**: the part of the trainer that decides what I should learn next and can defend the answer. It ends with a ranked, readable queue. It does not teach anything yet.

The motivation is specific. I am a top-50 ranked Flux player. Nine thousand of my ranked games have been solved and analysed, and the finding that shapes this whole phase is:

> I take a 5+ letter word **74% of the time** when it extends a word I already found, and **about 1%** otherwise.

So long words are, for me, almost entirely a chaining phenomenon. I do not find a 6-letter word by looking for 6-letter words; I find it by extending something already on the board. A word taught in isolation is a word I will not find. **That is why the unit of study here is a hook plus its branches, never a bare word.**

This phase comes before the teaching loop because if the ranking is wrong, Phase 3 will efficiently teach me the wrong things. The bar here is higher than for anything downstream.

---

## Where the context lives

Confirm each of these exists before planning, and say so if one is missing rather than guessing at its contents.

| Source | What it holds |
| --- | --- |
| `docs/SPEC.md` | The product spec. §6 (study value), §7.2 (family strength), §7.3 (affix grids), §7.5 and §7.5.1 (which stems work as hunting cues, and residual-based gating), §7.6 (cellmates), §8.1 (belief model), §12 (search filters). |
| `docs/BUILD_PLAN.md` | The phase plan. This is Phase 2. |
| `data/ranked/` | The derived tables from 9,034 of my ranked games plus 7,133 of Nicole's: per-word belief, presence by tier and grid, hook stems, family membership, per-word rates for me, the field and the top quartile, and the current alpha candidates. |
| `reports/analytics.html` | The full analysis behind those tables. Read the sections on hooks, the 74x chaining ratio, top-quartile gaps, and the alpha list. |
| `PHASE1_REPORT.md` (FluxCore) | Simulation results: reachability by affix, cellmate pathability, stem enumerability under curation, board norms. |
| The Phase 1 clone gate report | Live-play calibration from the trainer's own clone: swipe constants, invalid-attempt rates, duplicates, dead time. |
| The clone's SQLite export | Raw per-attempt logs, including every invalid attempt with its path and timing. The misswipe track below reads this directly. |
| `runs/full`, `runs/m3-curated` | Simulation outputs. Reuse, do not regenerate. |

**Where a number in this prompt disagrees with a source, the source wins and you flag it.** This prompt was written from memory of those documents. Reuse everything in `data/ranked/`; do not re-solve boards or recompute belief.

---

## What the Phase 1 clone measured, and what it changes

Eight games on the clone produced the first live-play data the project has ever had. Three results matter here:

1. **Invalid attempts are 48 per game**, against a spec estimate of 12 to 15. With 13 duplicate re-swipes, roughly 39% of my swipes score nothing, costing about 26% of the clock in pure finger motion. This is a larger lever than anything else measured.
2. **The cause is mixed.** 20% of invalid attempts carry an affix pattern, mostly `-ER`, `-S`, `-ERS`, `-ES`. 36% are a prefix of a real word, meaning I lifted early or dropped a letter. The rest are repeated non-words like RALL, SOLT, LINNE, TOSR. So the cost splits across affix ambiguity, motor error, and genuinely believing a non-word is a word. Only the first and third are learnable.
3. **`swipe_a` in the spec is wrong.** Measured at -0.085 with `swipe_b` at 0.086, against the placeholder 0.30 + 0.08n. Swiping is about half as expensive as modelled. Refit anything that used the old constants.

The sample is 8 games, so treat rates as provisional and structure as informative. Rare suffixes would not appear at this n, which is why affix work stays in the curriculum.

---

## The three tracks

The queue has three kinds of item. Keep them separate in the data model and in the UI, because they answer different questions and carry different confidence.

| Track | What it is | What learning it does |
| --- | --- | --- |
| **Par** | Top-quartile holes: words the strongest players take and I don't | Closes a measured gap, about 582 points a game |
| **Alpha** | Words almost nobody takes, the field included | Opens a gap rather than closing one |
| **Misswipe** | Strings I repeatedly swipe that are not words | Removes waste, worth up to \~26% of the clock |

### The misswipe track

This is new and comes directly from the clone data. Read the attempt log and surface **strings I have attempted two or more times that are not valid words.**

For each, show the attempt, how many times, the seconds lost, and the nearest valid neighbours on the boards where it happened, so the correction is learnable rather than just a scolding. Classify each by likely cause:

- **Affix error**: a real stem plus an affix that does not take (HOLERS, NILER, CUER, LUCER). These are genuine vocabulary and are fixed by the dead half of the affix grid.
- **Path error**: a valid word is within one substitution, transposition or insertion of the attempted path (TOSR against TORS). Motor, not vocabulary. Surface it so I notice the pattern, but do not generate study items from it.
- **Early lift**: the attempt is a prefix of a valid word that was reachable by continuing. Also motor.
- **True non-word belief**: no valid word nearby. I thought it was a word. These are the most valuable items in the track.

Only affix errors and true non-word beliefs become study items. Report the other two as diagnostics.

**One caution.** It is possible some invalid attempts are how I search: tracing paths to see what connects rather than executing a word I have decided on. If so, suppressing them would cut my word count. Do not build anything that pressures me to reduce them; the track exists to tell me which strings are not words, not to make me swipe less.

---

## Repricing the alpha list, before anything is built on it

The current expected-gain model applies a uniform 74% achievable rate to every word, taken from words I already find reliably. That is selection: a word is reliable *because* I find it. Applying 74% to a word I take 0.3% of the time assumes learning closes the entire gap.

The damage is visible in the existing top 200. Roughly a quarter are words I already find **more often than the field**:

| word | my rate | field rate |
| --- | --- | --- |
| ARTIES | 17.5% | 7.6% |
| ENATES | 17.0% | 7.1% |
| ARTIER | 15.4% | 6.6% |
| EATEN | 15.6% | 9.1% |
| SAIREST | 12.5% | 4.3% |
| ARSINE | 11.0% | 3.1% |

Those are my strengths, not gaps. They rank highly only because 74 minus my current rate is still large.

**The fix:** use the per-word top-quartile rate as the achievable ceiling, floored at my own current rate. Words where I already beat the top quartile drop out entirely.

```
achievable(w)    = max(top_quartile_rate(w), my_rate(w))
expected_gain(w) = presences_per_game(w) · points(w) · (achievable(w) − my_rate(w))
```

Report how much the list shrinks and how much total expected gain falls. I expect both to be large, and that is the point: a smaller honest number beats a large one resting on an assumption that cannot hold.

**Sanity checks to run and report:**

- Does any word still rank where my rate already exceeds the top quartile? If so the floor is not applied correctly.
- The top-quartile rate is noisy for rare words. Set a minimum presence count before trusting it, and say what you used.
- Does expected gain summed over the top 200 exceed what I could physically swipe in 80 seconds? If so the model ignores the swipe budget and should say so out loud rather than reporting an impossible total.

**A caution on alpha.** A word nobody finds is either unknown or structurally hard to see. The first is an opportunity, the second is a trap. Use the findability signals available (isolation, hook membership, path shape, vowel-initial) to separate them, and flag any alpha word that looks unfindable rather than unknown. The field's vowel-initial deficit, at 0.23 to 0.37x the consonant-initial rate, is the clearest case of words people *can* find and simply don't, and deserves calling out specifically.

---

## Hooks are the unit

Each hook in the queue carries:

- The stem, and every branch classified `additive`, `cellmate`, `mutating` or `dead` (§7.3, §7.6).
- My rate, the field rate and the top-quartile rate per branch.
- Presence by tier and grid.
- **Residual**: the unknown branches only, per §7.5.1. No cap on family size. A 40-branch hook where I know all but two is one of the best items available, and the drill later shows the two, not the forty.
- **Enumerability** (§7.5): `E[members findable | stem present]`, which decides whether the stem works as a hunting cue at all. Target 2 to 6. This is what keeps `-RS` out and lets `-LLERS` in. Phase 1's curated measurement put the usable band at 3 to 4 letters, with 5 as Spam-tier material; use the measured band, not the spec's original guess.
- **Reachability** per branch: P(branch present and reachable | stem path present), from the simulator. An affix at 0.028 reachability is close to worthless as free points whatever its other merits.
- **Dead branches**, which are what prevent misswipes. The clone data puts affix errors at about 20% of invalid attempts, so these are a real curriculum item, not a footnote. Weight them from the measured misswipe cost and state the weight you used.

---

## Ordering

Produce one ordered list of hooks blending the tracks, with the blend visible and adjustable. Order by expected points per unit of learning effort, and expose the components so I can see why something ranks where it does.

Two factors that are easy to omit and matter a lot:

- **Prefer hooks I already partly own** (`|owned| >= 2`). I have the stem, the motor pattern, and the habit of looking there, so the remaining branches are nearly free.
- **Prefer additive branches over mutating ones.** Additive branches extend a path I am already on; mutating ones must be found fresh and are worth much less per item.

---

## Deliverables

1. **The browser**, the main deliverable. A screen I can read and interrogate: the ranked hook queue, each hook expandable to its branches, showing per branch the word, my rate, field rate, top-quartile rate, presence, points, class and reachability; per hook the residual, enumerability, total expected gain, and a plain-language line explaining the ranking. Filters by track, stem length, grid, tier, class, my-rate range and owned-branch count. Sorts by expected gain, presence, points, residual size and enumerability. Plus word search with the §12 filters (starts, ends, contains, pattern, anagram-of, length, my status).
2. **`reports/queue_hooks.tsv` and `reports/queue_words.tsv`**, plain and sortable, so I can read them outside the app.
3. **`reports/misswipes.tsv`**: repeated invalid strings with counts, seconds lost, classification and nearest valid neighbours.
4. **A one-page summary**: how many hooks and words survived repricing, total expected gain per track, the distribution of my current rates in the queue, and the ten items you are least confident about and why.

It should be possible to look at any item and answer "why is this here" without reading code.

---

## The gate

I read the top 100 hooks and the top 200 words and judge whether they are worth learning. That cannot be automated and it is the main quality risk in the project.

If the list looks like junk, or like words I already know cold, the ranking model is wrong and Phase 3 must not be built on it. Say so if you suspect it rather than shipping a queue you do not believe.

---

## Out of scope

No board generation with target hooks, no branch-completion drill, no family sweep, no affix-grid drill, no spaced repetition, no session shell, no changes to the clone. Phase 3 and 4 cover those, and all of them depend on this queue being right first.

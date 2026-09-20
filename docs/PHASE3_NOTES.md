# Phase 3: the teaching loop

What was built, what was decided, and every place a number or an instruction disagreed with
its source. The gate's own numbers are not here: they come out of
`tools/train_report/gate.py` and need a week of play first.

---

## What exists now

| | |
| --- | --- |
| `tools/queue/hookrecord.py` | The Phase 2 → Phase 3 contract. One schema, two consumers. |
| `reports/hooks.ndjson.gz` | All 10,594 hooks and 1.09M branches. Canonical. 23 MB. |
| `ios/FluxClone/Resources/training_hooks.json` | The 1,336 the app carries, branches capped. 13 MB. |
| `ios/FluxClone/Training/` | Hook record, board types, the three exercises, the session, the belief model, the queue. |
| `core/`, `ios/FluxClone/Bridge/` | A density band on constrained generation; a full solve with paths. |
| `tools/trainprobe/` | What a Phase 3 board costs to make. |
| `tools/train_report/gate.py` | The gate. |

The app is still `FluxClone` and still installs over itself, so the seven-day re-signing
routine and the existing database carry over untouched. Schema 1 databases migrate to 2 on
first launch by adding three columns to `game` and creating the new tables.

---

## The hook record

Phase 2 and Phase 3 both read and write hooks, so the schema was fixed first, in one place.

The only thing crossing between the phases before this was `reports/queue_hooks.tsv`, which
is a report: it flattens a hook to one line, drops the branch list, and drops `presTier`
(per-tier, per-grid presence) because a dict does not fit in a TSV cell. A drill cannot run
on that.

`tools/queue/hookrecord.py` holds `SCHEMA_VERSION`, `HOOK_FIELDS` and `BRANCH_FIELDS`, and
writes both files. `HookRecord.swift` declares the same fields and refuses a schema it does
not know. The record is the brief's shape:

```
Hook { stem, branches[{ word, class, myRate, topQuartileRate, reachability, points }],
       residual, enumerability, presenceByTierGrid, expectedGain, track }
```

plus the fields the on-device recompute needs — the ranked numerator and denominator
(`presences`, `finds`, `opportunity`) rather than only the ratio, because the app adds its
own observations to them.

**The app's copy carries a trimmed branch list**, 40 live and 40 dead per hook, and that is
not size trimming for its own sake. SPEC 7.3's classification rule is containment: an
additive branch of `S` is exactly a word containing `S` contiguously. So the branches
present on a board are read off the board's own solve, not out of the bundle. What the
bundle has to carry is only what cannot be derived — Phase 2's per-pair reachability and the
player's per-word rates. `ERAS-` has 158 branches and a drill shows at most six.

**Note on two column names in `queue_hooks.tsv`**, because Phase 3 reads both and they
invite the opposite reading: `familySize` is the *additive* family over the dictionary (74
for `ERAS`) and `branches` is the whole branch list including cellmates and mutating forms
(158). The `why` text has them the right way round; the names do not.

Phase 2's output was already committed, in `5c47f15`. The brief's instruction to commit it
first was already satisfied.

---

## What was measured before it was designed around

### Constrained generation is cheap

SPEC 11.1 warns that up to 625 candidates each passing a 60–90% rejection filter could be
thousands of generate-solve cycles, and that if a board costs ten seconds then the
infeasibility fallback ladder *is* the product. `tools/trainprobe` answers it for the Phase 3
board types, on the real stems and the real band:

```
board                    builds   solves        ms    p90 ms   missing     short     words
drill 4x4 goodCasual       14.5     14.5         1         1      0.0%      0.0%       367
drill 5x5 goodCasual       14.8     14.8         1         2      0.0%      0.0%       631
acquisition 4x4 casual     16.8     16.8         1         1      0.0%      0.0%       363
acquisition 4x4 goodCasual 45.8     45.8         3         4      0.0%      0.0%       405
acquisition 5x5 casual     11.6     11.6         1         2      0.0%      0.0%       621
acquisition 5x5 goodCasual 59.2     59.2         6         8      0.0%      0.0%       740
```

One to six milliseconds a board on an M-series Mac, nothing infeasible. The fallback ladder
is an edge case here, not the product. The app still implements it and still flags a
degraded board, because "never silently serve a board that misses its targets" is worth
keeping whatever the measured rate is.

### The density band

The brief replaces SPEC 11.1's "reject outside the tier's middle 80%" with a wide floor and
ceiling on **total word count**, and says the floor matters more because embedding a hook
pulls boards dense. The band is p10 to p95 of the player's own current-regime boards, per
grid — 85% of the boards he actually meets:

| grid | p10 | median | p95 | boards |
| --- | ---: | ---: | ---: | ---: |
| 4x4 | 238 | 340 | 515 | 1,787 |
| 5x5 | 469 | 610 | 865 | 1,078 |

It bands word count rather than points because the task being trained is finding one hook
among the others, and "among 180" and "among 800" are different tasks. A points band cannot
separate them: a board's points are dominated by its longs.

---

## Where a source lost, and why

The brief says: where a number here disagrees with a source, the source wins and you flag
it. Four disagreements, plus two readings that could have gone either way.

### 1. `docs/BUILD_PLAN.md` does not exist

The file is `docs/Build plan.md`. Its Phase 3 section agrees with the brief throughout.

### 2. The 2,161 dropped candidates do not become rankable from in-app play

The brief lists, as a visible consequence of recomputing `myRate`:

> The 2,161 candidates Phase 2 dropped for insufficient presence evidence gradually become
> rankable as in-app presences accumulate.

`reports/PHASE2_SUMMARY.md` says what they were dropped for:

> Another 2,161 drop for want of evidence rather than want of value: their **top-quartile
> rate** rests on fewer than 30 presences and is not trusted.

The insufficient evidence is the *field's*, not the player's. `rank.py`'s `MIN_TOPQ` gates on
`nTopQAll`, the number of top-quartile opponents who met the word. In-app play adds the
player's own presences and cannot move that number; only another ranked export can.

What is implemented is what is implementable. The recompute combines ranked and in-app
presences into `myRate` and into belief, and both of the other two consequences work as
described: a learned hook falls in the ranking, and a word picked up elsewhere stops being
taught. `TrainingQueue.promotable` counts the dropped candidates on both conditions
separately — how many now clear the presence floor, and how many are still untrusted for
want of a top-quartile rate — so the distinction is visible rather than papered over.

### 3. Acquisition boards are not 60% Casual

SPEC 11.1 gives acquisition boards a 60% Casual / 40% Good Casual mix, no Spam. "No Spam" is
kept. The mix is not, and the reason is in the player's own boards: of his 1,787
current-regime 4x4 boards, **91% are Good Casual and 3.5% are Casual**. A board drawn 60%
Casual would be identifiable as a training board from its tier alone, before the first
swipe — which is exactly what SPEC 10.2 and this phase's brief forbid.

The tier is drawn from the ruleset's own shares with Spam redrawn, so an acquisition board is
drawn the way a ranked board is drawn. The density band then does the work SPEC 11.1's norm
check was there to do.

There is a second reason the 60/40 could not survive contact: the density floor is 238 words
on 4x4, and the Casual tier's own median is 188. A board that is both Casual and inside the
band is not a Casual board in any sense the player would recognise.

### 4. "Unscored" warm-up, read as unreviewed

The brief's warm-up is "60s, unscored, no review". It is played as an ordinary board with the
score on screen, because a warm-up that does not feel like a game does not warm anything up,
and the later section is explicit that the warm-up's presences *are* recorded:

> Every full board played in the app (warm-up, family sweep, acquisition) is already solved
> … Record all of them.

So "unscored" is implemented as: nothing is drilled off it, no hook is credited, no verdict
card beyond a one-line acknowledgement. If the intended reading was "hide the number", it is
one line in `TrainingSession.present`.

### 5. "No text during a drill" against "the board view is the clone's, unmodified"

These conflict over the word bubble, which shows the word forming under the finger. The
board-view rule is stated more strongly — *if the drill board feels different from the game
board, the motor pattern being trained is the wrong one* — and the bubble is part of the
board rather than part of the HUD. So the bubble stays and the HUD goes: no score, no word
count, no labels. The stem, a counter, and the clock.

The counter sits exactly where the score sits, so the grid's origin, tile size and hit
targets are byte-identical to the clone's.

### 6. "No re-solving boards"

Out-of-scope item, read as: do not re-solve the 9,034 ranked boards (which is what it meant
in Phase 2, and what would be expensive). Each *training* board is solved twice — once in
Count mode inside the generator's best-of-N, which is how the board is chosen, and once in
Full mode to get the cell paths the drill and the replay need. That second solve is about
three milliseconds and there is no way to light a stem or animate a miss without it.

---

## The know-against-see sort

Added after the first real session, because the first thing the player said on using it was
*"is this really teaching me new words, I lowkey already know these."* He was right, and the
data says so plainly. Here is what the top of the queue teaches, with how often he already
takes each word when it is on his board:

| word | hook | boards it was on | he takes | top 25% take | he found |
| --- | --- | ---: | ---: | ---: | ---: |
| ERASE | `ERAS-` | 243 | 1% | 28% | 2 / 243 |
| HEART | `HEAR-` | 110 | 25% | 46% | 28 / 110 |
| TRACE | `RACE-` | 76 | 12% | 47% | 9 / 76 |
| SAINT | `AINT-` | 156 | 20% | 34% | 31 / 156 |
| STORE | `TORE-` | 241 | 42% | 58% | 102 / 241 |

**ERASE was on 243 boards and he found it twice.** Across every word the queue teaches, the
median one he already takes 11% of the time. This is not a vocabulary list. It is a list of
words he knows and does not see, which is what the 74%-against-1% chaining finding predicted
and what the whole project is for.

The app was not saying any of that, which is why the drill read as busywork. Three fixes:

**1. The brief.** One card before a hook's first board, in his own numbers: *"ERASE was on
243 of your boards. You found it twice. The top 25% find it 28% of the time. This is a
seeing problem, not a knowing problem."* The hook record has carried a `why` line since
Phase 2 and nothing displayed it. `SightGap` orders by expected gain rather than by raw rate
difference, because ERASES has a wider rate gap (0% against 28%) and is worth a third as
much.

**2. Graded on seconds.** The verdict now shows time-to-find per branch and the change
against the last time that word was drilled. Found-or-missed cannot move on a word he
already knows, so it would have read the same in week 1 and week 6. `branch_event.t_found`
was already being recorded and nothing used it.

**3. The affix grid sorts before the board drills.** This is SPEC 8.1's missing calibration,
done per hook instead of once globally and with the exercise that already existed. 8.1 is
explicit that belief is the wrong instrument for this — it is derived from find rate, so
"never heard of SIREES" and "cannot see ERASE" are the same number — and prescribes a
one-time 200-item valid/invalid calibration. No phase built it. Now the grid runs first and
its answers and latencies sort the hook's words:

| call | latency | verdict | what the board drill is then for |
| --- | --- | --- | --- |
| correct | ≤ 1.2 s | `known` | vision. The number that moves is seconds-to-find. |
| correct | > 1.2 s | `shaky` | both problems at once. |
| wrong | any | `unknown` | genuine vocabulary. Acquisition. |

1.2 s is SPEC 7.3's own target for an affix judgement, not a new constant. The verdict
overrides belief on the vocabulary question in `TrainingQueue.recompute`, because a fast
correct call is direct evidence where belief is inference.

**A consequence worth naming:** the drill's board filter used to require a branch that was
not yet known, which rejected exactly the boards that matter — there is nothing left to
*learn* about ERASE and an enormous amount left to train. `worthDrilling` now accepts a
target if either half is open: the word is unlearned, **or** there is room between his rate
and the achievable one. The same reasoning removed a `status != "known"` filter from the
queue's gain calculation.

---

## The affix grid, after first contact

Two things were wrong, and the second was a straight defect.

**It was 73 cards for a 3-word problem.** The deck took 40 live branches and sorted them
*alphabetically*, so `TORE-` opened with PRESTORED and PROTORES and the four words the queue
actually wants — STORE, STORES, STORED, STORER — were buried past card 20. SPEC 7.5.1 says
the opposite in as many words: *"The drill shows the residual, not the family. You are not
re-reading 38 words you know to get to the two you don't."* Its bound on one sitting is 8,
and the median hook across the queue has **3** branches carrying any gain. The deck is now
the residual in value order, capped at 8 live and 8 dead — about ten cards.

**The throughput claim does not survive that, and should not.** The brief asks for 60 to 100
judgements in five minutes and calls that where vocabulary throughput lives. Sized to the
hook that is ten. The route back to 60-100 is more stems in the block, not more filler per
stem; that is a Phase 4 scheduling question and is not built.

**The dead half is now only strings he has actually swiped.** SPEC 7.3 mechanism 3 mines
dead affixes from the dictionary and keeps the most productive that do not complete the
stem. In practice that produced TOREER, TOREING, GTORE — strings nobody would ever swipe —
and 7.3 itself says "not a word" is only interesting for *"strings a player would plausibly
try"*. The strongest evidence that a string is plausible is that he has tried it, which is
SPEC 7.3.1's first ranking rule. The bundle now ships his whole invalid-attempt log (354
strings), the app adds its own as he plays, and the dead half is drawn from that and nothing
else.

The cost is coverage, and it is real: 354 strings cover 15% of the bundled hooks today, so
most grids start with no stem-specific dead cards. It fills at about 48 invalid attempts a
game. A floor of 3 dead cards is met from the rest of his own log when a stem has none,
because a deck whose answer is always "Word" trains pressing Word — and a fast reflexive
Word reads as `known` and corrupts the sort.

---

## Decisions the brief left open

**Which branches are the drill's targets.** Every additive branch present on the board *that
extends the lit stem path*. All three conditions, checked: contained in the word, present on
the board, and reachable by extending the path under the finger. A board is rejected and
regenerated unless it has 3 to 6 of them and at least one the player does not already own —
SPEC 7.5.1's residual, so a drill is never six words he already has.

**How much of a miss to replay.** The five longest missed branches, one path at a time, a
third of a second a cell. SPEC 9.2 gives a per-board review fifteen seconds; a sweep board
can carry a dozen branches and twelve paths would be a screensaver. The rest are in the log
and on the verdict card.

**Which stem path to light**, when the stem appears more than once. The one that the most
present branches extend. Lighting any other would ask him to extend a stem the answers do not
run through.

**Belief weighting.** The ranked import did not use SPEC 8.1's logit form; `s4.py` fitted an
opportunity-weighted Beta rate, and that is the `belief` column Phase 2 ranked on. Phase 3
continues that model rather than starting a second one, because the whole point is to add
in-app evidence to ranked evidence and two models cannot be added. The opportunity reference
table and the per-length Beta priors are recomputed for the current regime and shipped in the
bundle, so an in-app presence is weighted on exactly the same scale as a ranked one.

The exercise weights are the brief's ordering and are judgements, not measurements:

| evidence | weight |
| --- | ---: |
| Unprompted find on a full board | 1.00 |
| Family sweep, on a target branch | 0.60 |
| Lit-stem drill, on a target branch | 0.25 |
| Affix grid, on a live branch | 0.10 |

They live in one enum in `Belief.swift` so the gate can be re-run against a different set.
Four lit-stem finds are worth less than one unprompted find, which is checked in a test,
because the failure this prevents is specific: drill a hook, find its branches with the stem
lit, watch belief jump, watch the hook leave the queue, having learned nothing.

Every word on the board that is *not* a target carries the full unprompted weight whatever
exercise it came from — nobody pointed at it.

---

## Running it

```sh
# Regenerate the queue and the hook record together
sh tools/queue/run_all.sh

# What a Phase 3 board costs
cut -f2 reports/queue_hooks.tsv | tail -n +2 > /tmp/stems.txt
build/tools/trainprobe/trainprobe config/ruleset_v3.json data/dict/flux_capped.dawg /tmp/stems.txt

# The gate, against a phone export
build-analytics/venv/bin/python tools/train_report/gate.py ~/Downloads/fluxclone-*.sqlite \
    --out reports/phase3_gate.md
```

`FLUXCLONE_TRAIN=1` in the launch environment starts a short session as soon as the queue is
up, which is how a simulator run reaches a drill board without a tap.

---

## What Phase 4 inherits

No migration. `hook_state` already holds exposures, first and last drill, the grids a hook
has been seen on, and a due date; FSRS stability and difficulty are columns on it. The belief
model already has its per-word evidence in `presence` and `judgement`, weighted at write time
so a re-run cannot disagree with the weights in force when it was played. The scheduling
Phase 3 does is a flat seven-day due date and nothing else, which is the brief's cap.

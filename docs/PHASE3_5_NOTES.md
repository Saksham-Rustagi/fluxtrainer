# Phase 3.5: play, review, and the record of what I know

Written for whoever picks this repo up next, including me in three months. Phase 3's notes
are in `PHASE3_NOTES.md`; this covers what changed on top of `a308a55`, and — more usefully
— the places where a source said one thing and the data said another.

---

## The structural change

**Playing is the front door. Review is what a finished board comes back into.**

Phase 3 had it the other way round: the trainer sat above Play on the home screen, and a
finished board showed a score card with four rows on it. That made the app a content engine
with a game attached, and it had a second, quieter consequence that mattered more:

> **A ranked game wrote a `game` row, fifty `attempt` rows, and nothing the player model
> could read.** Only boards the *session* served were solved and turned into `presence`
> rows. So "the queue moves on its own as `myRate` recomputes from ranked plus in-app
> presences" — the brief's first mechanism for making learning visible — was false. The
> in-app half did not exist for the thing actually played most.

Every completed board now goes through `PlayedBoard.finish`: solved once, written as one
`presence` row per word and one `hook_meeting` row per family, then reviewed off the same
solve.

| Screen | What it is |
| --- | --- |
| **Play** | The front door. A board in one tap, no configuration. Mixed practice under it. |
| **Review** | Not a tab. What a finished board returns to. |
| **My stems** | Everything drilled or met in play, with completion and trend. |
| **Queue** | A reference tab. |
| **Drill** | Reached from review or from a family page. Still one tap, still never asks which hook. |

The daily session survives as a row on Play, deliberately smaller than the board button.
It is the same session Phase 3 built; what changed is that `TrainingSession` now takes a
`forcedHook`, so "drill this family" from review drills *that* family instead of asking the
queue again.

---

## Review is the interface, the queue is the ranker

This is the whole design and everything else follows from it.

What gets missed on any one board is mostly board luck. A review driven by "what did you
miss today" teaches board-specific trivia. The Phase 2 queue's expected-value ranking is a
far better selector than one game's misses — so review shows a board's worth of misses
ranked by `expectedGain`, which is measured over 2,865 ranked boards, and never by what
cost the most here.

`FamilyGapTests.testRankingIsExpectedValueNotPointsOnThisBoard` pins it: `PRAT-` loses
3,400 points on the test board against `ERAS-`'s 800, and comes second.

### SPEC 7.4's four cases, and what they are used for

The four cases are not equally interesting, and the difference is not how big the miss is —
it is **how realizable the advice is**:

| Case | Pattern | Weight |
| --- | --- | --- |
| 1 | Found 2+ of a family, missed a 5+ member | 1.00 |
| 3 | Found the base, missed 2+ extensions | 0.80 |
| 2 | Missed the family entirely, in a region demonstrably worked | 0.60 |
| 4 | Missed the family entirely, in a region never touched | 0.25 |

Ranking value is `missedExpectedGain × weight`. Case 4 is a coverage problem: SPEC 9.4 says
a coverage miss generates no study item, so it is shown and framed as scanning, not turned
into a word list.

"Demonstrably worked" needed a coverage signal the app did not have. `GameResult` now
carries `touchedCells` — every cell under any swipe, valid or not — and a family counts as
worked when at least half the cells of its missed members' paths were touched.

Two smaller things in the verdict, both wrong in the first draft. The percentile excludes
the board just played: leaving it in counts it as one it did not beat and drags every
percentile down by 1/n. And the points-per-second that converts wasted clock is the board's
own rate over its real elapsed time, not the time of the last find — a drill can end early
by clearing its targets, and the last find is not when the board ended.

### Seven things only running it exposed

Worth recording, because all seven look fine in code and are obviously wrong on screen or
in the first export. Three of them are about the same thing — review has a cap of six items
and no card may spend one of them saying what another card already said.

**1. The board was unreadable.** `MiniBoard` drew the swipe line last, the way the game
does, where the line is the thing being watched. At 34-point tiles the 8-point stroke sat
on top of the letters. It is three layers now — fills, line, letters — and the line goes
under the text.

**2. Three cards, one fact.** `OATS-`, `MOA-` and `ATOM-` came up one after another with
ATMOS, ATOMS and MOATS in all three. Containment is not exclusive, so neither are families.
A family whose missed members are more than 60% already on screen under another stem is
dropped (`ReviewBuilder.distinct`). The cap is six items and an item spent twice is wasted.

**3. The boards animated forever.** Each `MiniBoard` cycled its paths in a loop for as
long as the review was open — six timers behind a scrolling list, and, less obviously, an
app that never goes idle, which is how XCUITest decides it may look at the screen. The
review UI test went from 12 seconds to timing out at 147. It now walks each path once and
holds the last.

**4. Two stems, one family.** Not from the screenshot but from the first real export:
`IDL-` and `IDLE-`, `NOT-` and `NOTE-`, side by side. The word-set test above does not catch
these, because each hook's branch list is capped in the bundle and the two lists only partly
overlap. A stem inside a stem already on screen is the same family at a different level of
SPEC 12.2's containment chain, and the app's job is to say which level to hunt for, not to
show three. Nested stems sharing any missed word now collapse to one.

**5. "ALINE: you found it on 0 of the last 3 boards it appeared on. Owned."** Two bugs
under one absurd sentence. `word_belief` rows were written with `INSERT OR REPLACE`, so
`announced_status` was reset to NULL on every recompute and every announcement would repeat
for ever. And the very first row written for a word had a NULL `announced_status` and so
read as an unannounced crossing — the word had not crossed anything, it arrived owned out
of 2,865 ranked boards and the app was seeing it for the first time. `announced_status` is
now seeded to the status on insert and never touched on update, which is what makes a
transition mean a *change*.

**6. Three cards, one word.** `ERA-`, `RASE-` and `SEA-` all led with ERASE. Not nested, not
60% overlapping — genuinely three different families that happen to share their most
expensive miss. A card that opens by telling him something he has just read is a wasted
item, so the word a card leads with has to be one nothing else has shown.

**7. The headline leak said 244,600 points.** Two compounding errors. It summed
`pointsMissed` per *family*, so a word on nine stems counted nine times; and it included a
"coverage" bucket, which on any board is almost everything not found and therefore wins
every comparison while saying nothing. The leak is now distinct words across three buckets
— free points, misswipe clock, duplicate clock — and coverage is a card, not a headline.

### Four tabs, four rankings

Review answers four questions and one scroll answered none of them well.

| tab | the question | sorted by |
| --- | --- | --- |
| **Leaks** | what should I act on? | expected gain a game x realizability, capped at six |
| **Words** | what are the best words here to learn? | expected gain a game, with an **alpha** filter |
| **Families** | what was on the board and how much did I take? | points still on the table |
| **Board** | everything | points |

The three rankings are different on purpose. Leaks is the opinionated one and is the only
one with a cap. Families is sorted by points left rather than by gain a game, because most
families on a board have never been priced by Phase 2 and ranking by gain would sort the
list by whether the queue had an opinion.

**alpha** is rank.py's split on the *field's* take rate: below 10% the word is vocabulary
almost nobody has and finding it at all is the win; at or above it, it is a word he is
expected to take and is not seeing. Those are two different problems with two different
fixes, and the app could not tell them apart because only the *hook* carried a track. The
branch now carries `fieldRate`, and the label is derived from it on device rather than
shipped beside it -- `track` is exactly `fieldRate < 0.10`, so carrying both would be 700
KB of second source of truth, and the rate is the more useful of the two on screen.

That is schema 2 of the hook record. `tools/queue/hookrecord.py` regenerates it from the
Phase 2 cache; the app refuses a schema it does not read, so the two move together.

### Families read off the board, not out of the record

`FamilyIndex` answers "which of the 1,336 shipped hooks is this word a branch of", which is
right for ranking and wrong for browsing: a board carries hundreds of families the queue
has no opinion about, including the big obvious ones. `BoardFamilies` derives them from the
solve using SPEC 7.3's definition and nothing else -- every contiguous substring of every
solved word, kept where two or more words share it.

Two rules that look opposed and are not. **Equal member sets keep the longer stem**, since
that is the more specific name for exactly those words. **A strict subset keeps the shorter
one**, since that is a narrower level of a bigger family and the list is a list of families.
The whole word counts as its own stem, because SPEC 7.4's "found the base, missed two
extensions" needs the base to be a member.

The second rule folds SPEC 12.2's containment chain, and the fold is total on a chain as a
matter of arithmetic rather than judgement: if S is a substring of T then every word
containing T also contains S, so a longer stem's members are always a subset of a shorter
one's. Without it a 728-word board listed `ING-` (89 members), then `INGS-`, `KING-`,
`TING-` and sixty-four other levels of the same thing, and no other family reached the
screen. One row per chain, at the widest level, with the narrower stems carried on it.

**Three scopes, because points-left degenerates.** A family's points are its size, so
sorting the full list by what is left on the table opens with "every word with -ING in it",
which nobody hunts for. The default scope is **Cues**: SPEC 7.5's enumerability band,
applied to the family's size on this board. Two to six members is a question with an answer
you can hold in your head while the clock runs. **All** and **In the queue** are one tap
away, because the big obvious families are worth being able to open.

### The animations are gone

Phase 3 walked the missed branches along their paths on the board after a drill timed out,
and called it the most important feedback in the app. In use it is a wait: the answer is
already known by the time the animation starts. The same paths are now static on the
verdict and on every review card, drawn by tapping the word, where they can be looked at
for as long as they are wanted rather than for 0.32 seconds a cell.

### A way out of a drill

There was no way to end a drill board except the clock or the back button, and the back
button logs the board abandoned -- which claims he walked out, when the truth is usually
that the words are not there yet. "I don't know these" ends the board now, with the misses
recorded as misses. It sits in the header row so the board geometry below is identical to
the game's, which is the one thing the clone must not change.

---

## Misswipes, on the device

`tools/queue/misswipe.py` reimplemented in `Review/Misswipes.swift`, same four causes and
same precedence, so a string classified on the phone and in the Phase 2 report lands in the
same bucket.

    affixError > earlyLift > pathError > trueNonWord

The precedence is load-bearing and the reason is easy to miss: appending the missing last
letter is itself an insertion, so a generic edit-one test run first would swallow every
early lift into `pathError` and the motor bucket would swell for no reason.
`MisswipeTests.testEditOneExcludesTerminalAppends` guards it from the other side —
`editOne("HOL")` must not contain HOLE.

One deliberate difference from the Python. `misswipe.py` finds early lifts by indexing the
whole lexicon by prefix and asking which continuations are reachable. On the device it
walks the board out from the last cell instead: at most two cells, so at most 64 walks, and
it asks the question the right way round. The same two extra letters are a lift on one
board and not on another.

Only `affixError` and `trueNonWord` are learnable. The two motor causes are shown as
diagnostics in a dimmer colour and produce no study item — SPEC 16.6 and Phase 2 both warn
that some invalid attempts are just how he searches, and nothing here is scored or fed back
as pressure to swipe less.

---

## Learning has to change something, including downwards

### Slipping

The brief asks for this and the player's own history is why it matters more than the
promotion direction: a word is taken 25.2% of the time after a presence where it was taken
and 10.3% after one where it was missed, and 4,320 words were found once or twice and then
missed on five or more later presences. **Decay is the normal case here, not the exception.**

A branch is slipping when its rate over the last **6 unprompted presences** (at least 4
required) falls to **half or less** of its established ranked rate, and the established
rate is at least **0.40**.

Four things about those numbers:

- **Unprompted only.** A find with the stem lit would hide a slip and a miss on a drill
  board would invent one. Same rule as belief, same reason.
- **The floor exists so that "slipping" is not another name for "unknown".** A word never
  being taken cannot stop being taken.
- **A thin window against a thick baseline, in that direction.** The baseline rests on
  2,865 boards and is the thing we are confident about; the window is the claim.
- Halving is material at any rate above the floor and does not fire on one miss in six.

A slipping branch overrides both belief and the affix grid's verdict. The grid can say he
knows the word and belief can say he used to find it; neither is an argument that he is
finding it now, and finding it now is what the queue is for.

### Transitions, said once

`word_belief` gained `status` and `announced_status`. The difference between the two is
exactly one showing. Only the two ends are announced — `known` and `slipping`. "Learning"
is where most words live and announcing it would be announcing nothing. No streaks, no XP.

### Per-stem trend

`hook_meeting` is one row per (board, family) for every board played, ranked included. That
turns "have I got the ones worth having on `TORE-`" and "is the drill working" into indexed
selects instead of scans over every presence row ever written.

The trend line carries its own counts and says so when they are too thin:
`45% → 62% (18 before, 7 since) — too few to read yet`. Twenty presences a side before it
is called readable.

---

## The family page

The headline is the screen: **"You have 6 of the 9 branches worth knowing."**

"Worth knowing" is `expectedGain ≥ 1.0` points a game. That is the **median expected gain
of a live branch across the whole shipped queue** (7,778 branches carry any gain; p50 is
1.08, p90 is 4.20), so the line reads "at or above the middle of what the queue already
thought was worth ranking" rather than a number picked to make the count look good. For
`TORE-` it puts STORED and RESTORE above the line and TUTORED below it.

The same floor gates a family card in review and a word card. One constant, three uses.

Everything is sorted by expected value and never alphabetically — the complaint that opened
Phase 3's last round was an alphabetical affix deck burying STORE under PRESTORED. Dead
affixes get their own block, because knowing that `-IER` does not take is worth something
and it is not worth what knowing `-ER` is.

---

## Mixed practice

A normal scored 80-second board seeded with three to five families being learned, with
nothing on screen saying they are there, scored per family afterwards in review.

**The families are picked, not chosen for you.** The first version took them off the top of
the queue, and since `queue.ranked` is sorted deterministically that meant *the same five
families every time* -- a practice board that is the same board every time is not practice.
The picker lists everything worth practising with the reason it is on the list (drilled,
due, slipping, next up) and what each is worth, and Shuffle re-draws from the top of it.

The honest limitation, flagged rather than hidden: **only one stem can be handed to the
constrained generator.** The rest are found rather than placed. Two things follow, and the
first version got both wrong:

- **The constrained slot rotates.** Seeding always on the longest stem is the best way to
  get *that* stem onto the board, and it means every board is built around the same family
  while the others turn up by luck.
- **It stops when all of them are there, not three of them.** Three was a hedge against a
  long search; at 60 attempts of a few milliseconds each the search is cheap, and a board
  carrying three of the five asked for is a board that has quietly dropped two.

A family that could not be placed is reported as "not on the board" rather than as a miss,
the same rule a drill board that misses its target count already follows. And when no board
can carry the set at all, the app **says so and names the stems** -- the first version fell
back to an ordinary ranked game, which is why review then showed unrelated families and
nothing about the ones asked for.

This is the explicit version of Phase 4's unannounced re-injection. Both are wanted and
they are not the same thing: the hidden one is for honest scheduling, this one is for when
he wants to test himself and see the result broken out.

---

## Where a source lost, and why

### 1. "Hard cap of six items" — what counts as an item

SPEC 9.1 caps a board at six items and says every item is tappable through to its family
page. The cap here is on **actionable rows** — family gaps and word gaps — and the
misswipe and duplicate sections sit outside it as aggregate diagnostics. Counting a
misswipe block as one of the six would mean a board with four repeated strings could show
two families, and the misswipe track is explicitly the thing that teaches least.

### 2. SPEC 12.2's "presence, by grid" is not on the branch

The family page shows total ranked presences, not a 4x4/5x5 split. `presenceByTierGrid` is
a field on the **hook**, not on the branch, so the per-branch split does not exist on
device; deriving it from a handful of in-app boards would be worse than leaving it out. The
row shows in-app presences separately (`on 243 boards · +12 here`) because those the app
does have. It is one entry on `BRANCH_FIELDS` away whenever the record is regenerated.

### 3. SPEC 9.1's "every item is an action: add to study, or dismiss as known"

Not built. Dismissal is worth +1.5 in SPEC 8.1's logit model, and Phase 3's belief is the
opportunity-weighted Beta rate, not the logit form — there is no coherent scale to add a
dismissal to. The affix grid already answers "do you know this word" directly, with a
latency, and it is better evidence than a button pressed during review. A tap on an item
goes to the family page, where "drill this family" is the action.

### 4. The gate cannot be a script

The brief's gate is: play five boards; after each, does review tell you something you did
not know and would act on? That is a judgement. What `tools/train_report/gate.py` does now
is record and lay out **what review actually showed**, per board, so the judgement can be
made against an export rather than from memory. It also catches the two failure modes that
do not need a human:

- boards where review showed nothing at all, and
- the same stem leading most boards, which is either a drill that is not closing the
  biggest gap or a ranker that is stuck.

This needed a new table, `review_item`, holding what went on screen and why.

### 5. Three bugs found on the way, two older than this phase

All three are fixed here because they were in the path.

**`Sounds.start()` never checked the sound setting.** `play` did, so turning sound off in
settings still activated the audio session, preloaded fourteen buffers and started an
eight-node `AVAudioEngine` — everything except making a noise. It surfaced because the
simulator's audio server wedges under repeated launch cycles and then aborts the process on
a 10-second RPC watchdog inside `AURemoteIO::Cleanup`, which failed whatever test happened
to be running.

**Every board played from Play was logged as a `measurement` board.** `PlayedBoard.Context`
defaulted its purpose to `measurement`, and Phase 1's tooling reads
`COALESCE(purpose, 'ranked')` — so an ordinary game quietly dropped out of every ranked
query in `tools/clone_report`, out of `exposure()` in the gate, and out of the percentile
the app shows. Caught by reading the first real export, where five games in a row said
`measurement`. A ranked board now leaves the column NULL, as Phase 1 wrote it.

**`soundEnabled` could not be read from the argument domain.** The getter was
`object(forKey:) as? Bool`, and `-soundEnabled NO` on the command line stores the *string*
`"NO"`, which the cast silently drops. `bool(forKey:)` coerces both, so the setting now
works however it was written. The UI tests set it, which is why they no longer inherit a
simulator audio fault.

### 6. "Every input for that already exists" — one did not

The brief says review is "a query and a screen, not new machinery", and it is nearly right.
The one genuinely new thing is the reverse index: the hook record is stem → branches, and
review asks word → families for all 428 words on a board. Walking 1,336 hooks per word
would be 570,000 comparisons a board. `FamilyIndex` is built once beside the bundle —
32,025 distinct live words, 51,909 (word, stem) pairs — and is a dictionary lookup.

The other new machinery is `touchedCells`, above: coverage was not in the log.

---

## Schema 3

Added by `ALTER TABLE` and `CREATE TABLE IF NOT EXISTS`, so a Phase 3 database opens
without a migration step.

| Object | What it holds |
| --- | --- |
| `hook_meeting` | One row per (board, family) for every board played. Completion, trend, My Stems. |
| `review_item` | What review put on screen, in order, with its ranking value. |
| `word_belief.status` | What the recompute decided. |
| `word_belief.announced_status` | What the player has been told. The gap is one showing. |
| `word_belief.slipping` | Set by the recompute; drives the family page and the My Stems filter. |

`tools/train_report/gate.py` still runs against a schema-2 export and says so in the review
section rather than failing.

---

## Running it

```bash
# Build and test
cd ios && xcodegen && xcodebuild -scheme FluxClone -sdk iphonesimulator \
    -destination 'platform=iOS Simulator,name=iPhone 16e' test

# The gate, against a phone export
build-analytics/venv/bin/python tools/train_report/gate.py ~/Downloads/fluxclone-*.sqlite \
    --out reports/phase3_gate.md
```

`FLUXCLONE_BOARD_SECONDS` shortens the clock. It exists so a UI test can play a board
through to review without spending eighty seconds on it; nothing in the app sets it, and a
game played with it is otherwise identical.

---

## What Phase 4 inherits

- `hook_meeting` answers "when did I last meet this family and how much of it did I take"
  in one indexed select, which is the input a scheduler wants.
- Slipping is a state with a definition and no schedule. Phase 4 gives it one; here it only
  has to be visible and to let the branch back into the queue.
- `review_item` makes "did review say something useful" answerable over time, which is the
  only way to tell a ranking change from a ranking regression.
- Nothing here re-solves ranked boards, changes the Phase 2 ranking model, or touches the
  recognizer.

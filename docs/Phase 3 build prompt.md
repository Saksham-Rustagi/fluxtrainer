# Phase 3 build prompt: the teaching loop

Paste into Claude Code in the trainer repo. Phase 1 (the clone) and Phase 2 (the selection engine) are done.

---

## What this phase is, and why

Phase 2 produced a ranked queue of hooks worth about 4,500 points a game. **Reading that queue is worth nothing.** The finding the whole project rests on is that I take a 5+ letter word 74% of the time when it extends something I already found and about 1% otherwise, which means a word I have only read is a word I will not find. Vocabulary only converts when it becomes something my eye catches on a live board under a clock.

Phase 3 turns the queue into board vision. It is the product. Everything before it was preparation and everything after it is refinement.

The design constraint that matters most: **this has to be pleasant to open every day.** Not gamified, no streaks or XP, but fast, obvious, and short. If a session takes more than fifteen minutes or needs a decision before it starts, it will not survive contact with a real week.

---

## Before you write anything: settle the hook record

Phase 2 and Phase 3 both read and write hooks, and if their shapes drift the work gets redone. Fix the schema first, in one place, and make both sides use it:

```
Hook {
  stem, branches[{ word, class(additive|cellmate|mutating|dead),
                   myRate, topQuartileRate, reachability, points }],
  residual, enumerability, presenceByTierGrid, expectedGain, track
}
```

Also commit the Phase 2 output before touching it. It is currently untracked and it is the most valuable artifact in the repo.

---

## Where the context lives

| Source | What it holds |
| --- | --- |
| `docs/BUILD_PLAN.md` | The phase plan. This is Phase 3. |
| `docs/SPEC.md` | §7.3 affix grids, §7.5 enumerability, §7.5.1 residual gating, §7.6 cellmates, §9 review, §10 the loop, §11.1 constrained generation |
| `reports/queue_hooks.tsv`, `queue_words.tsv`, `misswipes.tsv` | The Phase 2 queue: 10,594 hooks, 3,331 words carrying gain, 24 repeated invalid strings |
| `reports/PHASE2_SUMMARY.md` | What the repricing did and the seven source disagreements it resolved |
| The Phase 1 clone gate report | swipe constants (a = −0.085, b = 0.086), baseline\_gap 0.383 s, 48 invalid attempts and 13 duplicates a game |
| FluxCore (`runs/v3-*`) | Generator, solver, reachability, enumerability |
| The clone app | Board rendering, swipe recognizer, timer, attempt logging. Reuse it; do not write a second board view. |

Where a number here disagrees with a source, the source wins and you flag it.

---

## Board types, and what each is allowed to constrain

This differs from §11.1, which applied a tier norm check to every training board. That was wrong: realism matters for transfer and for measurement, not for drills.

| Type | Constraint | Why |
| --- | --- | --- |
| **Drill board** | Hook present. Nothing else. | You are being shown where to look; realism is irrelevant |
| **Acquisition board** | Hook present, plus a loose density floor and ceiling on total word count | Has to feel like a real board or nothing transfers |
| **Measurement board** | Full ranked generation, tier and all | Comparability is the entire point |

The density band on acquisition boards is a wide floor and ceiling, not a tier's middle 80%. Finding a hook among 180 words is a different task from finding it among 800, and the second is the one that matters. Embedding a hook pulls boards dense, so the floor matters more than the ceiling.

Acquisition boards must not be identifiable as training boards. If I can tell mid-game which hook it was built around, nothing transfers to ranked.

---

## The three exercises

Build them in this order. Each is harder than the last and they form a progression for a single hook.

### 1. Branch completion (the core)

The stem is **lit on the board**. Find every additive extension before the timer. This is the exercise the 74x ratio points at: the skill is not knowing SERAI, it is seeing `RAI` already on screen and reaching for it.

- Drill board, 30 to 45 seconds, 3 to 6 targets.
- A counter shows how many remain, never which.
- On a find: the path draws, the branch ticks off, haptic per the clone's mapping.
- On timeout: the missed branches animate along their paths, one at a time, slowly. **Seeing the path is the lesson.** A list of missed words teaches nothing.
- Immediately offer the same hook on a fresh board, because the second attempt is where it sticks.

### 2. Family sweep

Same hook, **no stem lit**, acquisition board. Find every member. This is the transfer test: can you spot the hook yourself?

- 60 seconds, all words score normally so it feels like a game rather than a quiz.
- Review afterwards shows the hook's branches, found and missed, as paths.

### 3. Affix grid

Rapid valid/invalid judgements on a stem's branches, live and dead both. No board.

- One stem, branches one at a time, tap valid or not. Target under 1.2 s each.
- 60 to 100 judgements in about five minutes, which is where vocabulary throughput actually lives. A board gives you a handful of words in the same time.
- **Dead branches carry equal weight.** 20% of my invalid attempts carry an affix pattern, mostly `-ER`, `-S`, `-ERS`, `-ES`, and knowing a branch is dead is worth as much as knowing one is live.
- Pull dead branches from `misswipes.tsv` first where they exist: strings I have actually attempted are better teaching material than dictionary-derived ones.

---

## The session

One button on the home screen. Tapping it starts; no configuration, no menu, no choosing a hook.

```
  TAP ─── warm-up board (60s, unscored, no review)
           │  worth ~1,633 points on game 1 of a session; costs nothing
           │
           ├─ new hook: branch completion × 2 boards
           │                  then affix grid for the same stem
           │
           ├─ due hooks: family sweep × 2 acquisition boards
           │              (scheduled hooks embedded, unannounced)
           │
           └─ summary: 20 seconds. What stuck, what to expect tomorrow.
```

Ten to fifteen minutes. Two rules:

- **The app chooses the hook**, from the top of the queue filtered to `enumerability 2-6` and `owned >= 2`. Never ask me to pick. A queue of 10,594 hooks is a decision I should not have to make daily.
- **Any screen can be left mid-session** and resumed. Real sessions get interrupted.

A short-day path: one board plus one affix grid, about four minutes, graded normally. The spec's earlier idea of grading a short day at reduced weight penalises me for having a life and makes the schedule drift exactly when it shouldn't.

---

## What the UI must get right

- **Board view is the clone's**, unmodified. Same geometry, hit target, interpolation and haptics. If the drill board feels different from the game board, the motor pattern being trained is the wrong one.
- **No text during a drill.** Stem lit, counter, timer. Nothing else on screen.
- **Path animation on misses**, slow enough to follow. This is the single most important piece of feedback in the app.
- **One tap to start, one tap to repeat.** The most common action after a drill is doing it again.
- **No streaks, no XP, no daily goal rings.** The user is a top-50 player with a specific technical problem, and pressure to play while tired is worse than not playing.

---

## What gets recorded

Every exercise writes to the same attempt log the clone already uses, plus:

- Per branch: found or missed, time to find, whether the stem was lit, which board, attempt number for that hook.
- Per hook: exposures, find rate over time, first-attempt find rate on an unlit board (the number that actually matters).
- Affix grid: per branch correct/incorrect and latency, live and dead separately.

This feeds Phase 4's scheduling and the belief model in §8.1. Design it so Phase 4 does not need a migration.

### Learn from every board, not just the drilled hook

Every full board played in the app (warm-up, family sweep, acquisition) is already solved, so every word on it is an observed presence with a known outcome. Record all of them, not only the target hook's branches. Otherwise most of the signal is thrown away for free.

Per board, write a presence row for every solved word: the word, found or not, board id, grid, board density, whether it was reachable as an extension of something found earlier in that game, and time of find if found.

Update belief per §8.1 across all of it, with the same opportunity weighting the ranked import uses: presence on an 800-word board where I found 90 words is weak evidence of not knowing something; presence on a 180-word board is strong. Keep in-app and ranked observations distinguishable by source so either can be reweighted later.

Recompute the queue's `myRate` from combined ranked-plus-in-app data on a schedule, nightly or at session end. Three consequences should be visible:

- A hook I have learned falls in the ranking on its own.
- A word I picked up elsewhere stops being taught.
- The 2,161 candidates Phase 2 dropped for insufficient presence evidence gradually become rankable as in-app presences accumulate.

Show the queue's last-recomputed timestamp somewhere unobtrusive, so I can tell whether what I am looking at is current.

**Do not let drill outcomes alone drive belief.** Finding a branch with the stem lit is much weaker evidence than finding it unprompted on a full board, and treating them equally would make everything look learned: I would drill a hook, find its branches with the stem lit, watch belief jump, watch the hook leave the queue, and have learned nothing transferable. Weight by exercise type, strongest first: unprompted find on a full board, family sweep, lit-stem drill, affix grid (recognising a word is not finding it).

---

## The gate

**A hook drilled this week gets found unprompted, on a fresh acquisition board, next week.** First-attempt find rate with no stem lit, on a board I have not seen, at least a week after the drill.

Run it on the first 10 to 15 hooks. If they do not transfer, the exercises are wrong and no amount of scheduling in Phase 4 will rescue them. Report the rate plainly, including if it is bad.

Secondary, and worth watching from day one: does the time spent here show up in ranked play? Too early to attribute, but log it.

---

## Out of scope

No FSRS or spaced-repetition scheduling beyond a simple due date (Phase 4). No benchmark boards or progress dashboard (Phase 5). No longs-only, swipe-budget or opening drills (Phase 6). No changes to the Phase 2 ranking. No re-solving boards.

One exception: the warm-up board, because it is one unscored board at the top of the session and it is worth more per line of code than anything else in the app.

# Phase 3.5 build prompt: play, review, and the record of what I know

Paste into Claude Code in the trainer repo, after Phase 3 (`5d0892c`).

---

## Why this exists

Phase 3 built a good drill and no training app around it. Three things are missing, and they are the things that make the difference between a content engine and something worth opening:

1. **There is no way back to a stem I have learned.** I drilled `ERAS-`. I cannot see it again, cannot see which branches I own, cannot answer "have I got the ones worth having?" For `TORE-`, STORED is common and worth knowing and TUTORED is neither; the app knows this and will not tell me.
2. **There is no way to practise what I have learned.** No board seeded with several of my families, played normally, scored per family.
3. **There is no review.** I expected the core loop to be: play a board, and the app tells me which families I missed, which valuable words I missed, and which strings I keep swiping that are not words. Every input for that already exists. A board is solved on load, 428 presence rows get written per board, families and per-word expected gain are in the hook record, and repeated invalid strings are in `misswipes.tsv`. It is a query and a screen, not new machinery.

**The structural change:** playing becomes the home screen and drilling becomes something review sends me to. Right now it is the reverse.

### The tension to hold, because it is why the app is not just a solver

What I miss on any given board is mostly board luck. An app driven purely by "what did you miss today" teaches board-specific trivia and chases whatever I happened to fumble. The Phase 2 queue's expected-value ranking is a far better selector than one game's misses.

So: **review is the interface, the queue is the ranker.** When I miss 40 words on a board, show me the three that matter by expected value across all boards, not all 40. That is the whole design, and everything below follows from it.

---

## Where the context lives

| Source | What it holds |
| --- | --- |
| `docs/PHASE3_NOTES.md`, commit `5d0892c` | What Phase 3 built, and the judgement calls it made |
| `ios/FluxClone/Training/` | Hook record, board types, exercises, session, belief, queue |
| `reports/hooks.ndjson.gz` | All 10,594 hooks with 1.09M branches |
| `reports/queue_hooks.tsv`, `queue_words.tsv`, `misswipes.tsv` | The ranked queue and the repeated invalid strings |
| `docs/SPEC.md` §9 | The original board-first review design, which this phase finally implements |
| `docs/SPEC.md` §7.3, §7.5, §7.5.1, §7.6 | Affix grids, enumerability, residual, cellmates |
| The clone's SQLite | `presence`, `judgement`, `hook_state`, `word_belief`, the attempt log |

Where a number here disagrees with a source, the source wins and you flag it.

---

## 1. Restructure the app around playing

| Screen | What it is |
| --- | --- |
| **Play** | The home button. A fresh board, or mixed practice seeded with families I am learning. |
| **Review** | After every board. The engine of the app. |
| **My stems** | Everything I have drilled or met, with completion and trend. |
| **Drill** | Branch completion, family sweep, affix grid. Reached from review or from a stem, not from the front door. |
| **Queue** | Demoted to a reference tab. |

Playing a board must be one tap from launch, with no configuration.

---

## 2. Review, which has to be genuinely useful

After every board. Board-first, never a word list (§9.1). Hard cap of six items. Every item tappable through to its family page.

**The ordering rule: rank by expected value from the queue, not by what I missed most.** A board with 40 misses shows the three worth caring about.

Sections, in this order:

**Verdict.** One line. Score, tier percentile against my own history on that grid and tier, and the single biggest thing that went wrong.

**Families you missed.** The high-value ones only, using §7.4's priority ordering, which matters because these four cases are not equally interesting:

1. I found 2+ members of a family and missed another 5+ member. Cheapest possible points, and the strongest signal in review: I was on the stem and did not finish.
2. I missed a high-strength family entirely in a region I demonstrably worked.
3. I found the base and missed two or more extensions.
4. I missed a family entirely in a region I never touched.

Show each as the stem lit on the board with the missed branches animating along their paths, the same feedback as the drill's timeout. Suppress families that are only 3 and 4 letter words unless the board was sparse, because skipping those was correct play.

**Words you missed that are worth it.** Top three by expected gain from `queue_words.tsv`, not top three by anything local to this board. Each one shows its path, its family, and why it ranks: presence, points, my rate against the top quartile.

**Misswipes.** Strings I attempted that are not words, with a repeat count across all games. A first-time miss is noise; the fourth time I swipe RALL it is a fact about me. Classify as affix error, true non-word belief, path error, or early lift, per Phase 2's classification. Only the first two are learnable; show the other two as diagnostics without teaching anything from them.

**Duplicates.** Words I re-swiped after already finding them, with seconds lost. 13 a game costing 6.3 seconds is pure waste and nothing currently tells me it is happening.

Everything beyond the six items sits behind one tap into a full solution browser, deliberately out of the default flow.

---

## 3. The family page

Reachable from any review item, any stem, or search. This answers "have I learned the ones that matter?", which the app currently cannot.

For a stem, list every branch with:

- The word, its length and points
- **Status: owned, learning, or unknown**, from belief
- Presence: how often it turns up, by grid
- My rate against the top-quartile rate
- Expected gain if I learned it
- Class: additive, cellmate, mutating, dead

Sorted by expected value, not alphabetically. Dead affixes shown in their own block, because knowing `-IER` does not take is worth as much as knowing `-ER` does.

**The headline line is the point of the screen:** "You have 6 of the 9 branches worth knowing." Define "worth knowing" by expected gain above a threshold, and let me see the rest on request. For `TORE-`, STORED and RESTORE should sit above the line and TUTORED below it, and the screen should make that obvious without my having to reason about it.

Also on the page: when I last drilled this stem, how many times I have met it since, and my find rate on its branches before and after.

---

## 4. My stems

Everything I have drilled or met in play, with completion percentage, last drilled, last met, and the trend in find rate. Filterable by track, by completion, and by whether it is improving.

This is the record of what I have done. Without it the app has no memory I can see, and no way to answer "what have I actually learned this month."

---

## 5. Mixed practice

A board seeded with 3 to 5 families I am currently learning, played as a normal scored 80-second board with no hint that they are there.

Afterwards, scored per family: which I completed, which I part-found, which I missed entirely. This is the explicit version of Phase 4's unannounced re-injection, and I want both: the hidden one for honest scheduling, this one for when I want to test myself and see the result broken out.

---

## 6. Learning has to be visible, and has to change something

This is the part most likely to be built as a static list, and it would be much less useful that way. **If I am genuinely getting a word more often, the app has to notice and respond.** Three mechanisms:

**The queue moves on its own.** `myRate` recomputes from ranked plus in-app presences. A branch I now find reliably loses its expected gain, drops out of the queue, and stops being offered. A stem whose residual empties leaves the active list. I should never be drilled on something I have demonstrably learned, and if I am, the recompute is broken.

**Status transitions are surfaced, once.** When a word crosses unknown → learning → owned, say so in that board's review and then never again. "STORER: you have found it on 4 of the last 5 boards it appeared on. Owned." One line, no ceremony, no streaks or XP. The point is information, not reward.

**Per-stem trend, shown where the decision gets made.** On the family page and in My Stems: find rate on this stem's branches before the first drill against since, with the presence counts, so I can see whether the number means anything yet. Three presences is not evidence; twenty is.

**And the inverse, which matters as much.** If a branch I own starts getting missed again, it should come back. Your own data says retention is weak: a word is taken 25.2% of the time after a presence where it was taken, and 10.3% after one where it was missed, and 4,320 words were found once or twice and then missed on five or more later presences. So decay is the normal case, not the exception. Surface a **"slipping"** state on the family page and in My Stems when a previously owned branch's recent rate falls materially below its established rate, and let it re-enter the queue. Phase 4 will schedule this properly; here it only has to be visible.

**Weight evidence by how it was obtained**, as Phase 3 already does: an unprompted find on a full board is worth 1.00, a family sweep 0.60, a lit-stem drill 0.25, an affix grid 0.10. Status must be driven by unprompted finds. If four lit-stem finds could promote a word to owned, the app would congratulate itself for teaching me nothing.

---

## Out of scope

No FSRS or real scheduling (Phase 4). No benchmark boards or progress dashboard (Phase 5). No opening or longs-only drills (Phase 6). No changes to the Phase 2 ranking model or to the recognizer. Do not re-solve the ranked boards.

## The gate

Play five boards. After each, does review tell me something I did not know and would act on? If it mostly reports things I already knew, or buries the useful item among five that are not, the ordering is wrong and the fix is the ranking, not the UI.

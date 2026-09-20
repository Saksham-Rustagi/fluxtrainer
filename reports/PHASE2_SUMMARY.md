# Phase 2 — the selection engine

What this is: a ranked queue of **hooks**, each a stem plus the branches hanging off it, with
every number behind each position exposed. It teaches nothing yet. Read it at
[`reports/queue.html`](queue.html); the same content is in
[`queue_hooks.tsv`](queue_hooks.tsv), [`queue_words.tsv`](queue_words.tsv) and
[`misswipes.tsv`](misswipes.tsv).

Built from 2,865 current-regime ranked games (seasons 7-10) of 9,034
total, the v3 simulation under `runs/v3-full` and `runs/v3-m3-curated`, and the 8 clone games in
`data/fluxclone-20260920-004740.sqlite`. Reproduce with `sh tools/queue/run_all.sh`.

## What survived the repricing

The shipped alpha list priced every word at the take rate reached on words already found
reliably. Replaced by `achievable(w) = max(topQuartileRate(w), myRate(w))`, the list shrinks hard.

| | before | after |
| --- | --- | --- |
| alpha candidates carrying any gain | 3,698 | 830 (22%) |
| expected gain over that whole set | 19,368 pts/game | 986 pts/game (-95%) |
| expected gain, its top 200 | 3,695 pts/game | 609 pts/game (-84%) |

Of the 3,698 old candidates, **707 drop because you already
takes them more often than the top quartile does** — those were strengths ranked as gaps.
Another 2,161 drop for want of evidence rather than want of value: their
top-quartile rate rests on fewer than 30 presences and is not trusted. That
second group is the bigger cut and it is a data limit, not a finding.

The prompt's own diagnostic checks out on the published top 200:
30% of it are words you find more often than the field and
28% more often than the top quartile.

## The queue

**10,594 hooks** (3,560 with at least one word to
learn) mined from 11,526 candidate stems over the
11,993 words you actually meet, and **3,331
words** carrying gain.

| track | words | pts/game | in the top 200 words | what learning it does |
| --- | --- | --- | --- | --- |
| par | 1,939 | 3,262 | 169 words, 995 pts | closes a measured gap to the top quartile |
| alpha | 1,392 | 1,259 | 31 words, 202 pts | opens one |
| misswipe | 354 repeated strings, 152 of them study items | up to 5,692 at full weight, 1,138 at the 0.2 used | — | removes waste |

The top 100 hooks carry **1,725 points a game** across
522 distinct words
(1,278 par, 417
alpha, 30 misswipe). All 100 are hooks you already owns two
or more branches of, 83% are inside the 2-6 enumerability band, and
their stem lengths are 14 of length 3, 82 of length 4, 4 of length 5
— the 3-to-4 band Phase 1 measured.

### Top 20 hooks

| # | hook | track | score | pts/game | owned | items | enum | what it teaches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ERAS- | alpha | 10.63 | 49.7 | 15 | 5 | 2.0 *cue* | ERASE ERASED ERASES ERASER TERAS |
| 2 | TORE- | par | 8.21 | 33.5 | 8 | 4 | 2.4 *cue* | STORE STORES STORED STORER |
| 3 | TANE- | par | 6.39 | 22.2 | 3 | 3 | 2.1 *cue* | STANES STANE STANED |
| 4 | ONES- | par | 6.14 | 43.4 | 13 | 9 | 5.0 *cue* | IRONES RONES HONES DRONES NONES TRONES |
| 5 | ENTE- | par | 6.12 | 36.0 | 15 | 7 | 5.1 *cue* | RENTE RENTES SENTE ENTERS ENTERA TENTER |
| 6 | DERA- | par | 6.11 | 28.6 | 13 | 5 | 2.5 *cue* | DERAT DERATS DERAIL DERATE DERATES |
| 7 | INTER- | par | 5.86 | 20.4 | 24 | 3 | 4.5 *cue* | TINTER INTERS TINTERS |
| 8 | HEAR- | par | 5.82 | 30.7 | 15 | 6 | 4.5 *cue* | HEARTS HEART HEARSE HEARE SHEAR HEARD |
| 9 | RACE- | par | 5.34 | 15.4 | 20 | 2 | 4.1 *cue* | TRACES TRACE |
| 10 | RETIN- | par | 5.29 | 24.8 | 6 | 5 | 2.9 *cue* | RETINA RETINE RETINAS RETINES RETINAL |
| 11 | SIRE- | alpha | 4.85 | 25.6 | 5 | 6 | 2.1 *cue* | SIREN SIREES SIREE SIRED SIRENS SIRES |
| 12 | ASTE- | par | 4.71 | 39.0 | 119 | 11 | 7.0 | ASTER ASTERS TASTES HASTE RASTER GASTER |
| 13 | TERE- | par | 4.68 | 16.3 | 20 | 3 | 3.1 *cue* | STERE STERES STEREO |
| 14 | HALE- | par | 4.59 | 29.7 | 5 | 8 | 3.9 *cue* | HALERS HALER HALES SHALE HALED HALEST |
| 15 | AINT- | par | 4.56 | 35.0 | 7 | 10 | 3.3 *cue* | SAINTS SAINT DAINT DAINTS PAINT TAINT |
| 16 | LOSE- | par | 4.36 | 20.4 | 9 | 5 | 3.2 *cue* | LOSERS LOSER CLOSE LOSED LOSEN |
| 17 | TEAD- | par | 4.33 | 9.9 | 4 | 1 | 2.6 *cue* | STEAD |
| 18 | SHIN- | par | 4.28 | 14.9 | 6 | 3 | 4.6 *cue* | SHINER SHINE SHINS |
| 19 | ATES- | par | 4.25 | 35.2 | 82 | 11 | 7.1 | REATES URATES ORATES DERATES PLATES YATES |
| 20 | EIST- | alpha | 4.21 | 19.7 | 8 | 5 | 2.8 *cue* | REIST HEIST REISTS DEIST GEIST |

### Top 20 words

| # | word | track | pts | me | field | top 25% | n | per game | pts/game | hook | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ERASE | alpha | 800 | 0.8% | 7.8% | 27.8% | 205 | 0.085 | 18.3 | ERAS- | unknown |
| 2 | STORE | par | 800 | 42.3% | 46.7% | 58.2% | 177 | 0.084 | 10.7 | TORE- | learning |
| 3 | HATERS | par | 1400 | 55.1% | 59.6% | 77.8% | 54 | 0.031 | 9.9 | ATER- | known |
| 4 | ERAS | alpha | 400 | 6.9% | 10.0% | 18.2% | 500 | 0.218 | 9.9 | RSE- | unknown |
| 5 | STEAD | par | 800 | 19.3% | 29.4% | 44.3% | 106 | 0.049 | 9.8 | TEAD- | unknown |
| 6 | ASTER | par | 800 | 28.3% | 22.8% | 38.6% | 277 | 0.115 | 9.5 | ASTE- | learning |
| 7 | STERE | par | 800 | 19.7% | 22.1% | 34.6% | 182 | 0.080 | 9.5 | TERE- | unknown |
| 8 | RETINA | par | 1400 | 15.8% | 20.7% | 31.9% | 113 | 0.042 | 9.4 | RETIN- | unknown |
| 9 | STARE | par | 800 | 58.0% | 56.7% | 67.5% | 277 | 0.123 | 9.4 | TARE- | known |
| 10 | STANES | par | 1400 | 37.8% | 38.6% | 63.5% | 74 | 0.026 | 9.3 | TANE- | learning |
| 11 | ERASED | alpha | 1400 | 1.4% | 8.1% | 27.7% | 65 | 0.025 | 9.3 | ERAS- | unknown |
| 12 | STARED | par | 1400 | 52.9% | 53.2% | 71.3% | 94 | 0.036 | 9.1 | TARE- | known |
| 13 | ERASES | par | 1400 | 0.0% | 10.0% | 35.6% | 45 | 0.018 | 9.0 | ERAS- | unknown |
| 14 | STANE | par | 800 | 34.4% | 37.2% | 48.9% | 184 | 0.077 | 9.0 | TANE- | learning |
| 15 | HALERS | par | 1400 | 23.8% | 32.6% | 67.4% | 43 | 0.015 | 9.0 | HALE- | unknown |
| 16 | REIST | alpha | 800 | 4.7% | 8.9% | 17.1% | 217 | 0.090 | 8.9 | EIST- | unknown |
| 17 | STORES | par | 1400 | 43.2% | 46.4% | 63.8% | 58 | 0.031 | 8.9 | TORE- | learning |
| 18 | RENTE | par | 800 | 41.8% | 40.9% | 64.3% | 129 | 0.049 | 8.9 | ENTE- | learning |
| 19 | SIREN | alpha | 800 | 4.6% | 9.5% | 19.0% | 168 | 0.075 | 8.7 | SIRE- | unknown |
| 20 | SNORE | par | 800 | 19.4% | 23.7% | 37.5% | 144 | 0.059 | 8.6 | NOR- | unknown |

## The distribution of my current rates in the queue

| my current rate | top 200 | share | whole queue | share |
| --- | --- | --- | --- | --- |
| 0%-1% | 11 | 6% | 616 | 18% |
| 1%-5% | 21 | 10% | 573 | 17% |
| 5%-10% | 15 | 8% | 358 | 11% |
| 10%-20% | 39 | 20% | 492 | 15% |
| 20%-35% | 43 | 22% | 588 | 18% |
| 35%-50% | 42 | 21% | 440 | 13% |
| 50%-75% | 29 | 14% | 263 | 8% |
| 75%-101% | 0 | 0% | 1 | 0% |

Of the top 200 words, 99 are unknown by belief,
68 partly learned and 33
already known. **That last group is not a vocabulary problem** — those are words you know and
take at half the top quartile's rate, which is a seeing-and-reaching problem, and a word drill
is the wrong fix for them. They are kept in the queue and flagged, because Phase 3's board work
is exactly what they need.

## One thing to look at before you accept it

**189/200 of the top 200 words use at most one letter outside AEIORSTN**, and the top 100
hooks' stems are built from the same eight letters. That is not a bug: presence per game
multiplies every gain in the model, and the letters that appear on Flux boards are the letters
that appear in this queue. But it means the curriculum is narrower than the point totals make
it sound. It will train the E/R/S/T/A/N neighbourhoods hard and say nothing about anything
else, and if the transfer you want is general board vision rather than a specific set of
extensions, that is the thing to argue with.

## The sanity checks the prompt asked for

**Does any word rank where my rate already exceeds the top quartile?**
0 — the floor is applied, and such words score exactly zero.

**How much presence before the top-quartile rate is trusted?** 30 presences
in top-quartile games, pooled across regimes. That is a real choice and it moves the total a lot:

| min top-quartile presences | words with gain | total pts/game | top 200 pts/game |
| --- | --- | --- | --- |
| 10 | 5486 | 6,876 | 1,235 |
| 20 | 4594 | 5,856 | 1,222 |
| 30 | 3331 | 4,521 | 1,197 |
| 50 | 1910 | 2,929 | 1,128 |
| 100 | 651 | 1,195 | 838 |

The top 200 is far more stable than the total: 1,197 pts/game at 30 against
1,235 at 10 and
838 at 100. Shrinking the rate toward the per-length
mean instead of hard-gating moves the top 200 to 1,139 pts/game and keeps
167 of the same 200 words. Both estimates are in
`queue_words.tsv`.

**Does the top 200 exceed what 80 seconds can hold?** No. The top 200 implies
**1.3 extra words a game**, costing
**1.0 s** at the clone's measured constants
(`0.383 + -0.085 + 0.086n`). Against an 80 s clock with
95 words already in it, that fits — the gain is concentrated in rate
improvements on words already present, not in adding volume. It is worth saying that the clock
is nonetheless full: 27.1 s a game currently goes to invalid
attempts, which is where any new time would have to come from.

## The misswipe track

| cause | attempts | share | s / game | what it becomes |
| --- | --- | --- | --- | --- |
| affixError | 77 | 20% | 5.1 | study item |
| earlyLift | 52 | 14% | 3.6 | diagnostic |
| pathError | 170 | 45% | 12.1 | diagnostic |
| trueNonWord | 83 | 22% | 6.3 | study item |

Of 27.1 s a game on invalid attempts,
**11.4 s is learnable** — affix errors and true
non-word beliefs. The rest is motor and appears as diagnostics only. Nothing in the track is
scored and nothing pushes toward swiping less: some invalid attempts are how a board gets
searched, and suppressing them would cost words (SPEC 16.6).

The dead-affix weight is the softest number in the whole queue. The cost is measured
(5.1 s a game, worth up to
5,692 points at the clone's own productive rate) but
**nothing measures what share of it drilling actually removes**. The default weight of
0.2 is a judgement. At weight 0 the top 100 keeps
93 of the same hooks; at weight 1.0,
84. The slider in the browser is where to argue with it.

## Alpha: unknown against unfindable

1164 alpha words read as findable and simply not found;
228 are flagged **hard to see** — rarely sitting on a
path already swiped, few distinct paths on the boards that carry them, and not hanging off a
hook already part-owned. Those are traps, not opportunities, and are labelled in both the browser
and `queue_words.tsv`.

The clearest opportunity in the track is the field's vowel-initial deficit: at every length the
field takes vowel-initial words at
0.23 to
0.37 times the consonant-initial rate.
That is a habit, not a property of the board — those words are findable and are not found.
Vowel-initial words are 14% of the queue and
10% of its top 200, and ERASE, ERASED, ERASER and ERASES
between them are the single largest block of expected gain in the whole list.

## The ten items I am least confident about

1. **SHITES** (#175, par, 4.5 pts/game, me 44.4% against the top quartile's 70.0%) — the top-quartile rate rests on 30 presences, so its 95% interval is about +/-16%; only 36 of your 2,865 boards carried it.
2. **STORER** (#104, par, 5.4 pts/game, me 35.6% against the top quartile's 60.0%) — the top-quartile rate rests on 30 presences, so its 95% interval is about +/-18%; only 45 of your 2,865 boards carried it.
3. **DATERS** (#103, par, 5.4 pts/game, me 60.5% against the top quartile's 75.0%) — the top-quartile rate rests on 52 presences, so its 95% interval is about +/-12%; belief already calls it known, so the gap is consistency rather than vocabulary and a word drill is probably the wrong instrument.
4. **PASTER** (#116, par, 5.1 pts/game, me 63.5% against the top quartile's 83.7%) — the top-quartile rate rests on 43 presences, so its 95% interval is about +/-11%; belief already calls it known, so the gap is consistency rather than vocabulary and a word drill is probably the wrong instrument; only 52 of your 2,865 boards carried it.
5. **CRANES** (#150, par, 4.7 pts/game, me 39.2% against the top quartile's 58.1%) — the top-quartile rate rests on 31 presences, so its 95% interval is about +/-17%; belief already calls it known, so the gap is consistency rather than vocabulary and a word drill is probably the wrong instrument; only 51 of your 2,865 boards carried it.
6. **MASTER** (#73, par, 6.0 pts/game, me 52.9% against the top quartile's 77.1%) — the top-quartile rate rests on 35 presences, so its 95% interval is about +/-14%; belief already calls it known, so the gap is consistency rather than vocabulary and a word drill is probably the wrong instrument; only 51 of your 2,865 boards carried it.
7. **INNERS** (#129, par, 5.0 pts/game, me 0.0% against the top quartile's 29.0%) — the top-quartile rate rests on 31 presences, so its 95% interval is about +/-16%; its reachability off NNER- is fitted rather than measured, because the extension is not one of the 60 mined affixes; only 35 of your 2,865 boards carried it.
8. **LOOSE** (#168, par, 4.6 pts/game, me 35.7% against the top quartile's 64.9%) — the top-quartile rate rests on 37 presences, so its 95% interval is about +/-15%; its reachability off OOSE- is fitted rather than measured, because the extension is not one of the 60 mined affixes; only 56 of your 2,865 boards carried it.
9. **TRACES** (#29, par, 7.9 pts/game, me 12.8% against the top quartile's 54.3%) — the top-quartile rate rests on 35 presences, so its 95% interval is about +/-17%; its reachability off RACE- is fitted rather than measured, because the extension is not one of the 60 mined affixes; only 39 of your 2,865 boards carried it.
10. **TATERS** (#97, par, 5.5 pts/game, me 62.7% against the top quartile's 77.8%) — the top-quartile rate rests on 54 presences, so its 95% interval is about +/-11%; belief already calls it known, so the gap is consistency rather than vocabulary and a word drill is probably the wrong instrument.

## Where this disagrees with the brief, and why

The brief said the source wins. These are the places they differ.

0. **Three of the named sources sit elsewhere.** `docs/BUILD_PLAN.md` is `docs/Build plan.md`;
   `PHASE1_REPORT.md` is `docs/PHASE1_REPORT.md`; `reports/analytics.html` is a two-line
   redirect, and the report itself is `reports/analytics_miningmath.html` (with
   `analytics_nicole.html` beside it). All of them exist and were read. `data/ranked/` holds
   both players; only `miningmath` is used here, and `FLUX_PLAYER=nicole` would rebuild the
   whole queue against hers.
1. **`runs/full` and `runs/m3-curated` are the v1 runs.** PHASE1_REPORT Part A supersedes them
   under ruleset v3, where reachability moved by −23% to +27% by affix and cellmate pathability
   fell at every length. Everything here uses `runs/v3-full` and `runs/v3-m3-curated`.
2. **The old model is not a uniform 74%.** `tools/analytics/salpha.py` blends a per-word rate by
   length and situation off reliable words: median 0.41 across the candidate set
   and 0.56 across the published top 300, running from 0.24 to 0.74. The criticism stands
   unchanged — it is still a reliable-word rate applied to unreliable words — but 74% is the
   ceiling of that blend, not the constant.
3. **SPEC 7.2 rule 2 (coherence ≥ 0.65 and stem length ≥ 4) is reported, not applied.** It
   contradicts SPEC 7.5's measured 3-to-4 band and would delete the build plan's own `RAI-`
   example, whose coherence against SERAI is 0.60. Enumerability does the job coherence was
   there to do, and the coherence figure is on every hook row.
4. **Enumerability gates the cue, not the queue.** SPEC 7.5 says in terms that the 2-6 band
   "governs whether a stem works as a hunting cue, and nothing else... It does not decide what
   is worth studying." So `RAI-`, at 10.4, stays in the queue and is marked
   as not a board cue. The band is the browser's default filter, not a deletion.
5. **SPEC 6.2's `P(capacity | tier)` term is not used.** Expected gain here is measured presence
   times a measured rate gap; capacity is already inside both, and multiplying by it again would
   double-count. Presence by tier and grid is shown per word so the Spam-board caveat stays
   visible.
6. **Cellmates above 5 letters carry no value on a hook.** Phase 1 measured anagram pathability
   at 0.78 / 0.53 / 0.34 / 0.21 for lengths 3 to 6,
   so only 3s and 4s clear SPEC 7.6's 0.5 threshold. Before this rule the ranking was dominated
   by fragment stems that happened to sit inside one member of a large anagram set; ASTER and
   TERAS earn under their own stems, where they are additive.
7. **The clock cost.** The brief's "about 26% of the clock" is the swipe-only figure and is
   exactly right (26% for invalid plus duplicate re-swipes). All in, with
   decision time, `reports/clone_gate.md` puts invalid attempts alone at 33.9%.

## What is soft

- **The top-quartile rate is pooled across regimes** while presence and your own rate are
  current-regime only. Board generation changed before season 7, so how often a word is
  *present* moved; how often a strong player *takes* it once present should not have. Using
  current-regime-only top-quartile rates would drop the median denominator from 77 to 23.
- **Reachability for most branches is fitted, not measured.** Of the branch rows on the top 200
  hooks, 18,109 use the rate observed on your own boards,
  492 the simulator's measured affix table, and
  51,823 a per-letter multiplicative model fitted on those 60
  affixes (R² 0.987 on log p, median error
  4%). The model overstates long rare
  affixes by about 2x — `-LESS` fits at 0.013 against a measured 0.0064 — which flatters hooks
  whose dead grid is built on them.
- **Effort is a count, not a measurement.** Study items weighted 1.0 additive, 1.3 cellmate,
  0.35 for a valid/invalid judgment, times 0.6 on a hook with two or more owned
  branches. Nothing in the project measures learning time, and these weights move the order.
- **Eight clone games.** Every misswipe rate is provisional at that n. The structure — that
  20% is affix error and
  22% is true non-word belief — is
  the finding; the seconds are not.
- **Enumerability is calibrated, not directly measured, for rare stems.** Summing per-branch
  reachability answers M1's question (does it extend the stem's path), and SPEC 7.5's band was
  set against M3's (is the member findable at all). The ratio is recovered per stem length by
  running this model over M3's own curatedWord population:
  ×1.82 at 3 letters, ×1.15 at 4 letters, ×0.92 at 5 letters.
  Where the stem is present on 200+ of your boards the observed number is used instead, and
  every hook row says which.

## The gate

Read the top 100 hooks and the top 200 words and decide whether they are worth learning. That is
the judgement this phase exists to hand over, and Phase 3 should not be built until it is made.

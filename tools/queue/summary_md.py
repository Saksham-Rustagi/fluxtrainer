"""reports/PHASE2_SUMMARY.md: the one-page read on what the queue says and what it rests on."""
import os

import pandas as pd

import qcommon as Q
import rank as RK


def _t(rows, head):
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def write(B, path=None):
    s, q, hk = B["summaryStats"], B["queue"], B["hooks"]
    rp, ck, tr = s["repricing"], s["checks"], s["tracks"]
    m = s["meta"]
    hd = pd.DataFrame(hk)
    path = path or os.path.join(Q.REPORTS, "PHASE2_SUMMARY.md")

    top_hooks = _t([[h["rank"], h["stem"] + "-", h["track"], f"{h['score']:.2f}",
                     f"{h['value']:.1f}", h["owned"], h["studyItems"],
                     f"{h['enumerabilityFindable']:.1f}" + (" *cue*" if h["cueable"] else ""),
                     " ".join(w for w, _, _ in sorted(h["items"], key=lambda t: -t[1])[:6])]
                    for h in hk[:20]],
                   ["#", "hook", "track", "score", "pts/game", "owned", "items", "enum", "what it teaches"])
    tw = q.head(20)
    top_words = _t([[r["rank"], w, r.track, r.pts, f"{r.my:.1%}", f"{r.fieldRateAll:.1%}",
                     f"{r.topQ:.1%}", int(r.nTopQAll), f"{r.presPerGameCur:.3f}",
                     f"{r.expectedGain:.1f}", (r.hook + "-") if r.hook else "-", r.status]
                    for w, r in tw.iterrows()],
                   ["#", "word", "track", "pts", "me", "field", "top 25%", "n", "per game",
                    "pts/game", "hook", "status"])
    rates = _t([[k, v, f"{v / max(sum(s['myRateDistributionTop200'].values()), 1):.0%}",
                 s["myRateDistributionAll"][k],
                 f"{s['myRateDistributionAll'][k] / max(sum(s['myRateDistributionAll'].values()), 1):.0%}"]
                for k, v in s["myRateDistributionTop200"].items()],
               ["my current rate", "top 200", "share", "whole queue", "share"])
    sens = _t([[k, v["words"], f"{v['totalGain']:,.0f}", f"{v['top200Gain']:,.0f}"]
               for k, v in sorted(ck["topQSensitivity"].items(), key=lambda kv: int(kv[0]))],
              ["min top-quartile presences", "words with gain", "total pts/game", "top 200 pts/game"])
    doubt = "\n".join(f"{i+1}. **{d['word']}** (#{d['rank']}, {d['track']}, "
                      f"{d['expectedGain']:.1f} pts/game, me {d['myRate']:.1%} against the top "
                      f"quartile's {d['topQRate']:.1%}) — {d['why']}."
                      for i, d in enumerate(s["leastConfident"]))
    cause = _t([[k, v["attempts"], f"{v['attempts'] / 382:.0%}",
                 f"{v['secondsAllIn'] / 8:.1f}", "study item" if k in ("affixError", "trueNonWord")
                 else "diagnostic"]
                for k, v in tr["misswipe"]["byCause"].items()],
               ["cause", "attempts", "share", "s / game", "what it becomes"])

    conc = int(sum(1 for w in q.head(200).index
                   if sum(1 for c in w if c not in "AEIORSTN") <= 1))
    text = f"""# Phase 2 — the selection engine

What this is: a ranked queue of **hooks**, each a stem plus the branches hanging off it, with
every number behind each position exposed. It teaches nothing yet. Read it at
[`reports/queue.html`](queue.html); the same content is in
[`queue_hooks.tsv`](queue_hooks.tsv), [`queue_words.tsv`](queue_words.tsv) and
[`misswipes.tsv`](misswipes.tsv).

Built from {m['gamesCur']:,} current-regime ranked games (seasons 7-10) of {m['gamesAll']:,}
total, the v3 simulation under `runs/v3-full` and `runs/v3-m3-curated`, and the 8 clone games in
`data/fluxclone-20260920-004740.sqlite`. Reproduce with `sh tools/queue/run_all.sh`.

## What survived the repricing

The shipped alpha list priced every word at the take rate reached on words already found
reliably. Replaced by `achievable(w) = max(topQuartileRate(w), myRate(w))`, the list shrinks hard.

| | before | after |
| --- | --- | --- |
| alpha candidates carrying any gain | {rp['candidates']:,} | {rp['survivors']:,} ({rp['survivors'] / rp['candidates']:.0%}) |
| expected gain over that whole set | {rp['oldAllGain']:,.0f} pts/game | {rp['newSameSetGain']:,.0f} pts/game ({rp['newSameSetGain'] / rp['oldAllGain'] - 1:+.0%}) |
| expected gain, its top 200 | {rp['oldTop200Gain']:,.0f} pts/game | {rp['newTop200OfOldSet']:,.0f} pts/game ({rp['newTop200OfOldSet'] / rp['oldTop200Gain'] - 1:+.0%}) |

Of the {rp['candidates']:,} old candidates, **{rp['droppedBeatTopQ']:,} drop because you already
takes them more often than the top quartile does** — those were strengths ranked as gaps.
Another {rp['droppedTopQUntrusted']:,} drop for want of evidence rather than want of value: their
top-quartile rate rests on fewer than {ck['minTopQPresences']} presences and is not trusted. That
second group is the bigger cut and it is a data limit, not a finding.

The prompt's own diagnostic checks out on the published top 200:
{rp['oldTop200MyBeatsField']:.0%} of it are words you find more often than the field and
{rp['oldTop200MyBeatsTopQ']:.0%} more often than the top quartile.

## The queue

**{s['hooks']['inQueue']:,} hooks** ({s['hooks']['withStudyItems']:,} with at least one word to
learn) mined from {s['hooks']['mined']:,} candidate stems over the
{s['hooks']['universe']:,} words you actually meet, and **{tr['par']['words'] + tr['alpha']['words']:,}
words** carrying gain.

| track | words | pts/game | in the top 200 words | what learning it does |
| --- | --- | --- | --- | --- |
| par | {tr['par']['words']:,} | {tr['par']['gain']:,.0f} | {tr['par']['top200Words']} words, {tr['par']['top200Gain']:,.0f} pts | closes a measured gap to the top quartile |
| alpha | {tr['alpha']['words']:,} | {tr['alpha']['gain']:,.0f} | {tr['alpha']['top200Words']} words, {tr['alpha']['top200Gain']:,.0f} pts | opens one |
| misswipe | {tr['misswipe']['repeatedStrings']} repeated strings, {tr['misswipe']['studyItems']} of them study items | up to {tr['misswipe']['deadPointsCeilingPerGame']:,.0f} at full weight, {tr['misswipe']['deadPointsCeilingPerGame'] * tr['misswipe']['weightUsed']:,.0f} at the {tr['misswipe']['weightUsed']} used | — | removes waste |

The top 100 hooks carry **{s['hooks']['top100Value']:,.0f} points a game** across
{s['hooks']['top100DistinctWords']} distinct words
({s['hooks']['top100ValueParDistinct']:,.0f} par, {s['hooks']['top100ValueAlphaDistinct']:,.0f}
alpha, {s['hooks']['top100ValueMisswipe']:,.0f} misswipe). All 100 are hooks you already owns two
or more branches of, {s['hooks']['top100Cueable']:.0%} are inside the 2-6 enumerability band, and
their stem lengths are {', '.join(f"{v} of length {k}" for k, v in s['hooks']['top100StemLen'].items())}
— the 3-to-4 band Phase 1 measured.

### Top 20 hooks

{top_hooks}

### Top 20 words

{top_words}

## The distribution of my current rates in the queue

{rates}

Of the top 200 words, {s['statusTop200'].get('unknown', 0)} are unknown by belief,
{s['statusTop200'].get('learning', 0)} partly learned and {s['statusTop200'].get('known', 0)}
already known. **That last group is not a vocabulary problem** — those are words you know and
take at half the top quartile's rate, which is a seeing-and-reaching problem, and a word drill
is the wrong fix for them. They are kept in the queue and flagged, because Phase 3's board work
is exactly what they need.

## One thing to look at before you accept it

**{conc}/200 of the top 200 words use at most one letter outside AEIORSTN**, and the top 100
hooks' stems are built from the same eight letters. That is not a bug: presence per game
multiplies every gain in the model, and the letters that appear on Flux boards are the letters
that appear in this queue. But it means the curriculum is narrower than the point totals make
it sound. It will train the E/R/S/T/A/N neighbourhoods hard and say nothing about anything
else, and if the transfer you want is general board vision rather than a specific set of
extensions, that is the thing to argue with.

## The sanity checks the prompt asked for

**Does any word rank where my rate already exceeds the top quartile?**
{ck['wordsRankedWhereMyRateExceedsTopQ']} — the floor is applied, and such words score exactly zero.

**How much presence before the top-quartile rate is trusted?** {ck['minTopQPresences']} presences
in top-quartile games, pooled across regimes. That is a real choice and it moves the total a lot:

{sens}

The top 200 is far more stable than the total: {ck['top200Gain']:,.0f} pts/game at 30 against
{ck['topQSensitivity']['10']['top200Gain']:,.0f} at 10 and
{ck['topQSensitivity']['100']['top200Gain']:,.0f} at 100. Shrinking the rate toward the per-length
mean instead of hard-gating moves the top 200 to {ck['top200GainShrunk']:,.0f} pts/game and keeps
{ck['rawVsShrunkTop200Overlap']} of the same 200 words. Both estimates are in
`queue_words.tsv`.

**Does the top 200 exceed what 80 seconds can hold?** No. The top 200 implies
**{ck['top200ExtraWordsPerGame']:.1f} extra words a game**, costing
**{ck['top200ExtraSecondsPerGame']:.1f} s** at the clone's measured constants
(`0.383 + {Q.SWIPE_A} + {Q.SWIPE_B}n`). Against an 80 s clock with
{ck['meanWordsPerGame']:.0f} words already in it, that fits — the gain is concentrated in rate
improvements on words already present, not in adding volume. It is worth saying that the clock
is nonetheless full: {ck['secondsOnInvalidPerGame']:.1f} s a game currently goes to invalid
attempts, which is where any new time would have to come from.

## The misswipe track

{cause}

Of {tr['misswipe']['secondsPerGameAllInvalid']:.1f} s a game on invalid attempts,
**{tr['misswipe']['secondsPerGameLearnable']:.1f} s is learnable** — affix errors and true
non-word beliefs. The rest is motor and appears as diagnostics only. Nothing in the track is
scored and nothing pushes toward swiping less: some invalid attempts are how a board gets
searched, and suppressing them would cost words (SPEC 16.6).

The dead-affix weight is the softest number in the whole queue. The cost is measured
({tr['misswipe']['byCause']['affixError']['secondsAllIn'] / 8:.1f} s a game, worth up to
{tr['misswipe']['deadPointsCeilingPerGame']:,.0f} points at the clone's own productive rate) but
**nothing measures what share of it drilling actually removes**. The default weight of
{tr['misswipe']['weightUsed']} is a judgement. At weight 0 the top 100 keeps
{s['hooks']['top100OverlapAtMisswipe0.0']} of the same hooks; at weight 1.0,
{s['hooks']['top100OverlapAtMisswipe1.0']}. The slider in the browser is where to argue with it.

## Alpha: unknown against unfindable

{s['findabilityAlpha'].get('findable', 0)} alpha words read as findable and simply not found;
{s['findabilityAlpha'].get('hard to see', 0)} are flagged **hard to see** — rarely sitting on a
path already swiped, few distinct paths on the boards that carry them, and not hanging off a
hook already part-owned. Those are traps, not opportunities, and are labelled in both the browser
and `queue_words.tsv`.

The clearest opportunity in the track is the field's vowel-initial deficit: at every length the
field takes vowel-initial words at
{min(s['vowelInitial']['fieldRatioByLength'].values()):.2f} to
{max(s['vowelInitial']['fieldRatioByLength'].values()):.2f} times the consonant-initial rate.
That is a habit, not a property of the board — those words are findable and are not found.
Vowel-initial words are {s['vowelInitial']['queueShare']:.0%} of the queue and
{s['vowelInitial']['top200Share']:.0%} of its top 200, and ERASE, ERASED, ERASER and ERASES
between them are the single largest block of expected gain in the whole list.

## The ten items I am least confident about

{doubt}

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
   length and situation off reliable words: median {rp['uniformQ']:.2f} across the candidate set
   and 0.56 across the published top 300, running from 0.24 to 0.74. The criticism stands
   unchanged — it is still a reliable-word rate applied to unreliable words — but 74% is the
   ceiling of that blend, not the constant.
3. **SPEC 7.2 rule 2 (coherence ≥ 0.65 and stem length ≥ 4) is reported, not applied.** It
   contradicts SPEC 7.5's measured 3-to-4 band and would delete the build plan's own `RAI-`
   example, whose coherence against SERAI is 0.60. Enumerability does the job coherence was
   there to do, and the coherence figure is on every hook row.
4. **Enumerability gates the cue, not the queue.** SPEC 7.5 says in terms that the 2-6 band
   "governs whether a stem works as a hunting cue, and nothing else... It does not decide what
   is worth studying." So `RAI-`, at {_enum_of(hk, 'RAI'):.1f}, stays in the queue and is marked
   as not a board cue. The band is the browser's default filter, not a deletion.
5. **SPEC 6.2's `P(capacity | tier)` term is not used.** Expected gain here is measured presence
   times a measured rate gap; capacity is already inside both, and multiplying by it again would
   double-count. Presence by tier and grid is shown per word so the Spam-board caveat stays
   visible.
6. **Cellmates above 5 letters carry no value on a hook.** Phase 1 measured anagram pathability
   at {_cm(B, 3):.2f} / {_cm(B, 4):.2f} / {_cm(B, 5):.2f} / {_cm(B, 6):.2f} for lengths 3 to 6,
   so only 3s and 4s clear SPEC 7.6's 0.5 threshold. Before this rule the ranking was dominated
   by fragment stems that happened to sit inside one member of a large anagram set; ASTER and
   TERAS earn under their own stems, where they are additive.
7. **The clock cost.** The brief's "about 26% of the clock" is the swipe-only figure and is
   exactly right ({(17.0 + 3.8) / 80:.0%} for invalid plus duplicate re-swipes). All in, with
   decision time, `reports/clone_gate.md` puts invalid attempts alone at 33.9%.

## What is soft

- **The top-quartile rate is pooled across regimes** while presence and your own rate are
  current-regime only. Board generation changed before season 7, so how often a word is
  *present* moved; how often a strong player *takes* it once present should not have. Using
  current-regime-only top-quartile rates would drop the median denominator from 77 to 23.
- **Reachability for most branches is fitted, not measured.** Of the branch rows on the top 200
  hooks, {s['reachSourceMix'].get('observed', 0):,} use the rate observed on your own boards,
  {s['reachSourceMix'].get('measured', 0):,} the simulator's measured affix table, and
  {s['reachSourceMix'].get('fitted', 0):,} a per-letter multiplicative model fitted on those 60
  affixes (R² {s['reachFit']['4x4:goodCasual']['r2LogP']:.3f} on log p, median error
  {s['reachFit']['4x4:goodCasual']['medianAbsRatio']:.0%}). The model overstates long rare
  affixes by about 2x — `-LESS` fits at 0.013 against a measured 0.0064 — which flatters hooks
  whose dead grid is built on them.
- **Effort is a count, not a measurement.** Study items weighted 1.0 additive, 1.3 cellmate,
  0.35 for a valid/invalid judgment, times {RK.OWNED_DISCOUNT} on a hook with two or more owned
  branches. Nothing in the project measures learning time, and these weights move the order.
- **Eight clone games.** Every misswipe rate is provisional at that n. The structure — that
  {tr['misswipe']['byCause']['affixError']['attempts'] / 382:.0%} is affix error and
  {tr['misswipe']['byCause']['trueNonWord']['attempts'] / 382:.0%} is true non-word belief — is
  the finding; the seconds are not.
- **Enumerability is calibrated, not directly measured, for rare stems.** Summing per-branch
  reachability answers M1's question (does it extend the stem's path), and SPEC 7.5's band was
  set against M3's (is the member findable at all). The ratio is recovered per stem length by
  running this model over M3's own curatedWord population:
  {', '.join(f'×{v:.2f} at {k} letters' for k, v in sorted(s['hooks']['enumCalibration'].items(), key=lambda kv: int(kv[0])))}.
  Where the stem is present on 200+ of your boards the observed number is used instead, and
  every hook row says which.

## The gate

Read the top 100 hooks and the top 200 words and decide whether they are worth learning. That is
the judgement this phase exists to hand over, and Phase 3 should not be built until it is made.
"""
    with open(path, "w") as f:
        f.write(text)
    return path


def _enum_of(hk, stem):
    for h in hk:
        if h["stem"] == stem:
            return h["enumerabilityFindable"]
    return float("nan")


def _cm(B, n):
    import reach as Rch
    return Rch.Reach(B["meta"]["tierMixCur"], B["meta"]["gridMixCur"]).cellmate_p(n)

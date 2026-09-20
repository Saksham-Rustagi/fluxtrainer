"""Assemble reports/analytics_<player>.html and reports/manifest_<player>.json for FLUX_PLAYER.

Both players' reports share one structure. Every directional claim is computed from the
player's own results, so the same sentence can read the other way round in the other report.
"""
import datetime
import hashlib
import html
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import (BUILD, FIGS, NAME, PEER, PEER_NAME, PLAYER, RANKED, REPORTS, ROOT, SHARED, WORDLIST,  # noqa: E402
                    build_dir, ranked_dir)

R = json.load(open(os.path.join(BUILD, "results.json")))
F = json.load(open(os.path.join(BUILD, "figures.json")))
PR_PATH = os.path.join(build_dir(PEER), "results.json")
PR = json.load(open(PR_PATH)) if os.path.exists(PR_PATH) else None
CV = json.load(open(os.path.join(SHARED, "crossval.json")))
USED = []
FIGREL = f"figures/{PLAYER}"
PRON = {"MiningMath": ("he", "him", "his"), "Nicole": ("she", "her", "her")}
he, him, his = PRON[PEER_NAME]
hers = {"his": "his", "her": "hers"}[his]
VP = {"survives": "survives", "underpowered": "is underpowered", "does not survive": "does not survive", "no finding to test": "has nothing to test"}
He = he.capitalize()
IS_MM = PLAYER == "miningmath"


def n(x, d=0):
    """Thousands-separated; negative d rounds to tens/hundreds (n(3144, -2) -> '3,100')."""
    if d < 0:
        return f"{round(x, d):,.0f}"
    return f"{x:,.{d}f}"


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return f"{100 * x:+.{d}f} pp"


def ppa(x, d=1):
    return f"{abs(100 * x):.{d}f} pp"


def fig(name, alt=None):
    USED.append(name)
    f = F[name]
    return (f'<figure><img alt="{html.escape(alt or f["caption"])}" src="data:image/png;base64,{f["png"]}">'
            f'<figcaption>{html.escape(f["caption"])} <span class="tsv">{FIGREL}/{name}.tsv</span></figcaption></figure>')


def table(rows, head, cls=""):
    h = "".join(f"<th>{html.escape(c)}</th>" for c in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw {cls}"><table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def ci(t, f=pp):
    return f"{f(t[1])} to {f(t[2])}"


def excl0(t):
    """True if a (mean, lo, hi) interval excludes zero."""
    return t[1] > 0 or t[2] < 0


def ml(x, more="more", less="less"):
    return more if x > 0 else less


s0, s1, s2, s3, s4, s4a, s5, s6, s7, sd, sa, sr = (R[k] for k in ("s0", "s1", "s2", "s3", "s4", "s4_all", "s5", "s6", "s7", "sd", "sa", "sr"))
sh = R.get("sh")
dr = R["drift"]
cost = s2["cost"]
ot = s2["openingTest"]
otc = ot["current"]
bl = s4["baselines"]
bla = s4a["baselines"]
tr = s1["trendPerMonth"]
elo = json.load(open(os.path.join(RANKED, "elo_fit.json")))
ing = json.load(open(os.path.join(RANKED, "ingest.json")))
bf = s5["fit"]
mech = s6["mechanical"]
reg = s6["regression"]["byLength"]
hr = sa["headroom"]["current"]
al = sa["alpha"]
lf = cost["lossesFlipped15"]
ls_ = s7["longSessions"]
op10 = s2["open10"]
dec = s2["decileCurves"]
runs = s2["runs"]["rates"]
G = pd.read_parquet(os.path.join(RANKED, "games.parquet"), columns=["season", "createdAt", "tierConfidence", "margin", "split"])
NG = len(G)
ncur = int((G.season >= 7).sum())
split_n = G.split.value_counts().to_dict()
test_start = G[G.split == "test"].createdAt.min()
cur_start = G[G.season >= 7].createdAt.min()
d0, d1 = G.createdAt.min(), G.createdAt.max()
ho = R["holdout"]
peer_ho = {h["finding"]: h for h in (PR or {}).get("holdout", [])}
_margins = G[G.season >= 7].margin.values


def day(t):
    return f"{t.day} {t.strftime('%b %Y')}"


def mech_at(points):
    """Win-rate gain from adding `points` to every game, opponent unchanged: the losses it flips, plus half the ties."""
    return float((((_margins < 0) & (_margins + points > 0)).sum() + 0.5 * ((_margins == 0) & (points > 0)).sum()) / len(_margins))


def holdout_row(prefix):
    return [h for h in ho if h["finding"].startswith(prefix)][0]


def verdict(prefix):
    return holdout_row(prefix)["verdict"]


log100 = s6["regression"]["points"]["train"]["amePer100"]
open_pts = cost["forgone15"][0]
fz = pd.read_parquet(os.path.join(RANKED, "finds_derived.parquet"), columns=["who", "pts"])
pts_per_word = float(fz[fz.who == "player"].pts.mean())
# Volume cost of opening at strong opponents' length: the linear fit in seasons 7-10, the pooled fit,
# and the longest-opening eighth of games. The low end is the smallest non-negative of these.
bins = pd.read_csv(os.path.join(FIGS, "s2_2b_opening_test.tsv"), sep="\t")
top_oct = bins[bins.block == "nWords_res"].sort_values("x").iloc[-1]
cands = [-otc["nWords"]["atDelta"], -ot["all"]["nWords"]["perLetter"] * ot["delta"]]
vol_lo = max(0.0, min(cands))
vol_hi = max(vol_lo, max(cands), -float(top_oct["mean"]))
net_hi = open_pts - vol_lo * pts_per_word
net_lo = open_pts - vol_hi * pts_per_word
opening_leak = ot["delta"] > 0.1 and verdict("Points forgone in the first 15") == "survives"

alpha_words = pd.read_csv(os.path.join(RANKED, "alpha_words.tsv"), sep="\t")
alpha_fam = pd.read_csv(os.path.join(RANKED, "alpha_families.tsv"), sep="\t")
top200 = alpha_words.head(200)
cum200 = float(top200.gainPerGameCur.sum())
odm = holdout_row("Your opening deficit minus")
GAPS = [("familyCompletion", "family completion"), ("affixTake", "additive-affix take"), ("freeExtensionTake", "free-extension take"),
        ("anagramCompletion", "anagram-set completion"), ("cellmateTake", "cellmate take"), ("dropTerminalTake", "drop-terminal take")]
trail = [(k, lab) for k, lab in GAPS if bl[k]["gap_topQuartile"][2] < 0]
lead = [(k, lab) for k, lab in GAPS if bl[k]["gap_topQuartile"][1] > 0]


def gaplist(items):
    return ", ".join(f"{lab} by {ppa(bl[k]['gap_topQuartile'][0])}" for k, lab in items)


def peer_val(path, default=None):
    x = PR
    for k in path:
        if x is None or k not in x:
            return default
        x = x[k]
    return x


# ---------------------------------------------------------------- headlines
fat = s7["fatigue"]
warm = verdict("Score residual, games 8+")
gap6 = s7["gap"]["score"][">6 h"]["mean"]
peer_found = pd.read_parquet(os.path.join(ranked_dir(PEER), "presence.parquet"), columns=["word", "foundPlayer", "foundOpp"])
peer_found = peer_found[peer_found.word.isin([x["word"] for x in sd["named"]])]
peer_acc = (peer_found.foundPlayer | peer_found.foundOpp.fillna(False).astype(bool)).groupby(peer_found.word).agg(["size", "sum"])
own_finds = {x["word"]: x["finds"] for x in sd["named"]}
acc_named = [w for w in own_finds if own_finds[w] > 0 or (w in peer_acc.index and peer_acc.loc[w, "sum"] > 0)]
sus = pd.read_csv(os.path.join(FIGS, "sd_dictionary_suspects.tsv"), sep="\t")
dead_set = set(pd.read_csv(os.path.join(FIGS, "s0_never_accepted_words.tsv"), sep="\t").word)
imp10 = sus[sus.word.isin(dead_set) & (sus.qAtP10SameInitial < 1e-3) & ~sus.removedByFlux.astype(bool)].sort_values("trials", ascending=False).word.tolist()

h_open = (f"""<li><p><b>Your opening is the clearest fixable leak.</b> Your first 15 finds average {ot['yourOpen15']:.2f} letters against
{ot['strongOpen15']:.2f} for opponents who beat you by 10k+. Priced against their opening profile on the same boards (seasons 7 to 10), that is
{n(open_pts)} points a game, and it survives the holdout. In your own games, opening longer costs {vol_lo:.1f} to {vol_hi:.1f} words of volume, so the net is
{n(net_lo, -2)} to {n(net_hi, -2)} points: {pp(mech_at(net_lo))} to {pp(mech_at(net_hi))} of win rate if added to your score with the opponent unchanged,
and at least {pp(net_lo / 100 * log100)} on the more conservative model.</p>{fig("s2_2b_opening_test")}</li>""" if opening_leak else
          f"""<li><p><b>Your opening is not where you lose points.</b> Your first 15 finds average {ot['yourOpen15']:.2f} letters against {ot['strongOpen15']:.2f}
for opponents who beat you by 10k+ (section 2.2).</p></li>""")
h_fam = f"""<li><p><b>Against the strongest players, you trail on {'every family measure' if len(trail) >= 3 and not lead else ', '.join(lab for _, lab in trail) if trail else 'no family measure'}{'; you lead on ' + ', '.join(lab for _, lab in lead) if lead else ''}.</b>
Against top-quartile opponents in the same games you trail on {gaplist(trail) if trail else 'nothing'}{'; you lead on ' + gaplist(lead) if lead else ''}.
The better player on each board takes {ppa(bl['freeExtensionTake']['gap_frontier'][0])} more free extensions than you. Closing only the top-quartile gap on free
extensions is worth about {n(hr['topQuartileRatePts'], -2)} points a game.</p>{fig("s4_0_baselines")}</li>"""
ex3 = ", ".join(f"{r_.word} on {r_.hookStem}" for r_ in alpha_words.head(12).itertuples() if isinstance(r_.hookStem, str))
ex3 = ", ".join(ex3.split(", ")[:4])
h_alpha = f"""<li><p><b>There are uncontested points on almost every board, and they hang off stems you already find.</b> {n(al['candidatesExclDead'])} words of 5+ letters
appear on 50+ of your boards and are found under 10% of the time by anyone. Your best 300 are {pct(al['top300ByClass'].get('free', 0) / 300, 0)} free extensions of words you
already find ({ex3}). Learned to the level of your reliable words, the first 200 are worth an estimated {n(cum200, -2)} points a game. That figure is an extrapolation and is
not additive past the swipe budget (section 10).</p>{fig("sa_alpha_words")}</li>"""
if warm == "survives":
    h_sess = f"""<li><p><b>Warm up before ranked. The first game of a session costs about {n(-fat['game1'][0], -2)} points.</b> Games 8 and later score
{n(fat['game8plus'][0])} against your board-controlled average, and the contrast survives the holdout. After more than 6 hours off, the first game is {n(-gap6, -2)} below.</p>{fig("s7_session_position")}</li>"""
else:
    h_sess = f"""<li><p><b>Coming back cold costs you. After more than 6 hours off, your first game scores {n(-gap6, -2)} below your board-controlled average.</b>
Game 1 of any session is {n(-fat['game1'][0], -2)} below; the warm-up contrast is {warm} on the holdout, so a warm-up board is a cheap bet rather than a proven fix.</p>{fig("s7_gap_before")}</li>"""
h_dict = f"""<li><p><b>The whole field underplays vowel-initial words, and Flux accepts them.</b> Of {n(dr['words'])} words present on 50+ of your boards that nobody in either
export ever had accepted, {pct(sd['vowelInitialShareDead'], 0)} start with a vowel, against {pct(sd['vowelInitialShareAll'], 0)} of all words.
{'Of the long-standing suspects, ' + ', '.join(acc_named) + ' have all been accepted for someone, in one export or the other.' if acc_named else ''}
A vowel-initial word you know is a word few opponents will take.</p>{fig("sd_dictionary")}</li>"""
h_h2h = ""
if sh:
    m_ = sh["decomposition"]["margin"][0]
    wr = sh["winRate"][0]
    vshare = sh["decomposition"]["vocabNet"][0] / m_
    oshare = sh["opening"]["regression"]["margin"]["atMeanDelta"] / m_
    if m_ < 0:
        h_h2h = f"""<li><p><b>On identical boards {PEER_NAME} beats you {pct(1 - wr)} of the time, mostly on words you rarely find anywhere, and the gap is closing.</b>
Over {sh['games']} shared games {he} averages {n(-m_)} more points. On a graded split, {pct(vshare, 0)} of that is in words you rarely take on your other boards; the difference in opening length accounts for about {pct(oshare, 0)}.
When you opened as long as {he} did, {he} still won by
{n(-sh['opening']['regression']['margin']['intercept'], -2)}. The margin fell from {n(-sh['halves']['first']['margin'][0], -2)} in the first half of your games to
{n(-sh['halves']['second']['margin'][0], -2)} in the second (section 8).</p>{fig("sh_3_decomposition")}</li>"""
    else:
        h_h2h = f"""<li><p><b>On identical boards you beat {PEER_NAME} {pct(wr)} of the time, mostly on words {he} rarely finds, but {he} is closing the gap.</b>
The margin fell from {n(sh['halves']['first']['margin'][0], -2)} in the first half of your shared games to {n(sh['halves']['second']['margin'][0], -2)} in the
second (section 8).</p></li>"""
head = f"""
<h2 id="headlines">Headline findings</h2>
<p class="note">Seasons 7 to 10 ({n(ncur)} games) are the current game. Anything that depends on how boards are generated uses only those seasons; behaviour
over time uses all {n(NG)}. Section 9 says which findings survive a chronological holdout inside seasons 7 to 10, and whether the same finding also holds
in {PEER_NAME}'s games, analysed separately with the same pipeline.</p>
<ol class="headlines">{h_open}{h_fam}{h_alpha}{h_sess}{h_dict}{h_h2h}</ol>
"""

# ---------------------------------------------------------------- section 0
bad = s0.get("badLists", [])
bad_txt = (" ".join(f"One opponent list (gid {b['gid']}, against {html.escape(str(b['opponent']))}) belongs to another board: {b['offBoard']} of its {b['words']} words "
                    f"cannot be traced on its own board, and it matches your board from {b['bestMatchWhen'][:10]} (gid {b['bestMatchGid']}). It is excluded from opponent inference."
                    for b in bad) if bad else "Every opponent word list traces on its own board.")
xv = CV
prompt_vs_merged = [
    ("Player mean length, first to last decile", "3.97 to 4.34", f"{dec['player'][0]:.2f} to {dec['player'][-1]:.2f}"),
    ("Consecutive-family rate, you vs opponents", "0.643 vs 0.629", f"{runs['player']['mean']:.3f} vs {runs['opponent']['mean']:.3f} (strong: {runs['strong']['mean']:.3f})"),
    ("Grid split 4x4 / 5x5", "62.6 / 37.4", f"seasons 7-10: {pct(bf['gridSplit']['current']['share4x4'])} 4x4"),
    ("Games decided by under 8,000", "2,590 of 4,512, 50.2% won", f"{n(s6['margin']['under8000'])} of {n(s6['margin']['games'])} ({pct(s6['margin']['under8000Share'])}), {pct(s6['margin']['winRateUnder8000'])} won"),
    ("wentFirst win rates", "53.8% vs 50.1%", f"{pct(s7['wentFirst']['sent']['winRate'])} vs {pct(s7['wentFirst']['accepted']['winRate'])} (all seasons)"),
] if IS_MM else []
arena = [x for x in sd["named"] if x["word"] == "ARENA"]
names_in_export = xv["sharedByName"][f"{PLAYER}ExportOpponentNames"]
sec0 = f"""
<h2 id="s0">0. Verification, regimes and power</h2>
<p>Both export parts are used: {n(s0['games'])} games, {ing['overlapRowsDropped']} duplicate rows. Row-major orientation solves {n(s0['playerFinds'] - s0['playerUnsolvable'])} of
{n(s0['playerFinds'])} of your finds. The dihedral transforms are indistinguishable by construction, while adjacency-breaking layouts solve
{pct(s0['orientationSolvable']['snake'])} (snake) and {pct(s0['orientationSolvable']['randomPermutation'])} (random). The §2.2 points table reproduces {n(s0['scoreMatch'])} of
{n(s0['games'])} of your scores and {n(s0['oppScoreMatch'])} of the opponents'. Find order is chronological: adjacent finds share a stem {pct(s0['adjacentStemShareObserved'])}
of the time, against {pct(s0['adjacentStemShareShuffled'])} shuffled. <code>didWin</code> is null exactly on the {s0['ties']} ties. {bad_txt}</p>
<h3 id="s0-2">0.2 The only independent check: the games you and {PEER_NAME} played each other</h3>
<p>{xv['sharedGames']} games appear in both exports, once from each side. They are matched on their start time rather than on usernames, because a username is stamped
at game time: in your export {PEER_NAME} appears as {', '.join(f'"{html.escape(k)}" ({v})' for k, v in names_in_export.items())}.
<b>All {xv['exactOnAll']} of {xv['sharedGames']} match exactly</b>: the board, both word lists in the same order, both scores, the outcome, who went first, the
completion time and the season. There are {len(xv['mismatches'])} mismatches. {len(xv['forfeits'])} of the shared games are forfeits in which one side found nothing;
they are consistent too, and are left out of the head-to-head. {'The corrupt opponent list in your export (gid 2309, against donq) is not a shared game and has no counterpart in the other export; the board it belongs to is one of your own.' if IS_MM else 'Your export has no opponent list that fails to trace on its board.'}
Since opponent word lists agree perfectly wherever they can be checked, the opponent lists are trusted throughout{'; the one known bad row is a misattached list, not a pattern' if bad else ''}.</p>
<h3>Regimes</h3>
<p>Board generation changed on the server before season 7 (§2.5). <b>Seasons 7 to 10 ({n(ncur)} of your games, {day(cur_start)} to {day(d1)}) are the current game.</b>
Board potential, tier mixture, capture, letter marginals, seeds, grid split, the section 5 generator comparisons and the opening-cost counterfactual use those seasons only.
Behaviour over time uses the full range with board potential as a control, and every time-series chart marks the break with a red dashed line. Vocabulary and presence
results give seasons 7 to 10 as the primary number and the full range as secondary. Section 5.4 uses the boards of both exports to characterise the earlier seasons.</p>
<h3>Holdout and power</h3>
<p>Validation is a chronological 70/30 split <i>inside</i> seasons 7 to 10: {n(split_n.get('train', 0))} training games and {n(split_n.get('test', 0))} test games from
{day(test_start)}. For every finding, section 9 gives the test standard error and the <b>minimum detectable effect</b> (2.8 standard errors: 80% power at the 5% level).
A finding the test period could not have confirmed is labelled <i>underpowered</i>, not absent. Findings that can only be established on the full range are labelled regime-pooled.</p>
{('<h3>Prompt figures recomputed</h3>' + table(prompt_vs_merged, ['quantity', 'prompt (part 2)', 'this report'])) if prompt_vs_merged else ''}
<h3 id="s0-1">0.1 Dictionary: the never-accepted words</h3>
<p>CSW21 stays the reference word list, and board potential and capture include every CSW21 word. A word counts as <b>never accepted</b> if it was present on 50+ of your
boards and nobody, you or any opponent, in <i>either</i> export ever had it accepted. On your export alone there are {n(dr['deadInThisExportOnly'])} such words; {n(dr['acceptedInPeerExport'])}
of them were accepted in the other export (for example {', '.join(dr['acceptedInPeerExamples'][:8])}), which leaves {n(dr['words'])}. A single export is not enough to call a word
rejected. The {n(dr['words'])} carry {pct(dr['potentialShare'])} of potential; they are kept out of every curriculum output, and every curriculum ranking is run with and without them
(section 10). Only {sd['removedOverlap']} of them are among the 419 offensive-word removals in the client list (§2.1).</p>
<p><b>Are the zeros explainable?</b> Each word is compared with CSW21 words of the same length and similar presence (within 30%) that someone did find. Against those,
{n(sd['impossibleAtMedian'])} of {n(sd['tested'])} zeros are statistically improbable at the comparison group's median rate (Benjamini-Hochberg q &lt; 0.001). But the whole field finds
vowel-initial words at {min(v['ratio'] for v in sd['suppression'].values()):.2f} to {max(v['ratio'] for v in sd['suppression'].values()):.2f}x the rate of consonant-initial words of
the same length, and {pct(sd['vowelInitialShareDead'], 0)} of the never-accepted words start with a vowel against {pct(sd['vowelInitialShareAll'], 0)} overall. Against comparable
words with the <i>same</i> kind of first letter, {sd['impossibleAtMedianSameInitial']} zeros are improbable at the median rate, and only <b>{sd['impossibleAtP10SameInitial']}</b> at the
group's 10th-percentile rate. The long-standing suspects:</p>
{table([(x['word'], n(x['trials']), x['finds'], f"{x.get('compMedianSameInitial', float('nan')):.3f}", f"{x.get('pZeroAtP10SameInitial', float('nan')):.3f}",
         (f"yes, {int(peer_acc.loc[x['word'], 'sum'])} of {int(peer_acc.loc[x['word'], 'size'])}" if x['word'] in peer_acc.index and peer_acc.loc[x['word'], 'sum'] > 0 else
          (f"no, 0 of {int(peer_acc.loc[x['word'], 'size'])}" if x['word'] in peer_acc.index else "not present")))
        for x in sd['named']],
       ["word", "presences (your export)", "finds (your export)", "same-initial median rate", "P(0), same-initial 10th pct", f"accepted in the other export?"])}
<p>{'Taking both exports together settles several of these: ' + ', '.join(acc_named) + ' have been accepted, so Flux accepts them and the zeros are behaviour. ' if acc_named else ''}The zeros that stay improbable even against same-initial words are
{', '.join(imp10) if imp10 else 'none'} (leaving out the client's own offensive-word removals): the best remaining candidates for words the server rejects. There is
no structural signature beyond the first letter: no contiguous alphabetical gap, which a truncated file would leave, and the share of common English words
({pct(sd['commonEnglishShare'], 0)}) matches comparable found words ({pct(sd['commonEnglishShareOfComparable'], 0)}). Some two-letter openings are nearly dead:
{', '.join(f"{v['open2']}- (median rate {v['medianRate']:.3f})" for v in sd['vowelOpenings'][:5])}.</p>
<p><b>What remains for the developer (§16.3).</b> Whether the words dead in <i>both</i> exports ({n(xv['neverAccepted'][PLAYER]['deadInBoth'])} of your export's list) are rejected by the
server. The practical consequence does not wait on the answer: vowel-initial words are underplayed by everyone, and the ones that have been accepted are points few players take.
Full list: <span class="tsv">{FIGREL}/sd_dictionary_suspects.tsv</span>.</p>
"""

# ---------------------------------------------------------------- section 1
st = {r_["season"]: r_ for r_ in s1["seasonTable"]}
big = [k for k, v in st.items() if v["n"] >= 150]
sA, sB = min(big), max(big)
sc_sl, op_sl = tr["yourScore_ctl"], tr["oppScore_ctl"]
improving = sc_sl["lo"] > 0
sec1 = f"""
<h2 id="s1">1. Time series (full range, regime break marked)</h2>
<p>Improvement needs the longest baseline, so this section uses all {n(NG)} games. Board potential is the control, and the red line marks season 7.
Own score, words and capture are controlled for log potential by grid. Win rate is also controlled for leave-one-out opponent rating.
Your score cannot depend on the opponent (duplicates score for both, §2.1), so controlling it for opponent rating would be circular.</p>
{fig("s1_headline_by_month")}
{table([
    ("Your score, board-controlled", n(sc_sl['slope']), f"{n(sc_sl['lo'])} to {n(sc_sl['hi'])}"),
    ("Opponents' score, board-controlled", n(op_sl['slope']), f"{n(op_sl['lo'])} to {n(op_sl['hi'])}"),
    ("Your words per game, board-controlled", f"{tr['nWords_ctl']['slope']:.2f}", f"{tr['nWords_ctl']['lo']:.2f} to {tr['nWords_ctl']['hi']:.2f}"),
    ("Your long share, board-controlled", f"{100 * tr['longShare_ctl']['slope']:.2f} pp", f"{100 * tr['longShare_ctl']['lo']:.2f} to {100 * tr['longShare_ctl']['hi']:.2f} pp"),
    ("Win rate, controlled", f"{100 * tr['S_ctl']['slope']:.2f} pp", f"p = {tr['S_ctl']['p']:.2f}"),
], ["trend per month (regime-pooled)", "estimate", "95% CI"])}
<p>{'You have improved in absolute terms' if improving else 'Your board-controlled score has not clearly risen'}: about {n(sc_sl['slope'])} points and {tr['nWords_ctl']['slope']:.1f} words a month on equivalent boards.
Your opponents' board-controlled score moved {n(op_sl['slope'])} a month, {'faster than yours' if op_sl['slope'] > sc_sl['slope'] else 'slower than yours'}, and win rate moved
{100 * tr['S_ctl']['slope']:+.2f} pp a month (p = {tr['S_ctl']['p']:.2f}). Season {sA} (median Elo {n(st[sA]['elo'])}) scored {n(st[sA]['score_ctl'])} controlled, and season {sB}
(Elo {n(st[sB]['elo'])}) scored {n(st[sB]['score_ctl'])}. These are regime-pooled slopes: board potential is controlled, but the season 7 generator change is a second,
unmodelled shift in what a board is.</p>
{fig("s1_confounds_by_month")}
{fig("s1_length_mix_by_month")}
{fig("s1_vocabulary")}
<p><b>Recovered opponent Elo.</b> K = {elo['K']:.1f} maximises the intraclass correlation of recovered ratings for the same opponent (ICC {elo['icc']:.3f}; within-opponent SD
{elo['withinOpponentSdElo']:.0f} Elo). Changes are floored at ±3, and seasons reset ratings (§2.5), so treat Elo as comparable within a season only. Every outcome analysis uses a
leave-one-out rating (the same opponent's other games within 14 days, {pct(elo['looCoverage'])} coverage).</p>
"""

# ---------------------------------------------------------------- section 2
pk = "peer" in op10
def_p, def_s = s2["openingDeficit"]["player"], s2["openingDeficit"]["strong"]
sal = s2["shortAfterLong"]
base_ = s2["shortBase"]
rel_p, rel_s = sal["player"]["mean"] / base_["player"], sal["strong"]["mean"] / base_["strong"]
rv = verdict("Consecutive-family rate")
pvol = peer_val(["s2", "openingTest", "all", "nWords", "perLetter"])
sec2 = f"""
<h2 id="s2">2. Sequence analysis</h2>
<p>Every chart in this section and the next carries four series: you, all opponents, opponents who beat you by 10k+, and {PEER_NAME} from {his} own export (all {his}
games in the chart's regime). {PEER_NAME} is a single named player and is kept apart from the opponent aggregates: {he} does not stand in for strong opponents.</p>
<h3>2.1 Length by position (behavioural, full range)</h3>
{fig("s2_1_length_by_position")}
<p>Your first 10 finds average {op10['player'][0]:.2f} letters, against {op10['opponent'][0]:.2f} for all opponents and {op10['strong'][0]:.2f} for opponents who beat you by
10k+. Opponents you beat by 10k+ open at {op10['weak'][0]:.2f}{f", and {PEER_NAME} at {op10['peer'][0]:.2f}" if pk else ''}. Over the first 15 finds in seasons 7 to 10 you are at
{ot['yourOpen15']:.2f} against {ot['strongOpen15']:.2f}. Across the game your length runs from {dec['player'][0]:.2f} in the first tenth of finds to {dec['player'][-1]:.2f} in the last.</p>
<p><b>Shape or level?</b> The opening deficit (mean length of finds 1 to 10 minus finds 11 to 40) is {def_p['mean']:+.2f} letters for you and {def_s['mean']:+.2f} for strong
opponents. In the same games, the difference is {odm['train']:+.3f} (train) and {odm['test']:+.3f} (test) letters: <i>{odm['verdict']}</i> on the holdout. By grid, your deficit is
{s2['deficitBy_grid']['4x4']['playerDeficit'][0]:+.2f} (4x4) and {s2['deficitBy_grid']['5x5']['playerDeficit'][0]:+.2f} (5x5); by v3-posterior tier in seasons 7 to 10 it is
{', '.join(f"{k} {v['playerDeficit'][0]:+.2f}" for k, v in s2['deficitBy_tier'].items())}. Tier labels are posterior classifications of unlabelled boards (section 5).</p>
{fig("s2_1_deficit_by_month")}
<h3>2.2 Cost of the opening (seasons 7 to 10)</h3>
<p>The counterfactual is priced against board contents, so it runs only on the current regime. Each of your first N finds is replaced by the length sequence of a
strong opponent's opening on the same grid and potential tercile, capped by what that board had left. A placebo draws from your own openings in other games.</p>
{fig("s2_2_opening_cost")}
{table([(f"first {N}", n(cost[f'forgone{N}'][0]), n(cost[f'placebo{N}'][0]), n(cost[f'self{N}'][0]), pct(cost[f'lossesFlipped{N}']['share']), pct(cost[f'lossesFlippedSelf{N}']))
        for N in (10, 15, 20, 25)], ["finds", "points forgone vs strong", "vs weak opponents", "vs your own (placebo)", "losses flipped", "flipped by placebo"])}
<p>Over {n(cost['games'])} games in seasons 7 to 10, the first 15 finds forgo {n(open_pts)} points a game (CI {n(cost['forgone15'][1])} to {n(cost['forgone15'][2])}).
The placebo gives {n(cost['self15'][0])}. In {pct(lf['share'])} of losses the gap exceeds the final margin, against {pct(cost['lossesFlippedSelf15'])} for the placebo.</p>
<h3>2.2b Does opening longer cost you volume? The within-player test</h3>
<p>The counterfactual assumes a longer word replaces a shorter one at no time cost. Your own openings vary (SD {ot['open15Sd']:.2f} letters across games), so the assumption
can be tested on you. Regress each game's outcome on the mean length of your first 15 finds, controlling for board potential by grid, the board's count of 5+ letter words,
and month (which absorbs improvement):</p>
{table([(lab, f"{otc[k]['perLetter']:+,.1f}", f"{otc[k]['ci'][0]:+,.1f} to {otc[k]['ci'][1]:+,.1f}", f"{otc[k]['atDelta']:+,.1f}", f"{ot['all'][k]['perLetter']:+,.1f}")
        for k, lab in (("nWords", "total words"), ("wordsAfter15", "words after find 15"), ("yourScore", "total score"),
                       ("ptsFirst15", "points in the first 15 finds"), ("ptsAfter15", "points after find 15"))],
       ["outcome", "per +1 letter of opening (seasons 7-10)", "95% CI", f"at the gap to strong opponents (+{ot['delta']:.2f} letters)", "per letter, all seasons"])}
<p>In seasons 7 to 10 the word-count slope is {otc['nWords']['perLetter']:+.1f} per letter (CI {otc['nWords']['ci'][0]:+.1f} to {otc['nWords']['ci'][1]:+.1f});
over all seasons it is {ot['all']['nWords']['perLetter']:+.1f}. In the eighth of your games with the longest openings (median {top_oct['x']:.2f} letters) you find
{top_oct['mean']:+.1f} words against your board-controlled average. So price the volume cost of opening at strong opponents' length at <b>{vol_lo:.1f} to {vol_hi:.1f} words</b>
(about {n(vol_lo * pts_per_word)} to {n(vol_hi * pts_per_word)} points at your {n(pts_per_word)} points per find), which puts the net opening gain at
<b>{n(net_lo, -2)} to {n(net_hi, -2)} points a game</b>. Score itself rises {n(otc['yourScore']['perLetter'])} per letter of opening in your own games, but that slope is the
less trustworthy one because good-form games raise both. The within-player volume slope is <i>{verdict('Within-player')}</i> on the holdout.</p>
<h3>2.3 Fresh finds</h3>
{fig("s2_3_fresh_rate")}
<p>Family continuation dominates from the second or third find for every group. From finds 20 to 40, your fresh rate is {pct(s2['fresh']['pos20to40']['player'])},
against {pct(s2['fresh']['pos20to40']['strong'])} for strong opponents{f" and {pct(s2['fresh']['pos20to40']['peer'])} for {PEER_NAME}" if pk else ''}.</p>
<h3>2.4 Run structure</h3>
{fig("s2_4_run_lengths")}
<p>Consecutive-family rate: you {runs['player']['mean']:.3f}, all opponents {runs['opponent']['mean']:.3f}, strong opponents {runs['strong']['mean']:.3f}{f", {PEER_NAME} {runs['peer']['mean']:.3f}" if pk else ''}.
In the same games you {'trail' if s2['runs']['pairedDiffVsStrong'][0] < 0 else 'lead'} strong opponents by {ppa(s2['runs']['pairedDiffVsStrong'][0])}, <i>{rv}</i> on the holdout.
Their runs are {runs['strong']['meanRunLength']:.2f} finds long against your {runs['player']['meanRunLength']:.2f}{f" ({PEER_NAME}: {runs['peer']['meanRunLength']:.2f})" if pk else ''}:
stronger players stay in a family longer before moving on.</p>
<h3>2.5 Length transitions</h3>
{fig("s2_5_length_transitions")}
<p>After a 6+ letter find, you drop to a 3 or 4 {pct(sal['player']['mean'])} of the time, against {pct(sal['strong']['mean'])} for strong opponents{f" and {pct(sal['peer']['mean'])} for {PEER_NAME}" if pk else ''}.
Relative to each group's overall share of 3 and 4 letter finds that is {rel_p:.2f}x for you and {rel_s:.2f}x for strong opponents, so
{'the difference is mostly the overall length mix, not a separate transition habit' if abs(rel_p - rel_s) < 0.08 else ('you drop back to short words after a long one more readily than strong opponents do, beyond your overall mix' if rel_p > rel_s else 'you drop back to short words after a long one less readily than strong opponents do')}
({verdict('P(next find is 3-4')} on the holdout).</p>
"""

# ---------------------------------------------------------------- section 3
cov = s3["coverage"]
tv = s3["travel"]
mlong = s3["missedLong"]
pc = "4x4_peer" in cov
sec3 = f"""
<h2 id="s3">3. Spatial analysis (behavioural, full range)</h2>
<p>{pct(s3['ambiguity']['player'])} of your finds have more than one valid path, so path-level results are partly inferred (Viterbi assignment minimising hand travel).</p>
{fig("s3_coverage")}
<p>By find 10 you have touched {pct(cov['4x4_player']['10'], 0)} of a 4x4 grid, against {pct(cov['4x4_opponent']['10'], 0)} for opponents{f" and {pct(cov['4x4_peer']['10'], 0)} for {PEER_NAME}" if pc else ''}.
By find 25 it is {pct(cov['4x4_player']['25'], 0)} against {pct(cov['4x4_opponent']['25'], 0)}{f" ({PEER_NAME} {pct(cov['4x4_peer']['25'], 0)})" if pc else ''}. Coverage saturates for everyone, so it
does not separate players.</p>
{fig("s3_travel")}
<p>Consecutive finds' centroids are {tv['player']['centroidUnambiguous']:.2f} cells apart, against {tv['player']['centroidShuffled']:.2f} shuffled, so you work regions.
Hand travel from the end of one find to the start of the next is {tv['player']['unambiguous']:.2f} cells against {tv['player']['shuffledUnambiguous']:.2f} shuffled
{'(no shorter than random)' if tv['player']['unambiguous'] >= tv['player']['shuffledUnambiguous'] - 0.05 else ''}, because continuations restart at the stem.</p>
{fig("s3_heatmap")}
<p>Normalised cell use is {s3['heatmap']['4x4']['ratioMin']:.2f} to {s3['heatmap']['4x4']['ratioMax']:.2f} on 4x4 and within {pct(s3['heatmap']['4x4']['playerVsOppMaxAbsDiff'], 1)}
of opponents on every cell: no blind spots.</p>
{fig("s3_missed_long_words")}
<p>{pct(mlong['missedAllCellsTouched'], 0)} of the 6+ letter words you missed had every cell touched during the game. The misses are structural, not regional.</p>
"""


# ---------------------------------------------------------------- section 4
def gap_row(name, lab):
    v, va = bl[name], bla[name]
    fr = f"{v['frontier']:.3f}" if "frontier" in v else "n/a"
    pv = peer_val(["s4", "baselines", name, "you"])
    return (lab, f"{v['you']:.3f} / {v['field']:.3f}", f"{v['you_in_topQuartile']:.3f} / {v['topQuartile']:.3f}",
            f"{pp(v['gap_topQuartile'][0])} ({ci(v['gap_topQuartile'])})", fr, pp(va['gap_topQuartile'][0]), "" if pv is None else f"{pv:.3f}")


holes = s4["holes"]
p1 = s4["phase1"]
m2 = {r_["len"]: r_ for r_ in p1["m2"]}
m3p = p1["m3Pooled"]
v3m3 = {(x["grid"], x["tier"], x["stemLen"]): x["enumerabilityOther"] for x in s5["rerun"]["m3"]["v3"]}
v3m2 = {(x["grid"], x["tier"], x["len"]): x["p"] for x in s5["rerun"]["m2"]["v3"]}
v3m1 = s5["rerun"]["m1gate"].get("v3", [])
pp1 = peer_val(["s4", "phase1"])
pbl = peer_val(["s4", "baselines"])
fbs = bl["familyBySize"]
sec4 = f"""
<h2 id="s4">4. Vocabulary and families: against the players you want to beat</h2>
<p>At your rating, "opponents" are players you go roughly 50/50 with. Matching them says only that you are average among equals. Every comparison in this section is therefore
made against strong opponents (who beat you by 10k+), against top-quartile opponents by leave-one-out rating (from {n(bl['topQuartileEloFrom'])} Elo), and against the frontier:
the better of the two players on each unit (family, anagram set, extension opportunity). Strong-opponent games are selected on the outcome, since you lost them badly, which
flatters the opponent. The top quartile is selected on rating only and is the cleaner benchmark. {PEER_NAME}'s own value over {his} seasons 7 to 10 games is shown as a
separate column; it is one player, not a benchmark. Primary numbers are seasons 7 to 10. Never-accepted words are excluded throughout.</p>
<h3>4.0 The benchmark table</h3>
{fig("s4_0_baselines")}
{table([gap_row("familyCompletion", "Family completion (given 1+ found)"), gap_row("affixTake", "Additive affix take (1-3 letters)"),
        gap_row("freeExtensionTake", "Free-extension take (any length)"), gap_row("anagramCompletion", "Anagram-set completion"),
        gap_row("cellmateTake", "Cellmate take (other anagram | one found)"), gap_row("dropTerminalTake", "Drop-terminal take")],
       ["metric (seasons 7-10)", "you / field", "you / top quartile (same games)", "gap to top quartile (95% CI)", "frontier", "gap, full range", f"{PEER_NAME} (own games)"])}
<p>Against top-quartile opponents you trail on {gaplist(trail) if trail else 'nothing'}{'; you lead on ' + gaplist(lead) if lead else ''}. The frontier is
{ppa(min(abs(bl[k]['gap_frontier'][0]) for k, _ in GAPS if 'gap_frontier' in bl[k]))} to {ppa(max(abs(bl[k]['gap_frontier'][0]) for k, _ in GAPS if 'gap_frontier' in bl[k]))} above you
on each measure. {'Drop-terminal is the clearest lead: you take the short terminal subwords of your own finds more than top-quartile opponents do. Those are the cheapest swipes on the board and the ones worth trading away for longer words.' if bl['dropTerminalTake']['gap_topQuartile'][1] > 0 else ''}</p>
{table([(r_['size'], f"{r_['you']:.3f}", f"{r_['you_in_topQuartile']:.3f}", f"{r_['topQuartile']:.3f}", f"{r_['frontier']:.3f}") for r_ in fbs],
       ["family size", "you (all games)", "you (top-quartile games)", "top quartile", "frontier"])}
<p>The top-quartile gap is {pp(fbs[0]['you_in_topQuartile'] - fbs[0]['topQuartile'])} on 2-member families and {pp(fbs[-1]['you_in_topQuartile'] - fbs[-1]['topQuartile'])} on 10+.</p>
<h3>4.1 Belief</h3>
<p>Opportunity-weighted belief (weighting each presence by how likely a known word of that length was to be taken on that board) is carried in <code>data/ranked/{PLAYER}/belief.tsv</code>
with seasons 7-10, train and test variants. It ranks words almost identically to raw belief (Spearman {s4['rawVsWeighted']['spearman']:.2f}) while lifting it by
{s4['rawVsWeighted']['meanDiff']:.2f}. {n(s4['coverage']['present>=10'])} words have 10+ presences in seasons 7 to 10 ({n(s4a['coverage']['present>=10'])} over the full range).</p>
{fig("s4_1_belief")}
<h3>4.2 Holes, against three references</h3>
{table([(ref, n(v['candidates']), v['significant'], f"{v['byKind'].get('branch miss', 0)} / {v['byKind'].get('true gap', 0)}", n(v['pointsPerGame']),
         ", ".join(t['word'] for t in v['top'][:8]), f"{s4a['holes'][ref]['significant']} ({n(s4a['holes'][ref]['pointsPerGame'])})")
        for ref, v in holes.items()],
       ["reference", "never-found words, 10+ presences", "significant (BH)", "branch / true gap", "points per game", "top", "full range: significant (pts/game)"])}
<p>Against the field there are few holes (about {n(holes['field']['pointsPerGame'])} points a game). Against top-quartile opponents there are {holes['topQuartile']['significant']},
worth about {n(holes['topQuartile']['pointsPerGame'])} points a game, and {pct(holes['topQuartile']['byKind'].get('branch miss', 0) / max(holes['topQuartile']['significant'], 1), 0)} of them
contain a stem you already find. On the holdout the holes finding {VP[verdict(str(s4['holesHoldout']['flagged']) + ' holes')]}. These are par words, the ones the best players take and you don't.
Learning them closes a gap; the alpha words in section 10 open one.</p>
{fig("s4_2_vocabulary_holes")}
<h3>4.3 Fragile knowledge</h3>
{fig("s4_3_retention")}
<p>After one earlier find, a word is taken {pct(s4['retention']['prior1_prevFound'])} of the time if the previous presence was taken, against
{pct(s4['retention']['prior1_prevMissed'])} after a miss (seasons 7 to 10). {n(s4a['fragile']['count'])} words were found once or twice and then missed on 5+ later presences over the full range.
<span class="tsv">{FIGREL}/s4_3_fragile_words.tsv</span></p>
<h3>4.4 Family completion</h3>
<p>By family size, stem length and tier, against the field, with {PEER_NAME}'s own completion marked. Against the top quartile and the frontier, see the size table in section 4.0.</p>
{fig("s4_4_family_completion")}
<h3>4.5 Affixes</h3>
<p>Of {bl['affixVsTopQuartile']['tested']} affixes with 20+ opportunities on both sides in top-quartile games, {bl['affixVsTopQuartile']['significant']} are individually significant after
correction. The largest excess leaks against the top quartile, in points per game, are
{', '.join(f"{t['affix']} ({pct(t['rate'], 0)} vs {pct(t['rateTopQ'], 0)})" for t in bl['affixVsTopQuartile']['top'][:6])}.</p>
{fig("s4_5_affix_misses")}
<h3>4.6 Anagram sets</h3>
{fig("s4_6_anagram_sets")}
<h3>4.7 Learning curve (full range, regime-pooled)</h3>
{fig("s4_7_learning_curve")}
<p>Words first found in season 1 are taken at {pct(min(s4a['learningCurve']['cohort'].values()), 0)} to {pct(max(s4a['learningCurve']['cohort'].values()), 0)} of later presences
through season 10, against {pct(min(s4a['learningCurve']['control'].values()), 0)} to {pct(max(s4a['learningCurve']['control'].values()), 0)} for all words of the same length mix.</p>
<h3>4.8 Phase 1 proxies, realised, against v3</h3>
{fig("s4_8_phase1_vs_real")}
{table([
    ("M1: reachable extensions per found word", "5.47", f"{sum(x['extPerStem'] for x in v3m1) / max(len(v3m1), 1):.2f}", f"{p1['m1']['reachableExtPerFoundStem']:.2f}", f"you take {p1['m1']['reachableExtFoundPerFoundStem']:.2f}",
     "" if not pp1 else f"{pp1['m1']['reachableExtPerFoundStem']:.2f} available, takes {pp1['m1']['reachableExtFoundPerFoundStem']:.2f}"),
    ("M2: 5-letter anagram pathable (4x4 Good Casual)", "0.413", f"{v3m2.get(('4x4', 'goodCasual', 5), float('nan')):.3f}", f"{m2[5]['pPresent']:.3f}",
     f"you take {m2[5]['pTakenGivenFoundAndPresent']:.2f}, top quartile {bl['cellmateTake']['topQuartile']:.2f} (all lengths)",
     "" if not pp1 else f"takes {[x for x in pp1['m2'] if x['len'] == 5][0]['pTakenGivenFoundAndPresent']:.2f}"),
    ("M3: curated 4-letter word-stems (4x4 Casual / Good Casual)", "2.03 / 2.34", f"{v3m3.get(('4x4', 'casual', 4), float('nan')):.2f} / {v3m3.get(('4x4', 'goodCasual', 4), float('nan')):.2f}",
     f"{m3p['4_curated']['present']:.2f}", f"{m3p['4_curated']['foundIfStemFound']:.2f} found given the stem",
     "" if not pp1 else f"{pp1['m3Pooled']['4_curated']['foundIfStemFound']:.2f} found given the stem"),
    ("Drop-terminal", "P = 1", "P = 1", f"{n(p1['dropTerminal']['opportunities'])} opportunities", f"you take {pct(p1['dropTerminal']['takeRate'], 0)}",
     "" if not pp1 else f"takes {pct(pp1['dropTerminal']['takeRate'], 0)}"),
    ("Family completion / affix take / anagram completion", "", "", "", f"{bl['familyCompletion']['you']:.2f} / {bl['affixTake']['you']:.2f} / {bl['anagramCompletion']['you']:.2f}",
     "" if not pbl else f"{pbl['familyCompletion']['you']:.2f} / {pbl['affixTake']['you']:.2f} / {pbl['anagramCompletion']['you']:.2f}"),
], ["measure", "Phase 1 (v1 simulated)", "v3 simulated (corrected)", "real boards, seasons 7-10", "realised (you)", f"{PEER_NAME} (own games)"])}
<p>Under the corrected generator, the simulated availability numbers come down to what real boards show. The gate (§15) still passes on real boards:
{p1['m1']['freeForPlayerPerBoard']:.0f} free extensions of your own finds per board, of which you leave {p1['m1']['missedFreePerBoard']:.0f}.</p>
"""

# ---------------------------------------------------------------- section 5
pot = s5["potential"]
lt = s5["letters"]
cap = s5["capture"]
tm = bf["tierMixture"]
srt = pd.DataFrame(sr["table"])
fill = srt[srt.season.isin([4, 5, 6, 9])]
pt = sr["potentialTests"]
sec5 = f"""
<h2 id="s5">5. Boards and generation (seasons 7 to 10)</h2>
<p>Every comparison here uses ruleset v3 (the client's letter weights, a two-per-letter cap applied during the fill, one seed per board; §2.3, §2.6) as the reference and
seasons 7 to 10 only. v1, the Phase 1 generator, is shown alongside so the size of the correction is visible.</p>
{fig("s5_potential_vs_sim")}
{table([(gr, n(v['realMedian']), n(v['v3Median']), n(v['v1Median']), f"{n(v['realP10'])} to {n(v['realP90'])}", f"{n(v['v3P10'])} to {n(v['v3P90'])}") for gr, v in pot.items()],
       ["grid", "real median", "v3 median", "v1 median", "real p10 to p90", "v3 p10 to p90"])}
<p>Potential here is on the Flux word list, which v3 simulates.</p>
{fig("s5_1_letters")}
<p>The letter marginal matches v3 to TV {lt['tvV3']:.3f}, against {lt['tvV1']:.3f} for v1, over {n(lt['cells'])} cells. No real board has three copies of a letter; neither do v3
boards ({pct(lt['structure4x4']['v3']['share3plus'], 0)}), where v1 puts a triple on {pct(lt['structure4x4']['v1']['share3plus'], 0)}. The 4x4 vowel-count SD is {lt['structure4x4']['real']['vowelSd']:.2f}
real and {lt['structure4x4']['v3']['vowelSd']:.2f} under v3.</p>
{fig("s5_generation")}
<p><b>Tier mixture</b> (EM on v3 densities, seasons 7 to 10): 4x4 {pct(tm['4x4']['weights']['casual'], 0)} / {pct(tm['4x4']['weights']['goodCasual'], 0)} / {pct(tm['4x4']['weights']['spam'], 0)},
5x5 {pct(tm['5x5']['weights']['casual'], 0)} / {pct(tm['5x5']['weights']['goodCasual'], 0)} / {pct(tm['5x5']['weights']['spam'], 0)} (Casual / Good Casual / Spam), against the stated 30/50/20.
The tier densities overlap heavily, so these weights are weakly identified, and per-board tier labels are soft (median posterior {G[G.season >= 7].tierConfidence.median():.2f}).
<b>Grid split:</b> {pct(bf['gridSplit']['current']['share4x4'])} 4x4 (CI {pct(bf['gridSplit']['current']['ci95'][0])} to {pct(bf['gridSplit']['current']['ci95'][1])}) against the stated 60%.</p>
{fig("s5_capture_vs_potential")}
<p><b>§3.1 holds.</b> Capture elasticity to potential is {cap['4x4']['captureElasticity']:.2f} (4x4) and {cap['5x5']['captureElasticity']:.2f} (5x5). Capture percentage mostly measures the
board, so tier percentile remains the right headline.</p>
<h3 id="s5-4">5.4 Earlier seasons, from both exports</h3>
<p>A single export only sees the seasons its player played. Pooled and deduplicated on the board letters, your export and {PEER_NAME}'s give {n(sr['boards'])} distinct boards.
The seasons that were thin or missing in one export are filled by the other: {', '.join(f"season {int(r_.season)} {r_.grid} {int(r_.boards)} boards" for r_ in fill.itertuples())}.
This subsection only describes boards; nothing about play uses these seasons, and board-generation findings elsewhere stay on seasons 7 to 10.</p>
{fig("s5_4_regimes_pooled")}
{table([(int(r_.season), r_.grid, n(r_.boards), f"{r_.first} to {r_.last}", n(r_.medianPotential), f"{r_.longestP10:.0f} to {r_.longestP90:.0f}",
         f"{r_.tvV3:.3f} / {r_.noise95:.3f}" if r_.tvV3 == r_.tvV3 else "", ("within noise" if r_.fitsV3 else "off") if r_.tvV3 == r_.tvV3 else "")
        for r_ in srt.itertuples()],
       ["season", "grid", "boards (pooled)", "dates", "median potential (CSW21)", "longest word present, p10 to p90", "letter TV vs v3 / noise95", "v3 letter fit"])}
<p><b>What the pooled boards settle.</b> The two-per-letter cap holds in every season: the most copies of one letter on any board is {sr['maxCopies']}. The break into the current regime
falls at the season 6/7 boundary, not earlier: season 6 boards are poorer than seasons 7 to 10 (median potential {pct(pt['6_4x4']['shiftVsCurrent'], 0)} on 4x4, p = {pt['6_4x4']['vsCurrentP']:.3f};
{pct(pt['6_5x5']['shiftVsCurrent'], 0)} on 5x5, p = {pt['6_5x5']['vsCurrentP']:.1e}) and indistinguishable from seasons 2 and 3 (p = {pt['6_4x4']['vsSeasons2to3P']:.2f} and {pt['6_5x5']['vsSeasons2to3P']:.2f}).
Season 4 looks like the old regime too ({pct(pt['4_4x4']['shiftVsCurrent'], 0)} and {pct(pt['4_5x5']['shiftVsCurrent'], 0)} against current), and season 9 looks current
({pct(pt['9_4x4']['shiftVsCurrent'], 0)} and {pct(pt['9_5x5']['shiftVsCurrent'], 0)}, p = {pt['9_4x4']['vsCurrentP']:.2f} and {pt['9_5x5']['vsCurrentP']:.2f}). Season 5 has
{int(srt[srt.season == 5].boards.sum())} boards in total, too few to say anything. The letter marginal is within v3's noise floor in the small seasons, but at those sample
sizes the test cannot tell regimes apart, so the potential shift is the regime signal. Season 1 remains its own regime: all 4x4, and far richer
({pct(pt['1_4x4']['shiftVsCurrent'], 0)} against current).</p>
"""

# ---------------------------------------------------------------- section 6
rep = s6["repeat"]
mb = s6["missedByOpp"]
ov = s6["overlap"]
h3 = holdout_row("Marginal win probability of one extra 3-letter")
sec6 = f"""
<h2 id="s6">6. Competitive analysis</h2>
{fig("s6_win_rate")}
<p>Win rate by v3-posterior tier (seasons 7 to 10): {', '.join(f"{k} {pct(v['mean'])} (n={v['n']})" for k, v in s6['winByTier'].items())}.
{pct(s6['margin']['under8000Share'], 0)} of games are decided by under 8,000 points.</p>
{fig("s6_margins")}
<h3>Points into wins</h3>
<p>Adding points to your score with the opponent unchanged flips exactly the games you lost by less than that. Duplicates score for both players, so nothing you find changes the
opponent's score. Read off the seasons 7 to 10 margin distribution:</p>
{table([(n(int(k)), pp(v)) for k, v in mech.items()], ["points added per game", "win-rate change"])}
<p>The logistic model of winning on your own score gives {pp(log100, 2)} per 100 points, against {pp(s6['mechanicalPer100'], 2)} mechanically. The regression is attenuated because
richer boards raise both players' scores. Use the mechanical numbers for "what adding points is worth", and the logistic ones as a floor.</p>
{fig("s6_marginal_value")}
{table([(L_, pp(reg['train'][f'ame_{k}'], 2), f"{pp(reg['train'][f'ci_{k}'][0], 2)} to {pp(reg['train'][f'ci_{k}'][1], 2)}", pp(reg['test'][f'ame_{k}'], 2), pp(reg['pooled'][f'ame_{k}'], 2))
        for L_, k in (("3", "n3"), ("4", "n4"), ("5", "n5"), ("6", "n6"), ("7+", "n7p"))],
       ["length", "seasons 7-10 train", "95% CI", "seasons 7-10 test", "all seasons (pooled)"])}
<p>The 3-letter word's marginal value is <i>{h3['verdict']}</i> on the holdout (test minimum detectable effect {pp(h3['mde'], 1)}): small, within about a point either way.</p>
<h3>Repeat opponents</h3>
{fig("s6_repeat_opponents")}
<p>{rep['opponents15plus']} opponents with 15+ games; {rep['significant']} differ from the leave-one-out Elo expectation after correction.</p>
<h3>Words opponents took that you missed</h3>
{fig("s6_missed_by_opponent")}
<p>Net of your own find rate on the same presences, the field's advantage is {n(mb['netExcessPerGame'])} points a game. The largest excess leaks are
{', '.join(f"{t['word']} ({pct(t['playerFindRate'], 0)} vs {pct(t['oppFindRate'], 0)})" for t in mb['topByExcess'][:6])}. <code>data/ranked/{PLAYER}/missed_by_opponent.tsv</code></p>
<h3>Overlap, normalised</h3>
{fig("s6_overlap")}
<p>Raw overlap falls with margin (r = {ov['corrRawWithMargin']:.2f}), mechanically: the more words you find, the smaller the share the opponent can match. Expected overlap is computed
from both word counts and each word's popularity. Relative to that, you overlap {ov['normMean']:.2f}x as much as chance predicts, {ov['normByMarginBin'][-1]:.2f}x in your biggest wins and
{ov['normByMarginBin'][0]:.2f}x in your biggest losses (r = {ov['corrNormWithMargin']:+.2f}). {'You do not win by searching differently; you win by finding the same words and more of them.' if ov['corrNormWithMargin'] >= -0.05 else 'Your biggest wins come with less overlap than chance predicts: you win partly by finding different words.'}</p>
"""

# ---------------------------------------------------------------- section 7
wf = s7["wentFirst"]
hwf = holdout_row("Win-rate gap")
sec7 = f"""
<h2 id="s7">7. Session and fatigue</h2>
{fig("s7_session_position")}
<p><b>Warm-up.</b> Controlled for the board, game 1 of a session scores {n(-fat['game1'][0])} below average and games 8+ score {n(fat['game8plus'][0])} against it.
The contrast {VP[warm]} on the seasons 7 to 10 holdout.</p>
<h3>Long sessions</h3>
<p>{ls_['sessions']} sessions of 20+ games ({n(ls_['games'])} games, median {ls_['medianMinutes']:.0f} minutes):</p>
{fig("s7_long_sessions")}
<p><b>Score</b> after game 5: {ls_['scorePerGameAfter5']:+.0f} points a game (CI {ls_['ci'][0]:+.0f} to {ls_['ci'][1]:+.0f}; {ls_['scorePerHour']:+,.0f} points an hour, CI
{ls_['perHourCi'][0]:+,.0f} to {ls_['perHourCi'][1]:+,.0f}). The test could have detected a change of about {n(ls_['mdePerHour'], -2)} points an hour.
<b>Win rate</b>: {100 * ls_['winPerGameAfter5']:+.2f} pp a game (CI {100 * ls_['winCi'][0]:.2f} to {100 * ls_['winCi'][1]:.2f}), controlling for opponent rating;
{pct(ls_['winByPosition']['6-10']['mean'], 0)} in games 6 to 10 and {pct(ls_['winByPosition']['41+']['mean'], 0) if '41+' in ls_['winByPosition'] else 'n/a'} past game 40.
{'Neither declines detectably: long sessions are not costing you.' if ls_['ci'][0] < 0 < ls_['ci'][1] and ls_['winCi'][0] < 0 < ls_['winCi'][1] else
   (f"Win rate slips about {abs(100 * ls_['winPerGameAfter5']) * 10:.1f} points per 10 games beyond game 5 while score {'holds' if ls_['ci'][0] < 0 < ls_['ci'][1] else 'moves too'}, which points at who you meet late rather than how you play; either way it is a cost of long sessions." if ls_['winCi'][1] < 0 else '')}</p>
{fig("s7_gap_before")}
<p>By the gap since your previous game: {', '.join(f"{html.escape(k)}: {v['mean']:+,.0f}" for k, v in s7['gap']['score'].items())} points against your board-controlled average.</p>
{fig("s7_time_of_day")}
<h3>wentFirst</h3>
<p>All seasons: {pct(wf['sent']['winRate'])} when you sent the challenge vs {pct(wf['accepted']['winRate'])} when you accepted one (p = {wf['winP']:.2g}). Opponents accepting your challenges are
{abs(wf['effect_eloDiff']['est']):.0f} Elo {'weaker' if wf['effect_eloDiff']['est'] < 0 else 'stronger'}, so any effect is partly selection. In seasons 7 to 10 the gap is
{pp(hwf['train'])} (train) and {pp(hwf['test'])} (test): <i>{hwf['verdict']}</i> (test MDE {pp(hwf['mde'], 1)}).</p>
"""

# ---------------------------------------------------------------- section 8: head-to-head
sec8 = ""
if sh:
    P = sh["paired"]
    D = sh["decomposition"]
    O = sh["opening"]
    RG = O["regression"]
    WR = sh["winRateWithout"]
    m_ = D["margin"][0]
    you_lead = m_ > 0
    lead_name, trail_name = ("you", PEER_NAME) if you_lead else (PEER_NAME, "you")
    ab = abs(m_)

    def row(k, lab, f="{:.2f}", scale=1):
        v = P[k]
        return (lab, f.format(v["subject"] * scale), f.format(v["peer"] * scale), f"{v['diff'] * scale:+.2f} ({v['lo'] * scale:+.2f} to {v['hi'] * scale:+.2f})".replace(".00", "") if scale == 1 and k not in ("score", "pts15") else
                f"{v['diff'] * scale:+,.0f} ({v['lo'] * scale:+,.0f} to {v['hi'] * scale:+,.0f})", f"{v['pWilcoxon']:.1e}")

    wr_rows = [("as played", pct(WR["actual"])),
               ("without the vocabulary component (graded)", pct(WR["vocabulary"])), ("without the execution component (graded)", pct(WR["execution"])),
               ("without the vocabulary component (50% threshold)", pct(WR["vocabularyThreshold"])),
               ("without the volume component", pct(WR["volume"])), ("without the value-per-word component", pct(WR["value"])),
               ("without the part associated with the opening difference", pct(WR["openingDifference"]))]
    s_ = -1 if not you_lead else 1   # express shares of the leader's margin
    voc_share, exe_share = D["vocabNet"][0] / m_, D["execNet"][0] / m_
    vol_share, val_share = D["volume"][0] / m_, D["value"][0] / m_
    open_share = RG["margin"]["atMeanDelta"] / m_
    slo, shi = sorted([RG["margin"]["slopeCi"][0] * RG["meanDOpen"] / m_, RG["margin"]["slopeCi"][1] * RG["meanDOpen"] / m_])
    wtop = sh["words"]
    pw = pd.DataFrame(wtop["peerOnlyTop"]).head(15)
    sw = pd.DataFrame(wtop["subjectOnlyTop"]).head(15)
    bys = sh["bySeasonTable"]
    tr8 = sh["trend"]
    hh = {h["finding"]: h for h in ho if h.get("section") == "sh"}
    you_open_longer = P["open15"]["diff"] > 0
    sec8 = f"""
<h2 id="s8">8. Head-to-head with {PEER_NAME}, on identical boards</h2>
<p>This is the cleanest comparison in the data. {sh['shared']} games appear in both exports ({sh['forfeits']} forfeits left out, {sh['games']} contested): same board,
same 80 seconds, both full find sequences. Every comparison is paired by construction, so the board cancels and nothing depends on how boards are generated; the games
span every regime ({', '.join(f"season {k}: {v}" for k, v in sh['bySeason'].items())}). They are {pct(sh['shared'] / NG, 0)} of your games, one opponent among many:
this section describes that matchup and does not stand in for strong opponents in general.</p>
<p><b>{'You win' if you_lead else PEER_NAME + ' wins'} {pct(sh['winRate'][0] if you_lead else 1 - sh['winRate'][0])}</b> of the contested games (95% CI
{pct(sh['winRate'][1] if you_lead else 1 - sh['winRate'][2])} to {pct(sh['winRate'][2] if you_lead else 1 - sh['winRate'][1])}), averaging {n(sh['meanScore']['subject'])} to
{n(sh['meanScore']['peer'])} for you and {PEER_NAME} respectively.</p>
{fig("sh_1_paired")}
{table([row("score", "score", "{:,.0f}"), row("words", "words", "{:.1f}"), row("meanLen", "mean length, all finds"), row("open10", "mean length, first 10"),
        row("open15", "mean length, first 15"), row("pts15", "points in the first 15 finds", "{:,.0f}"), row("capture", "capture (score / potential)", "{:.3f}")]
       + [(f"share of {L} letter finds", pct(P[f'share{L}']['subject']), pct(P[f'share{L}']['peer']), f"{pp(P[f'share{L}']['diff'])} ({pp(P[f'share{L}']['lo'])} to {pp(P[f'share{L}']['hi'])})",
           f"{P[f'share{L}']['pWilcoxon']:.1e}") for L in (3, 4, 5, 6, 7)],
       ["paired per board", "you", PEER_NAME, "difference, you minus " + PEER_NAME + " (95% CI)", "Wilcoxon p"])}
<p>The two length mixes are close: pooled over all finds in these games, {', '.join(f"{L if L < 7 else '7+'}s {pct(sh['lengthMixPooled']['s'][str(L)])} vs {pct(sh['lengthMixPooled']['p'][str(L)])}" for L in (3, 5, 6))}
(you vs {PEER_NAME}). The openings are not: {'your' if you_open_longer else PEER_NAME + "'s"} first 15 finds average {max(P['open15']['subject'], P['open15']['peer']):.2f} letters against
{min(P['open15']['subject'], P['open15']['peer']):.2f}, and {'yours' if you_open_longer else his} decline from there while {his if you_open_longer else 'yours'} rise (figure below).</p>
{fig("sh_2_opening_curves")}
<h3>8.1 Decomposing the margin</h3>
<p>The margin ({n(m_)} points a game, you minus {PEER_NAME}) can be split exactly in two ways.</p>
<ul>
<li><b>Words only one of you found.</b> Words you both found score for both and cancel, so the whole margin is the points in words only you found
({n(D['sOnlyPts'][0])} a game, {D['sOnlyN'][0]:.0f} words) minus the points in words only {PEER_NAME} found ({n(D['pOnlyPts'][0])}, {D['pOnlyN'][0]:.0f} words). You share only
{D['sharedN'][0]:.0f} words a game ({n(D['sharedPts'][0])} points). Most of what each of you finds, the other does not.</li>
<li><b>Volume and value.</b> {n(D['volume'][0])} (CI {n(D['volume'][1])} to {n(D['volume'][2])}) comes from the difference in word count, and {n(D['value'][0])}
(CI {n(D['value'][1])} to {n(D['value'][2])}) from the difference in points per word. {pct(vol_share, 0)} of the margin is volume.</li>
<li><b>Vocabulary and execution.</b> Each word only one of you found is weighted by the other player's find rate for it on all their <i>other</i> boards. At rate r, a share r
of its points is <i>execution</i> (the other player usually takes it, not this time) and 1 − r is <i>vocabulary</i> (the other player rarely takes it anywhere). Net of both
directions, vocabulary is {n(D['vocabNet'][0])} (CI {n(D['vocabNet'][1])} to {n(D['vocabNet'][2])}) and execution {n(D['execNet'][0])} (CI {n(D['execNet'][1])} to {n(D['execNet'][2])}):
{pct(voc_share, 0)} and {pct(exe_share, 0)} of the margin. With a hard threshold instead (knows it = takes it on half their other presences), vocabulary is {n(D['vocab50Net'][0])} and
execution {n(D['exec50Net'][0])}. The vocabulary component has the same sign and is at least most of the margin under both definitions; the execution component is not robust to the definition.
{'Of the points in words only ' + PEER_NAME + ' found, ' + pct(wtop['peerOnlyPtsSubjectRateUnder10'], 0) + ' are in words you take on under 10% of your other boards.'}</li>
</ul>
{fig("sh_3_decomposition")}
<h3>8.2 Sequencing or vocabulary?</h3>
<p><b>Order alone is worth nothing:</b> a score is a sum, so the same words in a different order score the same. Sequencing can only matter by changing <i>which</i> words
get found, or how many. Three tests on the paired boards:</p>
<ol>
<li><b>The section 2.2 counterfactual, both directions.</b> On an identical board the other player's opening lengths are always available, so the counterfactual reduces to the
difference in points scored in the first 15 finds: {n(abs(P['pts15']['diff']))} a game in {'your' if P['pts15']['diff'] > 0 else PEER_NAME + "'s"} favour
(CI {n(min(abs(P['pts15']['lo']), abs(P['pts15']['hi'])))} to {n(max(abs(P['pts15']['lo']), abs(P['pts15']['hi'])))}). Given {'your' if you_open_longer else PEER_NAME + "'s"} opening lengths,
{PEER_NAME if you_open_longer else 'you'} would score that much more in the first 15 finds, <i>if</i> the longer opening came at no cost later. Net of each player's own within-player volume cost
({O['volumeCostPerLetter']['subject']:+.1f} words per letter for you, {O['volumeCostPerLetter']['peer']:+.1f} for {PEER_NAME}, all seasons), it is
{n(abs(O['subjectNet'] if not you_open_longer else O['peerNet']), -2)}.</li>
<li><b>The paired regression.</b> Across the {sh['games']} boards, the margin rises {n(RG['margin']['slope'])} points per letter by which your opening is longer than {hers}
(CI {n(RG['margin']['slopeCi'][0])} to {n(RG['margin']['slopeCi'][1])}). At the average opening difference ({RG['meanDOpen']:+.2f} letters) that is {n(RG['margin']['atMeanDelta'])}
points: <b>{pct(abs(open_share), 0)} of the margin</b> (CI {pct(abs(slo), 0)} to {pct(abs(shi), 0)}). It is observational within pairs: a sharp game lengthens the opening and
raises the score at once, so this is an upper bound on what the opening itself causes.</li>
<li><b>Equal openings.</b> The regression's intercept, the margin when both open equally long, is {n(RG['margin']['intercept'])} (CI {n(RG['margin']['interceptCi'][0])} to
{n(RG['margin']['interceptCi'][1])}). In the {RG['equalOpenings']['games']} games where the openings were within 0.1 letters, the margin was {n(RG['equalOpenings']['margin'][0])}
and you won {pct(RG['equalOpenings']['winRate'])}.</li>
</ol>
<p>Where does the opening advantage go? Not into volume: the word-count difference moves {RG['dN']['slope']:+.1f} words per letter of opening difference
(CI {RG['dN']['slopeCi'][0]:+.1f} to {RG['dN']['slopeCi'][1]:+.1f}), which is no detectable effect, and the volume gap at equal openings is {RG['dN']['intercept']:+.1f} words.
It goes into value per word ({n(RG['value']['slope'])} per letter), and of the margin associated with the opening, {n(RG['vocabNet']['atMeanDelta'])} is the vocabulary component
and {n(RG['execNet']['atMeanDelta'])} execution: the long words in the stronger opening are mostly words the other player rarely finds.</p>
{fig("sh_4_opening_vs_margin")}
{table(wr_rows, ["your head-to-head win rate", "rate"])}
<p><b>The answer.</b> {'Your' if you_lead else PEER_NAME + "'s"} {pct(sh['winRate'][0] if you_lead else 1 - sh['winRate'][0])} is carried by vocabulary more than by sequencing.
Remove the vocabulary component from every game and your win rate goes from {pct(WR['actual'])} to {pct(WR['vocabulary'])}; remove the part of the margin
associated with the opening difference and it goes to {pct(WR['openingDifference'])}. Remove the volume component and it goes to {pct(WR['volume'])}. The two overlap rather than add: the opening's contribution is itself mostly vocabulary.
The single biggest component is volume, {pct(vol_share, 0)} of the margin, and volume is not explained by the opening: {'you find' if D['volume'][0] > 0 else PEER_NAME + ' finds'}
about {abs(P['words']['diff']):.0f} more words a game whatever the openings. The splits are different cuts of the same points, so they overlap rather than add.
The honest summary: about {pct(abs(voc_share), 0)} of the points gap sits in words the player who missed them rarely finds anywhere, about {pct(abs(open_share), 0)} is associated
with the opening, and the opening's share is itself mostly vocabulary.</p>
<h3>8.3 Words one of you takes and the other never does, same boards</h3>
<p>Because the board is fixed, these are cleaner vocabulary signals than the pooled opponent list in section 6. Listed: words on 3+ shared boards taken by one player and never by the
other there, with each player's find rate on their other boards. {wtop['peerOnlyNeverSubject']} words qualify for {PEER_NAME} and {wtop['subjectOnlyNeverPeer']} for you.
Full table: <span class="tsv">{FIGREL}/sh_words_all.tsv</span>.</p>
{fig("sh_5_exclusive_words")}
{table([(r_.word, int(r_.pts), f"{int(r_.peerOnly)} of {int(r_.boards)}", pct(r_.rateSubjectElsewhere, 0), pct(r_.ratePeerElsewhere, 0)) for r_ in pw.itertuples()],
       ["word " + PEER_NAME + " took, you never did", "points", "boards " + he + " took it", "your rate elsewhere", his + " rate elsewhere"])}
{table([(r_.word, int(r_.pts), f"{int(r_.subjectOnly)} of {int(r_.boards)}", pct(r_.ratePeerElsewhere, 0), pct(r_.rateSubjectElsewhere, 0)) for r_ in sw.itertuples()],
       ["word you took, " + PEER_NAME + " never did", "points", "boards you took it", his + " rate elsewhere", "your rate elsewhere"])}
<p>Words with a low "your rate elsewhere" in the first table are vocabulary you lack; words with a high one are words you know but did not reach on those boards.</p>
<h3>8.4 Is the gap narrowing?</h3>
{fig("sh_6_over_time")}
{table([(b['season'], b['games'], f"{b['margin']:+,.0f} ({b['lo']:+,.0f} to {b['hi']:+,.0f})", pct(b['winRate']), f"{b['open15_s']:.2f} / {b['open15_p']:.2f}", f"{b['words_s']:.0f} / {b['words_p']:.0f}") for b in bys],
       ["season", "games", "margin, you minus " + PEER_NAME, "your win rate", "first-15 length, you / " + PEER_NAME, "words, you / " + PEER_NAME])}
<p>The margin moves {n(tr8['margin']['slope'])} points a month (CI {n(tr8['margin']['lo'])} to {n(tr8['margin']['hi'])}; {n(tr8['marginControlled']['slope'])} controlled for board potential).
{'It is narrowing' if tr8['margin']['slope'] * m_ < 0 and tr8['margin']['hi'] * tr8['margin']['lo'] > 0 else 'There is no clear trend'}: {n(sh['halves']['first']['margin'][0])} in the first half of the shared games
({sh['halves']['first']['first']} to {sh['halves']['first']['last']}) and {n(sh['halves']['second']['margin'][0])} in the second. Word counts drive it: you add {tr8['n_s']['slope']:+.2f}
words a month in these games and {PEER_NAME} {tr8['n_p']['slope']:+.2f}, while the opening lengths barely move. The shared games are sparse in seasons 9 and 10, so the recent
end of the trend rests on few games.</p>
<h3>8.5 Holdout inside the head-to-head</h3>
{table([(html.escape(k), f"{v['train']:+,.1f}", f"{v['test']:+,.1f}", f"{v['mde']:,.1f}", v['verdict']) for k, v in hh.items()],
       ["finding (chronological 70/30 of the shared games)", "train", "test", "test MDE", "verdict"])}
<p>The margin, the word-count gap, the opening gap and the vocabulary component all hold in the later 30% of shared games. Because the gap has narrowed, the test-period values are
smaller than the training ones. The execution component and the opening slope do not survive: treat them as descriptive.</p>
"""

# ---------------------------------------------------------------- section 9: holdout
verd = {"survives": "<b>survives</b>", "underpowered": "underpowered", "does not survive": "does not survive", "no finding to test": "nothing to test"}


import re  # noqa: E402

peer_ho = {re.sub(r"^\d+ ", "", k): v for k, v in peer_ho.items()}


def peer_verdict(h):
    k = re.sub(r"^\d+ ", "", h["finding"].replace(PEER_NAME, NAME))
    p = peer_ho.get(k)
    return verd.get(p["verdict"], p["verdict"]) if p else ""


surv = [h["finding"] for h in ho if h["verdict"] == "survives"]
under = [h["finding"] for h in ho if h["verdict"] == "underpowered"]
fail = [h["finding"] for h in ho if h["verdict"] == "does not survive"]
both = [h["finding"] for h in ho if h["verdict"] == "survives" and (peer_ho.get(re.sub(r"^\d+ ", "", h["finding"].replace(PEER_NAME, NAME))) or {}).get("verdict") == "survives"]
sec9 = f"""
<h2 id="s9">9. Holdout: seasons 7 to 10, train 70% / test 30%</h2>
<p>Train: {n(split_n.get('train', 0))} games before {day(test_start)}. Test: {n(split_n.get('test', 0))} games from then. Test SEs are bootstrap over games, and the MDE is 2.8 SE
(80% power, 5% two-sided). <i>Survives</i> means the same sign and significant on test. <i>Underpowered</i> means not confirmed, with a train effect smaller than the test MDE.
<i>Does not survive</i> means the test period had the power and did not confirm. The last column is the same finding in {PEER_NAME}'s games, run independently through the same
pipeline and {his} own holdout: a finding that holds for two players is much stronger than one that holds for either. (Head-to-head rows use their own split; see section 8.5.)</p>
{table([(html.escape(h['finding']), '' if h['train'] is None else f"{h['train']:.4g}", '' if h['test'] is None else f"{h['test']:.4g}",
         '' if h.get('seTest') is None else f"{h['seTest']:.3g}", '' if h.get('mde') is None else f"{h['mde']:.3g}", h['unit'], verd.get(h.get('verdict'), h.get('verdict')),
         peer_verdict(h)) for h in ho],
       ["finding", "train", "test", "test SE", "MDE", "unit", "verdict", f"in {PEER_NAME}'s games"])}
<p><b>Survives for both players ({len(both)}):</b> {'; '.join(html.escape(x) for x in both)}.</p>
<p><b>Underpowered for you:</b> {'; '.join(html.escape(x) for x in under) or 'none'}. <b>Does not survive:</b> {'; '.join(html.escape(x) for x in fail) or 'none'}.</p>
"""

# ---------------------------------------------------------------- section 10: alpha
hd = sa["headroom"]
sec10 = f"""
<h2 id="s10">10. Alpha: points almost nobody takes</h2>
<p>Learning a word the field takes at 60% moves you to par. Learning one the field takes at 3% puts you ahead of everyone. For each word, the field find rate is all finds
(yours and opponents') over all player-presences. Candidates are present on 50+ of your boards, have 5+ letters, and have a field find rate under 10%. Each is classed by how it
reaches you on the boards where it appears:</p>
<ul>
<li><b>free:</b> an additive extension whose path extends a word you found there;</li>
<li><b>drop-terminal:</b> a terminal substring of a word you found;</li>
<li><b>cellmate:</b> an anagram of a word you found;</li>
<li><b>independent:</b> none of these.</li>
</ul>
<p><b>Expected gain per word learned</b> = presences per game × points × (the find rate you would achieve − your current rate). The find rate you would achieve is taken from your
<i>reliable</i> words ({n(sa['reliableWords'])} words you find on 50%+ of presences), in the same mix of situations. On those, you take a 6-letter word
{pct(sa['qTable']['6']['free'], 0)} of the time when it is a free extension of something you found, and about {pct(sa['qTable']['6']['none'], 0)} otherwise.
You find long words almost only by chaining, which is why nearly every alpha word is a free extension.</p>
{fig("sa_alpha_words")}
<p>{n(al['candidates'])} candidates, {n(al['candidatesExclDead'])} after removing never-accepted words. Of the top 300, {al['top300ByClass'].get('free', 0)} are free extensions and
{pct(al['top300WithHook'], 0)} contain a stem you already find reliably. Their median field find rate is {pct(al['top300FieldRateMedian'])}, and yours is {pct(al['top300MyRateMedian'])}.
<b>Sensitivity:</b> if never-accepted words are allowed, {al['sensitivity']['deadInTop300IfIncluded']} of them enter the top 300 and {al['sensitivity']['overlapTop300']} of the 300 are unchanged.
{pct(al['vowelInitialShareTop300'], 0)} of the top 300 are vowel-initial. Full ranked list with family, reachability class and hook stem: <code>data/ranked/{PLAYER}/alpha_words.tsv</code>
(top 300) and <span class="tsv">{FIGREL}/sa_alpha_all_candidates.tsv</span> (all candidates, with and without never-accepted words).</p>
<h3>Families even the strong field leaves incomplete</h3>
<p>For each 4+ letter word-stem on 20+ of your boards in seasons 7 to 10: completion by you, by top-quartile opponents and by the frontier, and the points left on boards where
<i>someone</i> opened the family but nobody finished it. Families overlap, since one word belongs to several, so the column does not sum.</p>
{table([(r_['stem'], r_['boards'], f"{r_['size']:.1f}", f"{r_['youCompletion']:.2f}", f"{r_['topQCompletion']:.2f}", f"{r_['frontierCompletion']:.2f}", n(r_['uncontestedPerGame']))
        for r_ in sa['families']['top'][:20]],
       ["stem", "boards", "mean size", "you", "top quartile", "frontier", "unclaimed points per game"])}
<p>The frontier completes a median of {pct(sa['families']['top50FrontierCompletionMedian'], 0)} of these families. <code>data/ranked/{PLAYER}/alpha_families.tsv</code></p>
<h3>Headroom: what the family curriculum is worth to you</h3>
{fig("sa_headroom")}
<p>Adding every missed word whose path extends one of your finds would add {n(hd['current']['ceilingPtsPerGame'])} points a game ({hd['current']['missedFreeWordsPerGame']:.0f} words).
That is arithmetic, not a bound: 80 seconds cannot hold it. <b>The credible bounds are the take rates real players reached on these boards.</b> Your free-extension take is {pct(hd['takeRates']['you'])}.</p>
{table([("top-quartile opponents' rate", pct(hd['takeRates']['topQuartile']), n(hr['topQuartileRatePts']), pp(mech_at(hr['topQuartileRatePts'])), pp(hr['topQuartileRatePts'] / 100 * log100)),
        ("frontier rate (best player on each board)", pct(hd['takeRates']['frontier']), n(hr['frontierRatePts']), pp(mech_at(hr['frontierRatePts'])), pp(hr['frontierRatePts'] / 100 * log100))],
       ["if your free-extension take rose to", "rate", "points per game", "win rate (mechanical)", "win rate (logistic floor)"])}
<p>That is what the family curriculum is worth to you: about {n(hr['topQuartileRatePts'], -2)} points a game to reach the top quartile, and {n(hr['frontierRatePts'], -2)} to reach
the frontier. For scale, the opening is worth {n(net_lo, -2)} to {n(net_hi, -2)}.</p>
"""

# ---------------------------------------------------------------- section 11: plan
top_rows = []
for i, r_ in enumerate(top200.itertuples(), 1):
    hook = r_.hookStem if isinstance(r_.hookStem, str) else (r_.family if isinstance(r_.family, str) else "")
    top_rows.append((i, f"<b>{r_.word}</b>", int(r_.pts), f"{r_.fieldRate:.1%}", f"{(r_.myRateCur if r_.myRateCur == r_.myRateCur else 0):.1%}",
                     f"{(r_.topQRate if r_.topQRate == r_.topQRate else 0):.1%}", r_.reachClass, hook, f"{r_.gainPerGameCur:.1f}",
                     "yes" if r_.word[0] in "AEIOU" else ""))
fam_rows = [(i, f"<b>{r_.stem}</b>", int(r_.boards), f"{r_.size:.1f}", f"{r_.youCompletion:.2f}", f"{r_.topQCompletion:.2f}", f"{r_.frontierCompletion:.2f}",
             n(r_.uncontestedPerGame)) for i, r_ in enumerate(alpha_fam.itertuples(), 1)]
h2h_words = ""
if sh:
    lack = [w for w in sh["words"]["peerOnlyTop"] if w["rateSubjectElsewhere"] < 0.1][:12]
    if lack:
        h2h_words = (f"<p><b>From the head-to-head.</b> Words {PEER_NAME} took on your shared boards and you never did, which you also rarely take anywhere else, are the cleanest "
                     f"vocabulary gaps in the data because the board was held fixed: {', '.join(w['word'] for w in lack)} (section 8.3). Add them to the batches of the stems they hang off.</p>")
warm_row = [("Warm-up board before ranked", n(-fat['game1'][0]), "on the first game of each session", pp(mech_at(-fat['game1'][0])) + " on that game", "",
             f"Measured; {warm} on the holdout. The cost of game 1 is observed, the fix assumes a warm-up board removes it")]
sec11 = f"""
<h2 id="s11">11. Training plan</h2>
<h3>Phase A, now: {'the opening' if opening_leak else 'habits'}</h3>
{f'''<p><b>What to do.</b> For the first 15 finds of every board, do not swipe a 3-letter word unless it is the tail of a longer word you just swiped. Look for a 5 or 6 first.
Two drills from §10.4 target this. <b>Longs only</b> rejects words under 5 letters, so it trains the search pattern. <b>Swipe budget</b> caps submissions, so it trains the
selection. Run them before ranked, not after.</p>''' if opening_leak else ''}
{table(([("Opening fix: first-15 profile of strong opponents", n(open_pts), f"{n(net_lo, -2)} to {n(net_hi, -2)}", f"{pp(mech_at(net_lo))} to {pp(mech_at(net_hi))}",
          pp(net_lo / 100 * log100), f"Counterfactual on your boards, survives the holdout; volume cost ({vol_lo:.1f} to {vol_hi:.1f} words) measured on your own games")] if opening_leak else []) + warm_row,
       ["intervention", "gross points / game", "net points / game", "win rate (mechanical)", "win rate (floor)", "evidence"])}
{f'''<p><b>How to tell whether it is working.</b> Track the mean length of your first 15 finds. It is {ot['yourOpen15']:.2f} now, strong opponents are at {ot['strongOpen15']:.2f}, and it varies
by {ot['open15Sd']:.2f} letters from game to game. Over 100 games its standard error is about {ot['open15Sd'] / 10:.3f}, so a move of 0.1 letters is visible within about 100 games.
Two guards: total word count should not fall by more than about {max(vol_hi, 1) + 1:.0f} a game, and board-controlled score should rise. If opening length rises and score does not, the
counterfactual was wrong and the plan should stop.</p>
<p><b>Evidence and extrapolation.</b> <i>Supported:</i> your opening is shorter than strong opponents' by {ot['delta']:.2f} letters; the gap is priced at about {n(open_pts)} points on
your own boards and survives the holdout; longer openings in your own games cost {vol_lo:.1f} to {vol_hi:.1f} words. <i>Extrapolation:</i> that you can lengthen the opening without
changing something else about your play, and that the mechanical conversion to wins holds when every game shifts at once.</p>''' if opening_leak else ''}
<h3>Phase B, after the opening: vocabulary, ordered by edge</h3>
<p>Ordered by the alpha analysis, not by what the field already knows. The top-quartile holes in section 4.2 (about {n(holes['topQuartile']['pointsPerGame'])} points a game) bring
you to par with the strongest players. The words below take you past them. Batch them by the stem they hang off, which is the unit §10.3's family batches drill, and for each batch
run §10.4's <b>branch completion</b> and <b>affix grid</b> drills on the hook stem.</p>
{h2h_words}
<p><b>Expected points</b> are per game, if the word is learned to the level of your reliable words (seasons 7 to 10). They are <i>not additive without limit</i>: every word
competes for the same 80 seconds. The first 50 are worth about {n(al['top50GainPerGame'], -2)} points a game and the first 200 about {n(cum200, -2)} on paper; treat the sum past a few
thousand points as an upper bound. <i>Supported:</i> each word's presence rate, field find rate, your find rate, the top-quartile rate, and how it reaches you on real boards.
<i>Extrapolation:</i> that a learned word will be taken at the rate your reliable words are.</p>
<details open><summary><b>The first 200 words</b></summary>
{table(top_rows, ["#", "word", "points", "field rate", "your rate", "top-quartile rate", "reaches you as", "hangs off", "points / game", "vowel-initial"], "long")}
</details>
<details open><summary><b>The first 50 families</b> (families overlap; ranked by points left on boards where someone opened the family and nobody finished it)</summary>
{table(fam_rows, ["#", "stem", "boards (s7-10)", "mean size", "your completion", "top quartile", "frontier", "unclaimed points / game"], "long")}
</details>
"""

sec12 = f"""
<h2 id="s12">12. Output</h2>
<ul>
<li><code>reports/analytics_{PLAYER}.html</code> (this file), <code>reports/{FIGREL}/*.tsv</code> (data behind every figure), <code>reports/manifest_{PLAYER}.json</code>.</li>
<li><code>data/ranked/{PLAYER}/</code>: <code>games.parquet</code>, <code>presence.parquet/</code>, <code>belief.tsv</code>, <code>missed_by_opponent.tsv</code>, <code>alpha_words.tsv</code>,
<code>alpha_families.tsv</code>, <code>board_norms_real.tsv</code>, <code>boards_fit.json</code>, <code>elo_fit.json</code>, <code>finds_derived.parquet</code>.</li>
<li><code>data/ranked/shared/</code>: <code>solutions.parquet</code> (every board in either export, solved once), <code>h2h.parquet</code> and <code>crossval.json</code> (the cross-export check).</li>
<li>Pipeline: <code>tools/analytics/run_all.sh</code> runs ingest, derive, crossval, boards, analyze and render for both players; <code>FLUX_PLAYER</code> selects the player for any single stage.</li>
</ul>
"""

sec13 = f"""
<h2 id="s13">13. What is not in this data</h2>
<p>No misswipes, no within-game timestamps, no paths. §4.3's Account B and §3.6's suffix-ambiguity cost remain unmeasured, and every cost here is in finds, not
seconds. Paths are inferred for {pct(s3['ambiguity']['player'], 0)} of finds. Tier labels are posteriors under v3, whose candidate counts are still provisional. Whether the words
never accepted in either export are rejected needs the developer. The within-season holdout has limited power, and section 9 says where that matters. The head-to-head is one matchup:
its vocabulary split depends on each player's find rate elsewhere standing in for "knows the word", which also absorbs how visible the word is to that player.</p>
"""

appendix_figs = [k for k in F if k not in USED]
appendix = "<h2 id='appendix'>Appendix: remaining figures</h2>" + "".join(fig(k) for k in appendix_figs)

css = open(os.path.join(os.path.dirname(__file__), "report.css")).read()
git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
nav = " ".join(f'<a href="#{a}">{t}</a>' for a, t in (("headlines", "Headlines"), ("s0", "0 Verification"), ("s0-1", "0.1 Dictionary"), ("s0-2", "0.2 Cross-check"), ("s1", "1 Time"),
                                                     ("s2", "2 Sequence"), ("s3", "3 Spatial"), ("s4", "4 Vocabulary"), ("s5", "5 Boards"), ("s6", "6 Competitive"),
                                                     ("s7", "7 Sessions"), ("s8", "8 Head-to-head"), ("s9", "9 Holdout"), ("s10", "10 Alpha"), ("s11", "11 Training plan"),
                                                     ("s13", "13 Limits"), ("appendix", "Appendix")))
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{NAME} Ranked Analytics</title><style>{css}</style></head><body><main>
<h1>Your ranked play, measured</h1>
<p class="sub">Written for {NAME}. {n(NG)} ranked games, {day(d0)} to {day(d1)}, seasons {int(G.season.min())} to {int(G.season.max())}. The current game is seasons 7 to 10
({n(ncur)} games). Measured against <code>docs/SPEC.md</code> and <code>docs/PHASE1_REPORT.md</code>; "§" always means a SPEC.md section and this report's own sections are
"section N". Generated {now} at {git_sha[:10]}{' (dirty)' if dirty else ''}.</p>
<nav>{nav}</nav>
{head}{sec0}{sec1}{sec2}{sec3}{sec4}{sec5}{sec6}{sec7}{sec8}{sec9}{sec10}{sec11}{sec12}{sec13}{appendix}
</main></body></html>"""
os.makedirs(REPORTS, exist_ok=True)
out_html = os.path.join(REPORTS, f"analytics_{PLAYER}.html")
open(out_html, "w").write(page)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


manifest = {
    "player": NAME, "generatedUtc": now, "gitSha": git_sha, "gitDirty": dirty, "pass": 3,
    "inputs": {p["file"]: {"sha256": p["sha256"], "games": p["gamesInThisPart"], "part": p["part"], "fetchedAt": p["fetchedAt"]} for p in ing["parts"]},
    "dictionary": {"wordlist": WORDLIST, "sha256": sha(WORDLIST), "dawgSha256": ing["dawgSha256"], "words": 279496},
    "configs": {c: sha(os.path.join(ROOT, "config", c)) for c in ("ruleset_v1.json", "ruleset_v2.json", "ruleset_v3.json")},
    "regime": {"current": "seasons 7-10", "games": ncur, "holdout": "chronological 70/30 within seasons 7-10", "train": split_n.get("train"), "test": split_n.get("test")},
    "counts": {"games": ing["games"], "finds": ing["finds"], "solutionRows": ing["solutionRows"], "neverAcceptedWords": dr["words"]},
    "crossValidation": {"sharedGames": CV["sharedGames"], "exactOnAll": CV["exactOnAll"], "mismatches": len(CV["mismatches"])},
    "figures": sorted(F), "reportBytes": len(page.encode()),
}
json.dump(manifest, open(os.path.join(REPORTS, f"manifest_{PLAYER}.json"), "w"), indent=2)
print("wrote", out_html, f"{len(page) / 1e6:.1f} MB,", len(USED), "figures")

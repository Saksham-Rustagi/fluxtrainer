"""Head-to-head: the subject against the other player on identical boards.

Every shared game has the same board, the same 80 seconds and both full find sequences,
so every comparison here is paired by construction and the board cancels. Forfeits (one
side found nothing) are excluded. The shared games span every regime; nothing here
depends on how boards are generated, because both players always faced the same one.

Decompositions of the per-game margin (subject minus peer), each an exact identity:
  exclusive words  margin = points of words only the subject found - points of words only
                   the peer found (shared words score for both and cancel)
  volume / value   margin = dN x mean value per word + d(value per word) x mean N
  vocabulary / execution
                   each exclusive word is weighted by the other player's find rate for it on
                   all their other boards (outside the shared games): at rate r, a share r of its
                   points is 'execution' (the other player usually finds it, not this time)
                   and 1 - r is 'vocabulary' (the other player rarely finds it anywhere)
The opening is tested three ways: the section 2.2 counterfactual run on the paired boards
in both directions, the paired regression of the margin on the opening-length difference,
and that regression's intercept (the margin when both open equally long).
"""
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import ttest_rel, wilcoxon

import holdout
import peer
from common import FIGS, PEER, PEER_NAME, len_class, points, ranked_dir
from viz import INK2, OPP, PEER as PEERC, PLAYER, STRONG, WEAK, band, boot_ratio_clustered, note_n, plt, save

B = 1000
LC = [3, 4, 5, 6, 7]


def boot(v, b=B, seed=0):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    w = np.random.default_rng(seed).poisson(1.0, (b, len(v)))
    m = (w @ v) / np.maximum(w.sum(axis=1), 1)
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def paired(a, b):
    d = np.asarray(a, float) - np.asarray(b, float)
    ok = np.isfinite(d)
    m, lo, hi = boot(d)
    nz = d[ok][d[ok] != 0]
    return {"subject": float(np.nanmean(a)), "peer": float(np.nanmean(b)), "diff": m, "lo": lo, "hi": hi,
            "pT": float(ttest_rel(np.asarray(a, float)[ok], np.asarray(b, float)[ok]).pvalue),
            "pWilcoxon": float(wilcoxon(nz).pvalue) if len(nz) > 10 else np.nan, "n": int(ok.sum())}


def rates_elsewhere(pres, exclude, m=5):
    """Find rate given presence on boards outside `exclude`, shrunk toward the length-class rate."""
    p = pres[~pres.gid.isin(exclude)]
    w = p.groupby("word").agg(n=("foundPlayer", "size"), k=("foundPlayer", "sum"), L=("len", "first"))
    w["lc"] = len_class(w.L)
    base = p.assign(lc=len_class(p.len)).groupby("lc").foundPlayer.mean()
    w["rate"] = (w.k + m * w.lc.map(base)) / (w.n + m)
    return w.rate, base


def section(R, g, f, pres):
    h = peer.h2h()
    if h is None or not peer.available():
        return
    r = {}
    hg = g[g.peerGame].copy()
    r["shared"] = int(len(hg))
    r["forfeits"] = int(hg.peerForfeit.sum())
    hg = hg[~hg.peerForfeit]
    gids = set(hg.gid)
    r["games"] = int(len(hg))
    r["bySeason"] = hg.season.value_counts().sort_index().to_dict()
    r["current"] = int(hg.current.sum())

    # ---- per-game metrics, both players --------------------------------------------------
    ff = f[f.gid.isin(gids) & f.valid].sort_values(["gid", "who", "pos"])
    side = {"player": "s", "opponent": "p"}
    per = {}
    for who, k in side.items():
        x = ff[ff.who == who]
        a = x.groupby("gid").agg(n=("len", "size"), meanLen=("len", "mean"), score=("pts", "sum"))
        a["open10"] = x[x.pos < 10].groupby("gid").len.mean()
        a["open15"] = x[x.pos < 15].groupby("gid").len.mean()
        a["pts15"] = x[x.pos < 15].groupby("gid").pts.sum()
        for L in LC:
            a[f"share{L}"] = x[len_class(x.len.values) == L].groupby("gid").size().reindex(a.index).fillna(0) / a.n
        per[k] = a
    d = hg.set_index("gid")[["createdAt", "season", "month", "current", "potential", "yourScore", "oppScore", "S", "grid"]].join(
        per["s"].add_suffix("_s")).join(per["p"].add_suffix("_p"))
    d["margin"] = d.yourScore - d.oppScore
    assert (d.score_s == d.yourScore).all() and (d.score_p == d.oppScore).all()
    d["capture_s"], d["capture_p"] = d.yourScore / d.potential, d.oppScore / d.potential
    r["winRate"] = boot(d.S)
    r["meanScore"] = {"subject": float(d.yourScore.mean()), "peer": float(d.oppScore.mean())}
    metrics = [("score", "yourScore", "oppScore"), ("words", "n_s", "n_p"), ("meanLen", "meanLen_s", "meanLen_p"),
               ("open10", "open10_s", "open10_p"), ("open15", "open15_s", "open15_p"), ("pts15", "pts15_s", "pts15_p"),
               ("capture", "capture_s", "capture_p")] + [(f"share{L}", f"share{L}_s", f"share{L}_p") for L in LC]
    r["paired"] = {name: paired(d[a], d[b]) for name, a, b in metrics}
    r["pairedByRegime"] = {reg: {name: paired(x[a], x[b]) for name, a, b in metrics[:5]}
                           for reg, x in (("seasons1to6", d[~d.current]), ("seasons7to10", d[d.current]))}
    agg = {}
    for who, k in side.items():
        x = ff[ff.who == who]
        agg[k] = pd.Series(len_class(x.len)).value_counts(normalize=True).sort_index().round(4).to_dict()
    r["lengthMixPooled"] = agg

    # ---- decompositions -----------------------------------------------------------------
    p = pres[pres.gid.isin(gids)].copy()
    p["fo"] = p.foundOpp.fillna(False).astype(bool)
    p["shared"] = p.foundPlayer & p.fo
    p["sOnly"] = p.foundPlayer & ~p.fo
    p["pOnly"] = p.fo & ~p.foundPlayer
    ex = p.groupby("gid").apply(lambda x: pd.Series({"sharedPts": x.pts[x.shared].sum(), "sOnlyPts": x.pts[x.sOnly].sum(),
                                                     "pOnlyPts": x.pts[x.pOnly].sum(), "sharedN": x.shared.sum(),
                                                     "sOnlyN": x.sOnly.sum(), "pOnlyN": x.pOnly.sum()}), include_groups=False)
    d = d.join(ex)
    assert np.allclose(d.sOnlyPts - d.pOnlyPts, d.margin)
    # volume and value per word, symmetric (exact)
    d["v_s"], d["v_p"] = d.yourScore / d.n_s, d.oppScore / d.n_p
    d["volume"] = (d.n_s - d.n_p) * (d.v_s + d.v_p) / 2
    d["value"] = (d.v_s - d.v_p) * (d.n_s + d.n_p) / 2
    # vocabulary / execution: other player's find rate for the word outside the shared games
    rs, base_s = rates_elsewhere(pres, gids)
    pp = pd.read_parquet(os.path.join(ranked_dir(PEER), "presence.parquet"), columns=["gid", "word", "len", "foundPlayer"])
    rp, base_p = rates_elsewhere(pp, set(h.peerGid))
    p["rS"] = p.word.map(rs).fillna(p.len.map(lambda L: base_s[min(L, 7)]))
    p["rP"] = p.word.map(rp).fillna(p.len.map(lambda L: base_p[min(L, 7)]))
    p["execS"] = np.where(p.sOnly, p.pts * p.rP, 0.0)          # subject found it; peer usually does
    p["vocabS"] = np.where(p.sOnly, p.pts * (1 - p.rP), 0.0)   # subject found it; peer rarely does
    p["execP"] = np.where(p.pOnly, p.pts * p.rS, 0.0)
    p["vocabP"] = np.where(p.pOnly, p.pts * (1 - p.rS), 0.0)
    # the same split with a hard threshold: 'knows it' = finds it on half their other presences
    p["execS50"] = np.where(p.sOnly & (p.rP >= 0.5), p.pts, 0.0)
    p["execP50"] = np.where(p.pOnly & (p.rS >= 0.5), p.pts, 0.0)
    ve = p.groupby("gid")[["execS", "vocabS", "execP", "vocabP", "execS50", "execP50"]].sum()
    d = d.join(ve)
    d["vocabNet"] = d.vocabS - d.vocabP
    d["execNet"] = d.execS - d.execP
    d["exec50Net"] = d.execS50 - d.execP50
    d["vocab50Net"] = d.margin - d.exec50Net
    assert np.allclose(d.vocabNet + d.execNet, d.margin)
    comp = {}
    for c in ["margin", "sharedPts", "sOnlyPts", "pOnlyPts", "volume", "value",
              "vocabS", "vocabP", "execS", "execP", "vocabNet", "execNet", "exec50Net", "vocab50Net", "sharedN", "sOnlyN", "pOnlyN"]:
        comp[c] = boot(d[c])
    r["decomposition"] = comp
    r["decompositionByRegime"] = {reg: {c: boot(x[c]) for c in ("margin", "volume", "value", "vocabNet", "execNet")}
                                  for reg, x in (("seasons1to6", d[~d.current]), ("seasons7to10", d[d.current]))}
    r["rateBase"] = {"subject": base_s.round(4).to_dict(), "peer": base_p.round(4).to_dict()}

    # ---- the opening -----------------------------------------------------------------------
    r["opening"] = opening(R, d, ff)
    # win rate for the subject if one component of each game's margin were removed (ties count half)
    reg = r["opening"]["regression"]["margin"]
    dOpen = (d.open15_s - d.open15_p).fillna(0)

    def wr(m):
        return float(((m > 0) + 0.5 * (m == 0)).mean())

    r["winRateWithout"] = {"actual": wr(d.margin), "vocabulary": wr(d.margin - d.vocabNet), "execution": wr(d.margin - d.execNet),
                           "volume": wr(d.margin - d.volume), "value": wr(d.margin - d.value),
                           "openingDifference": wr(d.margin - reg["slope"] * dOpen),
                           "vocabularyThreshold": wr(d.margin - d.vocab50Net), "executionThreshold": wr(d.margin - d.exec50Net)}
    # decile and position curves, paired set
    fg = ff.assign(grp=ff.who.map({"player": "subject", "opponent": "peer"}))
    curves = {}
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.6))
    for grp, color, label in (("subject", PLAYER, "you"), ("peer", PEERC, PEER_NAME)):
        x = fg[fg.grp == grp]
        t = boot_ratio_clustered(x, "gid", "decile", "len")
        band(axes[0], t.decile, t, color, label)
        t2 = boot_ratio_clustered(x[x.pos < 25], "gid", "pos", "len")
        band(axes[1], t2.pos + 1, t2, color, label)
        curves[grp] = {"decile": t["mean"].round(3).tolist(), "pos": t2["mean"].round(3).tolist()}
    axes[0].set_title("Mean length across the game, same boards")
    axes[0].set_xlabel("decile of normalised find position")
    axes[0].set_ylabel("mean word length (letters)")
    axes[1].set_title("The opening: first 25 finds, same boards")
    axes[1].set_xlabel("find number")
    axes[1].legend(fontsize=8)
    note_n(axes[0], f"{len(d):,} shared games")
    fig.tight_layout()
    save(fig, "sh_2_opening_curves", {"decile": pd.DataFrame(curves).T.reset_index()}, f"You and {PEER_NAME} on the same boards: mean find length by position, 95% bands over games.")
    r["curves"] = curves

    # ---- words: exclusive finds on identical boards -------------------------------------------
    w = p.groupby("word").agg(len=("len", "first"), pts=("pts", "first"), boards=("gid", "size"), subjectFound=("foundPlayer", "sum"),
                              peerFound=("fo", "sum"), subjectOnly=("sOnly", "sum"), peerOnly=("pOnly", "sum"), rateSubjectElsewhere=("rS", "first"),
                              ratePeerElsewhere=("rP", "first"))
    w["netPtsToPeer"] = (w.peerOnly - w.subjectOnly) * w.pts
    w["netPtsPerGame"] = w.netPtsToPeer / len(d)
    w = w.sort_values("netPtsToPeer", ascending=False)
    top_p = w[(w.peerOnly >= 3) & (w.subjectFound == 0)].head(40)
    top_s = w[(w.subjectOnly >= 3) & (w.peerFound == 0)].sort_values("netPtsToPeer").head(40)
    r["words"] = {"peerOnlyTop": top_p.reset_index().round(4).to_dict("records"), "subjectOnlyTop": top_s.reset_index().round(4).to_dict("records"),
                  "distinctPeerOnly": int((w.peerOnly > 0).sum()), "distinctSubjectOnly": int((w.subjectOnly > 0).sum()),
                  "peerOnlyNeverSubject": int(((w.peerOnly >= 3) & (w.subjectFound == 0)).sum()),
                  "subjectOnlyNeverPeer": int(((w.subjectOnly >= 3) & (w.peerFound == 0)).sum()),
                  # of the points in words only the peer took, how much sits in words the subject rarely finds anywhere
                  "peerOnlyPtsSubjectRateUnder10": float(p.pts[p.pOnly & (p.rS < 0.1)].sum() / max(p.pts[p.pOnly].sum(), 1)),
                  "subjectOnlyPtsPeerRateUnder10": float(p.pts[p.sOnly & (p.rP < 0.1)].sum() / max(p.pts[p.sOnly].sum(), 1))}
    _words_figure(top_p.head(25), top_s.head(25), len(d))
    wt = w.reset_index()
    save_tsv(wt, "sh_words_all")

    # ---- over time ---------------------------------------------------------------------------
    d["t"] = (d.createdAt - d.createdAt.min()).dt.days / 30.4
    tr = {}
    for col in ("margin", "S", "open15_s", "open15_p", "n_s", "n_p"):
        m = smf.ols(f"{col} ~ t", data=d).fit(cov_type="HC1")
        tr[col] = {"slope": float(m.params.t), "lo": float(m.conf_int().loc["t", 0]), "hi": float(m.conf_int().loc["t", 1]), "p": float(m.pvalues.t)}
    m = smf.ols("margin ~ t + np.log(potential) * C(grid)", data=d).fit(cov_type="HC1")
    tr["marginControlled"] = {"slope": float(m.params.t), "lo": float(m.conf_int().loc["t", 0]), "hi": float(m.conf_int().loc["t", 1]), "p": float(m.pvalues.t)}
    r["trend"] = tr
    bys = []
    for s_, x in d.groupby("season"):
        mm = boot(x.margin)
        bys.append({"season": int(s_), "games": int(len(x)), "margin": mm[0], "lo": mm[1], "hi": mm[2], "winRate": float(x.S.mean()),
                    "open15_s": float(x.open15_s.mean()), "open15_p": float(x.open15_p.mean()), "words_s": float(x.n_s.mean()), "words_p": float(x.n_p.mean())})
    r["bySeasonTable"] = bys
    half = d.sort_values("createdAt")
    k = len(half) // 2
    r["halves"] = {nm: {"margin": boot(x.margin), "winRate": float(x.S.mean()), "first": str(x.createdAt.min())[:10], "last": str(x.createdAt.max())[:10]}
                   for nm, x in (("first", half.iloc[:k]), ("second", half.iloc[k:]))}
    _time_figure(d, bys)

    # ---- summary figure ------------------------------------------------------------------------
    _decomp_figure(r)
    _paired_figure(r)

    # ---- holdout inside the head-to-head: chronological 70/30 of the shared games ---------------
    order = d.sort_values("createdAt").index.values
    cut = int(len(order) * 0.7)
    tr_, te_ = order[:cut], order[cut:]
    r["holdoutSplit"] = {"train": int(len(tr_)), "test": int(len(te_)), "cut": str(d.loc[order[cut], "createdAt"])[:16]}

    def rec(name, fn, unit, kind="sign", note=""):
        rng = np.random.default_rng(5)
        boots = [fn(te_[rng.integers(0, len(te_), len(te_))]) for _ in range(300)]
        holdout.record(R, name, fn(tr_), fn(te_), float(np.nanstd(boots)), unit, kind, note or "head-to-head, chronological 70/30 of shared games")

    rec(f"Head-to-head margin, you minus {PEER_NAME}", lambda ix: d.loc[ix, "margin"].mean(), "points/game")
    rec(f"Head-to-head words per game, you minus {PEER_NAME}", lambda ix: (d.loc[ix, "n_s"] - d.loc[ix, "n_p"]).mean(), "words/game")
    rec(f"Head-to-head opening (first 15), you minus {PEER_NAME}", lambda ix: (d.loc[ix, "open15_s"] - d.loc[ix, "open15_p"]).mean(), "letters")
    rec(f"Head-to-head vocabulary component of the margin", lambda ix: d.loc[ix, "vocabNet"].mean(), "points/game")
    rec(f"Head-to-head execution component of the margin", lambda ix: d.loc[ix, "execNet"].mean(), "points/game")
    op = r["opening"]["regression"]

    def slope(ix):
        x = d.loc[ix]
        return float(np.polyfit(x.open15_s - x.open15_p, x.margin, 1)[0])

    rec("Head-to-head: margin per letter of opening-length difference", slope, "points/letter")
    R["sh"] = r
    R["_h2h_frame"] = d


def opening(R, d, ff, N=15):
    """Section 2.2's counterfactual on identical boards, both directions, and the paired regression."""
    pres_len = R["_pres_len"]
    pts_table = points(np.arange(0, 30)).astype(float)
    pts_table[:3] = 0
    seq = {k: ff[(ff.who == who) & (ff.pos < N)].groupby("gid").len.apply(lambda s: s.values)
           for k, who in (("s", "player"), ("p", "opponent"))}
    rows = []
    for gid in d.index:
        a, b = seq["s"].get(gid), seq["p"].get(gid)
        if a is None or b is None or len(a) < N or len(b) < N:
            continue
        counts = pres_len.get(gid, {})

        def score(lens):
            left = dict(counts)
            tot = 0.0
            for L in lens:
                L = int(L)
                while L > 3 and left.get(L, 0) <= 0:
                    L -= 1
                left[L] = left.get(L, 0) - 1
                tot += pts_table[L]
            return tot
        rows.append({"gid": gid, "subjectWithPeerOpening": score(b) - pts_table[a].sum(),
                     "peerWithSubjectOpening": score(a) - pts_table[b].sum()})
    c = pd.DataFrame(rows).set_index("gid")
    out = {"games": int(len(c)), "subjectGain": boot(c.subjectWithPeerOpening), "peerGain": boot(c.peerWithSubjectOpening)}
    # the within-player volume cost of a longer opening, each player's own pooled estimate
    own = R["s2"]["openingTest"]["all"]["nWords"]["perLetter"]
    pr = peer.results()
    other = pr["s2"]["openingTest"]["all"]["nWords"]["perLetter"] if pr else np.nan
    dd = d.join(c, how="inner")
    delta = float((dd.open15_p - dd.open15_s).mean())
    ppw_s, ppw_p = float(dd.v_s.mean()), float(dd.v_p.mean())
    out["delta"] = delta
    out["volumeCostPerLetter"] = {"subject": own, "peer": other}
    out["subjectNet"] = out["subjectGain"][0] + min(own, 0) * delta * ppw_s
    out["peerNet"] = out["peerGain"][0] + min(other, 0) * (-delta) * ppw_p if np.isfinite(other) else np.nan
    # paired regression: board fixed by construction
    dd = d.assign(dOpen=d.open15_s - d.open15_p, dN=d.n_s - d.n_p).dropna(subset=["dOpen"])
    reg = {}
    for y in ("margin", "dN", "execNet", "vocabNet", "volume", "value"):
        m = smf.ols(f"{y} ~ dOpen", data=dd).fit(cov_type="HC1")
        reg[y] = {"intercept": float(m.params.Intercept), "interceptCi": m.conf_int().loc["Intercept"].tolist(),
                  "slope": float(m.params.dOpen), "slopeCi": m.conf_int().loc["dOpen"].tolist(), "p": float(m.pvalues.dOpen),
                  "r2": float(m.rsquared), "atMeanDelta": float(m.params.dOpen * dd.dOpen.mean())}
    reg["meanDOpen"] = float(dd.dOpen.mean())
    reg["sdDOpen"] = float(dd.dOpen.std())
    reg["shareSubjectLonger"] = float((dd.dOpen > 0).mean())
    # margin when the two openings were within 0.1 letters of each other
    eq = dd[dd.dOpen.abs() <= 0.1]
    reg["equalOpenings"] = {"games": int(len(eq)), "margin": boot(eq.margin), "winRate": float(eq.S.mean()) if len(eq) else np.nan}
    out["regression"] = reg
    dd["bin"] = pd.qcut(dd.dOpen, 8, labels=False, duplicates="drop")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.5))
    t = dd.groupby("bin").agg(x=("dOpen", "median"))
    for ax, y, title, unit in ((axes[0], "margin", "Margin", "points (you minus " + PEER_NAME + ")"),
                               (axes[1], "dN", "Words found", "words (you minus " + PEER_NAME + ")")):
        tt = t.join(pd.DataFrame([boot(v.values) for _, v in dd.groupby("bin")[y]], columns=["mean", "lo", "hi"]))
        band(ax, tt.x, tt, PLAYER, "binned (eighths of games)", marker="o")
        xs = np.linspace(dd.dOpen.quantile(0.02), dd.dOpen.quantile(0.98), 50)
        ax.plot(xs, reg[y]["intercept"] + reg[y]["slope"] * xs, color=STRONG, ls="--", label="linear fit")
        ax.axhline(0, color=INK2, lw=0.8)
        ax.axvline(0, color=INK2, lw=0.8, ls=":")
        ax.set_xlabel("opening difference: your first-15 mean length minus " + PEER_NAME + "'s (letters)")
        ax.set_ylabel(unit)
        ax.set_title(f"{title} against the opening difference, same board")
    axes[0].legend(fontsize=7.5)
    note_n(axes[1], f"{len(dd):,} shared games")
    fig.tight_layout()
    save(fig, "sh_4_opening_vs_margin", dd[["dOpen", "margin", "dN"]].reset_index(), "Paired: each point set is one shared board. Margin and word-count difference against the difference in opening length.")
    return out


def save_tsv(df, name):
    df.to_csv(os.path.join(FIGS, name + ".tsv"), sep="\t", index=False, float_format="%.5g")


def _words_figure(top_p, top_s, games):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.2))
    for ax, t, color, title, col in ((axes[0], top_p, PEERC, f"{PEER_NAME} took, you never did (same boards)", "peerOnly"),
                                     (axes[1], top_s, PLAYER, f"You took, {PEER_NAME} never did (same boards)", "subjectOnly")):
        t = t.iloc[::-1]
        ax.barh(np.arange(len(t)), t[col] * t.pts / 1000, color=color)
        ax.set_yticks(np.arange(len(t)))
        ax.set_yticklabels([f"{w}  {int(k)}/{int(n)} boards, elsewhere you {rs:.0%} / them {rp:.0%}" for w, k, n, rs, rp in
                            zip(t.index, t[col], t.boards, t.rateSubjectElsewhere, t.ratePeerElsewhere)], fontsize=6.8)
        ax.set_xlabel("points over the shared games (thousands)")
        ax.set_title(title)
    fig.tight_layout()
    save(fig, "sh_5_exclusive_words", pd.concat([top_p.reset_index().assign(side="peerOnly"), top_s.reset_index().assign(side="subjectOnly")]),
         f"Words found on 3+ shared boards by one player and never by the other there. 'Elsewhere': each player's find rate for the word on their other boards.")


def _time_figure(d, bys):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    t = pd.DataFrame(bys)
    x = np.arange(len(t))
    band(axes[0], x, t[["margin", "lo", "hi"]].rename(columns={"margin": "mean"}), PLAYER, "margin", marker="o")
    axes[0].axhline(0, color=INK2, lw=0.8)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f"s{s}\n{n}" for s, n in zip(t.season, t.games)], fontsize=8)
    axes[0].set_ylabel(f"points, you minus {PEER_NAME}")
    axes[0].set_title("Head-to-head margin by season (games below)")
    axes[1].plot(x, t.open15_s, "o-", color=PLAYER, label="you")
    axes[1].plot(x, t.open15_p, "s-", color=PEERC, label=PEER_NAME)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([f"s{s}" for s in t.season])
    axes[1].set_ylabel("mean length, first 15 finds")
    axes[1].set_title("Opening length by season, shared games")
    axes[1].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "sh_6_over_time", t, "Head-to-head by season: margin (95% band over games) and each player's opening length.")


def _decomp_figure(r):
    c = r["decomposition"]
    rows = [("margin (you minus " + PEER_NAME + ")", "margin", INK2),
            ("  from volume (more words)", "volume", PLAYER), ("  from value per word (length mix)", "value", WEAK),
            ("  words the other player rarely finds (vocabulary)", "vocabNet", STRONG),
            ("  words the other player usually finds (execution)", "execNet", OPP)]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    y = np.arange(len(rows))[::-1]
    for yi, (lab, k, col) in zip(y, rows):
        m, lo, hi = c[k]
        ax.barh(yi, m, color=col, height=0.6)
        ax.errorbar(m, yi, xerr=[[m - lo], [hi - m]], fmt="none", color="black", lw=1)
        ax.text((hi + 150) if m >= 0 else (lo - 150), yi, f"{m:+,.0f}", va="center", ha="left" if m >= 0 else "right", fontsize=8)
    ax.axhline(y[0] - 0.5, color=INK2, lw=0.6)
    ax.axhline(y[2] - 0.5, color=INK2, lw=0.6, ls=":")
    ax.set_yticks(y)
    ax.set_yticklabels([lab for lab, _, _ in rows], fontsize=8)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlabel("points per game (95% CI over games)")
    ax.set_title("Two exact splits of the same margin")
    lim = max(abs(c[k][1]) for _, k, _ in rows) * 1.35 + 300
    ax.set_xlim(-lim, lim)
    save(fig, "sh_3_decomposition", pd.DataFrame([{"component": k, "mean": c[k][0], "lo": c[k][1], "hi": c[k][2]} for _, k, _ in rows]),
         "The per-game margin split two ways: volume against value per word, and vocabulary against execution (see text).")


def _paired_figure(r):
    P = r["paired"]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.4), gridspec_kw={"width_ratios": [1, 1, 1.6]})
    for ax, keys, title, fmt in ((axes[0], ["words"], "Words per game", "{:.1f}"), (axes[1], ["open10", "open15", "meanLen"], "Mean length (letters)", "{:.2f}")):
        x = np.arange(len(keys))
        ax.bar(x - 0.2, [P[k]["subject"] for k in keys], width=0.38, color=PLAYER, label="you")
        ax.bar(x + 0.2, [P[k]["peer"] for k in keys], width=0.38, color=PEERC, label=PEER_NAME)
        for xi, k in zip(x, keys):
            ax.text(xi, max(P[k]["subject"], P[k]["peer"]) * 1.01, f"diff {P[k]['diff']:+.2f}\n[{P[k]['lo']:+.2f}, {P[k]['hi']:+.2f}]", ha="center", fontsize=6.8)
        ax.set_xticks(x)
        ax.set_xticklabels({"words": ["all finds"], "open10": None}.get(keys[0]) or ["first 10", "first 15", "all finds"])
        ax.set_title(title)
        lo = min(min(P[k]["subject"], P[k]["peer"]) for k in keys)
        ax.set_ylim(lo * 0.9 if keys[0] != "words" else 0, max(max(P[k]["subject"], P[k]["peer"]) for k in keys) * 1.12)
    ks = [f"share{L}" for L in LC]
    x = np.arange(len(ks))
    axes[2].bar(x - 0.2, [100 * P[k]["subject"] for k in ks], width=0.38, color=PLAYER, label="you")
    axes[2].bar(x + 0.2, [100 * P[k]["peer"] for k in ks], width=0.38, color=PEERC, label=PEER_NAME)
    for xi, k in zip(x, ks):
        axes[2].text(xi, 100 * max(P[k]["subject"], P[k]["peer"]) + 0.8, f"{100 * P[k]['diff']:+.1f} pp", ha="center", fontsize=7)
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(["3", "4", "5", "6", "7+"])
    axes[2].set_xlabel("word length")
    axes[2].set_ylabel("% of a game's finds (mean over games)")
    axes[2].set_title("Length mix, paired")
    axes[2].legend(fontsize=7.5, loc="upper right")
    fig.tight_layout()
    save(fig, "sh_1_paired", pd.DataFrame(P).T.reset_index(names="metric"), f"Paired per shared board: you against {PEER_NAME}. Differences are you minus {PEER_NAME} with 95% bootstrap CIs over games.")

"""Report sections 6 (competitive) and 7 (session and fatigue)."""
import collections
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.proportion import proportions_ztest

import holdout
from common import FIGS, RANKED, load_wordlist
from viz import EXTRA, INK2, OPP, PLAYER, STRONG, WEAK, band, bh, boot_by, boot_mean, note_n, plt, save


def ame(model, d, col, delta=1):
    """Average marginal effect on P(win) of adding `delta` to `col`."""
    up = d.copy()
    up[col] = up[col] + delta
    return float((model.predict(up) - model.predict(d)).mean())


def auc(y, p):
    y = np.asarray(y)
    p = np.asarray(p)
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    n1 = y.sum()
    n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def section6(R, g, f, pres):
    r = {}
    d = g[g.outcome != "tie"].copy()
    d["win"] = (d.outcome == "win").astype(int)
    d["eloDiffB"] = pd.cut(d.eloDiffLoo, [-1000, -150, -75, -25, 25, 75, 150, 1000])
    d["potD"] = pd.qcut(d.potential, 10, labels=False)
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.4))
    tsv = {}
    dcur = d[d.current]
    for ax, (col, label) in zip(axes.ravel(), (("potD", "board potential decile (within all games)"), ("grid", "grid"),
                                               ("tier", "tier (v3 posterior, seasons 7-10 only)"), ("eloDiffB", "opponent Elo minus yours (recovered, leave-one-out)"),
                                               ("hourUtc", "hour of day (UTC)"), ("dow", "day of week (0 = Monday, UTC)"))):
        t = boot_by(dcur if col == "tier" else d, col, "win")
        x = np.arange(len(t))
        ax.errorbar(x, t["mean"], yerr=[t["mean"] - t.lo, t.hi - t["mean"]], fmt="o", color=PLAYER, ms=4)
        ax.axhline(0.5, color=INK2, lw=0.8, ls=":")
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in t[col]], rotation=45 if col == "eloDiffB" else 0, fontsize=7)
        ax.set_xlabel(label)
        ax.set_title(f"Win rate by {label.split(' (')[0]}")
        tsv[col] = t.astype({col: str})
    axes[0, 0].set_ylabel("win rate (ties excluded)")
    axes[1, 0].set_ylabel("win rate")
    fig.tight_layout()
    save(fig, "s6_win_rate", tsv, "Win rate by board potential, grid, tier, relative opponent rating, hour and weekday. 95% bootstrap intervals.")
    r["winByTier"] = boot_by(d[d.current], "tier", "win").set_index("tier")[["mean", "lo", "hi", "n"]].round(4).to_dict("index")
    r["winByGrid"] = boot_by(d, "grid", "win").set_index("grid")[["mean", "lo", "hi", "n"]].round(4).to_dict("index")
    r["winByEloDiff"] = boot_by(d, "eloDiffB", "win").astype({"eloDiffB": str}).set_index("eloDiffB")[["mean", "n"]].round(4).to_dict("index")
    r["winOverall"] = float(d.win.mean())

    # ---- margins ------------------------------------------------------------------------
    close = g[g.margin.abs() < 8000]
    r["margin"] = {"games": int(len(g)), "under8000": int(len(close)), "under8000Share": float(len(close) / len(g)),
                   "winRateUnder8000": float((close.outcome == "win").mean()), "medianAbs": float(g.margin.abs().median()),
                   "under2000Share": float((g.margin.abs() < 2000).mean()), "under4000Share": float((g.margin.abs() < 4000).mean())}
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.hist(g.margin / 1000, bins=np.arange(-60, 61, 2), color=PLAYER)
    ax.axvspan(-8, 8, color=STRONG, alpha=0.12, label=f"|margin| < 8,000: {len(close) / len(g):.0%} of games")
    ax.set_xlabel("your score minus opponent's (thousand points)")
    ax.set_ylabel("games")
    ax.set_title("Margin distribution")
    ax.legend(fontsize=7.5)
    note_n(ax, f"{len(g):,} games")
    save(fig, "s6_margins", pd.DataFrame({"margin": g.margin}), "Distribution of final margins.")

    # ---- points to wins: mechanically, with the opponent held fixed --------------------------------
    # Adding delta points to your score flips exactly the games you lost by less than delta
    # (and wins half the ties). This is the right conversion for "points added to my score":
    # duplicates score for both players, so nothing you find changes the opponent's score.
    # The logistic coefficient on own score is attenuated by shared board effects (richer boards
    # raise both scores), so it understates this; both are reported.
    gc = g[g.current]

    def flips(delta, gg=gc):
        m_ = gg.margin.values
        flip = ((m_ < 0) & (m_ + delta > 0)).astype(float) + 0.5 * ((m_ == 0) & (delta > 0))
        return float(flip.mean())
    r["mechanical"] = {str(dv): flips(dv) for dv in (100, 400, 800, 1400, 1800, 3000, 5000)}
    r["mechanicalPer100"] = flips(1000) / 10

    # ---- marginal value regression ---------------------------------------------------------
    d["logPot"] = np.log(d.potential)
    d["eloDiffF"] = d.eloDiffLoo.fillna(d.eloDiff).fillna(0)
    d["n7p"] = d.n7
    d["score_k"] = d.yourScore / 1000
    sets = {"train": d[d.split == "train"], "test": d[d.split == "test"], "pooled": d}
    specs = {"byLength": "win ~ n3 + n4 + n5 + n6 + n7p + logPot * C(grid) + eloDiffF",
             "prompt": "win ~ nWords + longShare + capture + logPot * C(grid) + eloDiffF",
             "points": "win ~ score_k + logPot * C(grid) + eloDiffF"}
    Ls = ["n3", "n4", "n5", "n6", "n7p"]
    r["regression"] = {}
    rng = np.random.default_rng(4)
    for name, fml in specs.items():
        res = {}
        for sname, dd in sets.items():
            m = smf.logit(fml, data=dd).fit(disp=0)
            rr = {"n": int(len(dd)), "auc": auc(dd.win, m.predict(dd)), "pseudoR2": float(m.prsquared)}
            if name == "byLength":
                boots = {L: [] for L in Ls}
                for _ in range(100):
                    bs = dd.iloc[rng.integers(0, len(dd), len(dd))].reset_index(drop=True)
                    mb = smf.logit(fml, data=bs).fit(disp=0)
                    for L in Ls:
                        boots[L].append(ame(mb, bs, L))
                for L in Ls:
                    rr[f"ame_{L}"] = ame(m, dd, L)
                    rr[f"ci_{L}"] = [float(np.percentile(boots[L], 2.5)), float(np.percentile(boots[L], 97.5))]
                    rr[f"se_{L}"] = float(np.std(boots[L]))
            if name == "points":
                rr["amePer100"] = ame(m, dd, "score_k", 0.1)
            res[sname] = rr
        r["regression"][name] = res
    rl = r["regression"]["byLength"]
    for L, lab in (("n5", "5-letter"), ("n6", "6-letter"), ("n3", "3-letter")):
        holdout.record(R, f"Marginal win probability of one extra {lab} word", rl["train"][f"ame_{L}"], rl["test"][f"ame_{L}"],
                       rl["test"][f"se_{L}"], "P(win)")
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    x = np.arange(5)
    for off, sname, color, label in ((-0.27, "pooled", OPP, "all seasons (regime-pooled)"), (0, "train", PLAYER, "seasons 7-10, train"),
                                     (0.27, "test", WEAK, "seasons 7-10, test")):
        v = rl[sname]
        ax.bar(x + off, [v[f"ame_{L}"] * 100 for L in Ls], width=0.26, color=color, label=f"{label} (n = {v['n']:,})")
        ax.errorbar(x + off, [v[f"ame_{L}"] * 100 for L in Ls],
                    yerr=[[100 * (v[f"ame_{L}"] - v[f"ci_{L}"][0]) for L in Ls], [100 * (v[f"ci_{L}"][1] - v[f"ame_{L}"]) for L in Ls]],
                    fmt="none", color=INK2, lw=1)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(["3", "4", "5", "6", "7+"])
    ax.set_xlabel("one extra word of length")
    ax.set_ylabel("change in P(win), percentage points")
    ax.set_title("What one more word is worth in wins (logistic, board and opponent held fixed)")
    ax.legend(fontsize=7)
    save(fig, "s6_marginal_value", pd.DataFrame([{"set": k, "length": L, "ame": v[f"ame_{L}"], "lo": v[f"ci_{L}"][0], "hi": v[f"ci_{L}"][1]}
                                                 for k, v in rl.items() for L in Ls]),
         "Average marginal effect on win probability of one additional word by length, with 95% bootstrap CIs.")

    # ---- repeat opponents ------------------------------------------------------------------
    d["E"] = 1 / (1 + 10 ** (d.eloDiffF / 400))
    rep = d.groupby("oppName").agg(games=("win", "size"), wins=("win", "sum"), exp=("E", "sum"),
                                   var=("E", lambda e: (e * (1 - e)).sum()), overlap=("overlap", "mean"),
                                   oppOpen10=("oppOpen10", "mean"), oppLongShare=("oppLongShare", "mean"))
    rep = rep[rep.games >= 15].copy()
    rep["z"] = (rep.wins - rep.exp) / np.sqrt(rep["var"])
    from scipy.stats import norm
    rep["p"] = 2 * norm.sf(rep.z.abs())
    rep["q"] = bh(rep.p.values)
    rep = rep.sort_values("games", ascending=False)
    r["repeat"] = {"opponents15plus": int(len(rep)), "gamesCovered": int(rep.games.sum()), "significant": int((rep.q < 0.05).sum()),
                   "zSd": float(rep.z.std()), "top": rep.head(25).reset_index().round(3).to_dict("records"),
                   "overlapCorrWithZ": float(rep.overlap.corr(rep.z))}
    top = rep.head(30).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    y = np.arange(len(top))
    diff = (top.wins - top.exp) / top.games
    se = np.sqrt(top["var"]) / top.games
    ax.errorbar(diff, y, xerr=1.96 * se, fmt="o", color=[STRONG if q < 0.05 else PLAYER for q in top.q][0], ecolor=INK2, ms=4)
    ax.scatter(diff, y, color=[STRONG if q < 0.05 else PLAYER for q in top.q], zorder=3, s=18)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{n} ({int(k)} games)" for n, k in zip(top.index, top.games)], fontsize=7.5)
    ax.set_xlabel("win rate minus Elo expectation")
    ax.set_title("Head-to-head against the 30 most frequent opponents")
    save(fig, "s6_repeat_opponents", rep.reset_index(), "Observed minus Elo-expected win rate per repeat opponent (15+ games), BH-corrected.")

    # ---- words opponents found that he missed --------------------------------------------------
    p = pres[pres.foundOpp.notna()].merge(g[["gid", "eloAtStart", "oppElo", "margin"]], on="gid")
    p["fo"] = p.foundOpp.astype(bool)
    p["oppStrength"] = 1 / (1 + 10 ** ((p.eloAtStart - p.oppElo.fillna(p.eloAtStart)) / 400))
    words = load_wordlist()
    akey = collections.Counter("".join(sorted(w)) for w in words)
    wstat = p.groupby("word").agg(len=("len", "first"), pts=("pts", "first"), present=("fo", "size"),
                                  playerFound=("foundPlayer", "sum"), oppFound=("fo", "sum"))
    m = p[p.fo & ~p.foundPlayer]
    mw = m.groupby("word").agg(times=("gid", "size"), strengthWeighted=("oppStrength", "sum"), inLosses=("margin", lambda s: (s < 0).sum()))
    mw = mw.join(wstat)
    mw["pointsTotal"] = mw.times * mw.pts
    mw["strengthWeightedPoints"] = mw.strengthWeighted * mw.pts
    mw["playerFindRate"] = mw.playerFound / mw.present
    mw["oppFindRate"] = mw.oppFound / mw.present
    # what he loses relative to the field: the opponents' find rate minus his, on the same presences
    mw["excessPoints"] = (mw.oppFindRate - mw.playerFindRate) * mw.present * mw.pts
    mw["anagramKey"] = ["".join(sorted(w)) for w in mw.index]
    mw["anagramDictSize"] = mw.anagramKey.map(akey)
    found3 = set(wstat[wstat.playerFound >= 3].index)

    def branch(w):
        L = len(w)
        for k in range(L - 1, max(2, L - 4), -1):
            for st in range(L - k + 1):
                if w[st:st + k] in found3:
                    return w[st:st + k]
        return ""
    mw["branchStem"] = [branch(w) for w in mw.index]
    mw = mw.sort_values("strengthWeightedPoints", ascending=False)
    mw.reset_index().to_csv(os.path.join(RANKED, "missed_by_opponent.tsv"), sep="\t", index=False, float_format="%.5g")
    keys = mw.groupby("anagramKey").strengthWeightedPoints.sum().sort_values(ascending=False)
    r["missedByOpp"] = {"distinctWords": int(len(mw)), "events": int(mw.times.sum()),
                        "eventsPerGame": float(mw.times.sum() / g.gid.nunique()),
                        "pointsPerGame": float(mw.pointsTotal.sum() / g.gid.nunique()),
                        "top": mw.head(30).reset_index()[["word", "times", "pts", "strengthWeightedPoints", "playerFindRate", "oppFindRate", "anagramKey", "anagramDictSize", "branchStem"]].round(4).to_dict("records"),
                        "topByFrequency": mw.sort_values("times", ascending=False).head(20).index.tolist(),
                        "topAnagramKeys": keys.head(15).round(0).to_dict(),
                        "shareOfTop100InMultiMemberAnagramSets": float((mw.head(100).anagramDictSize >= 2).mean()),
                        "shareOfTop100Branch": float((mw.head(100).branchStem != "").mean()),
                        "top12Keys": mw.head(12).anagramKey.value_counts().to_dict(),
                        "topByExcess": mw.sort_values("excessPoints", ascending=False).head(25).reset_index()[["word", "present", "pts", "playerFindRate", "oppFindRate", "excessPoints", "anagramKey", "branchStem"]].round(4).to_dict("records"),
                        "excessPerGameTotal": float(mw.excessPoints.clip(lower=0).sum() / g.gid.nunique()),
                        "netExcessPerGame": float(mw.excessPoints.sum() / g.gid.nunique()),
                        "top12KeysAERSTShare": float((mw.head(12).anagramKey == "AERST").mean())}
    top = mw.head(30).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(np.arange(len(top)), top.strengthWeightedPoints / 1000, color=[STRONG if b else PLAYER for b in top.branchStem != ""])
    ax.set_yticks(np.arange(len(top)))
    ax.set_yticklabels([f"{w}  {int(t)}x, you {pr:.0%} vs opp. {orr:.0%}" for w, t, pr, orr in zip(top.index, top.times, top.playerFindRate, top.oppFindRate)], fontsize=7)
    ax.set_xlabel("points, weighted by opponent strength (thousands)")
    ax.set_title("Words opponents took that you missed")
    ax.plot([], [], color=STRONG, lw=6, label="contains a stem you find (branch)")
    ax.plot([], [], color=PLAYER, lw=6, label="no found stem inside")
    ax.legend(fontsize=7.5, loc="lower right")
    save(fig, "s6_missed_by_opponent", mw.head(500).reset_index(), "Words the opponent found and you missed, ranked by strength-weighted points.")

    # ---- overlap against margin, normalised ------------------------------------------------------
    # Raw overlap (share of your finds the opponent also found) falls mechanically when you find
    # many more words than the opponent. Expected overlap under the null that the opponent's
    # finds are drawn by word popularity: each present word gets p = min(1, c * r_w), where r_w is
    # the word's field find rate and c scales the board so the p's sum to the opponent's word
    # count. Expected overlap = mean p over your finds. Normalised overlap = observed / expected.
    pr = pres[pres.foundOpp.notna()]
    rate = (pr.groupby("word").foundPlayer.mean() + pr.groupby("word").foundOpp.apply(lambda x: x.astype(float).mean())) / 2
    pr = pr.assign(r=pr.word.map(rate))
    tot = pr.groupby("gid").r.sum()
    c = g.set_index("gid").oppNWords / tot
    pr = pr.assign(pexp=np.minimum(1, pr.gid.map(c) * pr.r))
    exp_ov = pr[pr.foundPlayer].groupby("gid").pexp.mean()
    o = g.dropna(subset=["overlap"]).copy()
    o["expected"] = o.gid.map(exp_ov)
    o["norm"] = o.overlap / o.expected
    o["mb"] = pd.qcut(o.margin, 12, labels=False)
    t = boot_by(o, "mb", "overlap").merge(o.groupby("mb").margin.median().rename("m").reset_index(), on="mb")
    tn = boot_by(o, "mb", "norm").merge(o.groupby("mb").margin.median().rename("m").reset_index(), on="mb")
    te_ = boot_by(o, "mb", "expected")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.3))
    band(axes[0], t.m / 1000, t, PLAYER, "observed")
    band(axes[0], t.m / 1000, te_.assign(m=t.m), OPP, "expected from word counts and popularity")
    axes[0].set_xlabel("margin (thousand points)")
    axes[0].set_ylabel("share of your finds the opponent also found")
    axes[0].set_title("Raw overlap against margin")
    axes[0].legend(fontsize=7.5)
    band(axes[1], tn.m / 1000, tn, PLAYER, "observed / expected")
    axes[1].axhline(1, color=INK2, lw=0.8, ls=":")
    axes[1].set_xlabel("margin (thousand points)")
    axes[1].set_ylabel("normalised overlap")
    axes[1].set_title("After normalising for word counts")
    note_n(axes[1], f"{len(o):,} games")
    fig.tight_layout()
    save(fig, "s6_overlap", {"raw": t, "normalised": tn, "expected": te_}, "Overlap against margin, raw and normalised by the overlap expected from both word counts and word popularity.")
    r["overlap"] = {"mean": float(o.overlap.mean()), "expectedMean": float(o.expected.mean()), "normMean": float(o.norm.mean()),
                    "corrRawWithMargin": float(o.overlap.corr(o.margin)), "corrNormWithMargin": float(o.norm.corr(o.margin)),
                    "corrNormWithAbsMargin": float(o.norm.corr(o.margin.abs())),
                    "rawByMarginBin": t["mean"].round(4).tolist(), "normByMarginBin": tn["mean"].round(4).tolist(),
                    "corrWithPotential": float(o.overlap.corr(np.log(o.potential)))}
    R["s6"] = r


def section7(R, g, f):
    r = {}
    g = g.copy()
    for col in ("yourScore", "nWords", "longShare", "open10"):
        d = g[[col, "potential", "grid"]].dropna()
        m = smf.ols(f"{col} ~ np.log(potential) * C(grid)", data=d).fit()
        g[col + "_res"] = np.nan
        g.loc[d.index, col + "_res"] = m.resid
    sl = g.groupby("session").agg(games=("gid", "size"), start=("createdAt", "min"), end=("completedAt", "max"))
    sl["minutes"] = (sl.end - sl.start).dt.total_seconds() / 60
    r["sessions"] = {"count": int(len(sl)), "gamesMedian": float(sl.games.median()), "gamesMean": float(sl.games.mean()),
                     "gamesP90": float(sl.games.quantile(0.9)), "minutesMedian": float(sl.minutes.median()),
                     "shareOfGamesInSessions10plus": float(g[g.sessionLen >= 10].shape[0] / len(g)),
                     "hist": np.bincount(np.minimum(sl.games, 30)).tolist()}
    r["wallSeconds"] = {"median": float(g.wallSeconds.median()), "p10": float(g.wallSeconds.quantile(0.1)), "p90": float(g.wallSeconds.quantile(0.9))}
    g["posB"] = np.minimum(g.sessionPos, 12)
    fig, axes = plt.subplots(1, 4, figsize=(13.5, 3.2))
    tsv = {}
    for ax, (col, title) in zip(axes, (("yourScore_res", "score (residual, points)"), ("nWords_res", "words (residual)"),
                                       ("longShare_res", "long share (residual)"), ("S", "win rate"))):
        t = boot_by(g, "posB", col)
        band(ax, t.posB, t, PLAYER, col, marker="o")
        ax.axhline(0 if col != "S" else 0.5, color=INK2, lw=0.8, ls=":")
        ax.set_xlabel("game number within session (12 = 12+)")
        ax.set_title(title)
        tsv[col] = t
    note_n(axes[0], f"{len(sl):,} sessions")
    fig.tight_layout()
    save(fig, "s7_session_position", tsv, "Performance by position within a session (new session after a 20-minute gap), board-controlled.")
    within = g[g.sessionLen >= 5]
    m = smf.ols("yourScore_res ~ sessionPos", data=within).fit(cov_type="cluster", cov_kwds={"groups": within.session})
    wl = within.dropna(subset=["eloDiffLoo"])
    m2 = smf.ols("S ~ sessionPos + eloDiffLoo", data=wl).fit(cov_type="cluster", cov_kwds={"groups": wl.session})
    r["fatigue"] = {"scorePerGame": float(m.params.sessionPos), "ci": m.conf_int().loc["sessionPos"].tolist(), "p": float(m.pvalues.sessionPos),
                    "winPerGame": float(m2.params.sessionPos), "winCi": m2.conf_int().loc["sessionPos"].tolist(),
                    "game1": boot_mean(g[g.sessionPos == 1].yourScore_res.values)[:3],
                    "game8plus": boot_mean(g[g.sessionPos >= 8].yourScore_res.values)[:3]}
    holdout.per_game(R, "Score residual, games 8+ of a session minus game 1 (warm-up)", g,
                     g.set_index("gid").yourScore_res.where(g.set_index("gid").sessionPos >= 8).fillna(0)
                     - g.set_index("gid").yourScore_res.where(g.set_index("gid").sessionPos == 1).fillna(0),
                     pd.Series(1.0, index=g.gid), unit="points", note="per-game contrast; sign test")

    # ---- fatigue inside long sessions: 20+ games, where an hour has actually elapsed ----------------
    lg = g[g.sessionLen >= 20].copy()
    lg["elapsedMin"] = (lg.createdAt - lg.groupby("session").createdAt.transform("min")).dt.total_seconds() / 60
    lg["posB"] = pd.cut(lg.sessionPos, [0, 5, 10, 20, 30, 40, 1000], labels=["1-5", "6-10", "11-20", "21-30", "31-40", "41+"])
    ml = smf.ols("yourScore_res ~ sessionPos", data=lg[lg.sessionPos > 5]).fit(cov_type="cluster", cov_kwds={"groups": lg[lg.sessionPos > 5].session})
    mw = smf.ols("S ~ sessionPos + eloDiffLoo", data=lg[lg.sessionPos > 5].dropna(subset=["eloDiffLoo"])).fit(
        cov_type="cluster", cov_kwds={"groups": lg[lg.sessionPos > 5].dropna(subset=["eloDiffLoo"]).session})
    me = smf.ols("yourScore_res ~ elapsedMin", data=lg[lg.sessionPos > 5]).fit(cov_type="cluster", cov_kwds={"groups": lg[lg.sessionPos > 5].session})
    tb = boot_by(lg, "posB", "yourScore_res")
    tw = boot_by(lg, "posB", "S")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.2))
    for ax, t, title, ylab in ((axes[0], tb, "Score in long sessions (20+ games)", "score residual (points)"),
                               (axes[1], tw, "Win rate in long sessions", "win rate")):
        ax.errorbar(np.arange(len(t)), t["mean"], yerr=[t["mean"] - t.lo, t.hi - t["mean"]], fmt="o-", color=PLAYER)
        ax.set_xticks(np.arange(len(t)))
        ax.set_xticklabels([f"{k}\nn={n}" for k, n in zip(t.posB, t.n)], fontsize=7.5)
        ax.set_xlabel("game number within the session")
        ax.set_title(title)
        ax.set_ylabel(ylab)
    axes[0].axhline(0, color=INK2, lw=0.8, ls=":")
    axes[1].axhline(0.5, color=INK2, lw=0.8, ls=":")
    fig.tight_layout()
    save(fig, "s7_long_sessions", {"score": tb.astype({"posB": str}), "win": tw.astype({"posB": str})},
         "Sessions of 20+ games only: board-controlled score and win rate by position.")
    r["longSessions"] = {"sessions": int(lg.session.nunique()), "games": int(len(lg)),
                         "medianMinutes": float(lg.groupby("session").elapsedMin.max().median()),
                         "scorePerGameAfter5": float(ml.params.sessionPos), "ci": ml.conf_int().loc["sessionPos"].tolist(), "p": float(ml.pvalues.sessionPos),
                         "scorePerHour": float(me.params.elapsedMin * 60), "perHourCi": (me.conf_int().loc["elapsedMin"] * 60).tolist(),
                         "winPerGameAfter5": float(mw.params.sessionPos), "winCi": mw.conf_int().loc["sessionPos"].tolist(),
                         "byPosition": tb.astype({"posB": str}).set_index("posB")[["mean", "lo", "hi", "n"]].round(1).to_dict("index"),
                         "winByPosition": tw.astype({"posB": str}).set_index("posB")[["mean", "n"]].round(4).to_dict("index")}
    # detectable effect: per-hour slope the test could have seen
    r["longSessions"]["mdePerHour"] = float(2.8 * (me.bse.elapsedMin * 60))

    # time of day, weekday
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.2))
    tsv = {}
    for ax, col, label in ((axes[0], "hourUtc", "hour of day (UTC)"), (axes[1], "dow", "day of week (0 = Monday)")):
        t = boot_by(g, col, "yourScore_res")
        ax.errorbar(t[col], t["mean"], yerr=[t["mean"] - t.lo, t.hi - t["mean"]], fmt="o", color=PLAYER, ms=4)
        ax.axhline(0, color=INK2, lw=0.8, ls=":")
        ax.set_xlabel(label)
        ax.set_ylabel("score residual (points)")
        tsv[col] = t
    axes[0].set_title("Score by hour (board-controlled)")
    axes[1].set_title("Score by weekday (board-controlled)")
    fig.tight_layout()
    save(fig, "s7_time_of_day", tsv, "Board-controlled score by UTC hour and weekday.")
    hr = boot_by(g, "hourUtc", "yourScore_res")
    r["hour"] = {"best": hr.sort_values("mean").iloc[-1][["hourUtc", "mean", "n"]].to_dict(), "worst": hr.sort_values("mean").iloc[0][["hourUtc", "mean", "n"]].to_dict(),
                 "gamesByHour": g.hourUtc.value_counts().sort_index().to_dict()}
    mh = smf.ols("yourScore_res ~ C(hourUtc)", data=g).fit()
    r["hour"]["anovaP"] = float(mh.f_pvalue)
    md = smf.ols("yourScore_res ~ C(dow)", data=g).fit()
    r["dowAnovaP"] = float(md.f_pvalue)

    # gap before a game against the opening
    g["gapB"] = pd.cut(g.gapBeforeMin, [-1e9, 1, 3, 20, 360, 1e9], labels=["<1 min", "1-3 min", "3-20 min", "20 min-6 h", ">6 h"])
    t1 = boot_by(g.dropna(subset=["gapB"]), "gapB", "open10_res")
    t2 = boot_by(g.dropna(subset=["gapB"]), "gapB", "yourScore_res")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.2))
    for ax, t, title, ylabel in ((axes[0], t1, "Opening length after a gap", "mean length of finds 1-10 (residual)"),
                                 (axes[1], t2, "Score after a gap", "score residual (points)")):
        ax.errorbar(np.arange(len(t)), t["mean"], yerr=[t["mean"] - t.lo, t.hi - t["mean"]], fmt="o", color=PLAYER)
        ax.set_xticks(np.arange(len(t)))
        ax.set_xticklabels([f"{k}\nn={n}" for k, n in zip(t.gapB, t.n)], fontsize=7.5)
        ax.axhline(0, color=INK2, lw=0.8, ls=":")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
    fig.tight_layout()
    save(fig, "s7_gap_before", {"open10": t1.astype({"gapB": str}), "score": t2.astype({"gapB": str})}, "Opening length and score by time since the previous game ended.")
    r["gap"] = {"open10": t1.astype({"gapB": str}).set_index("gapB")[["mean", "lo", "hi", "n"]].round(4).to_dict("index"),
                "score": t2.astype({"gapB": str}).set_index("gapB")[["mean", "lo", "hi", "n"]].round(1).to_dict("index")}

    # wentFirst: selection or readiness?
    d = g[g.outcome != "tie"].copy()
    d["win"] = (d.outcome == "win").astype(int)
    a1, a0 = d[d.wentFirst], d[~d.wentFirst]
    z, pz = proportions_ztest([a1.win.sum(), a0.win.sum()], [len(a1), len(a0)])
    wf = {"sent": {"n": int(len(a1)), "winRate": float(a1.win.mean()), "score": float(a1.yourScore.mean()), "oppScore": float(a1.oppScore.mean()),
                   "eloDiff": float(a1.eloDiffLoo.mean()), "open10": float(a1.open10.mean())},
          "accepted": {"n": int(len(a0)), "winRate": float(a0.win.mean()), "score": float(a0.yourScore.mean()), "oppScore": float(a0.oppScore.mean()),
                       "eloDiff": float(a0.eloDiffLoo.mean()), "open10": float(a0.open10.mean())},
          "winZ": float(z), "winP": float(pz)}
    for name, fml in (("eloDiff", "eloDiffLoo ~ wentFirst"), ("open10", "open10 ~ wentFirst + eloDiffLoo + np.log(potential) * C(grid)"),
                      ("yourScore", "yourScore ~ wentFirst + np.log(potential) * C(grid)"),
                      ("oppScore", "oppScore ~ wentFirst + np.log(potential) * C(grid)"),
                      ("win", "win ~ wentFirst + eloDiffLoo + np.log(potential) * C(grid)")):
        dd = d.dropna(subset=["eloDiffLoo", "open10"])
        mm = smf.ols(fml, data=dd).fit(cov_type="HC1")
        k = "wentFirst[T.True]"
        wf[f"effect_{name}"] = {"est": float(mm.params[k]), "ci": mm.conf_int().loc[k].tolist(), "p": float(mm.pvalues[k])}
    wf["part2"] = {"sentWin": float(d[(d.part == 2) & d.wentFirst].win.mean()), "acceptedWin": float(d[(d.part == 2) & ~d.wentFirst].win.mean()),
                   "n": [int(((d.part == 2) & d.wentFirst).sum()), int(((d.part == 2) & ~d.wentFirst).sum())]}
    wf["bySeason"] = d.groupby(["season", "wentFirst"]).win.mean().unstack().round(4).to_dict("index")
    r["wentFirst"] = wf
    def wf_gap(gids):
        x = d[d.gid.isin(set(gids))]
        return x[x.wentFirst].win.mean() - x[~x.wentFirst].win.mean()
    holdout.by_fn(R, "Win-rate gap, sent minus accepted challenges", g, wf_gap, unit="win rate",
                  note=f"merged-set z = {z:.2f}, p = {pz:.3f}")
    R["s7"] = r

"""Report sections 0 (verification) and 1 (time series)."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import kruskal, spearmanr

from common import points
from viz import INK2, OPP, PLAYER, STRONG, WEAK, EXTRA, band, boot_by, boot_mean, month_break, note_n, plt, regime_line, save


def has_path(board, side, word):
    n = side * side
    nbr = [[j for j in range(n) if j != i and abs(j // side - i // side) <= 1 and abs(j % side - i % side) <= 1]
           for i in range(n)]

    def dfs(i, k, used):
        if k == len(word):
            return True
        for j in nbr[i]:
            if not used >> j & 1 and board[j] == word[k] and dfs(j, k + 1, used | 1 << j):
                return True
        return False

    return any(board[i] == word[0] and dfs(i, 1, 1 << i) for i in range(n))


def transforms(letters, side):
    grid = np.array(list(letters)).reshape(side, side)
    out = {}
    for k in range(4):
        r = np.rot90(grid, k)
        out[f"rot{90 * k}"] = "".join(r.ravel())
        out[f"rot{90 * k}+flip"] = "".join(np.fliplr(r).ravel())
    out["columnMajor"] = "".join(grid.T.ravel())
    # Non-dihedral controls. Every dihedral image preserves 8-way adjacency, so it solves
    # exactly the same words; only a layout that breaks adjacency can fail the test.
    snake = grid.copy()
    snake[1::2] = snake[1::2, ::-1]
    out["snake"] = "".join(snake.ravel())
    perm = np.random.default_rng(len(letters)).permutation(side * side)
    out["randomPermutation"] = "".join(np.array(list(letters))[perm])
    return out


def section0(R, g, f, pres):
    r = {}
    pl = f[f.who == "player"]
    op = f[f.who == "opponent"]
    r["playerFinds"] = int(len(pl))
    r["playerUnsolvable"] = int((pl.nPaths == 0).sum())
    r["oppFinds"] = int(len(op))
    r["oppUnsolvable"] = int((op.nPaths == 0).sum())
    bad = op[op.nPaths == 0]
    r["oppUnsolvableGames"] = sorted(bad.gid.unique().tolist())
    # which board does each off-board opponent list belong to?
    gg = g.set_index("gid")
    r["badLists"] = []
    for gid in r["oppUnsolvableGames"]:
        words = set(op[op.gid == gid].word)
        hit = pres[pres.word.isin(words)].groupby("gid").word.nunique().sort_values(ascending=False)
        r["badLists"].append({"gid": int(gid), "opponent": gg.loc[gid, "oppName"], "when": str(gg.loc[gid, "createdAt"]),
                              "offBoard": int((bad.gid == gid).sum()), "words": len(words),
                              "bestMatchGid": int(hit.index[0]), "bestMatchPresent": int(hit.iloc[0]),
                              "bestMatchWhen": str(gg.loc[hit.index[0], "createdAt"])})

    # Power check: solve 300 boards' player finds under every dihedral transform, column-major,
    # and two adjacency-breaking layouts. Only the last two can fail (see transforms()).
    sample = g.sample(300, random_state=1)
    words_by = pl.groupby("gid").word.apply(list)
    rates = {}
    for row in sample.itertuples():
        for name, b in transforms(row.letters, row.side).items():
            ws = words_by.get(row.gid, [])
            ok = sum(has_path(b, row.side, w) for w in ws)
            a = rates.setdefault(name, [0, 0])
            a[0] += ok
            a[1] += len(ws)
    r["orientationSolvable"] = {k: v[0] / v[1] for k, v in rates.items()}

    tab = pl.groupby("gid").pts.sum().reindex(g.gid).fillna(0).values
    r["scoreMatch"] = int((tab == g.yourScore.values).sum())
    tabo = f[f.who == "opponent"].groupby("gid").pts.sum().reindex(g.gid).fillna(0).values
    r["oppScoreMatch"] = int((tabo == g.oppScore.values).sum())
    r["games"] = int(len(g))

    # find order
    def pair_rate(x, key):
        v = x[key].values
        return (v[1:] >= v[:-1]).mean() if len(v) > 1 else np.nan

    ordered = pl.sort_values(["gid", "pos"])
    alpha = ordered.groupby("gid").word.apply(lambda s: np.mean([a <= b for a, b in zip(s.values[:-1], s.values[1:])]))
    lenrate = ordered.groupby("gid").len.apply(lambda s: np.mean(s.values[1:] >= s.values[:-1]))
    r["alphaPairRate"] = float(alpha.mean())
    r["alphaSortedGames"] = int((alpha == 1).sum())
    r["lenNondecreasingPairRate"] = float(lenrate.mean())
    r["lenSortedGames"] = int((lenrate == 1).sum())
    rho = ordered.groupby("gid").apply(lambda x: spearmanr(x.pos, x.startCellMean).statistic if len(x) > 5 else np.nan,
                                       include_groups=False)
    r["startCellSpearmanMean"] = float(rho.mean())
    r["startCellSpearmanAbsGt03"] = float((rho.abs() > 0.3).mean())
    r["startCellSpearmanPooled"] = float(spearmanr(ordered.relPos, ordered.startCellMean).statistic)
    # positive evidence of chronology: adjacent finds share a stem far more than shuffled order does
    rng = np.random.default_rng(3)
    sh = []
    for gid, x in ordered.groupby("gid"):
        w = x.word.values.copy()
        rng.shuffle(w)
        tri = [{s[i:i + 3] for i in range(len(s) - 2)} for s in w]
        sh.extend(not tri[i].isdisjoint(tri[i - 1]) for i in range(1, len(tri)))
    r["adjacentStemShareObserved"] = float(ordered[ordered.pos > 0].cont1.mean())
    r["adjacentStemShareShuffled"] = float(np.mean(sh))
    lens = boot_by(ordered.assign(dec=ordered.decile), "dec", "len")
    r["lenByDecileMonotone"] = bool(np.all(np.diff(lens["mean"].values) >= -0.01))
    r["wordsFoundCountMatch"] = int((pl.groupby("gid").size().reindex(g.gid).fillna(0).values == g.wordsFoundCount.values).sum())
    r["ties"] = int((g.yourScore == g.oppScore).sum())
    r["didWinNull"] = int(g.didWin.isna().sum())
    r["didWinNullAndTie"] = int((g.didWin.isna() & (g.yourScore == g.oppScore)).sum())
    r["winConsistent"] = int(((g.didWin == True) == (g.yourScore > g.oppScore))[g.didWin.notna()].sum())  # noqa: E712
    r["decided"] = int(g.didWin.notna().sum())
    R["s0"] = r


def controlled(g, col):
    """Residualise against board potential and grid; add back the mean.

    A player's own score cannot depend on the opponent (duplicates score for both, spec
    2.1), so own-performance series are controlled for the board only. Win rate is
    controlled for the board and the opponent's rating relative to the player's.
    """
    rhs = "np.log(potential) * C(grid)" + (" + eloDiffLoo" if col == "S" else "")
    d = g[[col, "potential", "grid"] + (["eloDiffLoo"] if col == "S" else [])].dropna()
    m = smf.ols(f"{col} ~ {rhs}", data=d).fit()
    out = pd.Series(np.nan, index=g.index)
    out[d.index] = m.resid + d[col].mean()
    return out, m


def section1(R, g, f):
    r = {}
    g = g.copy()
    g["seasonL"] = g.season.astype(int)
    pl = f[f.who == "player"].merge(g[["gid", "season", "month", "createdAt"]], on="gid")
    # the prompt's quartile claim, recomputed on the merged set
    q = g.groupby("timeQuartile").agg(score=("yourScore", "mean"), elo=("eloAtStart", "mean"),
                                      potential=("potential", "mean"), oppElo=("oppElo", "mean"),
                                      first=("createdAt", "min"), last=("createdAt", "max"), n=("gid", "size"))
    r["quartiles"] = q.assign(first=q["first"].astype(str), last=q["last"].astype(str)).reset_index().to_dict("records")
    q2 = g[g.part == 2].copy()
    q2["tq"] = pd.qcut(q2.createdAt.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
    r["quartilesPart2"] = q2.groupby("tq").agg(score=("yourScore", "mean"), elo=("eloAtStart", "mean")).reset_index().to_dict("records")

    models = {}
    for col in ("yourScore", "nWords", "capture", "S", "longShare", "oppScore"):
        g[col + "_ctl"], models[col] = controlled(g, col)
    r["controlModels"] = {k: {"r2": m.rsquared, "coef": {n: float(v) for n, v in m.params.items()}} for k, m in models.items()}

    # headline series, raw vs controlled, by season and by month
    series = [("yourScore", "Your score (points)"), ("oppScore", "Opponent score (points)"),
              ("nWords", "Your words per game"), ("S", "Win rate (ties = 0.5)")]
    for grp, label in (("seasonL", "season"), ("month", "month")):
        fig, axes = plt.subplots(2, 2, figsize=(11, 6.4))
        tsv = {}
        for ax, (col, title) in zip(axes.ravel(), series):
            raw = boot_by(g, grp, col)
            ctl = boot_by(g, grp, col + "_ctl")
            x = np.arange(len(raw))
            band(ax, x, raw, PLAYER, "raw", marker="o")
            band(ax, x, ctl, STRONG, "controlled (board potential x grid; win rate also relative opp. Elo)", ls="--", marker="s")
            ax.set_xticks(x)
            ax.set_xticklabels([f"{k}\n{n:,}" for k, n in zip(raw[grp], raw.n)], rotation=0, fontsize=6.5 if grp == "month" else 8)
            ax.set_title(title)
            ax.set_xlabel(f"{label} (games below)")
            if grp == "month":
                regime_line(ax, month_break(raw[grp]), label=(col == "yourScore"))
            else:
                regime_line(ax, float(np.searchsorted(raw[grp].values, 7)) - 0.5, label=(col == "yourScore"))
            tsv[col] = raw.assign(kind="raw").rename(columns={grp: "bucket"})
            tsv[col + "_ctl"] = ctl.assign(kind="controlled").rename(columns={grp: "bucket"})
        axes[0, 0].legend(loc="upper left")
        ns = g.groupby(grp).size()
        note_n(axes[1, 1], "n per " + label + ": " + ", ".join(f"{k}:{v}" for k, v in ns.items()) if grp == "seasonL" else "")
        fig.tight_layout()
        save(fig, f"s1_headline_by_{label}", tsv, f"Headline series by {label}, raw and controlled. 95% bootstrap bands; n per bucket in TSV.")

    # Elo and board potential / opponent strength by month (the confound, plotted)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4))
    tsv = {}
    for ax, (col, title, color) in zip(axes, (("eloAtStart", "Your Elo at game start", PLAYER),
                                               ("oppElo", "Recovered opponent Elo", STRONG),
                                               ("potential", "Board potential (points)", WEAK))):
        t = boot_by(g, "month", col)
        x = np.arange(len(t))
        band(ax, x, t, color, col, marker="o")
        ax.set_xticks(x)
        ax.set_xticklabels(t["month"], rotation=45, fontsize=7.5)
        ax.set_title(title)
        regime_line(ax, month_break(t["month"]), label=(col == "eloAtStart"))
        tsv[col] = t
    fig.tight_layout()
    save(fig, "s1_confounds_by_month", tsv, "Your Elo, recovered opponent Elo and board potential by month (95% bands).")

    # length mix stacked area by month
    pl["lc"] = np.minimum(pl.len, 7)
    mix = pl.groupby(["month", "lc"]).size().unstack(fill_value=0)
    share = mix.div(mix.sum(axis=1), axis=0)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    cols = [PLAYER, STRONG, WEAK, EXTRA[0], EXTRA[1]]
    ax.stackplot(np.arange(len(share)), share.T.values, labels=["3", "4", "5", "6", "7+"], colors=cols, edgecolor="white", linewidth=1)
    ax.set_xticks(np.arange(len(share)))
    ax.set_xticklabels(share.index, rotation=45, fontsize=8)
    ax.set_ylabel("share of finds")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", bbox_to_anchor=(1, 1), title="length")
    ax.set_title("Length mix of finds by month")
    regime_line(ax, month_break(share.index))
    note_n(ax, f"finds per month {int(mix.sum(axis=1).min()):,}-{int(mix.sum(axis=1).max()):,}")
    save(fig, "s1_length_mix_by_month", share.reset_index().merge(mix.sum(axis=1).rename("finds").reset_index()),
         "Share of your finds by length class, per month.")
    r["lengthMixBySeason"] = pl.groupby("season").lc.value_counts(normalize=True).unstack().round(4).to_dict("index")

    # vocabulary: cumulative distinct words and new-word rate
    pl = pl.sort_values(["createdAt", "pos"])
    pl["firstEver"] = ~pl.word.duplicated()
    g2 = pl.groupby("gid").agg(newWords=("firstEver", "sum"), finds=("word", "size")).reset_index().merge(g[["gid", "month", "seasonL", "createdAt"]], on="gid")
    g2["newRate"] = g2.newWords / g2.finds
    g2 = g2.sort_values("createdAt")
    g2["cumDistinct"] = g2.newWords.cumsum()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    axes[0].plot(np.arange(len(g2)), g2.cumDistinct, color=PLAYER)
    axes[0].set_xlabel("game number (chronological)")
    axes[0].set_ylabel("distinct words ever found")
    axes[0].set_title("Cumulative distinct vocabulary")
    regime_line(axes[0], float(np.argmax(g2.seasonL.values >= 7)))
    t = boot_by(g2, "month", "newRate")
    x = np.arange(len(t))
    band(axes[1], x, t, PLAYER, "new-word rate", marker="o")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(t["month"], rotation=45, fontsize=8)
    axes[1].set_ylabel("share of finds never found before")
    axes[1].set_title("New-word rate by month")
    regime_line(axes[1], month_break(t["month"]), label=False)
    fig.tight_layout()
    save(fig, "s1_vocabulary", {"cumulative": g2[["gid", "createdAt", "cumDistinct"]], "newRate": t},
         "Cumulative distinct words found, and the monthly share of finds that were first-ever finds.")
    r["distinctWordsEver"] = int(g2.cumDistinct.iloc[-1])
    r["newRateByMonth"] = t.set_index("month")["mean"].round(4).to_dict()
    r["wordsPerGameMean"] = float(g.nWords.mean())

    # season comparability: do board potential and opponent strength differ by season?
    big = g[g.season.isin(g.season.value_counts()[lambda s: s >= 300].index)]
    r["seasonKW"] = {
        col: {"H": float(kruskal(*[x[col].dropna() for _, x in big.groupby("season")]).statistic),
              "p": float(kruskal(*[x[col].dropna() for _, x in big.groupby("season")]).pvalue)}
        for col in ("potential", "oppElo", "nPresent")
    }
    r["seasonTable"] = g.groupby("season").agg(n=("gid", "size"), share4x4=("side", lambda s: (s == 4).mean()),
                                               potential4x4=("potential", lambda s: s[g.loc[s.index, "side"] == 4].median()),
                                               oppElo=("oppElo", "median"), elo=("eloAtStart", "median"),
                                               score=("yourScore", "mean"), score_ctl=("yourScore_ctl", "mean"),
                                               oppScore_ctl=("oppScore_ctl", "mean"), nWords_ctl=("nWords_ctl", "mean"),
                                               winRate=("S", "mean"), first=("createdAt", "min")).assign(
        first=lambda d: d["first"].dt.strftime("%Y-%m-%d")).reset_index().to_dict("records")
    # trend tests: slope of raw and controlled score per 1000 games (chronological)
    g["t"] = (g.createdAt - g.createdAt.min()).dt.days / 30.4
    for col in ("yourScore", "yourScore_ctl", "oppScore", "oppScore_ctl", "nWords", "nWords_ctl", "capture_ctl", "S", "S_ctl",
                "longShare", "longShare_ctl", "eloAtStart"):
        m = smf.ols(f"{col} ~ t", data=g).fit(cov_type="HC1")
        r.setdefault("trendPerMonth", {})[col] = {"slope": float(m.params["t"]), "lo": float(m.conf_int().loc["t", 0]),
                                                  "hi": float(m.conf_int().loc["t", 1]), "p": float(m.pvalues["t"])}
    R["s1"] = r
    return g

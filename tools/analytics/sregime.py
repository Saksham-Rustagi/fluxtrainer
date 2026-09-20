"""Season regimes on the pooled boards of both exports (report section 5.4).

Each export sees only the seasons its player played. Pooled and deduplicated on the
board letters, the two exports fill seasons one of them barely covers. Per season and
grid: board count, grid split, median potential, longest word present, and the letter
marginal's distance from ruleset v3 against the distance a same-size sample drawn from
v3 itself would show (the noise floor). Descriptive only: no analysis of play uses these
seasons, and board-generation findings elsewhere stay on seasons 7-10.
"""
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from common import PLAYER, PLAYERS, load
from s5 import SPEC, marginal, mixture, sim
from viz import INK2, OPP, PEER, PLAYER as BLUE, STRONG, plt, regime_line, save

COLS = ["letters", "side", "season", "createdAt", "potential", "potentialFlux", "longestPresent"]


def pooled():
    parts = []
    for p in PLAYERS:
        g = load("games.parquet", p, columns=COLS)
        g["src"] = p
        parts.append(g)
    g = pd.concat(parts, ignore_index=True).sort_values("createdAt")
    src = g.groupby("letters").src.agg(lambda s: "both" if s.nunique() > 1 else s.iloc[0])
    g = g.drop_duplicates("letters").drop(columns="src").merge(src.rename("src"), left_on="letters", right_index=True)
    g["grid"] = g.side.map({4: "4x4", 5: "5x5"})
    return g


def section(R):
    g = pooled()
    s3 = sim("sim_v3")
    ref = {gr: marginal(mixture(s3, gr, SPEC, 30000).letters) for gr in ("4x4", "5x5")}
    pools = {gr: s3[s3.side == gr].letters.values for gr in ("4x4", "5x5")}
    rng = np.random.default_rng(17)

    def tv(ls, gr):
        return float(0.5 * np.abs(marginal(ls) - ref[gr]).sum())

    def noise95(n, gr, reps=200):
        pool = pools[gr]
        return float(np.percentile([tv(pool[rng.integers(0, len(pool), n)], gr) for _ in range(reps)], 95))

    rows = []
    for (season, gr), x in g.groupby(["season", "grid"]):
        n = len(x)
        rows.append({"season": int(season), "grid": gr, "boards": n,
                     **{f"from_{p}": int((x.src == p).sum()) for p in list(PLAYERS) + ["both"]},
                     "first": x.createdAt.min().strftime("%Y-%m-%d"), "last": x.createdAt.max().strftime("%Y-%m-%d"),
                     "medianPotential": float(x.potential.median()), "medianPotentialFlux": float(x.potentialFlux.median()),
                     "longestP10": float(x.longestPresent.quantile(0.1)), "longestP90": float(x.longestPresent.quantile(0.9)),
                     "longestMean": float(x.longestPresent.mean()),
                     "tvV3": tv(x.letters.values, gr) if n >= 5 else np.nan,
                     "noise95": noise95(n, gr) if n >= 5 else np.nan})
    t = pd.DataFrame(rows)
    t["fitsV3"] = t.tvV3 <= t.noise95
    split = g.groupby("season").agg(boards=("letters", "size"), share4x4=("side", lambda s: (s == 4).mean()))

    # the seasons the single-player tables could not characterise, against the regimes either side
    cur = g[g.season >= 7]
    old = g[g.season.isin([2, 3])]
    tests = {}
    for season in sorted(g.season.unique()):
        for gr in ("4x4", "5x5"):
            x = g[(g.season == season) & (g.grid == gr)].potential
            if len(x) < 5:
                continue
            c = cur[(cur.grid == gr) & (cur.season != season)].potential
            o = old[(old.grid == gr) & (old.season != season)].potential
            tests[f"{season}_{gr}"] = {"n": int(len(x)), "median": float(x.median()),
                                       "vsCurrentP": float(mannwhitneyu(x, c).pvalue), "vsSeasons2to3P": float(mannwhitneyu(x, o).pvalue),
                                       "shiftVsCurrent": float(x.median() / c.median() - 1), "shiftVsSeasons2to3": float(x.median() / o.median() - 1)}

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    for gr, color, mk in (("4x4", BLUE, "o"), ("5x5", STRONG, "s")):
        y = t[t.grid == gr].sort_values("season")
        axes[0].plot(y.season, y.medianPotential / 1000, marker=mk, color=color, label=gr)
        for s_, v, n in zip(y.season, y.medianPotential / 1000, y.boards):
            axes[0].annotate(f"{n:,}", (s_, v), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=6.5, color=INK2)
        ok = y[y.boards >= 5]
        axes[1].plot(ok.season, ok.tvV3 / ok.noise95, marker=mk, color=color, label=gr)
    axes[0].set_title("Median board potential by season (boards labelled)")
    axes[0].set_xlabel("season")
    axes[0].set_ylabel("thousand points (CSW21)")
    axes[0].legend(fontsize=7.5)
    axes[1].axhline(1, color=INK2, lw=1, ls="--")
    axes[1].set_title("Letter marginal vs ruleset v3 (1 = noise floor)")
    axes[1].set_xlabel("season")
    axes[1].set_ylabel("TV distance / 95th pct. of v3 self-TV")
    axes[1].legend(fontsize=7.5, loc="center right")
    for ax in axes[:2]:
        regime_line(ax, 6.5, label=ax is axes[1])
        ax.set_xticks(sorted(g.season.unique()))
    seasons = sorted(g.season.unique())
    bottom = np.zeros(len(seasons))
    for p in [PLAYER, next(k for k in PLAYERS if k != PLAYER), "both"]:
        color = BLUE if p == PLAYER else OPP if p == "both" else PEER
        v = np.array([int(((g.season == s_) & (g.src == p)).sum()) for s_ in seasons])
        axes[2].bar(seasons, v, bottom=bottom, color=color, label="in both exports" if p == "both" else f"{PLAYERS[p]} only")
        bottom += v
    axes[2].set_yscale("log")
    axes[2].set_title("Where each season's boards come from")
    axes[2].set_xlabel("season")
    axes[2].set_ylabel("boards (log)")
    axes[2].set_xticks(seasons)
    axes[2].legend(fontsize=7)
    fig.tight_layout()
    save(fig, "s5_4_regimes_pooled", t, "Season regimes on the pooled, deduplicated boards of both exports. Seasons 7-10 remain the only regime used for generation analysis.")
    R["sr"] = {"boards": int(len(g)), "bySource": g.src.value_counts().to_dict(), "table": t.to_dict("records"),
               "split": split.reset_index().to_dict("records"), "potentialTests": tests,
               "maxCopies": int(g.letters.map(lambda s: max(pd.Series(list(s)).value_counts())).max())}

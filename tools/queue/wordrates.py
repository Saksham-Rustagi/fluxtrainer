"""Per-word rates: mine, the field's and the top quartile's, plus presence and belief.

One row per word ever present on one of the player's ranked boards. Definitions follow
tools/analytics/salpha.py so the numbers reconcile with the analytics report:

  myRate      finds / presences, over the player's own games
  fieldRate   (my finds + opponents' finds) / (my presences + opponents' presences)
  topQRate    opponents' find rate restricted to opponents in the top quartile of
              leave-one-out Elo (q75 taken over current-regime games)
  strongRate  opponents' find rate restricted to games lost by 10,000+

The primary regime is the current one (season >= 7, SPEC 2.5); the all-regime columns are
carried for sensitivity. Presence by grid comes from the export; presence by tier and grid
comes from the v3 simulation's word_stats, which is the only source with a tier breakdown
that is not confounded by the player's own tier mix.
"""
import os

import numpy as np
import pandas as pd

import qcommon as Q


def _load_games():
    g = pd.read_parquet(os.path.join(Q.RANKED, "games.parquet"),
                        columns=["gid", "season", "margin", "oppEloLoo", "grid", "tier", "yourScore",
                                 "wordsFoundCount", "createdAt"])
    g["current"] = g.season >= Q.CURRENT_FROM_SEASON
    return g


def build():
    g = _load_games()
    pres = pd.read_parquet(os.path.join(Q.RANKED, "presence.parquet"),
                           columns=["gid", "word", "len", "pts", "foundPlayer", "foundOpp"])
    pres = pres.merge(g[["gid", "current", "margin", "oppEloLoo", "grid", "tier"]], on="gid")
    pres["fp"] = pres.foundPlayer.astype(float)
    pres["fo"] = pres.foundOpp.astype(float)
    q75 = float(g[g.current].oppEloLoo.quantile(0.75))
    games_cur = int(g.current.sum())
    games_all = int(len(g))

    def agg(p, suffix):
        mine = p.groupby("word").agg(**{f"n{suffix}": ("fp", "size"), f"k{suffix}": ("fp", "sum")})
        ov = p[p.foundOpp.notna()]
        opp = ov.groupby("word").agg(**{f"nO{suffix}": ("fo", "size"), f"kO{suffix}": ("fo", "sum")})
        tq = ov[ov.oppEloLoo >= q75].groupby("word").agg(
            **{f"nTopQ{suffix}": ("fo", "size"), f"kTopQ{suffix}": ("fo", "sum")})
        st = ov[ov.margin <= -10000].groupby("word").agg(
            **{f"nStrong{suffix}": ("fo", "size"), f"kStrong{suffix}": ("fo", "sum")})
        return mine.join(opp).join(tq).join(st)

    cur = agg(pres[pres.current], "Cur")
    alw = agg(pres, "All")
    w = alw.join(cur, how="left")

    grid = pd.crosstab(pres[pres.current].word, pres[pres.current].grid)
    for c in ("4x4", "5x5"):
        w[f"nCur_{c}"] = grid[c] if c in grid else 0
    w[["nCur_4x4", "nCur_5x5"]] = w[["nCur_4x4", "nCur_5x5"]].fillna(0)

    w["len"] = w.index.str.len().astype(int)
    w["pts"] = Q.points(w.len.values)
    for s in ("Cur", "All"):
        w[f"n{s}"] = w[f"n{s}"].fillna(0)
        for c in ("k", "nO", "kO", "nTopQ", "kTopQ", "nStrong", "kStrong"):
            w[f"{c}{s}"] = w[f"{c}{s}"].fillna(0)
        w[f"myRate{s}"] = np.where(w[f"n{s}"] > 0, w[f"k{s}"] / w[f"n{s}"].replace(0, np.nan), np.nan)
        denom = w[f"n{s}"] + w[f"nO{s}"]
        w[f"fieldRate{s}"] = np.where(denom > 0, (w[f"k{s}"] + w[f"kO{s}"]) / denom.replace(0, np.nan), np.nan)
        w[f"topQRate{s}"] = np.where(w[f"nTopQ{s}"] > 0, w[f"kTopQ{s}"] / w[f"nTopQ{s}"].replace(0, np.nan), np.nan)
        w[f"strongRate{s}"] = np.where(w[f"nStrong{s}"] > 0, w[f"kStrong{s}"] / w[f"nStrong{s}"].replace(0, np.nan), np.nan)
    w["presPerGameCur"] = w.nCur / games_cur
    w["presPerGameAll"] = w.nAll / games_all

    bel = pd.read_csv(os.path.join(Q.RANKED, "belief.tsv"), sep="\t",
                      usecols=["word", "beliefWeighted", "beliefWeighted_s7to10"]).set_index("word")
    w = w.join(bel)
    w["belief"] = w.beliefWeighted_s7to10.fillna(w.beliefWeighted)

    dead = set(pd.read_csv(os.path.join(Q.FIGS, "s0_never_accepted_words.tsv"), sep="\t").word)
    w["neverAccepted"] = w.index.isin(dead)
    w["inLexicon"] = w.index.isin(Q.lexicon())

    meta = {"gamesCur": games_cur, "gamesAll": games_all, "oppEloQ75": q75,
            "words": int(len(w)),
            "tierMixCur": g[g.current].tier.value_counts(normalize=True).to_dict(),
            "gridMixCur": g[g.current].grid.value_counts(normalize=True).to_dict(),
            "meanWordsCur": float(g[g.current].wordsFoundCount.mean()),
            "meanScoreCur": float(g[g.current].yourScore.mean())}
    return w, meta


def sim_presence():
    """P(word appears) per grid and tier, from the v3 5.2M-board run."""
    ws = pd.read_csv(os.path.join(Q.SIM_FULL, "word_stats.tsv"), sep="\t",
                     usecols=["grid", "tier", "word", "pAppear"])
    p = ws.pivot_table(index="word", columns=["grid", "tier"], values="pAppear", aggfunc="first")
    p.columns = [f"pAppear_{a}_{b}" for a, b in p.columns]
    return p.fillna(0.0)


if __name__ == "__main__":
    w, meta = build()
    Q.ensure_build()
    w.to_parquet(os.path.join(Q.BUILD, "word_rates.parquet"))
    sim_presence().to_parquet(os.path.join(Q.BUILD, "sim_presence.parquet"))
    Q.dump_json(meta, os.path.join(Q.BUILD, "word_rates_meta.json"))
    print(meta)
    print(w.shape)

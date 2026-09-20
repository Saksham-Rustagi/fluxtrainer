"""Derive the reusable tables from the ingest.

  finds_derived.parquet  per find: assigned path, travel, family flags
  games.parquet          per game: board, potential, performance, Elo, session
  presence/              word x game presence with found flags, partitioned by grid
  elo_fit.json           the recovered-Elo fit and its validation

Path assignment: a word can have several valid paths. The export has none, so
each find sequence is assigned the path sequence that minimises total hand
travel (end of one find to the start of the next), by Viterbi over the stored
paths. The share of finds with more than one path is the ambiguity rate.
"""
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import RANKED, decode_paths, len_class, load, load_solutions, points, trigrams  # noqa: E402


def distance_tables():
    out = {}
    for side in (4, 5):
        idx = np.arange(side * side)
        r, c = idx // side, idx % side
        out[side] = np.sqrt((r[:, None] - r[None, :]) ** 2 + (c[:, None] - c[None, :]) ** 2)
    return out


def viterbi(cands, D):
    """cands: list (per find) of list of paths. Returns chosen index per find."""
    n = len(cands)
    if n == 0:
        return []
    starts = [np.array([p[0] for p in ps]) for ps in cands]
    ends = [np.array([p[-1] for p in ps]) for ps in cands]
    acc = np.zeros(len(cands[0]))
    back = [None]
    for i in range(1, n):
        cost = acc[:, None] + D[ends[i - 1][:, None], starts[i][None, :]]
        arg = cost.argmin(axis=0)
        back.append(arg)
        acc = cost[arg, np.arange(cost.shape[1])]
    choice = [0] * n
    choice[-1] = int(acc.argmin())
    for i in range(n - 1, 0, -1):
        choice[i - 1] = int(back[i][choice[i]])
    return choice


def fit_elo(g):
    """Recover opponent ratings by inverting change = K(S - E).

    K is chosen to maximise the intraclass correlation of recovered opponent
    ratings within (opponent, 2-day window): the right K makes the same
    opponent look like the same player across games. The ICC is scale-free,
    unlike a raw within-opponent SD, which shrinks mechanically with K.
    """
    S = g.didWin.map({True: 1.0, False: 0.0}).astype(float).fillna(0.5)
    c = g.eloChange.astype(float)
    win2d = g.createdAt.dt.floor("2D")
    # Changes are floored at |3| and season-start placement games run a larger
    # K (the 17-31 tail clusters on season start dates), so neither is used to fit.
    fit_mask = (c.abs() > 3) & (c.abs() <= 16) & (S != 0.5)

    def recover(K):
        E = S - c / K
        ok = (E > 0.01) & (E < 0.99)
        # E = 1 / (1 + 10^((R_opp - R) / 400))  =>  R_opp = R + 400 log10(1/E - 1)
        R = g.eloAtStart + 400 * np.log10(1 / E.where(ok) - 1)
        return R, ok

    def icc(K):
        R, ok = recover(K)
        d = pd.DataFrame({"R": R, "opp": g.oppName, "w": win2d})[fit_mask & ok]
        n = d.groupby(["opp", "w"]).R.transform("size")
        d = d[n > 1]
        within = d.groupby(["opp", "w"]).R.var().mean()
        return 1 - within / d.R.var(), float(np.sqrt(within)), len(d)

    grid = np.arange(14, 24.01, 0.25)
    scan = [(float(K), *icc(K)) for K in grid]
    K = max(scan, key=lambda t: t[1])[0]
    R, ok = recover(K)
    quality = np.where(c.abs() <= 3, "floored", np.where(c.abs() > 16, "placement", "direct"))
    quality = pd.Series(np.where(~ok & (quality == "direct"), "invalid", quality), index=g.index)
    d = pd.DataFrame({"R": R, "opp": g.oppName, "t": g.createdAt, "q": quality})

    # Floored and placement games carry only a bound or a different K. Impute
    # them from the same opponent's direct estimates within 14 days.
    direct = d[d.q == "direct"]
    by_opp = {k: v for k, v in direct.groupby("opp")}
    imputed = d.R.copy()
    method = pd.Series("direct", index=d.index)
    for i in d.index[d.q != "direct"]:
        v = by_opp.get(d.at[i, "opp"])
        if v is not None:
            near = v[(v.t - d.at[i, "t"]).abs() <= pd.Timedelta(days=14)]
            if len(near):
                imputed[i] = near.R.median()
                method[i] = "imputed"
                continue
        method[i] = "bound" if d.at[i, "q"] == "floored" and pd.notna(d.at[i, "R"]) else "missing"
        if method[i] == "missing":
            imputed[i] = np.nan
    # Leave-one-out rating: the same opponent's direct estimates from OTHER games within 14 days.
    # A game's own recovered rating is a function of its outcome, so anything that relates
    # opponent strength to that outcome must use this one instead.
    loo = pd.Series(np.nan, index=d.index)
    for opp, v in direct.groupby("opp"):
        idx = d.index[d.opp == opp]
        t = v.t.values
        rv = v.R.values
        for i in idx:
            near = (np.abs(t - d.at[i, "t"].to_datetime64()) <= np.timedelta64(14, "D")) & (v.index.values != i)
            if near.any():
                loo[i] = np.median(rv[near])
    fit = {
        "K": K,
        "looCoverage": float(loo.notna().mean()),
        "icc": max(t[1] for t in scan),
        "withinOpponentSdElo": [t[2] for t in scan if t[0] == K][0],
        "scan": [{"K": t[0], "icc": t[1], "withinSd": t[2], "rows": t[3]} for t in scan],
        "floor": 3,
        "method": method.value_counts().to_dict(),
    }
    return imputed, method, loo, fit


def main():
    games = load("games_raw.parquet")
    finds = load("finds.parquet")
    sol = load_solutions()
    sol["pts"] = points(sol["len"]).astype("int32")

    # --- presence and board potential ------------------------------------
    pres = sol[["gid", "word", "len", "pts", "pathCount"]].copy()
    fp = finds[finds.who == "player"][["gid", "word", "pos"]].rename(columns={"pos": "posPlayer"})
    fo = finds[finds.who == "opponent"][["gid", "word", "pos"]].rename(columns={"pos": "posOpp"})
    pres = pres.merge(fp, on=["gid", "word"], how="left").merge(fo, on=["gid", "word"], how="left")
    pres["foundPlayer"] = pres.posPlayer.notna()
    pres["foundOpp"] = pres.posOpp.notna().astype("boolean")
    pres = pres.merge(games[["gid", "side"]], on="gid")
    # An opponent list with a word the board cannot hold belongs to another board (for
    # MiningMath, gid 2309, section 0): no opponent inference from that game.
    on_board = set(zip(sol.gid, sol.word))
    off = finds[[(gid, w) not in on_board for gid, w in zip(finds.gid, finds.word)]]
    bad_opp = sorted(off[off.who == "opponent"].gid.unique().tolist())
    if (off.who == "player").any():
        raise SystemExit(f"player finds not on their board: {off[off.who == 'player'].head().to_dict('records')}")
    print("opponent lists not on their board:", bad_opp)
    pres.loc[pres.gid.isin(bad_opp), "foundOpp"] = pd.NA

    lc = len_class(sol["len"])
    pot = sol.groupby("gid").agg(potential=("pts", "sum"), nPresent=("word", "size"),
                                 longestPresent=("len", "max"))
    pot["nPresent5p"] = sol[sol.len >= 5].groupby("gid").size().reindex(pot.index).fillna(0).astype(int)
    for L in (3, 4, 5, 6, 7):
        pot[f"present{L}"] = sol[lc == L].groupby("gid").size().reindex(pot.index).fillna(0).astype(int)

    # --- paths, travel, family flags per find -----------------------------
    D = distance_tables()
    paths = {(r.gid, r.word): (r.paths, r.pathCount) for r in sol[["gid", "word", "paths", "pathCount"]].itertuples(index=False)}
    side_of = dict(zip(games.gid, games.side))
    finds = finds.sort_values(["gid", "who", "pos"]).reset_index(drop=True)
    chosen, npaths, travel, start_mean, cells_mask = [], [], [], [], []
    cont1, cont5 = [], []
    for (gid, who), grp in finds.groupby(["gid", "who"], sort=False):
        words = grp.word.tolist()
        side = side_of[gid]
        cands, counts = [], []
        for w in words:
            p = paths.get((gid, w))
            if p is None:  # only a mismatched opponent list (bad_opp)
                cands.append(None)
                counts.append(0)
            else:
                cands.append(decode_paths(p[0]))
                counts.append(p[1])
        # Viterbi over maximal runs of solvable finds
        choice = [None] * len(words)
        i = 0
        while i < len(words):
            if cands[i] is None:
                i += 1
                continue
            j = i
            while j < len(words) and cands[j] is not None:
                j += 1
            ch = viterbi(cands[i:j], D[side])
            for k, cidx in enumerate(ch):
                choice[i + k] = cidx
            i = j
        prev_end = None
        tri_hist = []
        for k, w in enumerate(words):
            tg = trigrams(w)
            cont1.append(k > 0 and not tg.isdisjoint(tri_hist[-1]))
            cont5.append(k > 0 and any(not tg.isdisjoint(t) for t in tri_hist[-5:]))
            tri_hist.append(tg)
            if cands[k] is None:
                chosen.append("")
                npaths.append(0)
                travel.append(np.nan)
                start_mean.append(np.nan)
                cells_mask.append(0)
                prev_end = None
                continue
            p = cands[k][choice[k]]
            chosen.append("".join(chr(97 + x) for x in p))
            npaths.append(counts[k])
            travel.append(np.nan if prev_end is None else D[side][prev_end, p[0]])
            start_mean.append(float(np.mean([q[0] for q in cands[k]])))
            m = 0
            for x in p:
                m |= 1 << x
            cells_mask.append(m)
            prev_end = p[-1]
    finds["path"] = chosen
    finds["nPaths"] = np.array(npaths, dtype="int32")
    finds["travel"] = travel
    finds["startCellMean"] = start_mean
    finds["cells"] = np.array(cells_mask, dtype="int64")
    finds["cont1"] = cont1
    finds["cont5"] = cont5
    finds["pts"] = points(finds["len"]).astype("int32")
    finds = finds.merge(games[["gid", "side"]], on="gid")
    finds["n"] = finds.groupby(["gid", "who"]).pos.transform("size")
    finds["relPos"] = np.where(finds.n > 1, finds.pos / (finds.n - 1).clip(lower=1), 0.0)
    finds["decile"] = np.minimum((finds.relPos * 10).astype(int), 9)
    finds["valid"] = ~(finds.gid.isin(bad_opp) & (finds.who == "opponent"))

    # --- per-game table ---------------------------------------------------
    g = games.merge(pot, left_on="gid", right_index=True, how="left")
    for who, pre in (("player", ""), ("opponent", "opp")):
        f = finds[(finds.who == who) & finds.valid]
        agg = f.groupby("gid").agg(nWords=("word", "size"), meanLen=("len", "mean"))
        agg["open10"] = f[f.pos < 10].groupby("gid").len.mean()
        agg["longShare"] = f[f.len >= 5].groupby("gid").pts.sum().reindex(agg.index).fillna(0) / f.groupby("gid").pts.sum()
        for L in (3, 4, 5, 6, 7):
            agg[f"n{L}"] = f[len_class(f.len) == L].groupby("gid").size().reindex(agg.index).fillna(0).astype(int)
        agg.columns = [pre + c[0].upper() + c[1:] if pre else c for c in agg.columns]
        g = g.merge(agg, left_on="gid", right_index=True, how="left")
    g.loc[g.gid.isin(bad_opp), [c for c in g.columns if c.startswith("opp") and c not in ("oppName", "oppScore")]] = np.nan
    g["capture"] = g.yourScore / g.potential
    g["oppCapture"] = g.oppScore / g.potential
    g["margin"] = g.yourScore - g.oppScore
    g["outcome"] = np.where(g.didWin.isna(), "tie", np.where(g.didWin == True, "win", "loss"))  # noqa: E712
    g["S"] = g.didWin.map({True: 1.0, False: 0.0}).astype(float).fillna(0.5)

    # overlap: share of his finds the opponent also found
    both = pres[pres.foundPlayer].groupby("gid").foundOpp.mean()
    g["overlap"] = g.gid.map(both)
    g.loc[g.gid.isin(bad_opp), "overlap"] = np.nan

    # Elo
    R, method, loo, fit = fit_elo(g)
    g["oppElo"] = R
    g["oppEloMethod"] = method
    g["eloDiff"] = g.oppElo - g.eloAtStart
    g["oppEloLoo"] = loo
    g["eloDiffLoo"] = g.oppEloLoo - g.eloAtStart

    # sessions: a gap of more than 20 minutes between game starts opens a new session
    g = g.sort_values("createdAt").reset_index(drop=True)
    gap = g.createdAt.diff().dt.total_seconds() / 60
    g["gapBeforeMin"] = (g.createdAt - g.completedAt.shift()).dt.total_seconds() / 60
    g["session"] = (gap.isna() | (gap > 20)).cumsum().astype(int) - 1
    g["sessionPos"] = g.groupby("session").cumcount() + 1
    g["sessionLen"] = g.groupby("session").gid.transform("size")
    g["wallSeconds"] = (g.completedAt - g.createdAt).dt.total_seconds()
    g["month"] = g.createdAt.dt.strftime("%Y-%m")
    g["hourUtc"] = g.createdAt.dt.hour
    g["dow"] = g.createdAt.dt.dayofweek
    g["timeQuartile"] = pd.qcut(g.createdAt.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
    g["grid"] = g.side.map({4: "4x4", 5: "5x5"})

    os.makedirs(RANKED, exist_ok=True)
    finds.to_parquet(os.path.join(RANKED, "finds_derived.parquet"))
    g.to_parquet(os.path.join(RANKED, "games_stage1.parquet"))
    shutil.rmtree(os.path.join(RANKED, "presence.parquet"), ignore_errors=True)
    pres["grid"] = pres.side.map({4: "4x4", 5: "5x5"})
    pres.drop(columns=["side"]).to_parquet(os.path.join(RANKED, "presence.parquet"), partition_cols=["grid"])
    json.dump(fit, open(os.path.join(RANKED, "elo_fit.json"), "w"), indent=2)
    amb = finds[finds.valid & (finds.nPaths > 0)]
    print("K", fit["K"], "icc", round(fit["icc"], 4), "method", fit["method"])
    print("ambiguity: player", (amb[amb.who == "player"].nPaths > 1).mean(), "opp", (amb[amb.who == "opponent"].nPaths > 1).mean())


if __name__ == "__main__":
    sys.exit(main())

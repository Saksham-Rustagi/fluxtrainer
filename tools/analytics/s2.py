"""Report section 2: sequence analysis from find order."""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

import holdout
import peer
from common import points
from viz import (EXTRA, INK2, OPP, PEER, PLAYER, STRONG, WEAK, band, boot_mean, boot_ratio_clustered, month_break, note_n, plt,
                 poisson_w, regime_line, save)

GROUPS = [("player", PLAYER, "you"), ("opponent", OPP, "all opponents"),
          ("strong", STRONG, "opponents who beat you by 10k+"), ("weak", WEAK, "opponents you beat by 10k+")]
# The other player, from their own export: a single named player, kept apart from the aggregates.
PEERG = ("peer", PEER, peer.LABEL)
MAIN = GROUPS[:3] + ([PEERG] if peer.available() else [])
META = ["gid", "season", "tier", "grid", "potential", "current", "split"]


def tag_groups(f, g):
    m = g.set_index("gid").margin
    f = f[f.valid].copy()
    f["margin"] = f.gid.map(m)
    parts = [f[f.who == "player"].assign(grp="player"), f[f.who == "opponent"].assign(grp="opponent"),
             f[(f.who == "opponent") & (f.margin <= -10000)].assign(grp="strong"),
             f[(f.who == "opponent") & (f.margin >= 10000)].assign(grp="weak")]
    if peer.available():
        parts.append(peer.finds().assign(grp="peer", margin=np.nan))
    return pd.concat(parts, ignore_index=True)




def curves(ax, fg, bucket, groups=GROUPS, maxpos=None):
    out = {}
    for key, color, label in groups:
        x = fg[fg.grp == key]
        if maxpos is not None:
            x = x[x[bucket] < maxpos]
        t = boot_ratio_clustered(x, "gid", bucket, "len")
        xs = t[bucket].values + (1 if bucket == "pos" else 0)
        band(ax, xs, t, color, label)
        out[key] = t
    return out


def section2(R, g, f):
    r = {}
    fg = tag_groups(f, g)
    meta = pd.concat([g[META]] + ([peer.games(META)] if peer.available() else []), ignore_index=True)
    fg = fg.merge(meta, on="gid", suffixes=("", "_g"))
    r["games"] = {k: int(fg[fg.grp == k].gid.nunique()) for k, _, _ in GROUPS + [PEERG]}

    # ---- 2.1 length by position --------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.8))
    ALLG = GROUPS + MAIN[3:]
    dec = curves(axes[0], fg, "decile", groups=ALLG)
    axes[0].set_xlabel("decile of normalised find position (0 = first 10% of finds)")
    axes[0].set_ylabel("mean word length (letters)")
    axes[0].set_title("Mean length across the game")
    ab = curves(axes[1], fg, "pos", groups=ALLG, maxpos=25)
    axes[1].set_xlabel("find number")
    axes[1].set_title("The opening: first 25 finds")
    axes[1].legend(loc="lower right", fontsize=7.5)
    note_n(axes[0], "games: " + ", ".join(f"{k} {v:,}" for k, v in r["games"].items()))
    fig.tight_layout()
    save(fig, "s2_1_length_by_position", {**{f"decile_{k}": v for k, v in dec.items()}, **{f"pos_{k}": v for k, v in ab.items()}},
         f"Mean find length by position, 95% bands bootstrapped over games. {peer.LABEL}: all of their own games, a single player shown apart from the opponent aggregates.")
    r["decileCurves"] = {k: v["mean"].round(3).tolist() for k, v in dec.items()}
    r["posCurves"] = {k: v["mean"].round(3).tolist() for k, v in ab.items()}

    # opening deficit per game: first 10 finds against finds 11-40
    def deficit(x):
        a = x[x.pos < 10].groupby("gid").len.mean()
        b = x[(x.pos >= 10) & (x.pos < 40)].groupby("gid").len.mean()
        return (a - b).dropna()

    r["openingDeficit"] = {}
    for key, _, _ in ALLG:
        d = deficit(fg[fg.grp == key])
        m, lo, hi, n = boot_mean(d.values)
        r["openingDeficit"][key] = {"mean": m, "lo": lo, "hi": hi, "n": n}
    r["open10"] = {k: boot_mean(fg[(fg.grp == k) & (fg.pos < 10)].groupby("gid").len.mean())[:3] for k, _, _ in ALLG}
    r["open15"] = {k: boot_mean(fg[(fg.grp == k) & (fg.pos < 15)].groupby("gid").len.mean())[:3] for k, _, _ in ALLG}
    r["lengthMix"] = {k: (np.minimum(fg[fg.grp == k].len, 7).value_counts(normalize=True).sort_index().round(4)).to_dict() for k, _, _ in ALLG}

    # breakouts: player vs all opponents, first 25 finds, by grid / tier / season
    for dim, levels in (("grid", ["4x4", "5x5"]), ("tier", ["casual", "goodCasual", "spam"]),
                        ("season", sorted(g.season.unique()))):
        # tiers come from the v3 posterior, which only describes the current generation regime
        fgd = fg[fg.current] if dim == "tier" else fg
        levels = [lv for lv in levels if (fgd[dim] == lv).sum() > 0 and fgd[(fgd[dim] == lv) & (fgd.grp == "player")].gid.nunique() >= 60]
        ncol = min(4, len(levels))
        nrow = int(np.ceil(len(levels) / ncol))
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.1 * ncol, 2.6 * nrow), sharey=True, squeeze=False)
        tsv = {}
        for ax, lv in zip(axes.ravel(), levels):
            sub = fgd[fgd[dim] == lv]
            res = curves(ax, sub, "pos", groups=GROUPS[:3], maxpos=25)
            ax.set_title(f"{dim} {lv}")
            note_n(ax, f"{sub[sub.grp == 'player'].gid.nunique():,} games")
            for k, v in res.items():
                tsv[f"{lv}_{k}"] = v
        for ax in axes.ravel()[len(levels):]:
            ax.axis("off")
        axes[0, 0].legend(fontsize=6.5, loc="lower right")
        axes[0, 0].set_ylabel("mean length")
        fig.tight_layout()
        save(fig, f"s2_1_opening_by_{dim}", tsv, f"First 25 finds by {dim}: you, all opponents, strong opponents." + (" Seasons 7-10, tiers from the v3 posterior." if dim == "tier" else ""))
        rows = {}
        for lv in levels:
            sub = fgd[fgd[dim] == lv]
            dp = deficit(sub[sub.grp == "player"])
            do = deficit(sub[sub.grp == "strong"])
            rows[str(lv)] = {"playerDeficit": boot_mean(dp.values)[:4], "strongDeficit": boot_mean(do.values)[:4]}
        r[f"deficitBy_{dim}"] = rows

    # is the habit moving? per-game opening deficit against time
    pd_ = deficit(fg[fg.grp == "player"]).rename("d").reset_index().merge(g[["gid", "createdAt", "season"]], on="gid")
    pd_["t"] = (pd_.createdAt - pd_.createdAt.min()).dt.days / 30.4
    m = smf.ols("d ~ t", data=pd_).fit(cov_type="HC1")
    r["deficitTrendPerMonth"] = {"slope": float(m.params.t), "lo": float(m.conf_int().loc["t", 0]),
                                 "hi": float(m.conf_int().loc["t", 1]), "p": float(m.pvalues.t)}
    pd_["month"] = pd_.createdAt.dt.strftime("%Y-%m")
    t = pd_.groupby("month").d.apply(lambda s: pd.Series(boot_mean(s.values), index=["mean", "lo", "hi", "n"])).unstack().reset_index()
    fig, ax = plt.subplots(figsize=(10, 3.2))
    x = np.arange(len(t))
    band(ax, x, t, PLAYER, "you", marker="o")
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(t.month, rotation=45, fontsize=8)
    ax.set_ylabel("letters")
    ax.set_title("Opening deficit by month: mean length of finds 1-10 minus finds 11-40")
    so = r["openingDeficit"]["strong"]
    ax.axhspan(so["lo"], so["hi"], color=STRONG, alpha=0.15, label="strong opponents (all games)")
    regime_line(ax, month_break(t.month))
    ax.legend(loc="lower right")
    save(fig, "s2_1_deficit_by_month", t, "Per-game opening deficit (finds 1-10 minus 11-40), monthly mean with 95% band.")

    # holdout: opening deficit, and its gap to strong opponents in the same games
    dp = deficit(fg[fg.grp == "player"])
    holdout.per_game(R, "Your opening is shorter than your midgame (finds 1-10 minus 11-40)", g, dp, unit="letters")
    ds_ = deficit(fg[fg.grp == "strong"])
    pair = (dp.reindex(ds_.index) - ds_).dropna()
    holdout.per_game(R, "Your opening deficit minus strong opponents', same games", g[g.gid.isin(pair.index)], pair, unit="letters")

    # ---- 2.2 cost of the opening -------------------------------------------------
    r["cost"] = opening_cost(R, g, fg)

    # ---- 2.3 crossover: fresh finds by position ------------------------------------
    fg["fresh"] = (~fg.cont5).astype(float)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.6))
    tsv = {}
    cross = {}
    for key, color, label in MAIN:
        x = fg[(fg.grp == key) & (fg.pos < 100)]
        t = boot_ratio_clustered(x, "gid", "pos", "fresh")
        t = t[t.clusters >= 200]
        band(axes[0], t.pos + 1, t, color, label)
        tsv["pos_" + key] = t
        sm = t["mean"].rolling(5, center=True, min_periods=1).mean().values
        below = np.where(sm < 0.5)[0]
        cross[key] = int(t.pos.values[below[0]] + 1) if len(below) else None
        t2 = boot_ratio_clustered(fg[fg.grp == key], "gid", "decile", "fresh")
        band(axes[1], t2.decile, t2, color, label)
        tsv["decile_" + key] = t2
    axes[0].axhline(0.5, color=INK2, lw=1, ls=":")
    axes[0].set_xlabel("find number")
    axes[0].set_ylabel("share of finds that are fresh")
    axes[0].set_title("Fresh (no shared 3-letter stem with previous 5 finds)")
    axes[1].set_xlabel("decile of normalised position")
    axes[1].set_title("Same, normalised position")
    axes[0].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "s2_3_fresh_rate", tsv, "Fresh-find rate by position. Fresh = shares no 3+ letter substring with any of the previous 5 finds.")
    pl_ = tsv["pos_player"].set_index("pos")["mean"]
    op_ = tsv["pos_opponent"].set_index("pos")["mean"]
    diff = (pl_ - op_).dropna()
    sign = np.sign(diff.rolling(5, center=True, min_periods=1).mean())
    flips = np.where(np.diff(sign.values) != 0)[0]
    r["fresh"] = {"crossBelowHalf": cross, "playerVsOppCross": [int(diff.index[i] + 1) for i in flips],
                  "first5": {k: float(tsv["pos_" + k]["mean"].iloc[:5].mean()) for k, _, _ in MAIN},
                  "pos20to40": {k: float(tsv["pos_" + k].query("pos>=20 and pos<40")["mean"].mean()) for k, _, _ in MAIN}}

    # ---- 2.4 run structure --------------------------------------------------------
    runs = {}
    rates = {}
    for key, _, _ in MAIN:
        x = fg[fg.grp == key].sort_values(["gid", "pos"])
        start = ~x.cont1.values
        run_id = np.cumsum(start)
        lens = pd.Series(run_id).value_counts().values
        runs[key] = np.bincount(np.minimum(lens, 10), minlength=11)[1:]
        y = x[x.pos > 0]
        rates[key] = boot_ratio_clustered(y.assign(c=y.cont1.astype(float), one=1), "gid", "one", "c").iloc[0].to_dict()
        rates[key]["meanRunLength"] = float(lens.mean())
    # paired difference, player minus opponent in the same game
    pc = fg[(fg.pos > 0) & (fg.grp == "player")].groupby("gid").cont1.mean()
    oc = fg[(fg.pos > 0) & (fg.grp == "opponent")].groupby("gid").cont1.mean()
    sc = fg[(fg.pos > 0) & (fg.grp == "strong")].groupby("gid").cont1.mean()
    d = (pc - oc).dropna()
    ds = (pc - sc).dropna()
    r["runs"] = {"rates": rates, "pairedDiffVsOpp": boot_mean(d.values)[:4], "pairedDiffVsStrong": boot_mean(ds.values)[:4],
                 "dist": {k: (v / v.sum()).round(4).tolist() for k, v in runs.items()}}
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    w = 0.8 / len(MAIN)
    for i, (key, color, label) in enumerate(MAIN):
        p = runs[key] / runs[key].sum()
        ax.bar(np.arange(1, 11) + (i - (len(MAIN) - 1) / 2) * w, p, width=w - 0.02, color=color, label=label)
    ax.set_xticks(np.arange(1, 11))
    ax.set_xticklabels([str(i) for i in range(1, 10)] + ["10+"])
    ax.set_xlabel("family-run length (consecutive finds sharing a 3+ letter stem)")
    ax.set_ylabel("share of runs")
    ax.set_title("Run structure")
    ax.legend(fontsize=7.5)
    save(fig, "s2_4_run_lengths", pd.DataFrame({k: v for k, v in runs.items()}, index=range(1, 11)).reset_index(names="runLength"),
         "Distribution of family-run lengths.")
    holdout.per_game(R, "Consecutive-family rate: you minus strong opponents (same games)", g[g.gid.isin(ds.dropna().index)],
                     ds.dropna(), unit="rate")

    # ---- 2.5 length transitions ----------------------------------------------------
    trans = {}
    keys = [k for k, _, _ in MAIN if k != "opponent"]
    names = {"player": "You", "strong": "Strong opponents", "peer": peer.LABEL}
    fig, axes = plt.subplots(2, len(keys), figsize=(4 * len(keys), 7))
    labels = ["3", "4", "5", "6", "7+"]

    def matrix(ax, M, title, cmap, vmin, vmax, fmt):
        ax.imshow(M, cmap=cmap, vmin=vmin, vmax=vmax)
        for i in range(5):
            for j in range(5):
                ax.text(j, i, format(M[i, j], fmt), ha="center", va="center", fontsize=8,
                        color="white" if cmap == "Blues" and M[i, j] > 0.35 else "black")
        ax.set_xticks(range(5))
        ax.set_xticklabels(labels)
        ax.set_yticks(range(5))
        ax.set_yticklabels(labels)
        ax.set_xlabel("next find length")
        ax.set_ylabel("this find length")
        ax.set_title(title)
        ax.grid(False)

    for ax, key in zip(axes[0], keys):
        x = fg[fg.grp == key].sort_values(["gid", "pos"])
        lc = np.minimum(x.len.values, 7) - 3
        same = x.gid.values[1:] == x.gid.values[:-1]
        M = np.zeros((5, 5))
        np.add.at(M, (lc[:-1][same], lc[1:][same]), 1)
        P = M / M.sum(axis=1, keepdims=True)
        trans[key] = P
        matrix(ax, P, f"{names[key]}: P(next | this)", "Blues", 0, 0.6, ".2f")
    for ax, key in zip(axes[1], keys[1:]):
        matrix(ax, trans["player"] - trans[key], f"You minus {names[key].lower() if key == 'strong' else names[key]}", "RdBu_r", -0.12, 0.12, "+.2f")
    for ax in axes[1][len(keys) - 1:]:
        ax.axis("off")
    fig.tight_layout()
    rows = []
    for k, P in trans.items():
        for i in range(5):
            for j in range(5):
                rows.append({"group": k, "from": labels[i], "to": labels[j], "p": P[i, j]})
    save(fig, "s2_5_length_transitions", pd.DataFrame(rows), "Markov transition matrices over length classes for consecutive finds.")

    # bootstrap P(next is 3-4 | this is 6+) by game, player vs strong
    def short_after_long(x):
        x = x.sort_values(["gid", "pos"])
        nxt = x.groupby("gid").len.shift(-1)
        y = x[(x.len >= 6) & nxt.notna()].assign(short=(nxt[(x.len >= 6) & nxt.notna()] <= 4).astype(float))
        return boot_ratio_clustered(y.assign(one=1), "gid", "one", "short").iloc[0].to_dict()

    r["transitions"] = {k: np.round(v, 4).tolist() for k, v in trans.items()}
    r["shortAfterLong"] = {k: short_after_long(fg[fg.grp == k]) for k, _, _ in MAIN}
    # control: overall share of 3-4 letter finds, so the conditional is read against the base rate
    r["shortBase"] = {k: float((fg[fg.grp == k].len <= 4).mean()) for k, _, _ in MAIN}
    # per-game counts so the holdout can resample games cheaply
    cnt = {}
    for key in ("player", "strong"):
        x = fg[fg.grp == key].sort_values(["gid", "pos"])
        nxt = x.groupby("gid").len.shift(-1)
        y = x[(x.len >= 6) & nxt.notna()].assign(short=(nxt <= 4))
        cnt[key] = (y.groupby("gid").short.sum(), y.groupby("gid").size())

    def sal_diff(gids):
        v = []
        for key in ("player", "strong"):
            a, b = cnt[key]
            v.append(a.reindex(gids).fillna(0).sum() / max(b.reindex(gids).fillna(0).sum(), 1))
        return v[0] - v[1]

    sg = g[g.gid.isin(cnt["strong"][1].index)]
    holdout.by_fn(R, "P(next find is 3-4 letters | this find is 6+): you minus strong opponents", sg, sal_diff, unit="probability")
    r["openingTest"] = opening_test(R, g, fg)
    R["s2"] = r


def opening_cost(R, g, fg, D=40, NS=(10, 15, 20, 25)):
    """Points forgone in the first N finds against strong opponents' length profile.

    For each game, draw D strong-opponent opening length sequences from games on the
    same grid and potential tercile, cap each length by what that board actually has
    left (falling to the longest shorter length available), and score it. The same
    procedure with weak opponents' openings is the placebo. Priced against board contents,
    so it runs on seasons 7-10 only (the current generation regime).
    """
    rng = np.random.default_rng(11)
    Nmax = max(NS)
    g = g[g.current].copy()
    fg = fg[fg.current]
    g["potT"] = g.groupby("grid").potential.transform(lambda s: pd.qcut(s, 3, labels=False))
    seq = {}
    for key in ("strong", "weak", "player"):
        x = fg[(fg.grp == key) & (fg.pos < Nmax)].sort_values(["gid", "pos"])
        arr = x.groupby("gid").len.apply(lambda s: s.values)
        arr = arr[arr.map(len) == Nmax]
        seq[key] = arr
    avail = g.set_index("gid")[[f"present{L}" for L in (3, 4, 5, 6)]]
    pres_len = R["_pres_len"]  # gid -> counts by exact length
    pl = fg[(fg.grp == "player") & (fg.pos < Nmax)].sort_values(["gid", "pos"]).groupby("gid").len.apply(lambda s: s.values)
    pl = pl[pl.map(len) == Nmax]
    gi = g.set_index("gid")
    pts_table = points(np.arange(0, 30)).astype(float)
    pts_table[:3] = 0
    out = []
    pools = {}
    for key in ("strong", "weak", "player"):
        s = seq[key]
        meta = gi.loc[s.index, ["grid", "potT"]]
        pools[key] = {k: np.stack(s[v.index].values) for k, v in meta.groupby(["grid", "potT"])}
    for gid, lens in pl.items():
        grid, pt = gi.at[gid, "grid"], gi.at[gid, "potT"]
        counts = pres_len.get(gid, {})
        row = {"gid": gid}
        cum_actual = np.cumsum(pts_table[lens])
        for key in ("strong", "weak", "player"):
            pool = pools[key].get((grid, pt))
            if pool is None or len(pool) < 5:
                continue
            draws = pool[rng.integers(0, len(pool), D)]
            tot = np.zeros((D, Nmax))
            for d in range(D):
                left = dict(counts)
                for k, L in enumerate(draws[d]):
                    L = int(L)
                    while L > 3 and left.get(L, 0) <= 0:
                        L -= 1
                    left[L] = left.get(L, 0) - 1
                    tot[d, k] = pts_table[L]
            cum = np.cumsum(tot, axis=1).mean(axis=0)
            for N in NS:
                row[f"{key}_forgone{N}"] = cum[N - 1] - cum_actual[N - 1]
        out.append(row)
    c = pd.DataFrame(out).merge(g[["gid", "margin", "outcome", "season", "grid", "nWords", "oppNWords"]], on="gid")
    res = {"games": int(len(c))}
    for N in NS:
        res[f"forgone{N}"] = boot_mean(c[f"strong_forgone{N}"].values)[:4]
        res[f"placebo{N}"] = boot_mean(c[f"weak_forgone{N}"].values)[:4]
        res[f"self{N}"] = boot_mean(c[f"player_forgone{N}"].values)[:4]
    losses = c[c.outcome == "loss"]
    for N in NS:
        flip = (losses[f"strong_forgone{N}"] > -losses.margin)
        res[f"lossesFlipped{N}"] = {"share": float(flip.mean()), "count": int(flip.sum()), "losses": int(len(losses)),
                                    "ci": list(boot_mean(flip.astype(float).values)[1:3])}
        flipp = (losses[f"weak_forgone{N}"] > -losses.margin)
        res[f"lossesFlippedPlacebo{N}"] = float(flipp.mean())
        res[f"lossesFlippedSelf{N}"] = float((losses[f"player_forgone{N}"] > -losses.margin).mean())
    res["byGrid"] = {k: boot_mean(x["strong_forgone15"].values)[:4] for k, x in c.groupby("grid")}
    # the time caveat: strong opponents do not buy their longer opening with fewer words overall
    sg = g[g.margin <= -10000]
    res["strongGamesWords"] = {"player": float(sg.nWords.mean()), "opponent": float(sg.oppNWords.mean()), "games": int(len(sg))}
    c = c.merge(g[["gid", "split"]], on="gid")
    holdout.per_game(R, "Points forgone in the first 15 finds vs strong opponents' length profile", g,
                     c.set_index("gid").strong_forgone15, unit="points/game")
    lc = c[c.outcome == "loss"].set_index("gid")
    flipdiff = (lc.strong_forgone15 > -lc.margin).astype(float) - (lc.player_forgone15 > -lc.margin).astype(float)
    holdout.per_game(R, "Share of losses the opening gap flips, net of the self-placebo", g[g.gid.isin(lc.index)], flipdiff, unit="share")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    xs = np.array(NS)
    s_ = pd.DataFrame([res[f"forgone{N}"] for N in NS], columns=["mean", "lo", "hi", "n"])
    p_ = pd.DataFrame([res[f"placebo{N}"] for N in NS], columns=["mean", "lo", "hi", "n"])
    band(axes[0], xs, s_, STRONG, "vs strong opponents' openings", marker="o")
    band(axes[0], xs, p_, WEAK, "vs weak opponents' openings", marker="s")
    se_ = pd.DataFrame([res[f"self{N}"] for N in NS], columns=["mean", "lo", "hi", "n"])
    band(axes[0], xs, se_, PLAYER, "placebo: vs your own openings from other games", marker="^")
    axes[0].axhline(0, color=INK2, lw=1)
    axes[0].set_xlabel("first N finds")
    axes[0].set_ylabel("points forgone per game")
    axes[0].set_title("Cost of the opening")
    axes[0].legend(fontsize=7.5)
    note_n(axes[0], f"{len(c):,} games")
    fl = pd.DataFrame([res[f"lossesFlipped{N}"] for N in NS])
    axes[1].bar(xs, fl.share, width=3, color=STRONG, label="vs strong profile")
    axes[1].bar(xs + 1.2, [res[f"lossesFlippedPlacebo{N}"] for N in NS], width=1.2, color=WEAK, label="vs weak opponents' profile")
    axes[1].bar(xs - 1.2, [res[f"lossesFlippedSelf{N}"] for N in NS], width=1.2, color=PLAYER, label="placebo: your own profile")
    for x, (_, row) in zip(xs, fl.iterrows()):
        axes[1].text(x, row.share + 0.005, f"{row.share:.1%}", ha="center", fontsize=8)
    axes[1].set_xlabel("first N finds")
    axes[1].set_ylabel("share of losses")
    axes[1].set_title("Losses the opening gap alone would have flipped")
    axes[1].legend(fontsize=7.5)
    note_n(axes[1], f"{res['lossesFlipped15']['losses']:,} losses")
    fig.tight_layout()
    save(fig, "s2_2_opening_cost", {"forgone": s_.assign(N=xs), "weakProfile": p_.assign(N=xs), "selfPlacebo": se_.assign(N=xs), "lossesFlipped": fl.assign(N=xs)},
         "Counterfactual points forgone in the opening, and the share of losses the gap would have flipped.")
    R["_cost_table"] = c
    return res


def opening_test(R, g, fg):
    """Within-player test of the opening counterfactual's key assumption.

    The counterfactual swaps shorter words for longer ones at no time cost. If opening
    longer costs you volume, games where your own opening was longer should show fewer
    words and fewer later points, board held fixed. Regress final word count, score, and
    what happened after find 15 on the mean length of your own first 15 finds,
    controlling for board potential by grid, the board's count of 5+ letter words, and
    month (which absorbs your improvement over time). Observational: good-form games raise
    both, so a positive slope is an upper bound on the benefit and a negative one is a
    real cost.
    """
    pl = fg[fg.grp == "player"].sort_values(["gid", "pos"])
    per = pl.groupby("gid").agg(open15=("len", lambda s: s.iloc[:15].mean()), n=("len", "size"))
    per["ptsAfter15"] = pl[pl.pos >= 15].groupby("gid").pts.sum()
    per["wordsAfter15"] = pl[pl.pos >= 15].groupby("gid").size()
    per["ptsFirst15"] = pl[pl.pos < 15].groupby("gid").pts.sum()
    d = g.merge(per.reset_index(), on="gid")
    d = d[d.n >= 15].fillna({"ptsAfter15": 0, "wordsAfter15": 0})
    d["logPot"] = np.log(d.potential)
    d["log5p"] = np.log1p(d.nPresent5p)
    strong15 = fg[(fg.grp == "strong") & (fg.pos < 15)].groupby("gid").len.mean().mean()
    mine15 = d.open15.mean()
    delta = strong15 - mine15
    out = {"strongOpen15": float(strong15), "yourOpen15": float(mine15), "delta": float(delta),
           "open15Sd": float(d.open15.std())}
    for regime, dd in (("current", d[d.current]), ("all", d)):
        res = {"games": int(len(dd))}
        for y in ("nWords", "yourScore", "wordsAfter15", "ptsAfter15", "ptsFirst15"):
            m = smf.ols(f"{y} ~ open15 + logPot * C(grid) + log5p + C(month)", data=dd).fit(cov_type="HC1")
            res[y] = {"perLetter": float(m.params.open15), "ci": m.conf_int().loc["open15"].tolist(), "p": float(m.pvalues.open15),
                      "atDelta": float(m.params.open15 * delta)}
        out[regime] = res
    # binned picture, current regime, board-controlled
    dc = d[d.current].copy()
    for y in ("nWords", "yourScore"):
        m = smf.ols(f"{y} ~ logPot * C(grid) + log5p + C(month)", data=dc).fit()
        dc[y + "_res"] = m.resid
    dc["b"] = pd.qcut(dc.open15, 8, labels=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    tsv = {}
    for ax, y, title, unit in ((axes[0], "nWords_res", "Words found, board-controlled", "words"),
                               (axes[1], "yourScore_res", "Score, board-controlled", "points")):
        t = dc.groupby("b").agg(x=("open15", "median")).join(
            pd.DataFrame([boot_mean(v.values)[:3] for _, v in dc.groupby("b")[y]], columns=["mean", "lo", "hi"]))
        band(ax, t.x, t, PLAYER, "you", marker="o")
        ax.axhline(0, color=INK2, lw=0.8, ls=":")
        ax.axvline(strong15, color=STRONG, lw=1, ls="--", label="strong opponents' mean")
        ax.set_xlabel("mean length of your first 15 finds (letters)")
        ax.set_ylabel(unit)
        ax.set_title(title)
        tsv[y] = t.reset_index()
    axes[0].legend(fontsize=7.5)
    note_n(axes[1], f"{len(dc):,} games, seasons 7-10")
    fig.tight_layout()
    save(fig, "s2_2b_opening_test", tsv, "Your own games binned by opening length (first 15 finds), outcomes residualised on board potential, 5+ count, grid and month.")
    cur = out["current"]
    holdout.per_game(R, "Within-player: longer own openings come with fewer words (board-controlled partial covariance)", g,
                     _resid_product(d), unit="covariance", note="negative = opening longer costs volume")
    return out


def _resid_product(d):
    """Per-game product of residualised opening length and residualised word count: its mean is the
    partial covariance, so its sign is the sign of the within-player slope, and it resamples by game."""
    d = d.copy()
    a = smf.ols("open15 ~ logPot * C(grid) + log5p + C(month)", data=d).fit().resid
    b = smf.ols("nWords ~ logPot * C(grid) + log5p + C(month)", data=d).fit().resid
    return pd.Series((a * b).values, index=d.gid.values)

"""Vocabulary benchmarks against the players you are trying to beat, not your equals.

"Opponents" at your rating are players you go 50/50 with, so matching them only says you
are average among equals. Each metric is therefore reported against:

  field        all opponents (for reference)
  strong       opponents who beat you by 10k+, compared with you in those same games
  topQuartile  opponents in the top quartile by leave-one-out rating, same games
  frontier     the best observed performance on each unit by either player

Paired comparisons use identical games, so board difficulty cancels. Strong games are
selected on the outcome (you lost big), so they flatter the opponent; the top quartile is
selected on rating only and is the cleaner benchmark.
"""
import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportions_ztest

import holdout
import peer
import viz
from viz import INK2, OPP, PEER, PLAYER, STRONG, WEAK, EXTRA, bh, plt


def _sums(df, num, den):
    return df.groupby("gid")[num].sum(), df.groupby("gid")[den].sum()


def _ratio(n, d, gids):
    return n.reindex(gids).fillna(0).sum() / max(d.reindex(gids).fillna(0).sum(), 1e-9)


def _paired(nA, dA, nB, dB, gids, b=300):
    """A - B with a bootstrap over games (same weights for both sides)."""
    gids = np.asarray(gids)
    arr = [x.reindex(gids).fillna(0).values for x in (nA, dA, nB, dB)]
    w = viz.RNG.poisson(1.0, (b, len(gids)))
    ra = (w @ arr[0]) / np.maximum(w @ arr[1], 1e-9)
    rb = (w @ arr[2]) / np.maximum(w @ arr[3], 1e-9)
    est = arr[0].sum() / max(arr[1].sum(), 1e-9) - arr[2].sum() / max(arr[3].sum(), 1e-9)
    return float(est), float(np.percentile(ra - rb, 2.5)), float(np.percentile(ra - rb, 97.5))


def _metric(sides, groups):
    """sides: {'you': (num, den), 'opp': (num, den), 'frontier': (num, den)} per-game sums."""
    out = {}
    you, opp, fr = sides["you"], sides["opp"], sides.get("frontier")
    out["you"] = _ratio(*you, groups["all"])
    out["field"] = _ratio(*opp, groups["all"])
    for gname in ("strong", "topQuartile"):
        gids = groups[gname]
        out[f"you_in_{gname}"] = _ratio(*you, gids)
        out[gname] = _ratio(*opp, gids)
        out[f"gap_{gname}"] = _paired(*you, *opp, gids)
        out[f"games_{gname}"] = int(len(gids))
    out["gap_field"] = _paired(*you, *opp, groups["all"])
    if fr is not None:
        out["frontier"] = _ratio(*fr, groups["all"])
        out["gap_frontier"] = _paired(*you, *fr, groups["all"])
    return out


def baselines(R, g, pres, bp, primary=True):
    q75 = g.oppEloLoo.quantile(0.75)
    groups = {"all": g.gid.values, "strong": g.gid[g.margin <= -10000].values,
              "topQuartile": g.gid[g.oppEloLoo >= q75].values}
    out = {"topQuartileEloFrom": float(q75), "games": {k: int(len(v)) for k, v in groups.items()}}
    M = {}

    fam = bp["fam"].copy()
    fam["mx"] = np.maximum(fam.foundP, fam.foundO)
    M["familyCompletion"] = {"you": _sums(fam[fam.foundP >= 1], "foundP", "size"),
                             "opp": _sums(fam[fam.foundO >= 1], "foundO", "size"),
                             "frontier": _sums(fam[fam.mx >= 1], "mx", "size")}
    a = bp["affix"]
    a = a[a.reachable].copy()
    a["one"] = 1.0
    a["either"] = (a.wordFoundP | a.wordFoundO).astype(float)
    M["affixTake"] = {"you": _sums(a[a.stemFoundP].assign(v=lambda d: d.wordFoundP.astype(float)), "v", "one"),
                      "opp": _sums(a[a.stemFoundO].assign(v=lambda d: d.wordFoundO.astype(float)), "v", "one"),
                      "frontier": _sums(a[a.stemFoundP | a.stemFoundO], "either", "one")}
    an = bp["ana"].copy()
    an["mx"] = np.maximum(an.foundP, an.foundO)
    M["anagramCompletion"] = {"you": _sums(an[an.foundP >= 1], "foundP", "present"),
                              "opp": _sums(an[an.foundO >= 1], "foundO", "present"),
                              "frontier": _sums(an[an.mx >= 1], "mx", "present")}
    m = bp["missed"]
    m = m.assign(one=1.0, fP=m.foundP.astype(float), fO=m.foundO.astype(float), fE=(m.foundP | m.foundO).astype(float))
    M["freeExtensionTake"] = {"you": _sums(m[m.freeForP], "fP", "one"), "opp": _sums(m[m.freeForO], "fO", "one"),
                              "frontier": _sums(m[m.freeForP | m.freeForO], "fE", "one")}
    c = bp["m2"].copy()
    c["nP"], c["dP"] = c.foundP * (c.foundP - 1), c.foundP * (c.presentInSet - 1)
    c["nO"], c["dO"] = c.foundO * (c.foundO - 1), c.foundO * (c.presentInSet - 1)
    mx = np.maximum(c.foundP, c.foundO)
    c["nF"], c["dF"] = mx * (mx - 1), mx * (c.presentInSet - 1)
    M["cellmateTake"] = {"you": _sums(c, "nP", "dP"), "opp": _sums(c, "nO", "dO"), "frontier": _sums(c, "nF", "dF")}
    dt = bp["dt"].assign(one=1.0, v=lambda d: d.foundP.astype(float))
    dto = bp["dtO"].assign(one=1.0, v=lambda d: d.foundO.astype(float))
    M["dropTerminalTake"] = {"you": _sums(dt, "v", "one"), "opp": _sums(dto, "v", "one")}

    for name, sides in M.items():
        out[name] = _metric(sides, groups)

    # family completion by size band against the top quartile and the frontier
    fam["sizeB"] = pd.cut(fam["size"], [1, 2, 3, 5, 9, 1000], labels=["2", "3", "4-5", "6-9", "10+"])
    tq = set(groups["topQuartile"])
    rows = []
    for sb, x in fam.groupby("sizeB", observed=True):
        xt = x[x.gid.isin(tq)]
        rows.append({"size": str(sb),
                     "you": x[x.foundP >= 1].foundP.sum() / x[x.foundP >= 1]["size"].sum(),
                     "you_in_topQuartile": xt[xt.foundP >= 1].foundP.sum() / max(xt[xt.foundP >= 1]["size"].sum(), 1),
                     "topQuartile": xt[xt.foundO >= 1].foundO.sum() / max(xt[xt.foundO >= 1]["size"].sum(), 1),
                     "frontier": x[x.mx >= 1].mx.sum() / x[x.mx >= 1]["size"].sum()})
    out["familyBySize"] = rows

    # affixes you trail the strongest opponents on, same games
    at = a[a.gid.isin(tq)]
    pts = lambda L: 100 if L == 3 else 400 if L == 4 else 800 if L == 5 else 1400 + 400 * (L - 6)  # noqa: E731
    at = at.assign(pts=at.word.str.len().map(pts))
    y = at[at.stemFoundP].groupby("affix").agg(n=("wordFoundP", "size"), k=("wordFoundP", "sum"), pts=("pts", "mean"))
    o = at[at.stemFoundO].groupby("affix").agg(nO=("wordFoundO", "size"), kO=("wordFoundO", "sum"))
    t = y.join(o, how="inner")
    t = t[(t.n >= 20) & (t.nO >= 20)]
    if len(t):
        t["rate"], t["rateTopQ"] = t.k / t.n, t.kO / t.nO
        t["p"] = [proportions_ztest([k, ko], [n, no], alternative="smaller")[1] for k, n, ko, no in zip(t.k, t.n, t.kO, t.nO)]
        t["q"] = bh(t.p.values)
        t["excessPerGame"] = (t.rateTopQ - t.rate) * t.n * t.pts / max(len(tq), 1)
        t = t.sort_values("excessPerGame", ascending=False)
    out["affixVsTopQuartile"] = {"tested": int(len(t)), "significant": int((t.q < 0.05).sum()) if len(t) else 0,
                                 "top": t.head(20).reset_index().round(4).to_dict("records") if len(t) else []}

    if primary:
        _figure(out)
        cur = g
        for name, label in (("familyCompletion", "family completion"), ("affixTake", "additive-affix take"),
                            ("freeExtensionTake", "free-extension take"), ("anagramCompletion", "anagram-set completion")):
            you, opp = M[name]["you"], M[name]["opp"]

            def fn(gids, you=you, opp=opp):
                gids = [x for x in gids if x in tq]
                return _ratio(*you, gids) - _ratio(*opp, gids)

            holdout.by_fn(R, f"You minus top-quartile opponents, {label} (same games)", cur, fn, unit="share")
    return out


def peer_figures(R):
    """Redraw the benchmark figure with the other player's own seasons 7-10 values, once both have run."""
    pr = peer.results()
    _figure(R["s4"]["baselines"], (pr or {}).get("s4", {}).get("baselines"))


def _figure(out, pout=None):
    names = [("familyCompletion", "Family completion\n(given 1+ found)"), ("affixTake", "Additive affix take"),
             ("freeExtensionTake", "Free-extension take"), ("anagramCompletion", "Anagram-set completion"),
             ("cellmateTake", "Cellmate take"), ("dropTerminalTake", "Drop-terminal take")]
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.4))
    rows = []
    for ax, (k, title) in zip(axes.ravel(), names):
        v = out[k]
        labels = ["you", "field", "you", "strong", "you", "top 25%", "frontier"]
        vals = [v["you"], v["field"], v["you_in_strong"], v["strong"], v["you_in_topQuartile"], v["topQuartile"], v.get("frontier", np.nan)]
        cols = [PLAYER, OPP, PLAYER, STRONG, PLAYER, WEAK, EXTRA[0]]
        x = [0, 1, 2.6, 3.6, 5.2, 6.2, 7.8]
        if pout is not None:
            labels.append(peer.LABEL.split(" ")[0])
            vals.append(pout[k]["you"])
            cols.append(PEER)
            x.append(9.2)
            rows.append({"metric": k, "vs": "peerOwnGames", "gap": pout[k]["you"], "lo": np.nan, "hi": np.nan})
        x = np.array(x)
        ax.bar(x, vals, color=cols, width=0.9)
        for xi, vi in zip(x, vals):
            if np.isfinite(vi):
                ax.text(xi, vi + 0.01, f"{vi:.2f}", ha="center", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7.5)
        ax.set_title(title)
        ax.set_ylim(0, max(v for v in vals if np.isfinite(v)) * 1.18)
        for gname in ("strong", "topQuartile"):
            e, lo, hi = v[f"gap_{gname}"]
            rows.append({"metric": k, "vs": gname, "gap": e, "lo": lo, "hi": hi})
        rows.append({"metric": k, "vs": "field", "gap": v["gap_field"][0], "lo": v["gap_field"][1], "hi": v["gap_field"][2]})
        if "gap_frontier" in v:
            rows.append({"metric": k, "vs": "frontier", "gap": v["gap_frontier"][0], "lo": v["gap_frontier"][1], "hi": v["gap_frontier"][2]})
    fig.text(0.5, 0.005, "pairs are the same games: 'you' next to 'strong' is you in the games they beat you by 10k+; next to 'top 25%' is you against top-quartile-rated opponents"
             + (f"; {peer.LABEL.split(' ')[0]}: that player's own value over their own seasons 7-10 games" if pout is not None else ""),
             ha="center", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    viz.save(fig, "s4_0_baselines", pd.DataFrame(rows), "Vocabulary metrics against the field, strong opponents, top-quartile opponents and the per-unit frontier, seasons 7-10. Gaps with 95% CIs in the TSV.")

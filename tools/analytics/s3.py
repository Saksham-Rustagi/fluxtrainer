"""Report section 3: spatial analysis on assigned paths."""
import numpy as np
import pandas as pd

import peer
from common import load_solutions
from viz import INK2, OPP, PEER, PLAYER, STRONG, WEAK, band, boot_mean, boot_ratio_clustered, note_n, plt, save


def popcount(a):
    a = np.asarray(a, dtype=np.int64)
    return np.array([bin(x).count("1") for x in a])


def region_of(paths, side):
    """Quadrant of each path's centroid; the 5x5 boundary sits on the middle row/column."""
    out = np.empty(len(paths), dtype=np.int8)
    mid = (side - 1) / 2
    for i, p in enumerate(paths):
        cells = [ord(c) - 97 for c in p]
        r = np.mean([c // side for c in cells])
        c = np.mean([c % side for c in cells])
        out[i] = (r >= mid) * 2 + (c >= mid)
    return out


def with_coverage(f):
    """Share of the grid touched by each find, cumulative within (game, who); f sorted by gid, who, pos."""
    f = f.copy()
    cov = np.empty(len(f))
    keys = f.gid.values * 4 + pd.factorize(f.who)[0]
    starts = np.r_[0, np.where(np.diff(keys) != 0)[0] + 1, len(f)]
    cells = f.cells.values
    for a, b in zip(starts[:-1], starts[1:]):
        cov[a:b] = np.bitwise_or.accumulate(cells[a:b])
    f["covCells"] = popcount(cov)
    f["covShare"] = f.covCells / (f.side ** 2)
    return f


def section3(R, g, f, pres):
    r = {}
    f = f[f.valid & (f.nPaths > 0)].copy()
    pl = f[f.who == "player"]
    r["ambiguity"] = {"player": float((pl.nPaths > 1).mean()), "opponent": float((f[f.who == "opponent"].nPaths > 1).mean()),
                      "playerCapHit": float((pl.nPaths > 64).mean()),
                      "playerByLen": pl.assign(a=pl.nPaths > 1).groupby(np.minimum(pl.len, 7)).a.mean().round(4).to_dict()}

    # ---- coverage by find position -------------------------------------------------
    f = with_coverage(f.sort_values(["gid", "who", "pos"]))
    pf = None
    if peer.available():
        pf = peer.finds()
        pf = with_coverage(pf[pf.valid & (pf.nPaths > 0)].sort_values(["gid", "pos"]))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4), sharey=True)
    tsv = {}
    r["coverage"] = {}
    series = [("player", PLAYER, "you", f), ("opponent", OPP, "opponents", f)] + ([("peer", PEER, peer.LABEL, pf)] if pf is not None else [])
    for ax, side in zip(axes, (4, 5)):
        for who, color, label, src in series:
            x = src[(src.side == side) & (src.who == who) & (src.pos < 60)]
            t = boot_ratio_clustered(x, "gid", "pos", "covShare")
            band(ax, t.pos + 1, t, color, label)
            tsv[f"{side}x{side}_{who}"] = t
            r["coverage"][f"{side}x{side}_{who}"] = {k: float(t.set_index("pos")["mean"].get(k - 1, np.nan)) for k in (5, 10, 25, 50)}
        ax.set_title(f"{side}x{side}: share of cells touched by find N")
        ax.set_xlabel("find number")
        ax.axvline(10, color=INK2, lw=0.8, ls=":")
        ax.axvline(25, color=INK2, lw=0.8, ls=":")
    axes[0].set_ylabel("share of grid touched")
    axes[0].legend()
    fig.tight_layout()
    save(fig, "s3_coverage", tsv, "Share of the grid touched by the Nth find (assigned paths), 95% bands over games.")
    last = f.groupby(["gid", "who"]).covShare.max().unstack()
    r["coverageEndOfGame"] = {"player": float(last.player.mean()), "playerAll": float((last.player == 1).mean())}

    # ---- travel between consecutive finds -------------------------------------------
    # Assignment minimises travel, so the unbiased comparison uses transitions where both finds
    # have exactly one path, against the same finds in shuffled order.
    f["prevUnamb"] = f.groupby(["gid", "who"]).nPaths.shift(1) == 1
    un = f[(f.nPaths == 1) & f.prevUnamb & f.travel.notna()]
    rng = np.random.default_rng(5)
    D = {s: np.sqrt(((np.arange(s * s)[:, None] // s - np.arange(s * s)[None, :] // s) ** 2) +
                    ((np.arange(s * s)[:, None] % s - np.arange(s * s)[None, :] % s) ** 2)) for s in (4, 5)}
    # End-to-start travel is what the hand does; centroid distance is where the eye works.
    # A family continuation (TEN -> TENS) restarts at the stem, so it travels far by the first
    # measure and not at all by the second.
    cr = np.array([np.mean([(ord(c) - 97) // s for c in p]) for p, s in zip(f.path.values, f.side.values)])
    cc = np.array([np.mean([(ord(c) - 97) % s for c in p]) for p, s in zip(f.path.values, f.side.values)])
    f["cr"], f["cc"] = cr, cc
    same = (f.gid.values[1:] == f.gid.values[:-1]) & (f.who.values[1:] == f.who.values[:-1])
    cd = np.full(len(f), np.nan)
    cd[1:][same] = np.hypot(np.diff(cr), np.diff(cc))[same]
    f["centroidDist"] = cd
    un = f[(f.nPaths == 1) & f.prevUnamb & f.travel.notna()]
    r["travel"] = {}
    for who in ("player", "opponent"):
        x = f[(f.who == who) & (f.nPaths == 1)]
        sh, shc = [], []
        for (gid, side), y in x.groupby(["gid", "side"]):
            idx = rng.permutation(len(y))
            p = y.path.values[idx]
            a_r, a_c = y.cr.values[idx], y.cc.values[idx]
            sh.extend(D[side][ord(a[-1]) - 97, ord(b[0]) - 97] for a, b in zip(p[:-1], p[1:]))
            shc.extend(np.hypot(np.diff(a_r), np.diff(a_c)))
        u = un[un.who == who]
        r["travel"][who] = {"assignedAll": float(f[f.who == who].travel.mean()), "unambiguous": float(u.travel.mean()),
                            "unambiguousN": int(len(u)), "shuffledUnambiguous": float(np.mean(sh)),
                            "centroidUnambiguous": float(u.centroidDist.mean()), "centroidShuffled": float(np.mean(shc)),
                            "unambiguousByGrid": u.groupby("side").travel.mean().to_dict()}
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.2))
    tsv = {}
    for ax, col, key, ylabel, title in ((axes[0], "travel", "shuffledUnambiguous", "cells, end to next start", "Hand travel"),
                                        (axes[1], "centroidDist", "centroidShuffled", "cells, centroid to centroid", "Where the eye moves")):
        for who, color in (("player", PLAYER), ("opponent", OPP)):
            t = boot_ratio_clustered(un[(un.who == who) & (un.pos < 60)].assign(b=lambda d: d.pos // 5 * 5), "gid", "b", col)
            band(ax, t.b + 3, t, color, "you" if who == "player" else "opponents")
            tsv[f"{col}_{who}"] = t
        ax.axhline(r["travel"]["player"][key], color=PLAYER, ls=":", lw=1, label="you, shuffled order")
        ax.set_xlabel("find number (bins of 5)")
        ax.set_ylabel(ylabel)
        ax.set_title(title + " between consecutive single-path finds")
    axes[0].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "s3_travel", tsv, "Travel between consecutive finds, unambiguous transitions only, against the same finds shuffled.")

    # ---- region revisits ------------------------------------------------------------
    rv = {}
    for who in ("player", "opponent"):
        x = f[f.who == who].copy()
        x["region"] = np.concatenate([region_of(y.path.values, s) for (gid, s), y in x.groupby(["gid", "side"], sort=False)])
        new_visit = (x.region != x.groupby("gid").region.shift()).values
        x["visit"] = np.cumsum(new_visit)
        v = x.groupby("visit").agg(gid=("gid", "first"), region=("region", "first"), finds=("word", "size"),
                                   pts=("pts", "sum"), start=("pos", "min"))
        v["revisit"] = v.duplicated(["gid", "region"])
        rv[who] = {"visitsPerGame": float(v.groupby("gid").size().mean()), "revisitShare": float(v.revisit.mean()),
                   "findsPerVisitFirst": float(v[~v.revisit].finds.mean()), "findsPerVisitRevisit": float(v[v.revisit].finds.mean()),
                   "ptsPerFindFirst": float(v[~v.revisit].pts.sum() / v[~v.revisit].finds.sum()),
                   "ptsPerFindRevisit": float(v[v.revisit].pts.sum() / v[v.revisit].finds.sum()),
                   "shareOfPointsFromRevisits": float(v[v.revisit].pts.sum() / v.pts.sum())}
    r["regions"] = rv

    # ---- cell-use heatmap, normalised by availability ---------------------------------
    sol = load_solutions(["gid", "word", "paths"])
    sol = sol.merge(g[["gid", "side"]], on="gid")
    heat = {}
    fig, axes = plt.subplots(2, 3, figsize=(10, 6.4))
    rows = []
    for i, side in enumerate((4, 5)):
        s = sol[sol.side == side]
        npaths = s.paths.str.count(",").values + 1
        strs = s.paths.values
        lens = np.array([len(x) for x in strs])
        buf = np.frombuffer("".join(strs).encode(), dtype=np.uint8)
        w = np.repeat(1.0 / npaths, lens)
        keep = buf != ord(",")
        avail = np.bincount(buf[keep] - 97, weights=w[keep], minlength=side * side)[: side * side]
        avail = avail / avail.sum()
        out = {}
        for who in ("player", "opponent"):
            p = f[(f.side == side) & (f.who == who)].path.values
            b = np.frombuffer("".join(p).encode(), dtype=np.uint8) - 97
            use = np.bincount(b, minlength=side * side)[: side * side].astype(float)
            out[who] = use / use.sum()
        ratio = out["player"] / avail
        for j, (m, title, cmap, vmin, vmax) in enumerate(((out["player"] * side * side, "your use / uniform", "Blues", 0.6, 1.4),
                                                        (avail * side * side, "availability / uniform", "Blues", 0.6, 1.4),
                                                        (ratio, "your use / availability", "RdBu_r", 0.8, 1.2))):
            ax = axes[i, j]
            M = m.reshape(side, side)
            ax.imshow(M, cmap=cmap, vmin=vmin, vmax=vmax)
            for a in range(side):
                for c in range(side):
                    ax.text(c, a, f"{M[a, c]:.2f}", ha="center", va="center", fontsize=8)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
            ax.set_title(f"{side}x{side} {title}", fontsize=9)
        heat[f"{side}x{side}"] = {"ratioMin": float(ratio.min()), "ratioMax": float(ratio.max()),
                                  "oppRatioMin": float((out["opponent"] / avail).min()), "oppRatioMax": float((out["opponent"] / avail).max()),
                                  "playerVsOppMaxAbsDiff": float(np.abs(out["player"] / out["opponent"] - 1).max())}
        for c in range(side * side):
            rows.append({"grid": f"{side}x{side}", "cell": c, "row": c // side, "col": c % side, "playerUse": out["player"][c],
                         "opponentUse": out["opponent"][c], "availability": avail[c], "playerOverAvailability": ratio[c]})
    fig.tight_layout()
    save(fig, "s3_heatmap", pd.DataFrame(rows), "Cumulative cell use. Left: your use; middle: where present words' paths run; right: the ratio.")
    r["heatmap"] = heat

    # ---- are missed high-value words in worked regions? ------------------------------------
    r["missedLong"] = missed_long(g, f, pres, sol)
    R["s3"] = r


def missed_long(g, f, pres, sol):
    """Find rate of present 6+ letter words against how hard the player worked their cells.

    Intensity of a word = mean, over its cells, of the player's cell-use count on that board
    divided by the board's mean cell use, excluding the word's own contribution when found.
    Over multiple paths, the most-worked path counts (the charitable reading of 'worked').
    """
    pl = f[f.who == "player"]
    side_of = dict(zip(g.gid, g.side))
    use = {}
    for gid, y in pl.groupby("gid"):
        s = side_of[gid]
        b = np.frombuffer("".join(y.path.values).encode(), dtype=np.uint8) - 97
        use[gid] = np.bincount(b, minlength=s * s).astype(float)
    long = pres[pres.len >= 6][["gid", "word", "len", "pts", "foundPlayer", "foundOpp"]]
    long = long.merge(sol[["gid", "word", "paths"]], on=["gid", "word"])
    own = dict(zip(zip(pl.gid, pl.word), pl.path))
    inten, touched = np.empty(len(long)), np.empty(len(long))
    for i, (gid, word, paths, found) in enumerate(zip(long.gid.values, long.word.values, long.paths.values, long.foundPlayer.values)):
        u = use.get(gid)
        if u is None:
            inten[i] = touched[i] = np.nan
            continue
        u = u.copy()
        if found:
            for c in own[(gid, word)]:
                u[ord(c) - 97] -= 1
        mean = u.mean() or 1.0
        best, tb = -1.0, 0.0
        for p in paths.split(",")[:16]:
            cs = [ord(c) - 97 for c in p]
            v = u[cs].mean() / mean
            if v > best:
                best, tb = v, float((u[cs] > 0).all())
        inten[i], touched[i] = best, tb
    long["intensity"] = inten
    long["allTouched"] = touched
    long = long.dropna(subset=["intensity"])
    long["q"] = pd.qcut(long.intensity, 10, labels=False, duplicates="drop")
    t = boot_ratio_clustered(long.assign(y=long.foundPlayer.astype(float)), "gid", "q", "y")
    lo = long[long.foundOpp.fillna(False).astype(bool) & ~long.foundPlayer]
    to = boot_ratio_clustered(long[long.foundOpp.notna()].assign(y=long.foundOpp.fillna(False).astype(float)), "gid", "q", "y")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
    band(axes[0], t.q + 1, t, PLAYER, "you find it")
    band(axes[0], to.q + 1, to, OPP, "opponent finds it")
    axes[0].set_xlabel("decile of local work intensity (your cell use on the word's path)")
    axes[0].set_ylabel("P(found | present, 6+ letters)")
    axes[0].set_title("Do long words get found where you work?")
    axes[0].legend(fontsize=7.5)
    miss = long[~long.foundPlayer]
    axes[1].hist([miss.intensity.clip(0, 3), long[long.foundPlayer].intensity.clip(0, 3), lo.intensity.clip(0, 3)], bins=30, density=True,
                 color=[OPP, PLAYER, STRONG], label=["missed by you", "found by you", "missed by you, found by opponent"], histtype="step", linewidth=2)
    axes[1].set_xlabel("local work intensity (1 = board average)")
    axes[1].set_ylabel("density")
    axes[1].set_title("Where the missed 6+ words sit")
    axes[1].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "s3_missed_long_words", {"player": t, "opponent": to}, "Find rate of present 6+ letter words by your work intensity on their cells.")
    return {"words": int(len(long)), "missed": int(len(miss)), "missedAllCellsTouched": float(miss.allTouched.mean()),
            "missedIntensityMedian": float(miss.intensity.median()), "oppFoundMissedIntensityMedian": float(lo.intensity.median()),
            "missedInWorkedRegionShare": float((miss.intensity >= 1).mean()),
            "oppFoundMissedInWorkedRegionShare": float((lo.intensity >= 1).mean()),
            "findRateByDecile": t["mean"].round(4).tolist(), "oppFindRateByDecile": to["mean"].round(4).tolist()}

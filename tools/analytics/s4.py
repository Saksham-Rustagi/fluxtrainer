"""Report section 4: vocabulary and families, and the realized Phase 1 proxies."""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import binomtest

import boardpass
import holdout
import peer
import viz
from common import FIGS, RANKED
from viz import EXTRA, INK2, OPP, PEER, PLAYER, STRONG, WEAK, band, bh, boot_mean, boot_ratio_clustered, note_n, plt

# Section 4 runs twice: seasons 7-10 (primary: figures, holdouts) and the full range
# (secondary: numbers only). A word's find rate given presence is comparable across
# regimes, but the board mix generating the presences is not.
PRIMARY = True


def save(fig, *a, **k):
    if PRIMARY:
        viz.save(fig, *a, **k)
    else:
        plt.close(fig)

LC = [3, 4, 5, 6, 7]


def beta_mom(p, n):
    """Beta prior by method of moments on per-word rates, correcting for binomial noise."""
    m = np.average(p, weights=n)
    v = np.average((p - m) ** 2, weights=n) - np.mean(m * (1 - m) / n)
    v = max(v, 1e-4)
    common = m * (1 - m) / v - 1
    common = max(common, 0.5)
    return m * common, (1 - m) * common


def section4(R, g, f, pres):
    global PRIMARY
    bp = boardpass.run(pres, g, "voc")
    cur = g[g.current]
    PRIMARY = True
    R["s4"] = _core(R, cur, pres[pres.gid.isin(cur.gid)], {k: _sub(v, cur.gid) for k, v in bp.items()})
    PRIMARY = False
    R["s4_all"] = _core(R, g, pres, bp)
    PRIMARY = True  # the learning curve is a full-range figure by design
    R["s4_all"].update(learning_curve(pres.merge(g[["gid", "season"]], on="gid").assign(
        lc=lambda d: np.minimum(d.len, 7), fp=lambda d: d.foundPlayer.astype(float)), g))
    PRIMARY = True
    import sbase
    R["s4"]["baselines"] = sbase.baselines(R, cur, pres[pres.gid.isin(cur.gid)], {k: _sub(v, cur.gid) for k, v in bp.items()}, primary=True)
    R["s4_all"]["baselines"] = sbase.baselines(R, g, pres, bp, primary=False)


def _sub(v, gids):
    return v[v.gid.isin(set(gids))] if isinstance(v, pd.DataFrame) and "gid" in v.columns else v


def _core(R, g, pres, bp):
    r = {}
    p = pres.merge(g[["gid", "season", "timeQuartile", "grid", "tier", "nWords", "split", "margin", "oppEloLoo"]], on="gid", suffixes=("", "_g"))
    p["lc"] = np.minimum(p.len, 7)
    p["fp"] = p.foundPlayer.astype(float)

    # ---- 4.1 belief: raw and opportunity-weighted ----------------------------------------
    # Opportunity of a presence = how likely a known word of that length was to be taken on
    # that board: the board's find rate for the length class, relative to the rate on the
    # boards where he took the most (90th percentile), capped at 1. On a 900-word board where
    # he found 96, opportunity is small, and a miss there says little about knowledge.
    br = p.groupby(["gid", "lc"]).agg(n=("fp", "size"), k=("fp", "sum")).reset_index()
    br["rate"] = br.k / br.n
    br = br.merge(g[["gid", "grid"]], on="gid")
    ref = br.groupby(["grid", "lc"]).rate.quantile(0.9).rename("ref").reset_index()
    br = br.merge(ref, on=["grid", "lc"])
    br["opp"] = (br.rate / br.ref).clip(upper=1)
    p = p.merge(br[["gid", "lc", "opp"]], on=["gid", "lc"])
    r["opportunityRef"] = ref.assign(key=ref.grid + "_" + ref.lc.astype(str)).set_index("key").ref.round(4).to_dict()
    r["meanOpportunity"] = p.groupby("lc").opp.mean().round(4).to_dict()

    def beliefs(d, suffix=""):
        w = d.groupby("word").agg(len=("len", "first"), present=("fp", "size"), found=("fp", "sum"), opp=("opp", "sum"),
                                  pts=("pts", "first"))
        w["lc"] = np.minimum(w.len, 7)
        w["beliefRaw"] = np.nan
        w["beliefWeighted"] = np.nan
        priors = {}
        for L, x in w.groupby("lc"):
            fit = x[x.present >= 10]
            a, b = beta_mom((fit.found / fit.present).values, fit.present.values)
            aw, bw = beta_mom((fit.found / fit.opp).clip(upper=1).values, fit.opp.values)
            w.loc[x.index, "beliefRaw"] = (x.found + a) / (x.present + a + b)
            w.loc[x.index, "beliefWeighted"] = ((x.found + aw) / (x.opp + aw + bw)).clip(upper=1)
            priors[int(L)] = {"raw": [a, b], "weighted": [aw, bw]}
        return w, priors

    wb, priors = beliefs(p)
    r["beliefPriors"] = priors
    r["coverage"] = {f"present>={k}": int((wb.present >= k).sum()) for k in (1, 5, 10, 20, 50)}
    r["coverage"]["presencesCoveredBy>=10"] = float(wb[wb.present >= 10].present.sum() / wb.present.sum())
    r["coverage"]["distinctWordsPresent"] = int(len(wb))
    r["coverage"]["distinctWordsFound"] = int((wb.found > 0).sum())
    cov = wb[wb.present >= 10]
    r["beliefByLen"] = {int(L): {"n": int(len(x)), "rawMedian": float(x.beliefRaw.median()), "weightedMedian": float(x.beliefWeighted.median()),
                                 "rawMean": float(x.beliefRaw.mean()), "weightedMean": float(x.beliefWeighted.mean()),
                                 "shareWeightedOver065": float((x.beliefWeighted > 0.65).mean()),
                                 "shareWeightedUnder035": float((x.beliefWeighted < 0.35).mean()),
                                 "shareRawUnder035": float((x.beliefRaw < 0.35).mean())}
                         for L, x in cov.groupby("lc")}
    r["rawVsWeighted"] = {"spearman": float(cov.beliefRaw.corr(cov.beliefWeighted, method="spearman")),
                          "meanDiff": float((cov.beliefWeighted - cov.beliefRaw).mean()),
                          "unknownRawButNotWeighted": int(((cov.beliefRaw < 0.35) & (cov.beliefWeighted >= 0.35)).sum()),
                          "ownedWeightedNotRaw": int(((cov.beliefWeighted > 0.65) & (cov.beliefRaw <= 0.65)).sum()),
                          "words": int(len(cov))}
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    data = [cov[cov.lc == L] for L in LC]
    pos = np.arange(len(LC))
    for off, col, color, label in ((-0.18, "beliefRaw", OPP, "raw found/present"), (0.18, "beliefWeighted", PLAYER, "opportunity-weighted")):
        box = axes[0].boxplot([d[col] for d in data], positions=pos + off, widths=0.3, patch_artist=True, showfliers=False,
                             medianprops={"color": "black"})
        for patch in box["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        axes[0].plot([], [], color=color, lw=6, alpha=0.6, label=label)
    axes[0].set_xticks(pos)
    axes[0].set_xticklabels([f"{L if L < 7 else '7+'}\n(n={len(d):,})" for L, d in zip(LC, data)])
    axes[0].set_xlabel("word length (words present on 10+ boards)")
    axes[0].set_ylabel("belief (Beta-smoothed)")
    axes[0].set_title("Belief by length, raw vs weighted")
    axes[0].legend(fontsize=7.5)
    s = cov.sample(min(6000, len(cov)), random_state=1)
    axes[1].scatter(s.beliefRaw, s.beliefWeighted, s=3, alpha=0.3, color=PLAYER)
    axes[1].plot([0, 1], [0, 1], color=INK2, lw=1)
    for v in (0.35, 0.65):
        axes[1].axvline(v, color=INK2, lw=0.6, ls=":")
        axes[1].axhline(v, color=INK2, lw=0.6, ls=":")
    axes[1].set_xlabel("raw belief")
    axes[1].set_ylabel("opportunity-weighted belief")
    axes[1].set_title("How much the weighting moves each word")
    note_n(axes[1], f"{len(s):,} of {len(cov):,} words shown")
    fig.tight_layout()
    save(fig, "s4_1_belief", cov.reset_index()[["word", "len", "present", "found", "opp", "beliefRaw", "beliefWeighted"]],
         "Per-word belief, raw against opportunity-weighted, words present on 10+ boards. Dotted lines: spec 7.5.1 thresholds.")

    # first vs last time quartile
    q1, _ = beliefs(p[p.timeQuartile == 1])
    q4, _ = beliefs(p[p.timeQuartile == 4])
    both = q1[["beliefWeighted", "present", "lc"]].join(q4[["beliefWeighted", "present"]], lsuffix="1", rsuffix="4", how="inner")
    both = both[(both.present1 >= 5) & (both.present4 >= 5)]
    both["d"] = both.beliefWeighted4 - both.beliefWeighted1
    r["beliefShiftQ1toQ4"] = {int(L): boot_mean(x.d.values)[:4] for L, x in both.groupby("lc")}
    r["beliefShiftQ1toQ4"]["all"] = boot_mean(both.d.values)[:4]

    # time-sliced variants and the belief table later phases consume (written from the full-range run)
    if not PRIMARY:
        cur, _ = beliefs(p[p.season >= 7])
        tr, _ = beliefs(p[p.split == "train"])
        te, _ = beliefs(p[p.split == "test"])
        out = wb.join(cur[["present", "found", "beliefWeighted"]].add_suffix("_s7to10"))
        out = out.join(tr[["present", "found", "beliefWeighted"]].add_suffix("_train")).join(te[["present", "found", "beliefWeighted"]].add_suffix("_test"))
        out = out.join(q1[["present", "found", "beliefWeighted"]].add_suffix("_q1")).join(q4[["present", "found", "beliefWeighted"]].add_suffix("_q4"))
        out.reset_index().rename(columns={"opp": "opportunity"}).to_csv(os.path.join(RANKED, "belief.tsv"), sep="\t", index=False, float_format="%.5g")

    # ---- 4.2 pure vocabulary holes ----------------------------------------------------------
    # A hole is a word a reference group takes and you never do. The null for each word is
    # your finding it at that group's observed rate. Three reference groups: all opponents
    # (your equals), strong opponents (beat you by 10k+) and the top quartile of opponents
    # by leave-one-out rating.
    p["fo"] = p.foundOpp.astype("float")
    topq = p.oppEloLoo >= g.oppEloLoo.quantile(0.75)
    refs = {"field": p.foundOpp.notna(), "strong": p.foundOpp.notna() & (p.margin <= -10000),
            "topQuartile": p.foundOpp.notna() & topq}
    found3 = set(wb[wb.found >= 3].index)

    def stem_in(w):
        L = len(w)
        for k in range(L - 1, max(2, L - 4), -1):
            for st in range(L - k + 1):
                if w[st:st + k] in found3:
                    return w[st:st + k]
        return ""

    r["holes"] = {}
    sigs = {}
    for ref, mask in refs.items():
        ow = p[mask].groupby("word").agg(refN=("fo", "size"), refK=("fo", "sum"))
        allw = wb[wb.present >= 10].join(ow, how="inner")
        allw = allw[allw.refN >= 5]
        allw["refRate"] = allw.refK / allw.refN
        allw["p"] = np.where(allw.found == 0, (1 - allw.refRate.clip(upper=0.999)) ** allw.present, 1.0)
        allw["q"] = bh(allw.p.values)
        allw["refForgone"] = allw.present * allw.refRate * allw.pts
        cand = allw[allw.found == 0].copy()
        cand["foundStem"] = [stem_in(w) for w in cand.index]
        cand["kind"] = np.where(cand.foundStem != "", "branch miss", "true gap")
        sig = cand[cand.q < 0.05].sort_values("refForgone", ascending=False)
        sigs[ref] = sig
        games_ = g.gid.nunique()
        r["holes"][ref] = {"candidates": int(len(cand)), "significant": int(len(sig)), "byKind": sig.kind.value_counts().to_dict(),
                           "pointsPerGame": float(sig.refForgone.sum() / games_),
                           "top": sig.head(40).reset_index()[["word", "len", "present", "refRate", "refForgone", "kind", "foundStem", "q"]].round(4).to_dict("records")}
    sig = sigs["topQuartile"]
    top = sig.head(30).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(np.arange(len(top)), top.refForgone, color=[STRONG if k == "branch miss" else PLAYER for k in top.kind])
    ax.set_yticks(np.arange(len(top)))
    ax.set_yticklabels([f"{w}  {int(n)}x, top-quartile opp. {o:.0%}" + (f", stem {s}" if s else "") for w, n, o, s in
                        zip(top.index, top.present, top.refRate, top.foundStem)], fontsize=7.5)
    ax.set_xlabel("points forgone at the top-quartile opponents' find rate, seasons 7-10")
    ax.set_title("Words the strongest opponents take and you never have (BH q < 0.05)")
    ax.plot([], [], color=STRONG, lw=6, label="branch miss: contains a stem you find")
    ax.plot([], [], color=PLAYER, lw=6, label="true gap")
    ax.legend(fontsize=7.5, loc="lower right")
    save(fig, "s4_2_vocabulary_holes", pd.concat([v.reset_index().assign(reference=k) for k, v in sigs.items()], ignore_index=True),
         "Words present 10+ times, never found by you, and taken by a reference group often enough that zero is significant (BH). Reference: top-quartile opponents by leave-one-out rating; all three references in the TSV.")
    if PRIMARY:
        # holdout: holes flagged against top-quartile opponents on the train period; on the test period,
        # your find rate minus top-quartile opponents' on the same presences
        trp = p[(p.split == "train") & refs["topQuartile"]]
        tw = p[p.split == "train"].groupby("word").agg(present=("fp", "size"), found=("fp", "sum")).join(
            trp.groupby("word").fo.mean().rename("refRate"), how="inner")
        tw = tw[tw.present >= 5]
        tw["p"] = np.where(tw.found == 0, (1 - tw.refRate.clip(upper=0.999)) ** tw.present, 1.0)
        tw["q"] = bh(tw.p.values)
        flagged = set(tw[(tw.found == 0) & (tw.q < 0.05)].index)
        fl = p[p.word.isin(flagged) & p.foundOpp.notna()]
        diff = (fl.fp - fl.fo).groupby(fl.gid).sum()
        cnt = fl.groupby("gid").size()
        holdout.per_game(R, f"{len(flagged)} holes vs top-quartile opponents (flagged on train): your find rate minus opponents'", g, diff, cnt,
                         unit="find rate")
        r["holesHoldout"] = {"flagged": len(flagged)}

    # ---- 4.3 fragile knowledge / retention --------------------------------------------------
    q = p.sort_values(["word", "gid"])[["word", "gid", "lc", "fp", "opp", "season"]].copy()
    q["prior"] = q.groupby("word").fp.cumsum() - q.fp
    q["prevFound"] = q.groupby("word").fp.shift(1)
    q["pb"] = pd.cut(q.prior, [-1, 0, 1, 2, 5, 1e9], labels=["0", "1", "2", "3-5", "6+"])
    fig, ax = plt.subplots(figsize=(7, 3.4))
    tsv = {}
    ret = {}
    for L, color in zip(LC, [PLAYER, STRONG, WEAK, EXTRA[0], EXTRA[1]]):
        x = q[q.lc == L]
        t = boot_ratio_clustered(x.assign(pbi=x.pb.cat.codes), "word", "pbi", "fp", b=200)
        band(ax, t.pbi, t, color, "7+" if L == 7 else str(L))
        tsv[str(L)] = t
        ret[L] = t["mean"].round(4).tolist()
    ax.set_xticks(range(5))
    ax.set_xticklabels(["0 (first-find\nhazard)", "1", "2", "3-5", "6+"])
    ax.set_xlabel("times found before this presence")
    ax.set_ylabel("P(found at this presence)")
    ax.set_title("Does a find stick? Find rate by prior finds")
    ax.legend(title="length", fontsize=7.5, ncol=5)
    save(fig, "s4_3_retention", tsv, "Find rate at a presence as a function of how many times the word was found before (bootstrap over words).")
    # conditional on one prior find: after a find vs after a miss at the previous presence
    one = q[q.prior == 1]
    r["retention"] = {"byPriorFinds": {str(k): v for k, v in ret.items()},
                      "prior1_prevFound": float(one[one.prevFound == 1].fp.mean()),
                      "prior1_prevMissed": float(one[one.prevFound == 0].fp.mean())}
    last = q.groupby("word").agg(k=("fp", "sum"), n=("fp", "size"), len=("lc", "first"))
    lastfind = q[q.fp == 1].groupby("word").gid.max()
    after = q.merge(lastfind.rename("lastFind"), left_on="word", right_index=True, how="left")
    after = after[after.gid > after.lastFind].groupby("word").size().rename("missesAfterLastFind")
    frag = last.join(after, how="inner")
    frag = frag[(frag.k <= 2) & (frag.k >= 1) & (frag.missesAfterLastFind >= 5)]
    frag["pts"] = [100 if len(w) == 3 else 400 if len(w) == 4 else 800 if len(w) == 5 else 1400 + 400 * (len(w) - 6) for w in frag.index]
    frag["forgone"] = frag.pts * frag.missesAfterLastFind
    once = last[(last.k == 1)].join(after, how="left").fillna(0)
    r["fragile"] = {"count": int(len(frag)), "foundOnceWith5LaterPresences": int(((last.k == 1) & (once.missesAfterLastFind >= 5)).sum()),
                    "top": frag.sort_values("forgone", ascending=False).head(25).reset_index()[["word", "k", "missesAfterLastFind", "forgone"]].to_dict("records")}
    frag.sort_values("forgone", ascending=False).reset_index().to_csv(os.path.join(FIGS, "s4_3_fragile_words.tsv"), sep="\t", index=False)

    # ---- board pass: families, affixes, anagrams, Phase 1 proxies --------------------------------
    r.update(families(R, bp))
    r.update(affixes(R, bp))
    r.update(anagrams(R, bp, None))
    r.update(phase1_proxies(R, bp))
    return r


def families(R, bp):
    fam = bp["fam"]
    t = fam[fam.foundP >= 1].copy()
    t["share"] = t.foundP / t["size"]
    t["sizeB"] = pd.cut(t["size"], [1, 2, 3, 5, 9, 1000], labels=["2", "3", "4-5", "6-9", "10+"])
    t["stemB"] = np.minimum(t.stemLen, 7)
    out = {}
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
    tsv = {}
    for ax, col, label in zip(axes, ("sizeB", "stemB", "tier"), ("family size on board", "stem length", "tier (MAP)")):
        res = boot_ratio_clustered(t.assign(one=1.0), "gid", col, "foundP", "size")
        tsv[col] = res
        ax.bar(np.arange(len(res)), res["mean"], color=PLAYER, width=0.6, label="player")
        ax.errorbar(np.arange(len(res)), res["mean"], yerr=[res["mean"] - res.lo, res.hi - res["mean"]], fmt="none", color=INK2)
        so = fam[(fam.foundO >= 1)].assign(sizeB=lambda d: pd.cut(d["size"], [1, 2, 3, 5, 9, 1000], labels=["2", "3", "4-5", "6-9", "10+"]),
                                          stemB=lambda d: np.minimum(d.stemLen, 7))
        ro = boot_ratio_clustered(so, "gid", col, "foundO", "size")
        ax.plot(np.arange(len(ro)), ro["mean"], "o", color=OPP, label="opponents")
        pc = ((peer.results() or {}).get("s4") or {}).get(f"completionBy_{col}") if PRIMARY else None
        if pc:
            ax.plot(np.arange(len(res)), [pc.get(str(k), [np.nan])[0] for k in res[col]], "D", color=PEER, label=peer.LABEL)
            tsv[col + "_peer"] = pd.DataFrame({col: list(pc), "peer": [v[0] for v in pc.values()]})
        ax.set_xticks(np.arange(len(res)))
        ax.set_xticklabels([str(v) for v in res[col]])
        ax.set_xlabel(label)
        ax.set_title(f"Family completion by {label}")
        out[f"completionBy_{col}"] = {str(k): [m, o] for k, m, o in zip(res[col], res["mean"], ro["mean"])}
    axes[0].set_ylabel("share of family found | 1+ member found")
    axes[0].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "s4_4_family_completion", tsv, "Share of an on-board family found, given at least one member was found. Family = present words containing a present word-stem of 4+ letters.")
    status = np.select([t.foundP == t["size"]], ["all"], "some")
    fam_any = fam.assign(status=np.select([fam.foundP == 0, fam.foundP == fam["size"]], ["none", "all"], "some"))
    out["familyStatus"] = fam_any.status.value_counts(normalize=True).round(4).to_dict()
    out["familyStatusOpp"] = fam.assign(s=np.select([fam.foundO == 0, fam.foundO == fam["size"]], ["none", "all"], "some")).s.value_counts(normalize=True).round(4).to_dict()
    out["familyCompletion"] = float(t.foundP.sum() / t["size"].sum())
    to = fam[fam.foundO >= 1]
    out["familyCompletionOpp"] = float(to.foundO.sum() / to["size"].sum())
    out["familiesPerBoard"] = float(fam.groupby("gid").size().mean())
    return out


def affixes(R, bp):
    a = bp["affix"]
    pl = a[a.stemFoundP & a.reachable].copy()
    pl["pts"] = pl.word.str.len().map(lambda L: 100 if L == 3 else 400 if L == 4 else 800 if L == 5 else 1400 + 400 * (L - 6))
    base = pl.wordFoundP.mean()
    op = a[a.stemFoundO & a.reachable]
    t = pl.groupby("affix").agg(opps=("wordFoundP", "size"), taken=("wordFoundP", "sum"), forgone=("pts", lambda s: 0))
    t["forgone"] = pl[~pl.wordFoundP].groupby("affix").pts.sum().reindex(t.index).fillna(0)
    t["rate"] = t.taken / t.opps
    o = op.groupby("affix").agg(oppOpps=("wordFoundO", "size"), oppTaken=("wordFoundO", "sum"))
    t = t.join(o)
    t["oppRate"] = t.oppTaken / t.oppOpps
    t = t[(t.opps >= 30) & (t.oppOpps >= 30)]
    # The question is systematic failure, so the comparison is the field's take rate for the same
    # affix in the same situation (stem found, extension present and reachable), not his average.
    from statsmodels.stats.proportion import proportions_ztest
    t["p"] = [proportions_ztest([k, ko], [n, no], alternative="smaller")[1] for k, n, ko, no in zip(t.taken, t.opps, t.oppTaken, t.oppOpps)]
    t["q"] = bh(t.p.values)
    t["excessForgone"] = (t.oppRate - t.rate) * t.opps * pl.groupby("affix").pts.mean().reindex(t.index)
    t = t.sort_values("forgone", ascending=False)
    if PRIMARY:
        t.reset_index().to_csv(os.path.join(FIGS, "s4_5_affixes_all.tsv"), sep="\t", index=False, float_format="%.5g")
    top = t.head(25).iloc[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(11, 6.2), gridspec_kw={"width_ratios": [1.3, 1]}, sharey=True)
    y = np.arange(len(top))
    axes[0].barh(y, top.forgone / 1000, color=[STRONG if q < 0.05 and d > 0 else OPP for q, d in zip(top.q, top.excessForgone)])
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(top.index, fontsize=8)
    axes[0].set_xlabel("points forgone, all games (thousands)")
    axes[0].set_title("Additive extensions left on the board, by affix")
    axes[1].plot(top.rate, y, "o", color=PLAYER, label="your take rate")
    axes[1].plot(top.oppRate, y, "o", color=OPP, label="opponents' take rate")
    prates = (((peer.results() or {}).get("s4") or {}).get("affix") or {}).get("rates") if PRIMARY else None
    if prates:
        axes[1].plot([prates.get(a, np.nan) for a in top.index], y, "D", color=PEER, markersize=4, label=f"{peer.LABEL}")
    axes[1].set_xlabel("P(extension found | stem found, extension present and reachable)")
    axes[1].set_title("Take rate")
    axes[1].legend(fontsize=7.5, loc="lower right")
    axes[0].plot([], [], color=STRONG, lw=6, label="you take it less often than opponents, BH q<0.05")
    axes[0].legend(fontsize=7.5, loc="lower right")
    fig.tight_layout()
    save(fig, "s4_5_affix_misses", t.reset_index(), "Additive extensions (1-3 letters) present and path-reachable from a found stem, by affix.")
    out = {"affix": {"baseTakeRate": float(base), "oppBaseTakeRate": float(op.wordFoundO.mean()), "affixesTested": int(len(t)),
                     "significantLow": int((t.q < 0.05).sum()), "top": t.head(20).reset_index().round(4).to_dict("records"),
                     "worstVsField": t[t.q < 0.05].sort_values("excessForgone", ascending=False).head(15).reset_index().round(4).to_dict("records"),
                     "excessForgoneSignificant": float(t[t.q < 0.05].excessForgone.sum()),
                     "suffixVsPrefix": {"suffix": float(pl[pl.affix.str.startswith("-")].wordFoundP.mean()),
                                        "prefix": float(pl[pl.affix.str.endswith("-")].wordFoundP.mean())},
                     "presentButNotReachable": float(1 - a[a.stemFoundP].reachable.mean()),
                     "rates": t.rate.round(4).to_dict()}}
    return out


def anagrams(R, bp, _):
    a = bp["ana"]
    t = a[a.foundP >= 1]
    out = {"anagramSetsPerBoard": float(a.groupby("gid").size().mean()),
           "completionGivenOne": float(t.foundP.sum() / t.present.sum()),
           "completionGivenOneOpp": float(a[a.foundO >= 1].foundO.sum() / a[a.foundO >= 1].present.sum()),
           "completeShare": float((t.foundP == t.present).mean())}
    pts = lambda L: 100 if L == 3 else 400 if L == 4 else 800 if L == 5 else 1400 + 400 * (L - 6)  # noqa: E731
    a = a.assign(missedPts=(a.present - a.foundP) * a.len.map(pts), cellmateMissedPts=np.where(a.foundP >= 1, (a.present - a.foundP) * a.len.map(pts), 0))
    w = a.groupby("key").agg(len=("len", "first"), boards=("gid", "size"), present=("present", "sum"), found=("foundP", "sum"),
                             foundByOpp=("foundO", "sum"), cellmateMissedPts=("cellmateMissedPts", "sum"), missedPts=("missedPts", "sum"))
    w["completion"] = w.found / w.present
    w = w.sort_values("cellmateMissedPts", ascending=False)
    w.reset_index().to_csv(os.path.join(FIGS, "s4_6_anagram_sets.tsv"), sep="\t", index=False, float_format="%.4g")
    out["worstSets"] = w.head(20).reset_index().round(4).to_dict("records")
    by = t.groupby("len").apply(lambda x: x.foundP.sum() / x.present.sum()).round(4).to_dict()
    out["completionByLen"] = {int(k): v for k, v in by.items()}
    top = w.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    ax.barh(np.arange(len(top)), top.cellmateMissedPts / 1000, color=PLAYER)
    ax.set_yticks(np.arange(len(top)))
    ax.set_yticklabels([f"{k} ({c:.0%} complete, {int(b)} boards)" for k, c, b in zip(top.index, top.completion, top.boards)], fontsize=7.5)
    ax.set_xlabel("points left in the set after finding at least one member (thousands)")
    ax.set_title("Anagram sets: cellmates left behind")
    save(fig, "s4_6_anagram_sets", w.head(200).reset_index(), "Anagram sets (sorted-letter keys) ranked by points left once one member was found.")
    return {"anagram": out}


def learning_curve(p, g):
    first = p[p.foundPlayer].groupby("word").season.min()
    s1 = first[first == 1].index
    x = p[p.word.isin(s1) & (p.season >= 2)]
    ctl = p[p.season >= 2]
    t = boot_ratio_clustered(x.assign(y=x.fp), "word", "season", "y", b=200)
    c = ctl.groupby("season").fp.mean()
    # same-length control: all words, reweighted to the season-1 cohort's length mix
    mix = x.groupby("lc").size() / len(x)
    cw = ctl.groupby(["season", "lc"]).fp.mean().unstack()
    cw = (cw * mix).sum(axis=1)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    band(ax, t.season, t, PLAYER, f"words first found in season 1 ({len(s1):,} words)", marker="o")
    ax.plot(cw.index, cw.values, "s--", color=OPP, label="all present words, same length mix")
    ax.set_xlabel("season")
    ax.set_ylabel("P(found | present)")
    ax.set_title("Does vocabulary stick once acquired?")
    ax.legend(fontsize=7.5)
    save(fig, "s4_7_learning_curve", {"cohort": t, "control": cw.rename("rate").reset_index()}, "Find rate on later presences of words first found in season 1.")
    return {"learningCurve": {"cohortWords": int(len(s1)), "cohort": t.set_index("season")["mean"].round(4).to_dict(),
                              "control": cw.round(4).to_dict()}}


def phase1_proxies(R, bp):
    out = {}
    # M1-real: misses that were free extensions of a word he found on the same board
    m = bp["missed"]
    miss = m[~m.foundP]
    out["m1"] = {"missedWordsPerBoard": float(miss.groupby("gid").size().mean()),
                 "missedFreeShare": float(miss.freeForP.mean()),
                 "missedFreePerBoard": float(miss.groupby("gid").freeForP.sum().mean()),
                 "freeForPlayerPerBoard": float(m.groupby("gid").freeForP.sum().mean()),
                 "freeTakenShare": float(m[m.freeForP].foundP.mean()),
                 "freeTakenShareOpp": float(m[m.freeForO].foundO.mean()),
                 "missedFreeShareByLen": miss.groupby(np.minimum(miss.len, 7)).freeForP.mean().round(4).to_dict(),
                 "missedFreeByExt": miss[miss.freeForP].minExt.clip(upper=4).value_counts(normalize=True).sort_index().round(4).to_dict(),
                 "byTier": {f"{gr}_{t}": {"free": float(x.groupby("gid").freeForP.sum().mean()), "takenShare": float(x[x.freeForP].foundP.mean())}
                            for (gr, t), x in m.groupby(["grid", "tier"])}}
    st = bp["m1stem"]
    out["m1"]["reachableExtPerFoundStem"] = float(st.reachableExt.mean())
    out["m1"]["reachableExtFoundPerFoundStem"] = float(st.reachableExtFound.mean())
    out["m1"]["byTierExt"] = {f"{gr}_{t}": [float(x.reachableExt.mean()), float(x.reachableExtFound.mean())] for (gr, t), x in st.groupby(["grid", "tier"])}
    fr = bp["free"]
    out["m1"]["perfectVocab"] = {"boards": int(len(fr)), "freeWordsPerBoard": float(fr.freeWords.mean()),
                                 "freeShareOfPresent": float((fr.freeWords / fr.present).mean()),
                                 "extPerPresentWord": float(fr.extPerPresentWord.mean())}
    # M2-real: anagram pathability on real boards, and realized cellmate takes
    a = bp["m2"]
    ap = a.groupby("len").apply(lambda x: pd.Series({
        "pPresent": (x.presentInSet * (x.presentInSet - 1)).sum() / (x.presentInSet * x.dictOthers).sum(),
        "pTakenGivenFoundAndPresent": (x.foundP * (x.foundP - 1)).sum() / max((x.foundP * (x.presentInSet - 1)).sum(), 1),
        "pTakenOpp": (x.foundO * (x.foundO - 1)).sum() / max((x.foundO * (x.presentInSet - 1)).sum(), 1),
        "pairs": (x.foundP * (x.presentInSet - 1)).sum()}))
    out["m2"] = ap.round(4).reset_index().to_dict("records")
    # drop-terminal-real
    d = bp["dt"]
    out["dropTerminal"] = {"violations": int(bp["dtViolations"]), "opportunities": int(len(d)), "takeRate": float(d.foundP.mean()),
                           "byShortLen": d.groupby(np.minimum(d.shortLen, 7)).foundP.mean().round(4).to_dict(),
                           "byLongLen": d.groupby(np.minimum(d.longLen, 9)).foundP.mean().round(4).to_dict()}
    dw = bp["dtWords"]
    dw["missed"] = dw.opportunities - dw.found
    dw["rate"] = dw.found / dw.opportunities
    dw = dw[dw.opportunities >= 20].sort_values("missed", ascending=False)
    out["dropTerminal"]["topMissed"] = dw.head(25).round(4).to_dict("records")
    dw.to_csv(os.path.join(FIGS, "s4_8_drop_terminal_words.tsv"), sep="\t", index=False, float_format="%.4g")
    # M3-real
    m3 = bp["m3"]
    rows = []
    for (grid, tier, L, cur), x in m3.groupby(["grid", "tier", "stemLen", "curated"]):
        rows.append({"grid": grid, "tier": tier, "stemLen": L, "curated": cur, "stems": int(x.stems.sum()),
                     "membersPresent": x.members.sum() / x.stems.sum(), "membersFound": x.membersFoundP.sum() / x.stems.sum(),
                     "membersPresentIfStemFound": x.membersIfStemFound.sum() / max(x.stemsFoundP.sum(), 1),
                     "membersFoundIfStemFound": x.membersFoundIfStemFound.sum() / max(x.stemsFoundP.sum(), 1)})
    m3t = pd.DataFrame(rows)
    out["m3"] = m3t.round(4).to_dict("records")
    def pooled(x):
        return {"present": float(x.members / x.stems), "found": float(x.membersFoundP / x.stems),
                "foundIfStemFound": float(x.membersFoundIfStemFound / max(x.stemsFoundP, 1)),
                "presentIfStemFound": float(x.membersIfStemFound / max(x.stemsFoundP, 1)), "stems": int(x.stems)}
    out["m3Pooled"] = {}
    for L, x in m3.groupby("stemLen"):
        out["m3Pooled"][f"{L}_all"] = pooled(x.sum(numeric_only=True))
        c = x[x.curated]
        if len(c):
            out["m3Pooled"][f"{L}_curated"] = pooled(c.sum(numeric_only=True))

    # the side-by-side figure: Phase 1 simulated availability against observed
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.6))
    ms = out["m2"]
    ls = [r_["len"] for r_ in ms if 3 <= r_["len"] <= 8]
    phase1_m2 = {3: 0.808, 4: 0.600, 5: 0.414, 6: 0.281, 7: 0.176, 8: 0.117}
    axes[0].plot(ls, [phase1_m2.get(L) for L in ls], "o--", color=OPP, label="Phase 1 simulated, 4x4 Good Casual")
    axes[0].plot(ls, [r_["pPresent"] for r_ in ms if r_["len"] in ls], "o-", color=WEAK, label="real boards: anagram present")
    axes[0].plot(ls, [r_["pTakenGivenFoundAndPresent"] for r_ in ms if r_["len"] in ls], "o-", color=PLAYER, label="you took it | found one, both present")
    axes[0].plot(ls, [r_["pTakenOpp"] for r_ in ms if r_["len"] in ls], "o:", color=STRONG, label="opponents, same")
    axes[0].axhline(0.5, color=INK2, lw=0.7, ls=":")
    axes[0].set_xlabel("word length")
    axes[0].set_ylabel("probability")
    axes[0].set_title("M2: anagram cellmates")
    axes[0].legend(fontsize=6.5)
    p3 = [(L, out["m3Pooled"].get(f"{L}_curated"), out["m3Pooled"].get(f"{L}_all")) for L in range(3, 8)]
    phase1_cw = {3: (5.26, 10.29), 4: (2.03, 3.68), 5: (1.04, 1.84), 6: (0.74, 1.24), 7: (0.58, 0.90)}
    Ls = [L for L, _, _ in p3]
    axes[1].fill_between(Ls, [phase1_cw[L][0] for L in Ls], [phase1_cw[L][1] for L in Ls], color=OPP, alpha=0.25, label="Phase 1 curatedWord range")
    axes[1].plot(Ls, [c["present"] if c else np.nan for _, c, _ in p3], "o-", color=WEAK, label="real: members present (curated stems)")
    axes[1].plot(Ls, [c["foundIfStemFound"] if c else np.nan for _, c, _ in p3], "o-", color=PLAYER, label="real: members you found | stem found")
    axes[1].axhspan(2, 6, color=STRONG, alpha=0.08, label="spec 7.5 target band 2-6")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("stem length")
    axes[1].set_ylabel("family members (excl. stem)")
    axes[1].set_title("M3: stem enumerability")
    axes[1].legend(fontsize=6.5)
    ph1 = {"4x4_casual": 4.04, "4x4_goodCasual": 4.76, "4x4_spam": 6.56, "5x5_casual": 4.69, "5x5_goodCasual": 5.90, "5x5_spam": 6.95}
    keys = [k for k in ph1 if k in out["m1"]["byTierExt"]]
    x = np.arange(len(keys))
    axes[2].bar(x - 0.27, [ph1[k] for k in keys], width=0.26, color=OPP, label="Phase 1: reachable ext. per found stem")
    axes[2].bar(x, [out["m1"]["byTierExt"][k][0] for k in keys], width=0.26, color=WEAK, label="real boards: reachable ext. per found stem")
    axes[2].bar(x + 0.27, [out["m1"]["byTierExt"][k][1] for k in keys], width=0.26, color=PLAYER, label="of which you found")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels([k.replace("_", "\n") for k in keys], fontsize=7.5)
    axes[2].set_title("M1: free extensions per found word")
    axes[2].legend(fontsize=6.5)
    fig.tight_layout()
    save(fig, "s4_8_phase1_vs_real", {"m2": pd.DataFrame(ms), "m3": m3t, "m1": pd.DataFrame(out["m1"]["byTierExt"], index=["available", "found"]).T.reset_index()},
         "Phase 1's simulated availability against observed availability and realized takes on real boards.")
    return {"phase1": out}

"""Alpha: points almost nobody takes, and the headroom of the family curriculum.

Learning a word the field takes at 60% moves you to par; learning one the field takes at 3%
puts you ahead of everyone. For every word the export shows present, the field find rate is
(your finds + opponents' finds) / (your presences + opponents' presences). Candidates are
present 50+ times, 5+ letters, and under 10% field find rate. Each is classed by how it would
reach you on a board: as an additive extension of a word you found there (free), a terminal
substring of one (drop-terminal), an anagram of one (cellmate), or none of these (independent).

Expected points gained per word learned, per game:
    presences per game x points x (q_word - your current find rate)
where q_word is the find rate you achieve, in the same situation mix, on your *reliable*
words (found on 50%+ of presences). That is an extrapolation: it assumes a learned word
behaves like the words you already own, and is labelled as such in the report.

Never-accepted words (section 0) have zero field finds by definition and would dominate any
"nobody finds it" ranking, so the primary list excludes them; a sensitivity run includes them.
"""
import os

import numpy as np
import pandas as pd

import boardpass
import holdout
import viz
from common import FIGS, RANKED, points
from viz import INK2, OPP, PLAYER, STRONG, WEAK, EXTRA, plt

SIT = ["free", "dropTerminal", "cellmate", "none"]


def _situation(m):
    return np.select([m.freeForP, m.dtOfFound, m.cellmateOfFound], ["free", "dropTerminal", "cellmate"], "none")


def section(R, g, f, pres):
    r = {}
    dead = set(pd.read_csv(os.path.join(FIGS, "s0_never_accepted_words.tsv"), sep="\t").word)
    bp = boardpass.run(pres, g, "all")
    m = bp["missed"].merge(g[["gid", "current", "margin", "oppEloLoo", "split"]], on="gid")
    m["sit"] = _situation(m)
    m["fP"] = m.foundP.astype(float)
    valid = pres.foundOpp.notna()
    p = pres.assign(fo=pres.foundOpp.astype(float), fp=pres.foundPlayer.astype(float)).merge(
        g[["gid", "current", "margin", "oppEloLoo"]], on="gid")
    q75 = g[g.current].oppEloLoo.quantile(0.75)

    # ---- word-level table ------------------------------------------------------------------
    allw = p.groupby("word").agg(len=("len", "first"), pts=("pts", "first"), n=("fp", "size"), kP=("fp", "sum"))
    ov = p[valid.values]
    allw = allw.join(ov.groupby("word").agg(nO=("fo", "size"), kO=("fo", "sum")))
    allw["fieldRate"] = (allw.kP + allw.kO.fillna(0)) / (allw.n + allw.nO.fillna(0))
    allw["myRate"] = allw.kP / allw.n
    cur = p[p.current]
    cw = cur.groupby("word").agg(nCur=("fp", "size"), kCur=("fp", "sum"))
    allw = allw.join(cw)
    allw["myRateCur"] = allw.kCur / allw.nCur
    sw = ov[ov.margin <= -10000].groupby("word").fo.agg(["size", "mean"]).rename(columns={"size": "nStrong", "mean": "strongRate"})
    tw = ov[ov.oppEloLoo >= q75].groupby("word").fo.agg(["size", "mean"]).rename(columns={"size": "nTopQ", "mean": "topQRate"})
    allw = allw.join(sw).join(tw)
    allw["dead"] = allw.index.isin(dead)
    allw["everAccepted"] = (allw.kP + allw.kO.fillna(0)) > 0

    # situation shares per word (current regime primary)
    for tag, mm in (("Cur", m[m.current]), ("All", m)):
        sh = pd.crosstab(mm.word, mm.sit, normalize="index")
        for s_ in SIT:
            allw[f"share_{s_}{tag}"] = sh[s_] if s_ in sh else 0.0
    host = m[m.host != ""].groupby("word").host.agg(lambda s: s.value_counts().index[0])
    allw["observedHost"] = host

    # reliable words and the take rates you achieve on them, by situation and length
    reliable = allw[(allw.n >= 10) & (allw.myRate >= 0.5) & ~allw.dead]
    rel = set(reliable.index)
    mc = m[m.current & m.word.isin(rel)]
    mc = mc.assign(lc=np.minimum(mc.len, 7))
    qtab = mc.groupby(["lc", "sit"]).fP.mean().unstack()
    r["qTable"] = qtab.round(4).to_dict("index")
    r["reliableWords"] = int(len(rel))

    def contained_stem(w):
        L = len(w)
        for k in range(L - 1, 2, -1):
            for st in range(L - k + 1):
                if w[st:st + k] in rel:
                    return w[st:st + k]
        return ""

    akey = {}
    for w in rel:
        akey.setdefault("".join(sorted(w)), []).append(w)

    cand = allw[(allw.n >= 50) & (allw.len >= 5) & (allw.fieldRate < 0.10)].copy()
    cand["hookStem"] = [contained_stem(w) for w in cand.index]
    cand["cellmateOf"] = [",".join(x for x in akey.get("".join(sorted(w)), []) if x != w) for w in cand.index]
    games_cur = int(g.current.sum())
    games_all = len(g)
    lcs = np.minimum(cand.len, 7)
    for tag, games_, ncol, rate in (("Cur", games_cur, "nCur", "myRateCur"), ("All", games_all, "n", "myRate")):
        qw = np.zeros(len(cand))
        for s_ in SIT:
            qs = lcs.map(lambda L: qtab.loc[L, s_] if (L in qtab.index and s_ in qtab.columns) else np.nan).fillna(0).values
            qw += cand[f"share_{s_}{tag}"].fillna(0).values * qs
        cand[f"q{tag}"] = qw
        cand[f"gainPerGame{tag}"] = (cand[ncol].fillna(0) / games_) * cand.pts * np.maximum(qw - cand[rate].fillna(0), 0)
    shares = cand[[f"share_{s_}Cur" for s_ in SIT]].fillna(0)
    cand["reachClass"] = np.where(shares.values[:, :3].max(axis=1) > 0, np.array(SIT[:3])[shares.values[:, :3].argmax(axis=1)], "independent")
    cand["family"] = np.where(cand.hookStem != "", cand.hookStem, np.where(cand.observedHost.fillna("") != "", cand.observedHost, ""))
    cand = cand.sort_values("gainPerGameCur", ascending=False)
    cols = ["len", "pts", "n", "nCur", "fieldRate", "myRate", "myRateCur", "strongRate", "topQRate", "reachClass",
            "share_freeCur", "share_dropTerminalCur", "share_cellmateCur", "hookStem", "cellmateOf", "observedHost", "family",
            "qCur", "gainPerGameCur", "gainPerGameAll", "dead", "everAccepted"]
    clean = cand[~cand.dead]
    top300 = clean.head(300)
    top300.reset_index().rename(columns={"index": "word"})[["word"] + cols].to_csv(os.path.join(RANKED, "alpha_words.tsv"), sep="\t", index=False, float_format="%.5g")
    cand.reset_index().rename(columns={"index": "word"})[["word"] + cols].to_csv(os.path.join(FIGS, "sa_alpha_all_candidates.tsv"), sep="\t", index=False, float_format="%.5g")
    withdead = cand.head(300)
    r["alpha"] = {
        "candidates": int(len(cand)), "candidatesExclDead": int(len(clean)),
        "top300GainPerGame": float(top300.gainPerGameCur.sum()), "top200GainPerGame": float(clean.head(200).gainPerGameCur.sum()),
        "top50GainPerGame": float(clean.head(50).gainPerGameCur.sum()),
        "top300ByClass": top300.reachClass.value_counts().to_dict(),
        "top300FieldRateMedian": float(top300.fieldRate.median()), "top300MyRateMedian": float(top300.myRateCur.median()),
        "top300WithHook": float((top300.hookStem != "").mean()),
        "sensitivity": {"deadInTop300IfIncluded": int(withdead.dead.sum()),
                        "overlapTop300": int(len(set(withdead.index) & set(top300.index))),
                        "top300GainIncludingDead": float(withdead.gainPerGameCur.sum())},
        "top": top300.head(60).reset_index().rename(columns={"index": "word"})[["word", "pts", "nCur", "fieldRate", "myRateCur", "topQRate", "reachClass", "hookStem", "family", "gainPerGameCur"]].round(4).to_dict("records"),
        "vowelInitialShareTop300": float(top300.index.str[0].isin(list("AEIOU")).mean()),
    }
    _alpha_figure(top300)

    # ---- family level: what even the strong field leaves on the board --------------------------
    bpv = boardpass.run(pres[~pres.word.isin(dead)], g, "voc")
    fam = bpv["fam"].merge(g[["gid", "current", "margin", "oppEloLoo"]], on="gid")
    fam = fam[fam.current]
    fam["opened"] = (fam.foundP + fam.foundO) >= 1
    fam["mx"] = np.maximum(fam.foundP, fam.foundO)
    tq = fam.oppEloLoo >= q75
    agg = fam.groupby("stem").agg(boards=("gid", "size"), size=("size", "mean"),
                                  ptsNoneOpened=("ptsNone", lambda s: s[fam.loc[s.index, "opened"]].sum()))
    agg["youCompletion"] = fam[fam.foundP >= 1].groupby("stem").apply(lambda x: x.foundP.sum() / x["size"].sum())
    agg["topQCompletion"] = fam[tq & (fam.foundO >= 1)].groupby("stem").apply(lambda x: x.foundO.sum() / x["size"].sum())
    agg["frontierCompletion"] = fam[fam.mx >= 1].groupby("stem").apply(lambda x: x.mx.sum() / x["size"].sum())
    agg["uncontestedPerGame"] = agg.ptsNoneOpened / games_cur
    ftab = agg[(agg.boards >= 20) & (agg.index.str.len() >= 4)].sort_values("uncontestedPerGame", ascending=False)
    ftab.head(50).reset_index().to_csv(os.path.join(RANKED, "alpha_families.tsv"), sep="\t", index=False, float_format="%.5g")
    ftab.reset_index().to_csv(os.path.join(FIGS, "sa_alpha_families_all.tsv"), sep="\t", index=False, float_format="%.5g")
    r["families"] = {"eligible": int(len(ftab)), "top50UncontestedPerGame": float(ftab.head(50).uncontestedPerGame.sum()),
                     "top50FrontierCompletionMedian": float(ftab.head(50).frontierCompletion.median()),
                     "top": ftab.head(50).reset_index().round(4).to_dict("records")}

    # ---- headroom: everything you find now, plus every additive extension you miss ---------------
    # Three bounds. "ceiling": every missed word that extends the path of a word you found, any
    # extension length and any stem, including 3-letter fragments. Arithmetic only: it runs to
    # 100+ words a game, which 80 seconds cannot hold. "affix": only 1-3 letter extensions of
    # found words of 4+ letters, which is what an affix-grid curriculum drills. "take rate":
    # your take rate on free extensions raised to the top-quartile opponents' and the frontier's,
    # rates real players reached on these boards, applied to your own free opportunities.
    mv = m[~m.word.isin(dead)].copy()
    mv["pts"] = points(mv.len)
    mv["hostLen"] = mv.host.str.len()
    q_free = float(m[m.current & m.word.isin(rel) & (m.sit == "free")].fP.mean())
    base = R["s4"]["baselines"]["freeExtensionTake"]
    r["headroom"] = {"qFreeReliable": q_free, "takeRates": {"you": base["you"], "topQuartile": base["topQuartile"],
                                                            "frontier": base["frontier"]}}
    per_point = R.get("s6", {}).get("regression", {}).get("points", {}).get("amePer100", np.nan) / 100
    for tag, gg in (("current", g[g.current]), ("all", g)):
        ids = set(gg.gid)
        sub = mv[mv.gid.isin(ids)]
        free = sub[sub.freeForP]
        miss = free[~free.foundP]
        ceil = miss.groupby("gid").pts.sum().reindex(gg.gid).fillna(0).values
        aff = miss[(miss.minExt <= 3) & (miss.hostLen >= 4)]
        affp = aff.groupby("gid").pts.sum().reindex(gg.gid).fillna(0).values
        opp_per_game = free.groupby("gid").size().reindex(gg.gid).fillna(0).values
        mean_pts = free.pts.mean()
        res = {"games": int(len(gg)), "meanScore": float(gg.yourScore.mean()), "winRate": float((gg.margin > 0).mean()),
               "freeOpportunitiesPerGame": float(opp_per_game.mean()), "missedFreeWordsPerGame": float((miss.groupby("gid").size().sum()) / len(gg)),
               "ceilingPtsPerGame": float(ceil.mean()), "ceilingWinRate": float(((gg.margin.values + ceil) > 0).mean()),
               "affixPtsPerGame": float(affp.mean()), "affixWordsPerGame": float(len(aff) / len(gg)),
               "affixWinRate": float(((gg.margin.values + affp) > 0).mean()),
               "affixAtReliableRatePts": float((affp * q_free).mean()),
               "affixAtReliableRateWinRate": float(((gg.margin.values + affp * q_free) > 0).mean())}
        for ref in ("topQuartile", "frontier"):
            add = (base[ref] - base["you"]) * opp_per_game * mean_pts
            res[f"{ref}RatePts"] = float(add.mean())
            res[f"{ref}RateWinRate"] = float(((gg.margin.values + add) > 0).mean())
            res[f"{ref}RateWinModel"] = float(add.mean() * per_point) if np.isfinite(per_point) else None
        r["headroom"][tag] = res
    _headroom_figure(r["headroom"])
    R["sa"] = r


def _alpha_figure(top):
    t = top.head(40).iloc[::-1]
    cmap = {"free": PLAYER, "dropTerminal": WEAK, "cellmate": STRONG, "independent": OPP}
    fig, ax = plt.subplots(figsize=(8.5, 8))
    ax.barh(np.arange(len(t)), t.gainPerGameCur, color=[cmap[c] for c in t.reachClass])
    ax.set_yticks(np.arange(len(t)))
    ax.set_yticklabels([f"{w}  field {fr:.0%}, you {me:.0%}" + (f", on {h}" if h else "") for w, fr, me, h in
                        zip(t.index, t.fieldRate, t.myRateCur.fillna(0), t.family)], fontsize=7)
    for c, col in cmap.items():
        ax.plot([], [], color=col, lw=6, label=c)
    ax.legend(fontsize=7.5, loc="lower right", title="how it reaches you")
    ax.set_xlabel("expected points gained per game if learned (seasons 7-10)")
    ax.set_title("Alpha words: 5+ letters, field find rate under 10%")
    viz.save(fig, "sa_alpha_words", top.reset_index().rename(columns={"index": "word"}),
             "Top alpha words by expected points gained per game, excluding never-accepted words. Full top 300: data/ranked/alpha_words.tsv.")


def _headroom_figure(h):
    c = h["current"]
    labels = ["now", "free-ext. take\nat top-25% rate", "free-ext. take\nat frontier rate"]
    pts = [0, c["topQuartileRatePts"], c["frontierRatePts"]]
    wins = [c["winRate"], c["topQuartileRateWinRate"], c["frontierRateWinRate"]]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    cols = [OPP, WEAK, EXTRA[3]]
    axes[0].bar(range(3), pts, color=cols)
    axes[1].bar(range(3), wins, color=cols)
    for ax, vals, fmt in ((axes[0], pts, "{:+,.0f}"), (axes[1], wins, "{:.1%}")):
        ax.set_xticks(range(3))
        ax.set_xticklabels(labels, fontsize=7.5)
        for i, v in enumerate(vals):
            ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=8)
    axes[0].set_ylabel("points added per game")
    axes[0].set_title("Family-curriculum headroom, seasons 7-10")
    axes[1].set_ylabel("win rate, opponent unchanged")
    axes[1].set_ylim(0, 1)
    axes[1].set_title("Win rate if those points were added")
    fig.tight_layout()
    viz.save(fig, "sa_headroom", pd.DataFrame([{"regime": k, **v} for k, v in h.items() if isinstance(v, dict) and "games" in v]),
             "What the family curriculum is worth to you: your free-extension take rate raised to rates real players reached on these boards. The arithmetic ceilings are in the TSV and text only.")

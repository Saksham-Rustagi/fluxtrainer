"""Report section 5: boards and generation, seasons 7-10 only (the current generation regime).

The reference generator is ruleset v3 (client letter weights, two-per-letter cap, one seed per
board), simulated on the Flux word list; real potential is compared on the same list. v1, the
Phase 1 generator, is kept as the comparison so the size of the correction is visible.
"""
import collections
import json
import os
import re

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import gaussian_kde

from common import RANKED, ROOT
from viz import INK2, OPP, PLAYER, STRONG, WEAK, band, boot_by, plt, save

TIERS = ["casual", "goodCasual", "spam"]
SPEC = {"casual": 0.3, "goodCasual": 0.5, "spam": 0.2}
VOWELS = set("AEIOU")


def sim(name):
    return pd.read_csv(os.path.join(ROOT, "build-analytics", "boards", name + ".tsv"), sep="\t")


def mixture(s, grid, weights, n=30000, seed=3):
    s = s[s.side == grid]
    return pd.concat([s[s.tier == t].sample(int(n * weights[t]), replace=True, random_state=seed) for t in TIERS if weights[t] > 0])


def marginal(letters):
    c = np.zeros(26)
    for s_ in letters:
        for ch in s_:
            c[ord(ch) - 65] += 1
    return c / c.sum()


def section5(R, g, f, pres):
    r = {}
    fit = json.load(open(os.path.join(RANKED, "boards_fit.json")))
    r["fit"] = fit
    gc = g[g.current]
    s3, s1 = sim("sim_v3"), sim("sim_v1")

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.6))
    tsv = {}
    r["potential"] = {}
    for ax, grid in zip(axes, ("4x4", "5x5")):
        real = gc[gc.grid == grid].potentialFlux / 1000
        bins = np.linspace(0, np.percentile(real, 99.5) * 1.3, 60)
        ax.hist(real, bins=bins, density=True, color=PLAYER, alpha=0.45, label=f"real, seasons 7-10 ({len(real):,})")
        xs = np.linspace(bins[0], bins[-1], 300)
        m3 = mixture(s3, grid, SPEC).points / 1000
        m1 = mixture(s1, grid, SPEC).points / 1000
        ax.plot(xs, gaussian_kde(m3)(xs), color=STRONG, label="ruleset v3 (corrected), 20/50/30")
        ax.plot(xs, gaussian_kde(m1)(xs), color=OPP, ls="--", label="ruleset v1 (Phase 1), 20/50/30")
        ax.set_xlabel("board potential, Flux word list (thousand points)")
        ax.set_title(f"{grid} board potential")
        ax.legend(fontsize=7)
        tsv[grid] = pd.DataFrame({"potential_k": real.values})
        r["potential"][grid] = {"realMedian": float(real.median() * 1000), "v3Median": float(m3.median() * 1000),
                                "v1Median": float(m1.median() * 1000), "realP10": float(real.quantile(.1) * 1000),
                                "realP90": float(real.quantile(.9) * 1000), "v3P10": float(m3.quantile(.1) * 1000),
                                "v3P90": float(m3.quantile(.9) * 1000)}
    axes[0].set_ylabel("density")
    fig.tight_layout()
    save(fig, "s5_potential_vs_sim", tsv, "Real board potential (seasons 7-10) against ruleset v3 and v1 at the stated tier shares.")

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.4))
    x = np.arange(3)
    for i, (grid, color) in enumerate((("4x4", PLAYER), ("5x5", STRONG))):
        w = fit["tierMixture"][grid]
        est = [w["weights"][t] for t in TIERS]
        lo = [w["ci95"][t][0] for t in TIERS]
        hi = [w["ci95"][t][1] for t in TIERS]
        axes[0].bar(x + (i - 0.5) * 0.3, est, width=0.28, color=color, label=f"{grid} fitted")
        axes[0].errorbar(x + (i - 0.5) * 0.3, est, yerr=[np.subtract(est, lo), np.subtract(hi, est)], fmt="none", color=INK2)
    axes[0].plot(x, [SPEC[t] for t in TIERS], "D", color=INK2, label="stated 30/50/20")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(TIERS)
    axes[0].set_ylabel("share of boards")
    axes[0].set_title("Tier mixture (EM on v3 densities)")
    axes[0].legend(fontsize=7)
    gs = fit["gridSplit"]
    keys = [k for k in ("season7", "season8", "season9", "season10") if k in gs]
    axes[1].bar(np.arange(len(keys)), [gs[k]["share4x4"] for k in keys], color=PLAYER)
    axes[1].axhline(0.6, color=INK2, ls="--", lw=1, label="stated 60%")
    axes[1].set_xticks(np.arange(len(keys)))
    axes[1].set_xticklabels([k.replace("season", "S") + f"\n{gs[k]['n']}" for k in keys], fontsize=8)
    axes[1].set_ylabel("share of 4x4 boards")
    axes[1].set_title("Grid split by season (n below)")
    axes[1].legend(fontsize=7)
    for grid, color in (("4x4", PLAYER), ("5x5", STRONG)):
        v = fit["seed"][grid]["variants"]
        ll = np.array([row["logLik"] for row in v])
        axes[2].plot([row["perCandidatePerMille"] / 10 for row in v], ll - ll.max(), "o-", color=color, label=grid)
    axes[2].axvline(50, color=INK2, ls="--", lw=1, label="stated 50%")
    axes[2].set_xlabel("per-board seed rate (%)")
    axes[2].set_ylabel("log-likelihood minus max")
    axes[2].set_title("Seed rate from longest word present")
    axes[2].set_ylim(-400, 20)
    axes[2].legend(fontsize=7)
    fig.tight_layout()
    save(fig, "s5_generation", {"tiers": pd.DataFrame([{"grid": k, **v["weights"]} for k, v in fit["tierMixture"].items()]),
                                "seed": pd.DataFrame([{"grid": k, **row} for k, v in fit["seed"].items() for row in v["variants"]])},
         "Seasons 7-10: tier mixture under v3, grid split by season, seed-rate profile likelihood.")
    r["gridSplitCurrent"] = gs["current"]

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.6))
    r["capture"] = {}
    tsv = {}
    for grid, color in (("4x4", PLAYER), ("5x5", STRONG)):
        d = gc[(gc.grid == grid) & (gc.yourScore > 0)].copy()
        m = smf.ols("np.log(capture) ~ np.log(potential)", data=d).fit()
        ms = smf.ols("np.log(yourScore) ~ np.log(potential)", data=d).fit()
        r["capture"][grid] = {"captureElasticity": float(m.params.iloc[1]), "ci": m.conf_int().iloc[1].tolist(),
                              "scoreElasticity": float(ms.params.iloc[1]), "scoreCi": ms.conf_int().iloc[1].tolist(),
                              "captureAtPotentialDecile": d.groupby(pd.qcut(d.potential, 10, labels=False)).capture.mean().round(4).tolist()}
        axes[0].scatter(d.potential / 1000, d.capture, s=3, alpha=0.2, color=color)
        d["b"] = pd.qcut(d.potential, 12, labels=False)
        t = boot_by(d, "b", "capture").merge(d.groupby("b").potential.median().rename("pot").reset_index(), on="b")
        band(axes[0], t.pot / 1000, t, color, f"{grid}: elasticity {m.params.iloc[1]:.2f}")
        t2 = boot_by(d, "b", "yourScore").merge(d.groupby("b").potential.median().rename("pot").reset_index(), on="b")
        band(axes[1], t2.pot / 1000, t2.assign(mean=t2["mean"] / 1000, lo=t2.lo / 1000, hi=t2.hi / 1000), color,
             f"{grid}: elasticity {ms.params.iloc[1]:.2f}")
        tsv[grid] = t.assign(scoreMean=t2["mean"])
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("board potential, CSW21 (thousand points, log)")
    axes[0].set_ylabel("capture = score / potential (log)")
    axes[0].set_title("Capture falls with potential")
    axes[0].legend(fontsize=7.5)
    axes[1].set_xlabel("board potential (thousand points)")
    axes[1].set_ylabel("score (thousand points)")
    axes[1].set_title("Score rises far less than potential")
    axes[1].legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, "s5_capture_vs_potential", tsv, "Seasons 7-10: capture and score against board potential (CSW21, never-accepted words included).")

    r["letters"] = letters(gc)
    r["rerun"] = rerun_comparison()
    R["s5"] = r


def letters(gc):
    s3, s1 = sim("sim_v3"), sim("sim_v1")
    share = {gr: (gc.grid == gr).mean() for gr in ("4x4", "5x5")}
    obs = marginal(gc.letters)

    def simmarg(s_):
        return sum(share[gr] * marginal(mixture(s_, gr, SPEC, 8000).letters) for gr in share)
    v3, v1 = simmarg(s3), simmarg(s1)
    out = {"tvV3": float(0.5 * np.abs(v3 - obs).sum()), "tvV1": float(0.5 * np.abs(v1 - obs).sum()),
           "cells": int(sum(len(x) for x in gc.letters))}
    L = pd.DataFrame({"observed": obs, "v3": v3, "v1": v1}, index=[chr(65 + i) for i in range(26)]).sort_values("observed", ascending=False)
    out["table"] = L.round(5).to_dict("index")
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 3.4), gridspec_kw={"width_ratios": [2.2, 1]})
    x = np.arange(26)
    for i, (col, color, label) in enumerate((("observed", PLAYER, "real boards, seasons 7-10"),
                                             ("v3", STRONG, f"ruleset v3 simulated (TV {out['tvV3']:.3f})"),
                                             ("v1", OPP, f"ruleset v1 simulated (TV {out['tvV1']:.3f})"))):
        axes[0].bar(x + (i - 1) * 0.28, L[col] * 100, width=0.27, color=color, label=label)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(L.index)
    axes[0].set_ylabel("% of cells")
    axes[0].set_title("Letter marginal")
    axes[0].legend(fontsize=7.5)

    def maxcopies(ls):
        return np.array([max(collections.Counter(s_).values()) for s_ in ls])

    def vowels(ls):
        return np.array([sum(c in VOWELS for c in s_) for s_ in ls])
    struct = {}
    for label, ls in (("real", gc[gc.side == 4].letters), ("v3", mixture(s3, "4x4", SPEC, 6000).letters),
                      ("v1", mixture(s1, "4x4", SPEC, 6000).letters)):
        mc, vw = maxcopies(ls), vowels(ls)
        struct[label] = {"share3plus": float((mc >= 3).mean()), "vowelSd": float(vw.std()), "vowelMean": float(vw.mean())}
    out["structure4x4"] = struct
    labs = list(struct)
    axes[1].bar(np.arange(3) - 0.2, [struct[k]["share3plus"] for k in labs], width=0.38, color=PLAYER, label="boards with 3+ of a letter")
    axes[1].bar(np.arange(3) + 0.2, [struct[k]["vowelSd"] / 2 for k in labs], width=0.38, color=WEAK, label="vowel-count SD / 2")
    axes[1].set_xticks(np.arange(3))
    axes[1].set_xticklabels(["real", "v3", "v1"])
    axes[1].set_title("Structure (4x4)")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    save(fig, "s5_1_letters", L.reset_index(names="letter"), "Seasons 7-10: observed letter marginal against ruleset v3 (corrected) and v1.")
    return out


def rerun_comparison():
    """Phase 1 numbers under v1 against the same measurements under v3."""
    out = {}
    for tag, path in (("v1", "full"), ("v3", "v3-full")):
        pth = os.path.join(ROOT, "runs", path, "board_norms.tsv")
        if os.path.exists(pth):
            b = pd.read_csv(pth, sep="\t")
            out.setdefault("boardNorms", {})[tag] = b[b.metric == "points"][["grid", "tier", "mean", "p50", "seededFrac"]].round(3).to_dict("records")
    for tag, path in (("v1", "v1-m3-curated-10k"), ("v3", "v3-m3-curated")):
        d = os.path.join(ROOT, "runs", path)
        if not os.path.exists(os.path.join(d, "family_stats.tsv")):
            continue
        fs = pd.read_csv(os.path.join(d, "family_stats.tsv"), sep="\t")
        fs = fs[(fs.nQuartile == "all") & (fs["sample"] == "curatedWord")]
        out.setdefault("m3", {})[tag] = fs[["grid", "tier", "stemLen", "enumerabilityOther"]].round(3).to_dict("records")
        cm = pd.read_csv(os.path.join(d, "cellmate_stats.tsv"), sep="\t")
        out.setdefault("m2", {})[tag] = cm[(cm.relation == "anagram")][["grid", "tier", "len", "p"]].round(4).to_dict("records")
        rows = []
        for fn in ("tables.txt", "stderr.txt", "stdout.txt"):
            tp = os.path.join(d, fn)
            if not os.path.exists(tp):
                continue
            for line in open(tp, errors="ignore").read().replace("\r", "\n").splitlines():
                mm = re.match(r"\s+(4x4|5x5) (\w+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)%", line)
                if mm:
                    rows.append({"grid": mm[1], "tier": mm[2], "extPerStem": float(mm[3]), "freeWordsPerBoard": float(mm[4]),
                                 "foundWordsPerBoard": float(mm[5]), "freeFraction": float(mm[6]) / 100})
            if rows:
                break
        out.setdefault("m1gate", {})[tag] = rows
    return out

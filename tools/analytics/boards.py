"""Board-level generation analysis: tier posterior, tier mixture, seed rate.

Real boards carry no tier label. Each is classified by its solved potential
against per-(grid, tier) potential densities simulated under ruleset v3 -- the
corrected generator (client letter weights, two-per-letter cap, one seed per
board) -- with the tier mixture weights fitted by EM per grid on seasons 7-10
only, the current generation regime. v3 solves against the Flux word list, so
real potential is recomputed on that list (CSW21 minus the 419 removals) for
the comparison. Seed rate is inferred from the longest word present, against
simulated longest-word distributions at several per-candidate seed rates.

Writes data/ranked/games.parquet (games_stage1 + tier posterior),
data/ranked/board_norms_real.tsv and data/ranked/boards_fit.json.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest, gaussian_kde

sys.path.insert(0, os.path.dirname(__file__))
from common import RANKED, ROOT, add_regime, load  # noqa: E402

GENBOARDS = os.path.join(ROOT, "build", "tools", "genboards", "genboards")
DAWG = os.path.join(ROOT, "build-analytics", "csw21.dawg")
DAWG_V3 = os.path.join(ROOT, "data", "dict", "flux_capped.dawg")
V3 = os.path.join(ROOT, "config", "ruleset_v3.json")
WORK = os.path.join(ROOT, "build-analytics", "boards")
TIERS = ["casual", "goodCasual", "spam"]
SPEC_SHARE = {"casual": 0.30, "goodCasual": 0.50, "spam": 0.20}


def genboards(config, boards, seed, name, dawg=DAWG):
    out = os.path.join(WORK, name + ".tsv")
    if not os.path.exists(out):
        subprocess.run([GENBOARDS, config, dawg, out, str(boards), str(seed)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pd.read_csv(out, sep="\t")


def seed_variant(pm):
    cfg = json.load(open(V3))
    cfg["seeding"]["probabilityPerMille"] = pm
    path = os.path.join(WORK, f"seed3_{pm}.json")
    json.dump(cfg, open(path, "w"), indent=1)
    return path


def em_weights(dens, iters=500):
    """dens: n x 3 component densities. Returns mixture weights."""
    w = np.full(dens.shape[1], 1 / dens.shape[1])
    for _ in range(iters):
        r = dens * w
        r /= r.sum(axis=1, keepdims=True)
        w = r.mean(axis=0)
    return w


def main():
    os.makedirs(WORK, exist_ok=True)
    g = add_regime(load("games_stage1.parquet"))
    removed = set(w.strip().upper() for w in open(os.path.join(ROOT, "data", "flux_removed_words.txt")) if w.strip())
    pres = pd.read_parquet(os.path.join(RANKED, "presence.parquet"), columns=["gid", "word", "pts"])
    flux = pres[~pres.word.isin(removed)].groupby("gid").pts.sum()
    g["potentialFlux"] = g.gid.map(flux)
    sim = genboards(V3, 6000, 4242, "sim_v3", DAWG_V3)
    sim1 = genboards(os.path.join(ROOT, "config", "ruleset_v1.json"), 6000, 4242, "sim_v1")
    sim2 = genboards(os.path.join(ROOT, "config", "ruleset_v2.json"), 6000, 4242, "sim_v2")
    fit = {"tierMixture": {}, "gridSplit": {}, "seed": {}, "regime": "seasons 7-10", "generator": "ruleset v3"}

    for t in TIERS:
        g[f"p_{t}"] = np.nan
        g[f"pSpec_{t}"] = np.nan
    for grid in ("4x4", "5x5"):
        m = g.grid == grid
        cur = (m & g.current).values[m.values]
        x = np.log(g.loc[m, "potentialFlux"].values)
        dens = np.column_stack([gaussian_kde(np.log(sim[(sim.side == grid) & (sim.tier == t)].points))(x) for t in TIERS])
        dens = np.maximum(dens, 1e-300)
        w = em_weights(dens[cur])
        rng = np.random.default_rng(7)
        dc = dens[cur]
        boots = np.array([em_weights(dc[rng.integers(0, len(dc), len(dc))], iters=200) for _ in range(200)])
        post = dens * w
        post /= post.sum(axis=1, keepdims=True)
        spec = dens * np.array([SPEC_SHARE[t] for t in TIERS])
        spec /= spec.sum(axis=1, keepdims=True)
        for i, t in enumerate(TIERS):
            g.loc[m, f"p_{t}"] = post[:, i]
            g.loc[m, f"pSpec_{t}"] = spec[:, i]
        ll_fit = np.log(dc @ w).sum()
        ll_spec = np.log(dc @ np.array([SPEC_SHARE[t] for t in TIERS])).sum()
        fit["tierMixture"][grid] = {
            "boards": int(cur.sum()),
            "weights": dict(zip(TIERS, map(float, w))),
            "ci95": {t: [float(np.percentile(boots[:, i], 2.5)), float(np.percentile(boots[:, i], 97.5))] for i, t in enumerate(TIERS)},
            "stated": SPEC_SHARE,
            "logLikGainOverStated": float(ll_fit - ll_spec),
        }
    g["tier"] = g[[f"p_{t}" for t in TIERS]].values.argmax(axis=1)
    g["tier"] = g["tier"].map(dict(enumerate(TIERS)))
    g["tierConfidence"] = g[[f"p_{t}" for t in TIERS]].max(axis=1)

    # grid split against the stated 60/40, current regime
    gc = g[g.current]
    n4 = int((gc.side == 4).sum())
    bt = binomtest(n4, len(gc), 0.6)
    fit["gridSplit"]["current"] = {"n4x4": n4, "n": int(len(gc)), "share4x4": n4 / len(gc), "p": bt.pvalue,
                                   "ci95": list(bt.proportion_ci())}
    for s, x in g.groupby("season"):
        k = int((x.side == 4).sum())
        fit["gridSplit"][f"season{s}"] = {"n4x4": k, "n": int(len(x)), "share4x4": k / len(x),
                                          "p": binomtest(k, len(x), 0.6).pvalue}
    for part, x in g.groupby("part"):
        k = int((x.side == 4).sum())
        fit["gridSplit"][f"part{part}"] = {"n4x4": k, "n": int(len(x)), "share4x4": k / len(x),
                                           "p": binomtest(k, len(x), 0.6).pvalue}

    # seed rate: longest-word likelihood across per-candidate seed rates
    rates = [0, 250, 500, 750, 1000]
    variants = {pm: (sim if pm == 500 else genboards(seed_variant(pm), 3000, 4242, f"seed3_{pm}", DAWG_V3)) for pm in rates}
    for grid in ("4x4", "5x5"):
        real = g[(g.grid == grid) & g.current]
        w = fit["tierMixture"][grid]["weights"]
        rows = []
        for pm, s in variants.items():
            s = s[s.side == grid]
            maxL = 16
            pmf = np.zeros(maxL + 1)
            seeded = 0.0
            for t in TIERS:
                h = np.bincount(np.minimum(s[s.tier == t].longest, maxL), minlength=maxL + 1).astype(float) + 0.5
                pmf += w[t] * h / h.sum()
                seeded += w[t] * s[s.tier == t].seeded.mean()
            obs = np.bincount(np.minimum(real.longestPresent, maxL), minlength=maxL + 1)
            rows.append({"perCandidatePerMille": pm, "logLik": float((obs * np.log(pmf)).sum()),
                         "winnersSeeded": float(seeded),
                         "simLongestMean": float((np.arange(maxL + 1) * pmf).sum()),
                         "simLongestGe8": float(pmf[8:].sum()), "simLongestGe10": float(pmf[10:].sum())})
        fit["seed"][grid] = {
            "realLongestMean": float(real.longestPresent.mean()),
            "realLongestGe8": float((real.longestPresent >= 8).mean()),
            "realLongestGe10": float((real.longestPresent >= 10).mean()),
            "realLongestHist": {int(k): int(v) for k, v in real.longestPresent.value_counts().sort_index().items()},
            "variants": rows,
        }

    # board norms: real, per grid and MAP tier, against the v1 and v2 simulated mixtures
    rows = []

    def summarize(label, grid, tier, x):
        for metric, col in (("points", "points"), ("words", "words"), ("words5plus", "words5plus")):
            v = x[col].values
            rows.append({"source": label, "grid": grid, "tier": tier, "metric": metric, "boards": len(v),
                         "mean": v.mean(), "sd": v.std(), "p10": np.percentile(v, 10), "p25": np.percentile(v, 25),
                         "p50": np.percentile(v, 50), "p75": np.percentile(v, 75), "p90": np.percentile(v, 90)})

    for regime, gg in (("current", g[g.current]), ("all", g)):
        real = gg.rename(columns={"potential": "points", "nPresent": "words", "nPresent5p": "words5plus"})
        for grid in ("4x4", "5x5"):
            summarize(f"real_{regime}", grid, "all", real[real.grid == grid])
            summarize(f"real_{regime}_fluxList", grid, "all", real[real.grid == grid].assign(points=real.potentialFlux))
            for t in TIERS:
                x = real[(real.grid == grid) & (real.tier == t)]
                if len(x):
                    summarize(f"real_{regime}_mapTier", grid, t, x)
    for grid in ("4x4", "5x5"):
        for label, s_ in (("sim_v3", sim), ("sim_v1", sim1), ("sim_v2", sim2)):
            s_ = s_[s_.side == grid]
            mix = pd.concat([s_[s_.tier == t].sample(int(20000 * SPEC_SHARE[t]), replace=True, random_state=3) for t in TIERS])
            summarize(label + "_mix203050", grid, "all", mix)
            for t in TIERS:
                summarize(label, grid, t, s_[s_.tier == t])
    pd.DataFrame(rows).to_csv(os.path.join(RANKED, "board_norms_real.tsv"), sep="\t", index=False, float_format="%.2f")

    g.to_parquet(os.path.join(RANKED, "games.parquet"))
    json.dump(fit, open(os.path.join(RANKED, "boards_fit.json"), "w"), indent=2, default=float)
    print(json.dumps(fit["tierMixture"], indent=1, default=float))
    print(json.dumps({k: v["share4x4"] for k, v in fit["gridSplit"].items()}, indent=1))
    for grid in fit["seed"]:
        print(grid, {k: v for k, v in fit["seed"][grid].items() if k != "variants" and k != "realLongestHist"})
        for r in fit["seed"][grid]["variants"]:
            print("  ", r)


if __name__ == "__main__":
    sys.exit(main())

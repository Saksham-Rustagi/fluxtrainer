"""Validate a simulated ruleset against the real ranked boards (Phase 1 rerun, step 5).

Compares, per grid:
  - the letter marginal (total variation distance, with a same-size noise floor
    drawn from the simulation itself),
  - letters appearing exactly twice per board, distinct letters per board, and the
    share of boards with any letter 3+ times,
  - board potential: real seasons 7-10 only (earlier seasons ran different server
    settings, SPEC 2.5) against the simulated ranked mix.

Simulated boards come from `genboards` (equal boards per cell); they are reweighted
to the ranked mix with the tier shares from the ruleset (20/50/30), since the grid
is compared separately. Real potentials come from `solve_boards` under the SAME
ruleset and dictionary, so both sides count the same words.

usage: validate_generator.py <genboards.tsv> <solve_boards.tsv> <ruleset.json> <out.json>
"""

import collections
import json
import sys

import numpy as np
import pandas as pd

LETTERS = [chr(65 + i) for i in range(26)]
RECENT = {7, 8, 9, 10}


def points(n):
    return {3: 100, 4: 400, 5: 800}.get(n, (n - 3) * 400 + 200)


def counts(letters):
    c = collections.Counter("".join(letters))
    return np.array([c[l] for l in LETTERS], float)


def fingerprint(letters):
    doubled, distinct, triple = [], [], []
    for b in letters:
        c = collections.Counter(b)
        doubled.append(sum(v == 2 for v in c.values()))
        distinct.append(len(c))
        triple.append(max(c.values()) >= 3)
    return float(np.mean(doubled)), float(np.mean(distinct)), float(np.mean(triple))


def weighted_quantiles(values, weights, qs):
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    cw = np.cumsum(w) / w.sum()
    return [float(v[np.searchsorted(cw, q)]) for q in qs]


def main():
    gen_path, solve_path, ruleset_path, out_path = sys.argv[1:5]
    ruleset = json.load(open(ruleset_path))
    tier_share = {g["side"]: {t: v["share"] for t, v in g["tiers"].items()} for g in ruleset["grids"]}

    sim = pd.read_csv(gen_path, sep="\t")
    sim["side"] = sim["side"].str[0].astype(int)
    # Per-board weight so each grid's boards form the ranked tier mix.
    n_cell = sim.groupby(["side", "tier"]).size()
    sim["w"] = [tier_share[s][t] / n_cell[(s, t)] for s, t in zip(sim.side, sim.tier)]

    games = pd.read_parquet("data/ranked/games_raw.parquet")
    sol = pd.read_csv(solve_path, sep="\t", usecols=["id", "word"])
    sol["len"] = sol.word.str.len()
    sol = sol[sol.len >= 3]
    pot = sol.assign(p=sol.len.map(points)).groupby("id").p.sum()
    games["potential"] = games.gid.map(pot).fillna(0)

    rng = np.random.default_rng(20260917)
    out = {"ruleset": ruleset_path, "genboards": gen_path, "grids": {}}
    for side in (4, 5):
        s = sim[sim.side == side]
        w = s.w.values
        # Weighted simulated marginal: each tier's cell marginal, mixed by share.
        ps = np.zeros(26)
        for tier, part in s.groupby("tier"):
            c = counts(part.letters)
            ps += tier_share[side][tier] * c / c.sum()
        ps /= ps.sum()

        grid = {}
        for label, real in (("allSeasons", games[games.side == side]),
                            ("seasons7to10", games[(games.side == side) & games.season.isin(RECENT)])):
            if len(real) == 0:
                continue
            pr = counts(real.letters)
            pr /= pr.sum()
            tvd = 0.5 * np.abs(pr - ps).sum()
            # Noise floor: TVD of a same-size weighted resample of the simulation
            # against the simulation's own marginal.
            noise = []
            prob = w / w.sum()
            for _ in range(200):
                idx = rng.choice(len(s), size=len(real), p=prob)
                pb = counts(s.letters.values[idx])
                noise.append(0.5 * np.abs(pb / pb.sum() - ps).sum())
            d, k, t3 = fingerprint(real.letters)
            grid[label] = {
                "boards": int(len(real)),
                "letterTVD": round(float(tvd), 4),
                "noise95": round(float(np.quantile(noise, 0.95)), 4),
                "doubledPerBoard": round(d, 2),
                "distinctPerBoard": round(k, 2),
                "shareWithTriple": round(t3, 4),
                "realMarginal": {l: round(100 * float(x), 2) for l, x in zip(LETTERS, pr)},
            }

        # Simulated fingerprint, weighted to the tier mix by resampling.
        idx = rng.choice(len(s), size=60000, p=w / w.sum())
        d, k, t3 = fingerprint(s.letters.values[idx])
        grid["simulated"] = {
            "boards": int(len(s)),
            "doubledPerBoard": round(d, 2),
            "distinctPerBoard": round(k, 2),
            "shareWithTriple": round(t3, 4),
            "marginal": {l: round(100 * float(x), 2) for l, x in zip(LETTERS, ps)},
        }

        # Potential, seasons 7-10 only.
        real = games[(games.side == side) & games.season.isin(RECENT)].potential.values
        qs = [0.1, 0.25, 0.5, 0.75, 0.9]
        sim_q = weighted_quantiles(s.points.values, w, qs)
        boot = np.array([np.quantile(rng.choice(real, len(real)), qs) for _ in range(1000)])
        grid["potentialSeasons7to10"] = {
            "realBoards": int(len(real)),
            "quantiles": qs,
            "real": [float(x) for x in np.quantile(real, qs)],
            "real95lo": [float(x) for x in np.quantile(boot, 0.025, axis=0)],
            "real95hi": [float(x) for x in np.quantile(boot, 0.975, axis=0)],
            "sim": sim_q,
            "realMean": float(real.mean()),
            "simMean": float(np.average(s.points.values, weights=w)),
            "simByTierMean": {t: float(p.points.mean()) for t, p in s.groupby("tier")},
        }
        out["grids"][f"{side}x{side}"] = grid

    json.dump(out, open(out_path, "w"), indent=1)
    for g, v in out["grids"].items():
        print(f"== {g}")
        for label in ("allSeasons", "seasons7to10"):
            if label in v:
                r = v[label]
                print(f"  real {label:13s} n={r['boards']:5d}  TVD {r['letterTVD']:.4f} (noise95 {r['noise95']:.4f})"
                      f"  doubled {r['doubledPerBoard']:.2f}  distinct {r['distinctPerBoard']:.2f}  triple {r['shareWithTriple']:.4f}")
        sv = v["simulated"]
        print(f"  simulated               doubled {sv['doubledPerBoard']:.2f}  distinct {sv['distinctPerBoard']:.2f}  triple {sv['shareWithTriple']:.4f}")
        p = v["potentialSeasons7to10"]
        print("  potential S7-10  q10/q25/q50/q75/q90")
        print("    real " + " ".join(f"{x:9.0f}" for x in p["real"]) + f"   mean {p['realMean']:.0f}")
        print("    95lo " + " ".join(f"{x:9.0f}" for x in p["real95lo"]))
        print("    95hi " + " ".join(f"{x:9.0f}" for x in p["real95hi"]))
        print("    sim  " + " ".join(f"{x:9.0f}" for x in p["sim"]) + f"   mean {p['simMean']:.0f}")


if __name__ == "__main__":
    main()

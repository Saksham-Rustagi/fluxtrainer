"""Inverse-fit the generator's base letter distribution (spec 2.4 item 1).

The observed letter marginal on ranked boards is post-selection: every board
won a best-of-N ranked by potential, and seeding put a real word on most of
them, so it is not the distribution the generator samples from. This finds the
base weights which, pushed through the full pipeline (tier draw, seeding,
best-of-N), reproduce the observed marginal.

Method: multiplicative fixed-point iteration with the simulator in the loop,
    w <- w * (observed / simulated) ** eta
where `simulated` is the tier-mixed (spec 20/50/30) marginal of genboards output,
with grids weighted by their share of real cells. Writes
data/ranked/fitted_distribution.json and config/ruleset_v2.json.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.join(ROOT, "build-analytics", "letterfit")
GENBOARDS = os.path.join(ROOT, "build", "tools", "genboards", "genboards")
DAWG = os.path.join(ROOT, "build-analytics", "csw21.dawg")
V1 = os.path.join(ROOT, "config", "ruleset_v1.json")
V2 = os.path.join(ROOT, "config", "ruleset_v2.json")
LETTERS = [chr(ord("A") + i) for i in range(26)]
TIER_SHARE = {"casual": 0.30, "goodCasual": 0.50, "spam": 0.20}


def marginal(letter_strings):
    counts = np.zeros(26)
    for s in letter_strings:
        for c in s:
            counts[ord(c) - 65] += 1
    return counts


def write_config(weights, path, version, about=None):
    cfg = json.load(open(V1))
    cfg["version"] = version
    w = np.maximum(1, np.round(weights / weights.sum() * 100000)).astype(int)
    w[np.argmax(w)] += 100000 - w.sum()
    cfg["letterWeights"] = {L: int(x) for L, x in zip(LETTERS, w)}
    if about:
        cfg["_letterWeights"] = about
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    return w


def simulate(config, boards, seed, out):
    subprocess.run([GENBOARDS, config, DAWG, out, str(boards), str(seed)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pd.read_csv(out, sep="\t")


def sim_marginal(df, grid_cell_share):
    """Tier-mixed, grid-weighted letter frequencies from a genboards dump."""
    total = np.zeros(26)
    for grid, gshare in grid_cell_share.items():
        for tier, tshare in TIER_SHARE.items():
            m = marginal(df[(df.side == grid) & (df.tier == tier)].letters)
            total += gshare * tshare * m / m.sum()
    return total


def main():
    os.makedirs(WORK, exist_ok=True)
    games = pd.read_parquet(os.path.join(ROOT, "data", "ranked", "games_raw.parquet"))
    obs_by_grid = {f"{s}x{s}": marginal(games[games.side == s].letters) for s in (4, 5)}
    cells = {k: v.sum() for k, v in obs_by_grid.items()}
    grid_cell_share = {k: v / sum(cells.values()) for k, v in cells.items()}
    obs = sum(obs_by_grid.values())
    obs = obs / obs.sum()

    v1 = json.load(open(V1))["letterWeights"]
    w = np.array([v1[L] for L in LETTERS], dtype=float)
    base_v1 = w / w.sum()

    history = []
    eta = 1.0
    for it in range(12):
        boards = 1500 if it < 6 else 4000
        cfg = os.path.join(WORK, f"iter{it}.json")
        write_config(w, cfg, 1)
        df = simulate(cfg, boards, 1000 + it, os.path.join(WORK, f"iter{it}.tsv"))
        sim = sim_marginal(df, grid_cell_share)
        tv = 0.5 * np.abs(sim - obs).sum()
        history.append({"iter": it, "boardsPerCell": boards, "tv": float(tv),
                        "maxRelGap": float(np.max(np.abs(sim / obs - 1)))})
        print(f"iter {it}: TV(sim, obs) = {tv:.5f}", flush=True)
        w = w * (obs / sim) ** eta
        w = w / w.sum()

    fitted = w / w.sum()
    about = ("Spec 2.4 item 1, FITTED rather than assumed. Inverse-fitted against the observed letter marginal "
             "of 9,034 real ranked boards (data/ranked/fitted_distribution.json): the base distribution which, "
             "pushed through tier draw, seeding and best-of-N as in ruleset v1, reproduces the observed "
             "post-selection marginal. Everything else is identical to ruleset_v1.json.")
    write_config(fitted, V2, 2, about)

    # Fresh, larger evaluation of both configs on a seed no iteration used.
    ev1 = sim_marginal(simulate(V1, 6000, 777, os.path.join(WORK, "eval_v1.tsv")), grid_cell_share)
    ev2 = sim_marginal(simulate(V2, 6000, 777, os.path.join(WORK, "eval_v2.tsv")), grid_cell_share)
    out = {
        "method": "multiplicative fixed point w <- w*(obs/sim), genboards in the loop, tiers 20/50/30, "
                  "grids weighted by real cell share",
        "gridCellShare": grid_cell_share,
        "observedCells": int(sum(cells.values())),
        "iterations": history,
        "letters": {
            L: {
                "observed": float(obs[i]),
                "observed4x4": float(obs_by_grid["4x4"][i] / obs_by_grid["4x4"].sum()),
                "observed5x5": float(obs_by_grid["5x5"][i] / obs_by_grid["5x5"].sum()),
                "baseV1": float(base_v1[i]),
                "simulatedUnderV1": float(ev1[i]),
                "fittedBase": float(fitted[i]),
                "simulatedUnderFitted": float(ev2[i]),
                "selectionGap": float(obs[i] - fitted[i]),
            }
            for i, L in enumerate(LETTERS)
        },
        "tv": {
            "observed_vs_fittedBase": float(0.5 * np.abs(obs - fitted).sum()),
            "observed_vs_simUnderV1": float(0.5 * np.abs(obs - ev1).sum()),
            "observed_vs_simUnderFitted": float(0.5 * np.abs(obs - ev2).sum()),
            "baseV1_vs_fittedBase": float(0.5 * np.abs(base_v1 - fitted).sum()),
        },
    }
    json.dump(out, open(os.path.join(ROOT, "data", "ranked", "fitted_distribution.json"), "w"), indent=2)
    print(json.dumps(out["tv"], indent=2))


if __name__ == "__main__":
    sys.exit(main())

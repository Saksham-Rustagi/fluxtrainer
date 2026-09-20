"""Reachability per branch: P(branch present and reachable | stem path present).

Two sources, in that order of preference:

1. **Measured.** `runs/v3-m3-curated/reachability.tsv` carries P(reachable) for each of the 60
   affixes the measure tool mined from the dictionary, per grid and tier, over 30,000 boards a
   cell. Where a branch extends its stem by exactly one of those affixes, on one side, the
   measured number is used unchanged.

2. **Fitted.** Branches extend their stem by arbitrary letters on either or both sides
   (SERAI is RAI with SE- on the front), and most such extensions are not in the mined 60. For
   those, a per-letter multiplicative model fitted on the 60:

       log P(reach) = sum over front letters of bF[c] + sum over back letters of bB[c]

   The model is not an assumption bolted on: the measured table is already very close to
   multiplicative. -E x -S = 0.196 against a measured -ES of 0.225; -E x -R = 0.094 x ... see
   the fit report written to build-queue/reach_fit.json for the residuals. Branches priced this
   way are flagged `reachEstimated` everywhere they appear.

Both are conditional on the stem's path being present, which is the conditioning the queue
wants: given you have found the stem, how often is the branch actually there to be taken.
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd

import qcommon as Q

CELLS = [(g, t) for g in ("4x4", "5x5") for t in ("casual", "goodCasual", "spam")]


def load_measured():
    r = pd.read_csv(os.path.join(Q.SIM_M3, "reachability.tsv"), sep="\t")
    a = r[r.breakdown == "affix"].copy()
    a["side"] = np.where(a.key.str.startswith("-"), "back", "front")
    a["letters"] = a.key.str.strip("-")
    return a


def fit(measured):
    """Per-cell least squares on log p, one coefficient per (side, letter). No intercept."""
    out, report = {}, {}
    for grid, tier in CELLS:
        sub = measured[(measured.grid == grid) & (measured.tier == tier)]
        keys = sorted({("front", c) for w in sub[sub.side == "front"].letters for c in w} |
                      {("back", c) for w in sub[sub.side == "back"].letters for c in w})
        idx = {k: i for i, k in enumerate(keys)}
        X = np.zeros((len(sub), len(keys)))
        for i, (side, letters) in enumerate(zip(sub.side, sub.letters)):
            for c in letters:
                X[i, idx[(side, c)]] += 1
        y = np.log(sub.pPerPath.values)
        # weight by stemPaths: the measured p for a rare affix is itself noisier
        wt = np.sqrt(sub.stemPaths.values / sub.stemPaths.values.mean())
        beta, *_ = np.linalg.lstsq(X * wt[:, None], y * wt, rcond=None)
        pred = X @ beta
        ss = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        out[(grid, tier)] = {k: float(beta[i]) for k, i in idx.items()}
        report[f"{grid}:{tier}"] = {
            "n": int(len(sub)), "params": len(keys), "r2LogP": float(ss),
            "medianAbsRatio": float(np.median(np.abs(np.expm1(y - pred)))),
            "worst": sorted(({"affix": k, "measured": float(m), "fitted": float(np.exp(p))}
                             for k, m, p in zip(sub.key, sub.pPerPath, pred)),
                            key=lambda d: -abs(np.log(d["measured"] / d["fitted"])))[:5]}
    return out, report


class Reach:
    def __init__(self, tier_mix, grid_mix):
        self.measured = load_measured()
        self.beta, self.fitReport = fit(self.measured)
        self.exact = defaultdict(dict)
        for _, row in self.measured.iterrows():
            self.exact[(row.grid, row.tier)][(row.side, row.letters)] = float(row.pPerPath)
        self.w = {(g, t): grid_mix.get(g, 0.0) * tier_mix.get(t, 0.0) for g, t in CELLS}
        s = sum(self.w.values())
        self.w = {k: v / s for k, v in self.w.items()}
        # cellmate pathability, P(anagram has a valid path | word has one), by length
        cm = pd.read_csv(os.path.join(Q.SIM_M3, "cellmate_stats.tsv"), sep="\t")
        cm = cm[cm.relation == "anagram"]
        cm["w"] = [self.w.get((g, t), 0.0) for g, t in zip(cm.grid, cm.tier)]
        self.cellmate = (cm.assign(pw=cm.p * cm.w).groupby("len").pw.sum() /
                         cm.groupby("len").w.sum()).to_dict()

    def _cell(self, grid, tier, front, back):
        if not front and not back:
            return 1.0, False            # the stem itself
        ex = self.exact[(grid, tier)]
        if front and not back and ("front", front) in ex:
            return ex[("front", front)], False
        if back and not front and ("back", back) in ex:
            return ex[("back", back)], False
        b = self.beta[(grid, tier)]
        lo = 0.0
        for c in front:
            lo += b.get(("front", c), min(b.values()))
        for c in back:
            lo += b.get(("back", c), min(b.values()))
        return float(np.exp(lo)), True

    def additive(self, front, back):
        """Mix-weighted P(reachable), plus the per-cell values and an estimated flag."""
        per, est = {}, False
        for g, t in CELLS:
            p, e = self._cell(g, t, front, back)
            per[f"{g}:{t}"] = p
            est = est or e
        return sum(per[f"{g}:{t}"] * self.w[(g, t)] for g, t in CELLS), per, est

    def cellmate_p(self, n):
        return float(self.cellmate.get(min(int(n), max(self.cellmate)), 0.0))


if __name__ == "__main__":
    import json
    meta = json.load(open(os.path.join(Q.BUILD, "word_rates_meta.json")))
    r = Reach(meta["tierMixCur"], meta["gridMixCur"])
    print(json.dumps(r.fitReport["4x4:goodCasual"], indent=1))
    Q.dump_json(r.fitReport, os.path.join(Q.BUILD, "reach_fit.json"))
    for f, b in [("", "S"), ("", "ES"), ("", "ERS"), ("S", ""), ("SE", ""), ("", "ING"), ("TE", "S"), ("", "IEST")]:
        p, _, e = r.additive(f, b)
        print(f"{f}- -{b}: {p:.4f} estimated={e}")
    print("cellmate", {k: round(v, 3) for k, v in r.cellmate.items()})


def enum_calibration(R, cache=None):
    """Put per-stem enumerability into the units SPEC 7.5's 2-to-6 band was measured in.

    Summing per-branch reachability gives E[branches that extend the stem's path | stem path
    present], which is M1's condition. Phase 1's M3 measured E[members *findable* | stem
    present], and a member can be findable by a path that does not extend the stem's at all,
    so M3 is the larger quantity. The ratio between them is recovered by running this model
    over the same curatedWord stem population M3 used and dividing, per stem length.
    """
    import json
    import os
    import sys

    import pandas as pd
    cache = cache or os.path.join(Q.BUILD, "enum_calibration.json")
    if os.path.exists(cache):
        return {int(k): v for k, v in json.load(open(cache)).items()}
    sys.path.insert(0, os.path.join(Q.ROOT, "tools", "analytics"))
    import boardpass
    lex = sorted(Q.lexicon())
    curated = boardpass.curated_word_stems(lex)
    idx = {}
    for w in lex:
        L = len(w)
        if L > 9:
            continue
        for k in (3, 4, 5):
            for i in range(L - k + 1):
                s = w[i:i + k]
                if s in curated and s != w:
                    idx.setdefault(s, []).append(w)
    fs = pd.read_csv(os.path.join(Q.SIM_M3, "family_stats.tsv"), sep="\t")
    fs = fs[(fs.nQuartile == "all") & (fs["sample"] == "curatedWord")].copy()
    fs["w"] = [R.w.get((g, t), 0.0) for g, t in zip(fs.grid, fs.tier)]
    meas = (fs.assign(x=fs.enumerabilityOther * fs.w).groupby("stemLen").x.sum()
            / fs.groupby("stemLen").w.sum())
    out = {}
    for k in (3, 4, 5):
        vals = []
        for s in (x for x in idx if len(x) == k):
            t = 0.0
            for w in idx[s]:
                i = w.index(s)
                t += R.additive(w[:i], w[i + len(s):])[0]
            vals.append(t)
        out[k] = float(meas.get(k, np.nan) / np.mean(vals)) if vals else 1.0
    Q.dump_json(out, cache)
    return out

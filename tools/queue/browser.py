"""Pack the queue into reports/queue.html: one self-contained file, no server, no network.

Everything the page needs is embedded, including the per-hook study items and effort, so the
three track weights are live: moving them re-runs the same greedy ordering in the browser that
rank.order runs here, over the same numbers.
"""
import json
import os
import pickle

import numpy as np
import pandas as pd

import hooks as H
import qcommon as Q
import rank as RK

BRANCH_CAP = 30
BRANCH_REACH_FLOOR = 0.005

HOOK_COLS = ["stem", "stemLen", "isWord", "track", "score", "scoreStandalone", "value",
             "gainPar", "gainAlpha", "deadPoints", "effort", "studyItems", "owned", "learning",
             "unknown", "familySize", "branches", "presentShare", "pres4x4", "pres5x5",
             "presentGames", "enumerability", "enumerabilityFindable", "enumerabilitySource",
             "cueable", "coherence", "residual", "deadBranches", "why"]
TIERS = ["4x4_casual", "4x4_goodCasual", "4x4_spam", "5x5_casual", "5x5_goodCasual", "5x5_spam"]
# Per-branch rows carry only what is specific to the hook. Everything else about the word --
# its rates, presence, points, belief, expected gain -- is already in the words table and is
# joined in the page, which keeps the file a third of the size it would otherwise be.
CLS = ["additive", "cellmate", "mutating", "dead"]
SRC = ["measured", "fitted", "observed"]
WORD_COLS = ["word", "len", "pts", "track", "hook", "hookClass", "myRate", "fieldRate",
             "topQRate", "nTopQ", "achievable", "presPerGame", "nCur", "expectedGain",
             "belief", "status", "findability", "freeShare", "pathCount", "vowelInitial"]


def _r(x, n=5):
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    return None if not np.isfinite(f) else round(f, n)


def pack(B):
    hooks = [h for h in B["hooks"] if h["studyItems"] > 0 or h.get("deadPoints", 0) > 0.5]
    sidx, strings = {}, []

    def si(word):
        if word not in sidx:
            sidx[word] = len(strings)
            strings.append(word)
        return sidx[word]

    hrows, hitems, hbranches, htiers, hdead = [], [], [], [], []
    for h in hooks:
        hrows.append([_r(h.get(c)) for c in HOOK_COLS])
        hitems.append([[si(w), _r(v, 3), 0 if t == "par" else 1] for w, v, t in h["items"]])
        htiers.append([_r(h["presTier"].get(t), 4) for t in TIERS])
        br = B["branches"][h["stem"]][0]
        keep = [b for b in br if b["gain"] > 0 or b["reach"] >= BRANCH_REACH_FLOOR
                or b["status"] in ("known", "learning")][:BRANCH_CAP]
        hbranches.append([[si(b["word"]), CLS.index(b["cls"]), _r(b["reach"], 4),
                           SRC.index(b["reachSource"]), 1 if b.get("earns") else 0]
                          for b in keep])
        hdead.append([[si(d["word"]), d["ext"]] for d in B["branches"][h["stem"]][1][:12]])

    q = B["queue"].rename(columns={"my": "myRate", "fieldRateAll": "fieldRate", "topQ": "topQRate",
                                   "nTopQAll": "nTopQ", "presPerGameCur": "presPerGame"})
    q = q.reset_index().rename(columns={"index": "word"})
    allw = B["words"].rename(columns={"my": "myRate", "fieldRateAll": "fieldRate",
                                      "topQ": "topQRate", "nTopQAll": "nTopQ",
                                      "presPerGameCur": "presPerGame"})
    allw = allw[(allw.nCur >= H.MIN_PRES) & allw.inLexicon & ~allw.neverAccepted].copy()
    allw = allw.reset_index().rename(columns={"index": "word"})
    allw["hook"] = allw.word.map(dict(zip(q.word, q.hook))).fillna("")
    allw["hookClass"] = allw.word.map(dict(zip(q.word, q.hookClass))).fillna("")
    allw["findability"] = allw.word.map(dict(zip(q.word, q.findability))).fillna("")
    fnd = RK.findability(B["words"])
    for c in ("freeShare", "pathCount"):
        allw[c] = allw.word.map(fnd[c])
    allw["vowelInitial"] = allw.word.str[0].isin(list("AEIOU"))
    allw["achievable"] = np.fmax(allw.topQRate, allw.myRate)
    sim = pd.read_parquet(os.path.join(Q.BUILD, "sim_presence.parquet"))
    allw = allw.join(sim, on="word")
    allw = allw.sort_values("expectedGain", ascending=False)
    words = [[si(r.word)] + [_r(getattr(r, c), 4) for c in WORD_COLS[1:]]
             + [_r(getattr(r, f"pAppear_{t}"), 4) for t in TIERS]
             + ["".join(sorted(r.word))] for r in allw.itertuples()]

    mw = B["misswipes"].fillna("")
    return {
        "meta": B["meta"], "summary": B["summaryStats"], "strings": strings,
        "hookCols": HOOK_COLS, "hooks": hrows, "hookItems": hitems, "hookTiers": htiers,
        "branches": hbranches, "dead": hdead, "cls": CLS, "src": SRC, "tiers": TIERS,
        "wordCols": WORD_COLS + [f"p_{t}" for t in TIERS] + ["akey"], "words": words,
        "misswipeCols": list(mw.columns),
        "misswipes": [[_r(v) for v in row] for row in mw.values.tolist()],
        "weights": dict(RK.WEIGHTS), "cost": dict(RK.COST),
        "ownedDiscount": RK.OWNED_DISCOUNT, "enumBand": list(H.ENUM_BAND),
        "deadMeta": B["deadMeta"], "clone": B["clone"], "branchCap": BRANCH_CAP,
        "generated": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
    }


def render(B, out=None):
    tmpl = open(os.path.join(os.path.dirname(__file__), "queue_template.html")).read()
    data = json.dumps(pack(B), separators=(",", ":"), default=Q._default)
    out = out or os.path.join(Q.REPORTS, "queue.html")
    with open(out, "w") as f:
        f.write(tmpl.replace("/*__DATA__*/null", data))
    return out, len(data)


if __name__ == "__main__":
    B = pickle.load(open(os.path.join(Q.BUILD, "bundle.pkl"), "rb"))
    if "summaryStats" not in B:
        import emit
        B["summaryStats"] = emit.summary(B)
    p, n = render(B)
    print(p, f"{n / 1e6:.1f} MB of data")

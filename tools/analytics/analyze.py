"""Run every report analysis for FLUX_PLAYER. Writes build-analytics/<player>/results.json and figures.json.

Usage: analyze.py [section ...]   (default: all). Sections: s0 s1 s2 s3 s4 s5 s6 s7
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import BUILD, FIGS, NAME, RANKED, add_regime, load  # noqa: E402
import viz  # noqa: E402

OUT = BUILD


def jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def main(argv):
    want = set(argv) or {"s0", "sd", "s1", "s2", "s3", "s4", "s5", "sr", "s6", "s7", "sh", "sa", "sp"}
    rpath = os.path.join(OUT, "results.json")
    fpath = os.path.join(OUT, "figures.json")
    R = json.load(open(rpath)) if os.path.exists(rpath) and argv else {}
    if os.path.exists(fpath) and argv:
        viz.FIGURES.update(json.load(open(fpath)))
    R["holdout"] = [h for h in R.get("holdout", []) if h.get("section") not in want]

    import peer
    g = peer.mark(add_regime(load("games.parquet")))
    f = load("finds_derived.parquet")
    pres = pd.read_parquet(os.path.join(RANKED, "presence.parquet"))
    pres["grid"] = pres.grid.astype(str)
    # Dictionary drift (report section 0): CSW21 words present on 50+ boards that nobody,
    # player or any opponent, ever had accepted -- in this export or the other player's.
    # Either Flux's list lacks them or the whole field ignores them; neither way are they
    # vocabulary targets, so section 4 drops them. A word accepted anywhere is accepted.
    anyf = pres.foundPlayer | pres.foundOpp.fillna(False).astype(bool)
    w = anyf.groupby(pres.word).agg(["size", "sum"])
    dead_here = w[(w["size"] >= 50) & (w["sum"] == 0)]
    peer_found = peer.found_words() if peer.available() else set()
    dead = dead_here[~dead_here.index.isin(peer_found)]
    R["_dead"] = set(dead.index)
    R["drift"] = {"words": int(len(dead)), "presenceShare": float(pres.word.isin(R["_dead"]).mean()),
                  "potentialShare": float(pres.pts[pres.word.isin(R["_dead"])].sum() / pres.pts.sum()),
                  "byLen": dead.index.str.len().value_counts().sort_index().to_dict(),
                  "mostPresent": dead.sort_values("size", ascending=False).head(40).index.tolist(),
                  "deadInThisExportOnly": int(len(dead_here)), "acceptedInPeerExport": int(len(dead_here) - len(dead)),
                  "acceptedInPeerExamples": dead_here[dead_here.index.isin(peer_found)].sort_values("size", ascending=False).head(12).index.tolist()}
    os.makedirs(FIGS, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    dead.rename(columns={"size": "presences", "sum": "finds"}).sort_values("presences", ascending=False).reset_index().to_csv(
        os.path.join(FIGS, "s0_never_accepted_words.tsv"), sep="\t", index=False)
    pres_voc = pres[~pres.word.isin(R["_dead"])]
    pl = pres.groupby(["gid", "len"]).size()
    R["_pres_len"] = {gid: dict(zip(x.index.get_level_values(1), x.values)) for gid, x in pl.groupby(level=0)}

    def dump():
        clean = {k: v for k, v in R.items() if not k.startswith("_")}
        clean["player"] = NAME
        json.dump(clean, open(rpath, "w"), indent=1, default=jsonable)
        json.dump(viz.FIGURES, open(fpath, "w"))

    def run(name, fn):
        if name not in want:
            return
        t = time.time()
        before = len(R.get("holdout", []))
        fn()
        for h in R["holdout"][before:]:
            h["section"] = name
        print(f"{name}: {time.time() - t:.1f}s", flush=True)
        dump()

    import importlib

    def mod(name):
        return importlib.import_module(name)

    run("s0", lambda: mod("s0_s1").section0(R, g, f, pres))
    run("sd", lambda: mod("sdict").section(R, g, pres))
    run("s1", lambda: mod("s0_s1").section1(R, g, f))
    run("s2", lambda: mod("s2").section2(R, g, f))
    run("s3", lambda: mod("s3").section3(R, g, f, pres))
    run("s4", lambda: mod("s4").section4(R, g, f, pres_voc))
    run("s5", lambda: mod("s5").section5(R, g, f, pres))
    run("s6", lambda: mod("s6_s7").section6(R, g, f, pres))
    run("s7", lambda: mod("s6_s7").section7(R, g, f))
    run("sr", lambda: mod("sregime").section(R))
    run("sh", lambda: mod("sh2h").section(R, g, f, pres))
    run("sa", lambda: mod("salpha").section(R, g, f, pres))
    run("sp", lambda: mod("sbase").peer_figures(R))
    clean = {k: v for k, v in R.items() if not k.startswith("_")}
    clean["player"] = NAME
    json.dump(clean, open(rpath, "w"), indent=1, default=jsonable)
    json.dump(viz.FIGURES, open(fpath, "w"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

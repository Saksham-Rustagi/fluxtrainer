"""The hook record: the one shape Phase 2 writes and Phase 3 reads.

Phase 2 ranks hooks and Phase 3 drills them. Before this module the only thing crossing
between them was `reports/queue_hooks.tsv`, which is a *report*: it flattens a hook to one
line, drops the branch list entirely and drops `presTier` (the per-tier, per-grid presence
bound) because a dict does not fit in a TSV cell. A drill cannot run on that. This module
is the contract instead, and both sides are generated from the field lists below so they
cannot drift:

    hookrecord.py  ->  reports/hooks.ndjson.gz          the full 10,594, canonical
                   ->  ios/FluxClone/Resources/training_hooks.json   what the app carries
                   ->  ios/FluxClone/Training/HookRecord.swift is checked against
                       SCHEMA_VERSION at load time and refuses a mismatch.

The record is the Phase 3 prompt's shape, with the extra fields the on-device recompute
needs (§"What gets recorded": the app recombines ranked and in-app presences, so it needs
the ranked numerator and denominator, not just the ratio):

    Hook {
      stem, branches[{ word, class, myRate, topQuartileRate, reachability, points }],
      residual, enumerability, presenceByTierGrid, expectedGain, track
    }

Naming note: the prompt writes `class` and `topQuartileRate`; the Phase 2 code calls them
`cls` and `topQRate`. The record uses the prompt's names, since it is the interface, and
the mapping lives here in one place.
"""
import gzip
import json
import os

import hooks as H
import qcommon as Q

SCHEMA_VERSION = 1

# A branch below this reachability is never on the board when the stem is (hooks.py's
# BRANCH_REACH_FLOOR). Kept out of the record for the same reason it is kept out of the
# listings: it is not something the player can be asked to find.
BRANCH_REACH_FLOOR = 0.005

# Hook fields, in the order the Swift decoder declares them.
HOOK_FIELDS = [
    "stem", "stemLen", "isWord", "rank", "track", "score", "expectedGain", "residual",
    "enumerability", "enumerabilityModel", "enumerabilitySource", "cueable",
    "owned", "learning", "unknown", "studyItems", "familySize", "branchCount",
    "presentShare", "presentGames", "presenceByTierGrid", "deadBranches", "deadPoints",
    "effort", "why",
]

BRANCH_FIELDS = [
    "word", "cls", "ext", "points", "reachability", "reachSource",
    "myRate", "topQuartileRate", "nTopQuartile", "presences", "finds", "opportunity",
    "presencesPerGame", "belief", "status", "expectedGain", "earns", "misswiped",
]

# The session draws from here (Phase 3 prompt, "The session"): top of the queue filtered to
# enumerability 2-6 and owned >= 2. The bundle carries a margin around that filter, because
# `owned` moves as the app plays -- a hook at owned == 1 today is eligible next week, and a
# bundle that only held today's eligible set would need a rebuild to notice.
BUNDLE_MIN_OWNED = 1
BUNDLE_MAX_HOOKS = 3000

# Branch caps, bundle only. The full file keeps everything above the reach floor.
#
# These are not size trimming for its own sake. A hook's live branch list on a *board* is
# not read from the bundle at all: SPEC 7.3's containment rule means an additive branch of
# S is exactly a solved word containing S, so the app derives the present branches from the
# board's own solve. What the bundle has to carry is the part that cannot be derived --
# Phase 2's per-pair reachability and the player's per-word rates -- and that is only worth
# carrying for branches the drill can actually reach. ERAS- has 158 branches and the drill
# shows at most 6.
BUNDLE_LIVE_BRANCHES = 40   # additive and cellmate, by value then reachability
BUNDLE_DEAD_BRANCHES = 40   # dead, already sorted by productivity * reachability
BUNDLE_MIN_REACH = 0.02     # below this a branch is on the board under 1 board in 50


def _branch(b, misswiped):
    """One branch, in the record's names. `cls` is the prompt's `class`, which is a Swift
    and a Python keyword on both sides, so the wire name stays `cls`."""
    return {
        "word": b["word"],
        "cls": b["cls"],
        "ext": b.get("ext", ""),
        "points": int(b.get("pts") or Q.points(len(b["word"]))),
        # SPEC 7.5.1's P(reachable | stem present): observed on the player's own boards
        # where the stem was present often enough, the fitted model otherwise.
        "reachability": _f(b.get("reach", b.get("reachModel"))),
        "reachSource": b.get("reachSource", "measured"),
        "myRate": _f(b.get("myRate")),
        "topQuartileRate": _f(b.get("topQRate")),
        "nTopQuartile": int(b.get("nTopQ") or 0),
        "presences": int(b.get("nCur") or 0),
        "finds": int(b.get("kCur") or 0),
        "opportunity": _f(b.get("opportunity")),
        "presencesPerGame": _f(b.get("presPerGame")),
        "belief": _f(b.get("belief")),
        "status": b.get("status", "unseen"),
        "expectedGain": _f(b.get("gain")),
        "earns": bool(b.get("earns", False)),
        "misswiped": int(misswiped.get(b["word"], 0)),
    }


def opportunity():
    """The ranked import's opportunity weighting, restricted to the current regime.

    SPEC 8.1 draws a hard line between "present, in a region you covered, not swiped"
    (evidence) and "present, in a region with zero swipe-time" (no inference possible).
    The ranked analysis (tools/analytics/s4.py) implements the continuous version of that
    line and Phase 3 has to continue it, not invent a second one: a presence is weighted by
    how likely a *known* word of that length was to be taken on that board, which is the
    board's own find rate for the length class against the rate on the boards where he took
    the most. On a 900-word board where he found 96, a miss says almost nothing.

    Returns (per-word sums, the p90 reference table, the per-length Beta priors). The last
    two go into the bundle so the device weights an in-app presence on exactly the same
    scale as a ranked one, which is the only way the two can be added together.
    """
    import numpy as np
    import pandas as pd
    from s4 import beta_mom

    g = pd.read_parquet(os.path.join(Q.RANKED, "games.parquet"),
                        columns=["gid", "season", "grid"])
    g = g[g.season >= Q.CURRENT_FROM_SEASON][["gid", "grid"]]
    p = pd.read_parquet(os.path.join(Q.RANKED, "presence.parquet"),
                        columns=["gid", "word", "len", "foundPlayer"])
    p = p.merge(g, on="gid")
    p["lc"] = np.minimum(p.len, 7)
    p["fp"] = p.foundPlayer.astype(float)

    br = p.groupby(["gid", "lc"], observed=True).agg(n=("fp", "size"), k=("fp", "sum")).reset_index()
    br["rate"] = br.k / br.n
    br = br.merge(g, on="gid")
    ref = br.groupby(["grid", "lc"], observed=True).rate.quantile(0.9).rename("ref").reset_index()
    br = br.merge(ref, on=["grid", "lc"])
    br["opp"] = (br.rate / br.ref).clip(upper=1)
    p = p.merge(br[["gid", "lc", "opp"]], on=["gid", "lc"])

    w = p.groupby("word").agg(lc=("lc", "first"), present=("fp", "size"), found=("fp", "sum"),
                              opp=("opp", "sum"))
    priors = {}
    for lc, x in w.groupby("lc"):
        fit = x[x.present >= 10]
        if len(fit) < 20:
            continue
        a, b = beta_mom((fit.found / fit.opp).clip(upper=1).values, fit.opp.values)
        priors[int(lc)] = [float(a), float(b)]

    table = {f"{r.grid}_{int(r.lc)}": float(round(r.ref, 6)) for r in ref.itertuples()}
    return w.opp.round(4).to_dict(), table, priors


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, 6)


def build(B, opp=None):
    """Turn the Phase 2 bundle into hook records. `B` is what emit.build() returns."""
    words = B["words"]
    nCur = words.nCur.to_dict()
    kCur = words.kCur.to_dict()
    opp = opp or {}
    misswiped = {}
    mw = B["misswipes"]
    for _, r in mw.iterrows():
        misswiped[r["attempt"]] = max(misswiped.get(r["attempt"], 0), int(r["times"]))

    out = []
    for h in B["hooks"]:
        brs, dead = B["branches"][h["stem"]]
        kept = []
        for b in list(brs) + list(dead):
            reach = b.get("reach", b.get("reachModel")) or 0.0
            if b["cls"] in ("additive", "cellmate") and reach < BRANCH_REACH_FLOOR:
                continue
            b = dict(b)
            b["nCur"] = nCur.get(b["word"], 0)
            b["kCur"] = kCur.get(b["word"], 0)
            b["opportunity"] = opp.get(b["word"])
            kept.append(_branch(b, misswiped))
        rec = {
            "stem": h["stem"],
            "stemLen": h["stemLen"],
            "isWord": bool(h["isWord"]),
            "rank": int(h["rank"]),
            "track": h["track"],
            "score": _f(h["score"]),
            # The hook's total: what the queue expects to gain a game from the branches it
            # is still teaching. gainPar and gainAlpha are the two tracks of the same sum.
            "expectedGain": _f(h["gainPar"] + h["gainAlpha"]),
            "residual": _f(h["residual"]),
            # The 2-to-6 band's units (SPEC 7.5 condition 1), which is the *findable*
            # number: observed where there is enough co-presence, calibrated otherwise.
            "enumerability": _f(h["enumerabilityFindable"]),
            "enumerabilityModel": _f(h["enumerability"]),
            "enumerabilitySource": h["enumerabilitySource"],
            "cueable": bool(h["cueable"]),
            "owned": int(h["owned"]),
            "learning": int(h["learning"]),
            "unknown": int(h["unknown"]),
            "studyItems": int(h["studyItems"]),
            "familySize": int(h["familySize"]),
            "branchCount": int(h["branches"]),
            "presentShare": _f(h["presentShare"]),
            "presentGames": int(h["presentGames"]),
            # SPEC 11.1 needs a tier for a training board; this is the per-(grid, tier)
            # presence bound rank.py computes, and it is a *lower* bound -- see
            # rank._tier_presence. The app uses it to pick a grid and tier that actually
            # carry the stem, never as a probability.
            "presenceByTierGrid": {k: _f(v) for k, v in h["presTier"].items()},
            "deadBranches": int(h["deadBranches"]),
            "deadPoints": _f(h.get("deadPoints", 0.0)),
            "effort": _f(h["effort"]),
            "why": h["why"],
            "branches": kept,
        }
        out.append(rec)
    return out


def write_full(records, path=None):
    """The canonical file: gzipped ndjson, one hook per line, ranked order."""
    path = path or os.path.join(Q.REPORTS, "hooks.ndjson.gz")
    header = {"schema": SCHEMA_VERSION, "hooks": len(records),
              "hookFields": HOOK_FIELDS, "branchFields": BRANCH_FIELDS,
              "branchReachFloor": BRANCH_REACH_FLOOR}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return path, os.path.getsize(path)


def read_full(path=None):
    path = path or os.path.join(Q.REPORTS, "hooks.ndjson.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = json.loads(f.readline())
        if header["schema"] != SCHEMA_VERSION:
            raise ValueError(f"hook record schema {header['schema']}, expected {SCHEMA_VERSION}")
        return header, [json.loads(line) for line in f]


def _trim(rec):
    """One bundled hook: same fields, a shorter branch list. See the cap constants."""
    live, dead, mut = [], [], []
    for b in rec["branches"]:
        if b["cls"] == "dead":
            dead.append(b)
        elif b["cls"] == "mutating":
            mut.append(b)
        elif b["earns"] or (b["reachability"] or 0) >= BUNDLE_MIN_REACH:
            live.append(b)
    live.sort(key=lambda b: (not b["earns"], -(b["expectedGain"] or 0),
                             -(b["reachability"] or 0)))
    out = dict(rec)
    out["branches"] = live[:BUNDLE_LIVE_BRANCHES] + mut + dead[:BUNDLE_DEAD_BRANCHES]
    out["branchesTrimmed"] = len(rec["branches"]) - len(out["branches"])
    return out


def _columnar(rows, fields):
    """[{...}] -> {"fields": [...], "rows": [[...]]}. JSON keys repeated once per hook
    instead of once per branch; on this data that is a little over a third of the bytes."""
    return {"fields": fields, "rows": [[r.get(f) for f in fields] for r in rows]}


# The acquisition board's density band, measured rather than invented.
#
# The Phase 3 prompt overrides SPEC 11.1's "reject outside the tier's middle 80%" with a wide
# floor and ceiling on total word count, and says the floor matters more because embedding a
# hook pulls boards dense. p10-to-p95 of the player's own current-regime boards, per grid, is
# that band: it covers 85% of the boards he actually meets, its floor is the real 4x4 floor
# rather than a tier's, and the ceiling only exists to keep a pathological board out.
DENSITY_LOW_Q, DENSITY_HIGH_Q = 0.10, 0.95


def board_density():
    import pandas as pd
    g = pd.read_parquet(os.path.join(Q.RANKED, "games.parquet"),
                        columns=["gid", "season", "grid", "nPresent"])
    g = g[g.season >= Q.CURRENT_FROM_SEASON]
    out = {}
    for grid, sub in g.groupby("grid"):
        side = int(str(grid)[0])
        out[str(side)] = {
            "minWords": int(round(sub.nPresent.quantile(DENSITY_LOW_Q))),
            "maxWords": int(round(sub.nPresent.quantile(DENSITY_HIGH_Q))),
            "medianWords": int(round(sub.nPresent.median())),
            "boards": int(len(sub)),
        }
    return out


def bundle(records, opp_table=None, priors=None):
    """What the app ships with. Everything the session can reach plus a margin."""
    keep = [_trim(r) for r in records
            if r["cueable"] and r["owned"] >= BUNDLE_MIN_OWNED and r["studyItems"] >= 1]
    keep = keep[:BUNDLE_MAX_HOOKS]
    hook_fields = HOOK_FIELDS + ["branchesTrimmed"]
    out = []
    for r in keep:
        row = {f: r[f] for f in hook_fields}
        row["branches"] = _columnar(r["branches"], BRANCH_FIELDS)
        out.append(row)
    return {"schema": SCHEMA_VERSION,
            "generated": _utcnow(),
            "player": Q.PLAYER,
            "hookFields": hook_fields,
            "branchFields": BRANCH_FIELDS,
            "queueTotal": len(records),
            "boardDensity": board_density(),
            # The belief model's two constants, so an in-app presence is weighted on the
            # same scale as a ranked one and the two can simply be added (SPEC 8.1).
            "opportunityRef": opp_table or {},
            "beliefPriors": priors or {},
            # SPEC 7.3 mechanism 3: the affix alphabet, mined from the dictionary. The app
            # derives a hook's dead branches from these plus a DAWG lookup rather than
            # carrying them per hook, which is the same derivation rank.py does.
            "minedAffixes": [{"side": s, "letters": a} for s, a in H.mined_affixes()],
            "hooks": out}


def write_bundle(records, path=None, opp_table=None, priors=None):
    path = path or os.path.join(Q.ROOT, "ios", "FluxClone", "Resources", "training_hooks.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    b = bundle(records, opp_table, priors)
    with open(path, "w") as f:
        json.dump(b, f, separators=(",", ":"))
    return path, os.path.getsize(path), len(b["hooks"])


def _utcnow():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    import pickle
    B = pickle.load(open(os.path.join(Q.BUILD, "bundle.pkl"), "rb"))
    opp, opp_table, priors = opportunity()
    records = build(B, opp)
    p1, s1 = write_full(records)
    p2, s2, n = write_bundle(records, opp_table=opp_table, priors=priors)
    branches = sum(len(r["branches"]) for r in records)
    print(f"{len(records):,} hooks, {branches:,} branches above the reach floor")
    print(f"{os.path.relpath(p1, Q.ROOT)}  {s1 / 1e6:.1f} MB")
    print(f"{os.path.relpath(p2, Q.ROOT)}  {s2 / 1e6:.1f} MB  ({n:,} hooks)")


if __name__ == "__main__":
    main()

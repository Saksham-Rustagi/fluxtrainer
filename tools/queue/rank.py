"""Repricing, hook assembly and ordering. This is the selection engine.

## Repricing

The alpha list shipped with Phase 0 priced every word at a uniform 74% achievable take rate,
taken from the rate the player reaches on words he already finds reliably. That is selection:
a word is reliable because he finds it. Applied to a word he takes 0.3% of the time it assumes
learning closes the whole gap.

Replaced by the per-word top-quartile rate, floored at his own:

    achievable(w)    = max(topQuartileRate(w), myRate(w))
    expectedGain(w)  = presencesPerGame(w) * points(w) * (achievable(w) - myRate(w))

Words he already takes more often than the top quartile go to zero gain by construction and
leave the queue. The top-quartile rate is the opponents' find rate restricted to opponents in
the top quartile of leave-one-out Elo, and it is noisy for rare words, so it is only trusted
above MIN_TOPQ presences; below that the word carries no gain and is flagged.

## Ordering

    score(H) = (wPar*gainPar + wAlpha*gainAlpha + wMisswipe*deadPoints) / effort(H)

Every component is written out per hook so the ranking can be read without running anything.
The three weights are the blend and are adjustable, in config and in the browser.

Effort counts study items, not words on the page: only the unknown branches that carry gain,
at 1.0 for an additive branch (it extends a path already being swiped), 1.3 for a cellmate
(the cells are located but the path must be found fresh) and 0.35 for a dead or mutating form
(a valid/invalid judgment at affix-grid throughput, not a word to learn). A hook with two or
more owned branches gets OWNED_DISCOUNT applied: the stem, the motor pattern and the habit of
looking there are already paid for, so the remaining branches are close to free.
"""
import heapq
import os
from collections import defaultdict

import numpy as np
import pandas as pd

import hooks as H
import misswipe as M
import qcommon as Q
import reach as Rch

MIN_TOPQ = 30          # top-quartile presences needed before that rate is trusted
MIN_PRES_WORD = 20     # a word needs this many current-regime presences to carry a gain
MIN_LEN = 4            # 3-letter words are filler (SPEC 3.2, 7.4); browsable, not rankable

COST = {"additive": 1.0, "cellmate": 1.3, "mutating": 0.35, "dead": 0.35}
OWNED_DISCOUNT = 0.6
DEAD_GRID_CAP = 8      # dead/mutating forms per hook that count as one sitting's drill

# SPEC 7.6: a cellmate is only worth teaching where the anagram actually has a path once the
# host does. Phase 1 measured that at 0.78 / 0.53 / 0.34 / 0.21 for lengths 3 / 4 / 5 / 6, so
# only 3s and 4s clear the 0.5 threshold. Longer anagrams are listed on the hook and carry no
# value and no effort: they earn under their own stems, where they are additive.
CELLMATE_MIN_P = 0.5
# A branch whose own presence accounts for nearly every game the stem was present is not
# evidence of anything -- the stem was present *because* the branch was. Above this the
# observed conditional is discarded and the simulator's number is used.
OBS_MAX_SHARE = 0.8

WEIGHTS = {"par": 1.0, "alpha": 1.0, "misswipe": 0.2}
# misswipe default 0.2: the clone measures what affix errors cost (5.14 s a game) but nothing
# measures how much of that drilling removes. 0.2 is a judgement, not a measurement, and the
# summary reports the top 100 at 0.0, 0.2 and 1.0.


def _bool(x):
    return bool(x) if x == x else False


def reprice(words):
    w = words.copy()
    w["topQ"] = np.where(w.nTopQAll >= MIN_TOPQ, w.topQRateAll, np.nan)
    w["topQTrusted"] = w.nTopQAll >= MIN_TOPQ
    w["my"] = w.myRateCur
    w["achievable"] = np.fmax(w.topQ, w.my)
    gap = np.where(np.isfinite(w.achievable) & np.isfinite(w.my), w.achievable - w.my, 0.0)
    w["rateGap"] = np.maximum(gap, 0.0)
    ok = (w.nCur >= MIN_PRES_WORD) & (w.len >= MIN_LEN) & w.inLexicon & ~w.neverAccepted
    w["rankable"] = ok & w.topQTrusted
    w["expectedGain"] = np.where(w.rankable, w.presPerGameCur * w.pts * w.rateGap, 0.0)
    w["track"] = np.where(w.fieldRateAll < 0.10, "alpha", "par")
    w["status"] = np.where(w.belief > H.BELIEF_OWNED, "known",
                           np.where(w.belief < H.BELIEF_UNKNOWN, "unknown", "learning"))
    # shrunk top-quartile rate, reported as a sensitivity only (empirical Bayes by length)
    w["topQShrunk"] = _shrink(w)
    ach2 = np.fmax(w.topQShrunk, w.my)
    w["expectedGainShrunk"] = np.where(ok, w.presPerGameCur * w.pts * np.maximum(ach2 - w.my, 0), 0.0)
    return w


def _shrink(w):
    """Beta-binomial shrinkage of the top-quartile rate toward the per-length mean."""
    out = np.full(len(w), np.nan)
    for L, idx in w.groupby(w.len).groups.items():
        sub = w.loc[idx]
        n, k = sub.nTopQAll.values, sub.kTopQAll.values
        m = n >= 10
        if m.sum() < 20:
            continue
        p = (k[m] / n[m])
        mu, var = p.mean(), p.var()
        if var <= 0 or mu <= 0 or mu >= 1:
            continue
        s = max(mu * (1 - mu) / var - 1, 1.0)
        out[w.index.get_indexer(idx)] = (k + mu * s) / (n + s)
    return out


def findability(words):
    """Measured chaining and path signals, for telling an unknown word from an unfindable one."""
    import pickle
    bp = pickle.load(open(os.path.join(Q.ROOT, "build-analytics", Q.PLAYER, "boardpass_all.pkl"), "rb"))
    g = pd.read_parquet(os.path.join(Q.RANKED, "games.parquet"), columns=["gid", "season"])
    cur = set(g.gid[g.season >= Q.CURRENT_FROM_SEASON])
    m = bp["missed"]
    m = m[m.gid.isin(cur)]
    f = m.groupby("word").agg(freeShare=("freeForP", "mean"), cellmateShare=("cellmateOfFound", "mean"),
                              dtShare=("dtOfFound", "mean"))
    host = m[m.host != ""].groupby("word").host.agg(lambda s: s.value_counts().index[0])
    f["observedHost"] = host
    pres = pd.read_parquet(os.path.join(Q.RANKED, "presence.parquet"), columns=["gid", "word", "pathCount"])
    f["pathCount"] = pres[pres.gid.isin(cur)].groupby("word").pathCount.mean()
    f["vowelInitial"] = f.index.str[0].isin(list("AEIOU"))
    return f


def assemble(words, meta):
    sim = pd.read_parquet(os.path.join(Q.BUILD, "sim_presence.parquet"))
    lex = Q.lexicon()
    R = Rch.Reach(meta["tierMixCur"], meta["gridMixCur"])
    affixes = H.mined_affixes()
    prod = H.affix_productivity(lex, affixes)
    cal = Rch.enum_calibration(R)
    fam, closure_dropped, n_uni = H.mine(words, lex)
    exclude = set(words.index[words.neverAccepted])
    stem_share, stem_games, obs, ngames, stem_grid = H.copresence(fam, words, exclude)

    w = reprice(words)
    fnd = findability(words)
    w = w.join(fnd)
    wd = w.to_dict("index")

    akey = defaultdict(list)
    for x in lex:
        if 4 <= len(x) <= H.MAX_MEMBER_LEN:
            akey["".join(sorted(x))].append(x)

    hook_rows, branch_rows = [], []
    for s, members in fam.items():
        share = stem_share.get(s, 0.0)
        if share < 0.005:
            continue
        brs = []
        for m in sorted(members):
            i = m.index(s)
            p, per, est = R.additive(m[:i], m[i + len(s):])
            o = obs.get((s, m))
            brs.append(dict(word=m, cls="additive", ext=(m[:i] + "-" if m[:i] else "") + ("-" + m[i + len(s):] if m[i + len(s):] else ""),
                            reachModel=p, reachObs=(o[1] if o else np.nan), coPresent=(o[0] if o else 0),
                            reachEstimated=est))
        seen = {b["word"] for b in brs} | {s}
        for b in list(brs):
            for c in akey.get("".join(sorted(b["word"])), []):
                if c in seen or s in c:
                    continue
                seen.add(c)
                o = obs.get((s, c))
                brs.append(dict(word=c, cls="cellmate", ext="anagram of " + b["word"],
                                reachModel=b["reachModel"] * R.cellmate_p(len(c)),
                                reachObs=(o[1] if o else np.nan), coPresent=(o[0] if o else 0),
                                reachEstimated=True))
        for m in sorted(H.mutating_candidates(s, lex)):
            if m not in seen:
                seen.add(m)
                brs.append(dict(word=m, cls="mutating", ext="mutation", reachModel=0.0,
                                reachObs=np.nan, coPresent=0, reachEstimated=False))
        dead, dead_exposure = [], 0.0
        for side, a in affixes:
            cand = (s + a) if side == "back" else (a + s)
            if cand in lex:
                continue
            p, _, _ = R.additive("" if side == "back" else a, a if side == "back" else "")
            dead.append(dict(word=cand, cls="dead",
                             ext=("-" + a) if side == "back" else (a + "-"),
                             reachModel=p, reachObs=np.nan, coPresent=0, reachEstimated=False,
                             weight=prod[(side, a)]))
            dead_exposure += prod[(side, a)] * p
        dead.sort(key=lambda d: -d["weight"] * d["reachModel"])

        enum = sum(b["reachModel"] for b in brs if b["cls"] == "additive")
        enum_obs = sum(b["reachObs"] for b in brs if b["cls"] == "additive" and b["reachObs"] == b["reachObs"])
        # the 2-to-6 band is in M3's units, so report enumerability there: measured on the
        # player's own boards where the stem is present often enough, calibrated model otherwise
        if stem_games[s] >= H.MIN_COPRESENT:
            enum_find, enum_src = enum_obs, "observed"
        else:
            enum_find, enum_src = enum * cal.get(len(s), 1.0), "calibrated"
        lens = [len(b["word"]) for b in brs if b["cls"] == "additive"]
        coherence = float(np.mean([len(s) / L for L in lens])) if lens else 0.0

        owned = unknown = learning = 0
        gain_par = gain_alpha = residual = effort = 0.0
        items = []
        sg = stem_games[s]
        for b in brs:
            d = wd.get(b["word"])
            use_obs = (b["reachObs"] == b["reachObs"] and sg >= H.MIN_COPRESENT
                       and b["coPresent"] <= OBS_MAX_SHARE * sg)
            b["reach"] = float(b["reachObs"] if use_obs else b["reachModel"])
            b["reachSource"] = ("observed" if use_obs else
                                ("fitted" if b["reachEstimated"] else "measured"))
            b["belief"] = float(d["belief"]) if d is not None and d["belief"] == d["belief"] else np.nan
            b["status"] = d["status"] if d is not None else "unseen"
            b["myRate"] = float(d["my"]) if d is not None else np.nan
            b["fieldRate"] = float(d["fieldRateAll"]) if d is not None else np.nan
            b["topQRate"] = float(d["topQ"]) if d is not None else np.nan
            b["nTopQ"] = int(d["nTopQAll"]) if d is not None else 0
            b["presPerGame"] = float(d["presPerGameCur"]) if d is not None else 0.0
            b["pts"] = int(Q.points(len(b["word"])))
            b["gain"] = float(d["expectedGain"]) if d is not None else 0.0
            b["track"] = d["track"] if d is not None else ""
            # Does this branch's gain belong to *this* hook? Only if the hook is how it gets
            # found: the path extends (additive), or the cells are reused at a rate worth
            # teaching (cellmate above SPEC 7.6's threshold). A mutating form does neither --
            # SPEC 7.3 prices it as misswipe prevention only.
            if b["cls"] == "additive":
                b["earns"] = True
            elif b["cls"] == "cellmate":
                b["earns"] = R.cellmate_p(len(b["word"])) >= CELLMATE_MIN_P
                b["cellmateP"] = R.cellmate_p(len(b["word"]))
            else:
                b["earns"] = False
            b["value"] = b["gain"] if b["earns"] else 0.0
            if b["status"] == "known":
                owned += 1
            elif b["status"] == "learning":
                learning += 1
            elif b["status"] == "unknown":
                unknown += 1
                if b["cls"] == "additive":
                    residual += b["pts"] * b["reach"]
            if b["value"] > 0 and b["status"] != "known":
                if b["track"] == "par":
                    gain_par += b["value"]
                else:
                    gain_alpha += b["value"]
                effort += COST[b["cls"]]
                items.append((b["word"], b["value"], b["track"]))
        n_dead_drill = min(len(dead) + sum(1 for b in brs if b["cls"] == "mutating"), DEAD_GRID_CAP)
        effort += n_dead_drill * COST["dead"]
        if owned >= 2:
            effort *= OWNED_DISCOUNT
        effort = max(effort, 0.5)
        if not any(b["cls"] == "additive" for b in brs):      # SPEC 7.2 rule 5
            continue

        hook_rows.append(dict(
            stem=s, stemLen=len(s), familySize=len(members), branches=len(brs),
            presentShare=share, presentGames=stem_games[s],
            pres4x4=stem_grid[s]["4x4"], pres5x5=stem_grid[s]["5x5"],
            presTier=_tier_presence(brs, sim),
            enumerability=enum, enumerabilityObserved=enum_obs,
            enumerabilityFindable=enum_find, enumerabilitySource=enum_src,
            cueable=H.ENUM_BAND[0] <= enum_find <= H.ENUM_BAND[1],
            coherence=coherence, specFamilyGate=_spec_gate(s, brs, coherence),
            owned=owned, learning=learning, unknown=unknown, studyItems=len(items), items=items,
            residual=residual, gainPar=gain_par, gainAlpha=gain_alpha,
            deadBranches=len(dead), deadExposure=dead_exposure,
            mutatingBranches=sum(1 for b in brs if b["cls"] == "mutating"),
            effort=effort, isWord=s in lex))
        brs.sort(key=lambda b: (-b["value"], -b["reach"]))
        branch_rows.append((s, brs, dead))
    return hook_rows, branch_rows, w, R, {
        "stemsMined": len(fam), "closureDropped": closure_dropped, "universe": n_uni,
        "games": ngames, "reachFit": R.fitReport, "enumCalibration": cal}


def _tier_presence(brs, sim):
    """A lower bound on P(stem path present) per grid and tier: the most common single member.
    The simulator prices words, not stems, and members are far from independent, so the union
    cannot be taken -- the bound is labelled as one everywhere it is shown."""
    out = {}
    words = [b["word"] for b in brs if b["cls"] == "additive"]
    sub = sim.reindex(words).dropna(how="all")
    for c in sim.columns:
        out[c.replace("pAppear_", "")] = float(sub[c].max()) if len(sub) else 0.0
    return out


def _spec_gate(stem, brs, coherence):
    """SPEC 7.2's own surfacing rules, reported rather than applied. See the module docstring
    in hooks.py for why coherence is not used as a gate."""
    add = [b for b in brs if b["cls"] == "additive"]
    n = len(add)
    return {"sizeOk": n >= 3 or (n == 2 and all(len(b["word"]) >= 6 for b in add)),
            "coherenceOk": coherence >= 0.65 and len(stem) >= 4,
            "twoLongOk": sum(1 for b in add if len(b["word"]) >= 5) >= 2,
            "additiveOk": n >= 1}


def dead_points(hook_rows, misswipe_totals, clone_stats):
    """Allocate the measured affix-error cost across hooks.

    Total is measured: the clone's affix-error attempts cost `affixSecondsPerGame` of an 80 s
    clock. Converting to points uses the clone's own productive rate -- one valid word costs
    `validGap` seconds all-in and is worth `pointsPerWord` -- so the total is an upper bound on
    what removing every affix error would be worth. Allocation across hooks is modelled, by
    each stem's dead-affix exposure weighted by how often its path is on the board.
    """
    sec = misswipe_totals["byCauseAllAttempts"].get("affixError", {}).get("secondsAllIn", 0.0) / misswipe_totals["games"]
    pps = clone_stats["pointsPerWord"] / clone_stats["validGap"]
    total = sec * pps
    wgt = np.array([h["deadExposure"] * h["presentShare"] for h in hook_rows])
    share = wgt / wgt.sum() if wgt.sum() > 0 else wgt
    for h, x in zip(hook_rows, share):
        h["deadPoints"] = float(total * x)
    return {"affixSecondsPerGame": sec, "pointsPerSecond": pps, "deadPointsPerGameTotal": total,
            "note": "upper bound; no measurement exists of the share drilling removes"}


def clone_rates(db=None):
    import sqlite3
    con = sqlite3.connect(db or Q.CLONE_DB)
    a = pd.read_sql("select result, points, gap_since_previous_submit g from attempt", con)
    con.close()
    v = a[a.result == "valid"]
    return {"pointsPerWord": float(v.points.mean()), "validGap": float(v.g.mean())}


def collapse_labels(hook_rows):
    """One label per study set. Stems nest and overlap, so many of them end up proposing the
    same words; SPEC 7.5 condition 3 only collapses identical *member* sets. Where two hooks
    would teach the same words, keep the one that reads best as a cue: a real word first, then
    the longer stem (more shared path), then the more coherent."""
    by = defaultdict(list)
    for h in hook_rows:
        if h["studyItems"]:
            by[frozenset(w for w, _, _ in h["items"])].append(h)
    drop = set()
    for group in by.values():
        if len(group) > 1:
            best = max(group, key=lambda h: (h["isWord"], h["stemLen"], h["coherence"], -ord(h["stem"][0])))
            for h in group:
                if h is not best:
                    drop.add(h["stem"])
                    h["collapsedInto"] = best["stem"]
    return [h for h in hook_rows if h["stem"] not in drop], len(drop)


def _value(h, weights, claimed=None):
    par = alpha = 0.0
    for w, v, tr in h["items"]:
        if claimed is not None and w in claimed:
            continue
        if tr == "par":
            par += v
        else:
            alpha += v
    return (weights["par"] * par + weights["alpha"] * alpha
            + weights["misswipe"] * h.get("deadPoints", 0.0))


def order(hook_rows, weights=WEIGHTS, dedup=True):
    """Greedy ordering by marginal points per unit of effort.

    The list is a queue, not a catalogue. Ranking every hook on its own value puts the same
    forty words in the top thirty slots under thirty different stems, because the stems overlap.
    Each pick therefore scores on the words no higher-ranked hook already teaches. The
    denominator stays the hook's full effort, which keeps the marginal score monotone and the
    lazy greedy exact.
    """
    for h in hook_rows:
        h["valueStandalone"] = _value(h, weights)
        h["scoreStandalone"] = h["valueStandalone"] / h["effort"]
    if not dedup:
        hook_rows.sort(key=lambda h: -h["scoreStandalone"])
        for i, h in enumerate(hook_rows, 1):
            h["rank"], h["score"], h["value"] = i, h["scoreStandalone"], h["valueStandalone"]
        return _tracks(hook_rows, weights)

    heap = [(-h["scoreStandalone"], i, 0) for i, h in enumerate(hook_rows)]
    heapq.heapify(heap)
    claimed, out, version = set(), [], 0
    while heap:
        neg, i, ver = heapq.heappop(heap)
        h = hook_rows[i]
        if ver != version:
            v = _value(h, weights, claimed) / h["effort"]
            if heap and v < -heap[0][0]:
                heapq.heappush(heap, (-v, i, version))
                continue
            neg = -v
        h["score"] = -neg
        h["value"] = -neg * h["effort"]
        h["newWords"] = sum(1 for w, _, _ in h["items"] if w not in claimed)
        out.append(h)
        before = len(claimed)
        claimed.update(w for w, _, _ in h["items"])
        if len(claimed) != before:
            version += 1
    for i, h in enumerate(out, 1):
        h["rank"] = i
    return _tracks(out, weights)


def _tracks(hook_rows, weights):
    for h in hook_rows:
        h["track"] = max((("par", h["gainPar"] * weights["par"]),
                          ("alpha", h["gainAlpha"] * weights["alpha"]),
                          ("misswipe", h.get("deadPoints", 0.0) * weights["misswipe"])),
                         key=lambda t: t[1])[0]
    return hook_rows

"""Build the queue and write everything out: the two TSVs, the misswipe table, the browser's
data file and the summary statistics the one-page report is generated from."""
import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

import hooks as H
import misswipe as M
import qcommon as Q
import rank as RK

TOP_HOOKS_IN_BROWSER = 1200
BRANCHES_IN_BROWSER = 60


def why(h):
    """The plain-language line. Anyone should be able to read why an item is where it is."""
    bits = []
    bits.append(f"{h['stem']}- is on {h['presentShare']:.0%} of your boards")
    n = h["branches"]
    if h["owned"] >= 2:
        bits.append(f"you already own {h['owned']} of the {n} words on it "
                    f"({h['familySize']} of them extend the stem's own path), so the rest cost little")
    elif h["owned"] == 1:
        bits.append(f"you own 1 of the {n} words on it")
    else:
        bits.append(f"you own none of the {n} words on it yet")
    top = sorted(h["items"], key=lambda t: -t[1])[:3]
    if top:
        bits.append("the queue wants " + ", ".join(w for w, _, _ in top)
                    + f" ({sum(v for _, v, _ in h['items']):.1f} points a game between "
                      f"{h['studyItems']} word" + ("s" if h["studyItems"] != 1 else "") + ")")
    e = h["enumerabilityFindable"]
    if h["cueable"]:
        bits.append(f"enumerability {e:.1f} is inside the 2-6 band, so it also works as "
                    f"something to scan for on a board")
    elif e > H.ENUM_BAND[1]:
        bits.append(f"enumerability {e:.1f} is above the band: study it, but do not hunt "
                    f"for it, there is too much under the stem to check")
    else:
        bits.append(f"enumerability {e:.1f} is below the band, so it is a study item and "
                    f"not a board cue")
    if h.get("deadPoints", 0) > 0.5:
        bits.append(f"{h['deadBranches']} dead affixes worth {h['deadPoints']:.1f} points a "
                    f"game in avoided misswipes at the current weight")
    return "; ".join(bits) + "."


def build():
    words = pd.read_parquet(os.path.join(Q.BUILD, "word_rates.parquet"))
    meta = json.load(open(os.path.join(Q.BUILD, "word_rates_meta.json")))
    hook_rows, branches, w, R, stats = RK.assemble(words, meta)
    mt, mtab = _misswipes()
    clone = RK.clone_rates()
    dead_meta = RK.dead_points(hook_rows, mt, clone)
    hook_rows, collapsed = RK.collapse_labels(hook_rows)
    hook_rows = RK.order(hook_rows)
    bd = {s: (b, d) for s, b, d in branches}

    # where each word is best taught: the highest-ranked hook that teaches it
    home, home_cls = {}, {}
    for h in hook_rows:
        for wd, _, _ in h["items"]:
            home.setdefault(wd, h["stem"])
    # a word the queue does not teach -- already known, or below the gain floor -- still gets
    # the best hook it sits on, so nothing in the browser is orphaned. An additive hook is
    # preferred over one that only holds the word as an anagram: TORE- explains STORE, whereas
    # ERAS- merely happens to share its cells.
    for pref in ("additive", None):
        for h in hook_rows:
            for b in bd[h["stem"]][0]:
                if pref is None or b["cls"] == pref:
                    home.setdefault(b["word"], h["stem"])
    for wd, st in home.items():
        home_cls[wd] = next((b["cls"] for b in bd[st][0] if b["word"] == wd), "")

    sim = pd.read_parquet(os.path.join(Q.BUILD, "sim_presence.parquet"))
    wq = w[w.expectedGain > 0].copy()
    wq["hook"] = wq.index.map(home).fillna("")
    wq["hookClass"] = wq.index.map(home_cls).fillna("")
    hook_by = {h["stem"]: h for h in hook_rows}
    wq["hookOwned"] = [hook_by[s]["owned"] if s else 0 for s in wq.hook]
    wq["hookRank"] = [hook_by[s]["rank"] if s else 0 for s in wq.hook]
    wq = wq.join(sim, how="left")
    wq = _alpha_risk(wq)
    wq = wq.sort_values("expectedGain", ascending=False)
    wq["rank"] = np.arange(1, len(wq) + 1)

    for h in hook_rows:
        h["why"] = why(h)
    return dict(words=w, queue=wq, hooks=hook_rows, branches=bd, meta=meta, stats=stats,
                misswipeTotals=mt, misswipes=mtab, clone=clone, deadMeta=dead_meta,
                collapsed=collapsed, reachFit=R.fitReport, R=R)


def _misswipes():
    p = os.path.join(Q.BUILD, "misswipes_repeated.tsv")
    if not os.path.exists(p):
        t, totals = M.run(H.mined_affixes())
        t.to_csv(p, sep="\t", index=False, float_format="%.3f")
        Q.dump_json(totals, os.path.join(Q.BUILD, "misswipe_totals.json"))
    return json.load(open(os.path.join(Q.BUILD, "misswipe_totals.json"))), pd.read_csv(p, sep="\t")


def _alpha_risk(wq):
    """Separate "nobody knows it" from "nobody can see it".

    A word almost nobody takes is an opportunity if it is simply unknown and a trap if it is
    structurally hard to see. The signals are all measured on the player's own boards:

      freeShare   share of presences where the word was already sitting on a path he had
                  swiped -- the direct measure of SPEC 4.1's isolation, and the one that
                  matters, since he takes a 5+ word 74% of the time in that situation
      pathCount   distinct paths the word has on boards carrying it. One path is one place
                  to look; six is six chances to notice it
      hookOwned   whether it hangs off a stem he already owns two or more branches of

    Vowel-initial is deliberately not part of the score. The field takes vowel-initial words
    at 0.23 to 0.37 times the consonant-initial rate at every length, and that is a habit, not
    a property of the board: those words are findable and simply are not found. They are
    reported as the clearest opportunity in the alpha track, not discounted as hard.
    """
    r_free = wq.freeShare.rank(pct=True)
    r_path = wq.pathCount.rank(pct=True)
    score = (0.5 * r_free.fillna(0) + 0.35 * r_path.fillna(0)
             + 0.15 * (wq.hookOwned >= 2).astype(float))
    wq["findabilityScore"] = score
    cut = score.quantile(0.10)
    wq["findability"] = np.where(score <= cut, "hard to see", "findable")
    wq["findabilityCut"] = cut
    return wq


def write(B):
    os.makedirs(Q.REPORTS, exist_ok=True)
    hooks_cols = ["rank", "stem", "stemLen", "isWord", "track", "score", "value", "gainPar",
                  "gainAlpha", "deadPoints", "effort", "studyItems", "newWords", "owned",
                  "learning", "unknown", "familySize", "branches", "presentShare",
                  "presentGames", "enumerability", "enumerabilityObserved", "enumerabilityFindable",
                  "enumerabilitySource", "cueable",
                  "coherence", "residual", "deadBranches", "deadExposure", "scoreStandalone",
                  "why"]
    hd = pd.DataFrame(B["hooks"])
    hd["learn"] = [" ".join(w for w, _, _ in sorted(h["items"], key=lambda t: -t[1]))
                   for h in B["hooks"]]
    hd[hooks_cols[:-1] + ["learn", "why"]].to_csv(
        os.path.join(Q.REPORTS, "queue_hooks.tsv"), sep="\t", index=False, float_format="%.5g")

    q = B["queue"]
    word_cols = ["rank", "track", "len", "pts", "hook", "hookClass", "hookRank", "hookOwned",
                 "myRate", "fieldRate", "topQRate", "nTopQ", "achievable", "rateGap",
                 "presPerGame", "nCur", "expectedGain", "expectedGainShrunk", "belief",
                 "status", "findability", "findabilityScore", "freeShare", "pathCount", "vowelInitial",
                 "pAppear_4x4_casual", "pAppear_4x4_goodCasual", "pAppear_4x4_spam",
                 "pAppear_5x5_casual", "pAppear_5x5_goodCasual", "pAppear_5x5_spam"]
    out = q.rename(columns={"my": "myRate", "fieldRateAll": "fieldRate", "topQ": "topQRate",
                            "nTopQAll": "nTopQ", "presPerGameCur": "presPerGame"})
    out = out.reset_index().rename(columns={"index": "word"})
    out[["word"] + word_cols].to_csv(os.path.join(Q.REPORTS, "queue_words.tsv"), sep="\t",
                                     index=False, float_format="%.5g")

    # the deliverable is the repeated strings; the full log of all 382 invalid attempts stays
    # in the browser, where it can be filtered without losing the aggregate
    mw = B["misswipes"]
    mw[mw.times >= 2].to_csv(os.path.join(Q.REPORTS, "misswipes.tsv"), sep="\t", index=False,
                             float_format="%.3f")
    return hd, out


# --------------------------------------------------------------------------------------------
# Summary statistics: everything the one-page report and the browser header quote.
# --------------------------------------------------------------------------------------------
def summary(B):
    w, q, hk = B["words"], B["queue"], B["hooks"]
    meta, mt = B["meta"], B["misswipeTotals"]
    s = {}

    # --- the repricing, like for like against the shipped alpha list -------------------------
    old = pd.read_csv(os.path.join(Q.FIGS, "sa_alpha_all_candidates.tsv"), sep="\t").set_index("word")
    old = old[~old.dead]
    j = old.join(w[["my", "topQ", "topQTrusted", "expectedGain", "presPerGameCur", "pts",
                    "nTopQAll", "rateGap"]], rsuffix="_new")
    s["repricing"] = {
        "candidates": int(len(old)),
        "oldTop200Gain": float(old.head(200).gainPerGameCur.sum()),
        "oldTop300Gain": float(old.head(300).gainPerGameCur.sum()),
        "oldAllGain": float(old.gainPerGameCur.sum()),
        "newSameSetGain": float(j.expectedGain.fillna(0).sum()),
        "newTop200OfOldSet": float(j.expectedGain.fillna(0).sort_values(ascending=False).head(200).sum()),
        "survivors": int((j.expectedGain.fillna(0) > 0).sum()),
        "droppedBeatTopQ": int(((j.my >= j.topQ) & j.topQTrusted.fillna(False)).sum()),
        "droppedTopQUntrusted": int((~j.topQTrusted.fillna(False)).sum()),
        "oldTop200MyBeatsField": float((old.head(200).myRateCur > old.head(200).fieldRate).mean()),
        "oldTop200MyBeatsTopQ": float((old.head(200).myRateCur >= old.head(200).topQRate).mean()),
        "uniformQ": float(old.qCur.median()),
    }

    # --- the sanity checks the prompt asks for ------------------------------------------------
    ranked = w[w.expectedGain > 0]
    sens = {}
    for k in (10, 20, 30, 50, 100):
        t = np.where(w.nTopQAll >= k, w.topQRateAll, np.nan)
        a = np.fmax(t, w.my)
        g = np.where((w.nCur >= RK.MIN_PRES_WORD) & (w.len >= RK.MIN_LEN) & w.inLexicon
                     & ~w.neverAccepted & (w.nTopQAll >= k),
                     w.presPerGameCur * w.pts * np.maximum(a - w.my, 0), 0.0)
        sens[str(k)] = {"words": int((g > 0).sum()), "totalGain": float(g.sum()),
                   "top200Gain": float(np.sort(g)[::-1][:200].sum())}
    extra_words = float((q.head(200).presPerGameCur * q.head(200).rateGap).sum())
    lens = q.head(200).len.values
    extra_secs = float((q.head(200).presPerGameCur * q.head(200).rateGap
                        * (Q.BASELINE_GAP + Q.SWIPE_A + Q.SWIPE_B * lens)).sum())
    s["checks"] = {
        "wordsRankedWhereMyRateExceedsTopQ": int(((ranked.my > ranked.topQ)).sum()),
        "minTopQPresences": RK.MIN_TOPQ,
        "topQSensitivity": sens,
        "rawVsShrunkTop200Overlap": int(len(set(q.head(200).index)
                                            & set(w.sort_values("expectedGainShrunk", ascending=False).head(200).index))),
        "top200Gain": float(q.head(200).expectedGain.sum()),
        "top200GainShrunk": float(q.head(200).expectedGainShrunk.sum()),
        "top200ExtraWordsPerGame": extra_words,
        "top200ExtraSecondsPerGame": extra_secs,
        "clockSeconds": Q.GAME_SECONDS,
        "secondsOnInvalidPerGame": mt["secondsAllInPerGame"],
        "meanWordsPerGame": meta["meanWordsCur"],
    }

    # --- tracks, rates, coverage --------------------------------------------------------------
    s["tracks"] = {t: {"words": int((q.track == t).sum()),
                       "gain": float(q.expectedGain[q.track == t].sum()),
                       "top200Words": int((q.head(200).track == t).sum()),
                       "top200Gain": float(q.head(200).expectedGain[q.head(200).track == t].sum())}
                   for t in ("par", "alpha")}
    s["tracks"]["misswipe"] = {
        "repeatedStrings": int(len(B["misswipes"])),
        "studyItems": int(B["misswipes"].studyItem.sum()),
        "secondsPerGameAllInvalid": mt["secondsAllInPerGame"],
        "secondsPerGameLearnable": float(
            sum(v["secondsAllIn"] for k, v in mt["byCauseAllAttempts"].items()
                if k in ("affixError", "trueNonWord")) / mt["games"]),
        "byCause": mt["byCauseAllAttempts"],
        "deadPointsCeilingPerGame": B["deadMeta"]["deadPointsPerGameTotal"],
        "weightUsed": RK.WEIGHTS["misswipe"],
    }
    cuts = [0, .01, .05, .1, .2, .35, .5, .75, 1.01]
    h = np.histogram(q.head(200).my.fillna(0), bins=cuts)[0]
    s["myRateDistributionTop200"] = {f"{a:.0%}-{b:.0%}": int(n) for a, b, n in zip(cuts, cuts[1:], h)}
    h2 = np.histogram(q.my.fillna(0), bins=cuts)[0]
    s["myRateDistributionAll"] = {f"{a:.0%}-{b:.0%}": int(n) for a, b, n in zip(cuts, cuts[1:], h2)}
    s["statusTop200"] = q.head(200).status.value_counts().to_dict()
    s["findabilityAlpha"] = q[q.track == "alpha"].findability.value_counts().to_dict()
    s["findabilityTop200"] = q.head(200).findability.value_counts().to_dict()
    hardest = q[(q.track == "alpha") & (q.findability == "hard to see")].head(12)
    s["alphaHardToSee"] = [{"word": i, "rank": int(r["rank"]), "expectedGain": float(r.expectedGain),
                            "freeShare": float(r.freeShare) if r.freeShare == r.freeShare else None,
                            "pathCount": float(r.pathCount) if r.pathCount == r.pathCount else None,
                            "myRate": float(r.my), "topQRate": float(r.topQ)}
                           for i, r in hardest.iterrows()]
    va = q[q.vowelInitial]
    s["vowelInitialQueue"] = [{"word": i, "rank": int(r["rank"]), "expectedGain": float(r.expectedGain),
                               "myRate": float(r.my), "fieldRate": float(r.fieldRateAll),
                               "topQRate": float(r.topQ)} for i, r in va.head(15).iterrows()]
    s["vowelInitial"] = {
        "queueShare": float(q.vowelInitial.mean()),
        "top200Share": float(q.head(200).vowelInitial.mean()),
        "fieldRatioByLength": pd.read_csv(os.path.join(Q.FIGS, "sd_dictionary.tsv"), sep="\t")
            .query("block=='suppression'").set_index("len").ratio.to_dict(),
    }

    # --- hooks ---------------------------------------------------------------------------------
    hd = pd.DataFrame(hk)
    s["hooks"] = {
        "mined": B["stats"]["stemsMined"], "closureDropped": B["stats"]["closureDropped"],
        "labelCollapsed": B["collapsed"], "inQueue": int(len(hd)),
        "withStudyItems": int((hd.studyItems > 0).sum()),
        "top100Value": float(hd.head(100).value.sum()),
        "top100Score": float(hd.head(100).score.sum()),
        "top100ValueMisswipe": float(hd.head(100).deadPoints.sum() * RK.WEIGHTS["misswipe"]),
        **_distinct_split(hk[:100]),
        "top100DistinctWords": int(len({x for h in hk[:100] for x, _, _ in h["items"]})),
        "top100StemLen": hd.head(100).stemLen.value_counts().sort_index().to_dict(),
        "top100IsWord": float(hd.head(100).isWord.mean()),
        "top100Cueable": float(hd.head(100).cueable.mean()),
        "top100OwnedGE2": float((hd.head(100).owned >= 2).mean()),
        "top100Track": hd.head(100).track.value_counts().to_dict(),
        "top100MedianOwned": float(hd.head(100).owned.median()),
        "top100MedianStudyItems": float(hd.head(100).studyItems.median()),
        "universe": B["stats"]["universe"],
        "enumCalibration": B["stats"]["enumCalibration"],
    }
    for wt in ({"par": 1, "alpha": 1, "misswipe": 0.0}, {"par": 1, "alpha": 1, "misswipe": 1.0}):
        alt = RK.order([dict(x) for x in hk], wt)
        s["hooks"][f"top100OverlapAtMisswipe{wt['misswipe']}"] = int(
            len({h["stem"] for h in alt[:100]} & set(hd.head(100).stem)))
    s["weights"] = dict(RK.WEIGHTS)
    s["reachFit"] = {k: {"r2LogP": v["r2LogP"], "medianAbsRatio": v["medianAbsRatio"]}
                     for k, v in B["reachFit"].items()}
    s["reachSourceMix"] = _reach_mix(B)
    s["leastConfident"] = least_confident(B)
    s["clone"] = B["clone"]
    s["meta"] = meta
    return s


def _distinct_split(hks):
    """Value of the top hooks counted once per word. Hooks overlap, so summing each hook's own
    gainPar and gainAlpha counts shared words more than once."""
    seen, par, alpha = set(), 0.0, 0.0
    for h in hks:
        for w, v, t in h["items"]:
            if w in seen:
                continue
            seen.add(w)
            if t == "par":
                par += v
            else:
                alpha += v
    return {"top100ValueParDistinct": par, "top100ValueAlphaDistinct": alpha,
            "top100ValueWordsDistinct": par + alpha}


def _reach_mix(B):
    c = defaultdict(int)
    for h in B["hooks"][:200]:
        for b in B["branches"][h["stem"]][0]:
            c[b["reachSource"]] += 1
    return dict(c)


def least_confident(B, n=10):
    """The ten items in the top 200 most likely to be wrong, chosen to span the failure modes.

    Four things threaten a row: a thin top-quartile denominator, a reachability that came from
    the fitted model rather than a measured one, a large move between the raw and the shrunk
    rate, and a findability or belief flag that says a word drill is the wrong instrument.
    Ranking on a single composite returns ten copies of whichever term dominates, so the two
    worst on each term are taken first and the rest fills from the composite.
    """
    q = B["queue"].head(200).copy()
    hook_by = {h["stem"]: h for h in B["hooks"]}
    fitted = []
    for word, r in q.iterrows():
        h = hook_by.get(r.hook)
        b = next((x for x in B["branches"][r.hook][0] if x["word"] == word), None) if h else None
        fitted.append(1.0 if (b and b["reachSource"] == "fitted") else 0.0)
    q["fitted"] = fitted
    q["thin"] = (RK.MIN_TOPQ / q.nTopQAll.clip(lower=1)).clip(upper=1)
    q["move"] = ((q.expectedGain - q.expectedGainShrunk).abs()
                 / q.expectedGain.clip(lower=1e-9)).clip(upper=1)
    q["instrument"] = ((q.findability == "hard to see").astype(float)
                       + (q.status == "known").astype(float)).clip(upper=1)
    q["doubt"] = 1.0 * q.thin + 1.0 * q.move + 0.6 * q.instrument + 0.5 * q.fitted
    picked = []
    for term in ("thin", "move", "instrument", "fitted"):
        for word in q.sort_values([term, "doubt"], ascending=False).index:
            if word not in picked:
                picked.append(word)
                break
        for word in q.sort_values([term, "doubt"], ascending=False).index[1:]:
            if word not in picked:
                picked.append(word)
                break
    for word in q.sort_values("doubt", ascending=False).index:
        if len(picked) >= n:
            break
        if word not in picked:
            picked.append(word)
    out = []
    for word in picked[:n]:
        r = q.loc[word]
        reasons = []
        if r.nTopQAll < 60:
            se = 1.96 * np.sqrt(max(r.topQ, 1e-6) * (1 - r.topQ) / max(r.nTopQAll, 1))
            reasons.append(f"the top-quartile rate rests on {int(r.nTopQAll)} presences, so its "
                           f"95% interval is about +/-{se:.0%}")
        if r.move > 0.25:
            reasons.append(f"shrinking that rate toward the per-length mean moves the gain from "
                           f"{r.expectedGain:.1f} to {r.expectedGainShrunk:.1f} points a game")
        if r.findability == "hard to see":
            reasons.append("it is flagged hard to see: rarely on a path you have already swiped, "
                           "and few distinct paths on the boards that carry it")
        if r.status == "known":
            reasons.append("belief already calls it known, so the gap is consistency rather than "
                           "vocabulary and a word drill is probably the wrong instrument")
        if r.fitted:
            reasons.append(f"its reachability off {r.hook}- is fitted rather than measured, "
                           "because the extension is not one of the 60 mined affixes")
        if r.nCur < 60:
            reasons.append(f"only {int(r.nCur)} of your 2,865 boards carried it")
        if not reasons:
            reasons.append("nothing specific; it is simply the weakest row above the cut")
        out.append({"word": word, "rank": int(r["rank"]), "track": r.track,
                    "expectedGain": float(r.expectedGain), "myRate": float(r.my),
                    "topQRate": float(r.topQ), "nTopQ": int(r.nTopQAll),
                    "why": "; ".join(reasons)})
    return out

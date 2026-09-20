"""Dictionary: are the never-accepted words absent from Flux's list, or just unplayed?

CSW21 stays the reference list for potential and capture. The question is whether the words
nobody ever has accepted are rejected by the server or simply never swiped. For each suspect:

  * its field find rate against comparable CSW21 words: same length, presence within +/-30%,
    and at least one find by anyone (so known to be accepted);
  * the probability of zero finds in all its player-presences if it were found at the 10th
    percentile of that comparable group's rate (conservative) and at the group median;
  * the same test against comparable words that share its first-letter class (vowel- or
    consonant-initial), because the whole field finds vowel-initial words far less often;
  * structural properties: first letter, alphabetical position, overlap with the client's 419
    removals, and whether it is a common English word (/usr/share/dict/words, web2).
"""
import os

import numpy as np
import pandas as pd

import viz
from common import FIGS, ROOT, load_wordlist
from viz import INK2, OPP, PLAYER, STRONG, WEAK, bh, plt

SUSPECTS = ["ARENA", "AHEAD", "ADMIT", "ADIEU", "AFAR", "AHOY", "AEGIS"]
VOWELS = set("AEIOU")


def section(R, g, pres):
    r = {}
    p = pres[pres.foundOpp.notna()]
    trials = p.groupby("word").size() * 2
    finds = p.groupby("word").apply(lambda x: x.foundPlayer.sum() + x.foundOpp.astype(bool).sum())
    w = pd.DataFrame({"trials": trials, "finds": finds})
    w["len"] = w.index.str.len()
    w["rate"] = w.finds / w.trials
    w["vi"] = w.index.str[0].isin(list(VOWELS))
    dead = pd.read_csv(os.path.join(FIGS, "s0_never_accepted_words.tsv"), sep="\t").word
    removed = set(x.strip().upper() for x in open(os.path.join(ROOT, "data", "flux_removed_words.txt")) if x.strip())
    web2 = set()
    if os.path.exists("/usr/share/dict/words"):
        web2 = set(x.strip().upper() for x in open("/usr/share/dict/words") if x.strip() and x.strip().islower())
    accepted = w[w.finds > 0]

    rows = []
    for word in sorted(set(dead) | set(SUSPECTS)):
        if word not in w.index:
            continue
        x = w.loc[word]
        comp = accepted[(accepted.len == x.len) & (accepted.trials.between(0.7 * x.trials, 1.3 * x.trials))]
        compv = comp[comp.vi == x.vi]
        row = {"word": word, "len": int(x.len), "trials": int(x.trials), "finds": int(x.finds), "vowelInitial": bool(x.vi),
               "removedByFlux": word in removed, "commonEnglish": word in web2, "comparable": int(len(comp))}
        for tag, c in (("", comp), ("SameInitial", compv)):
            if len(c) >= 10:
                p10, med = np.percentile(c.rate, 10), c.rate.median()
                row[f"compP10{tag}"], row[f"compMedian{tag}"] = p10, med
                row[f"pZeroAtP10{tag}"] = float((1 - p10) ** x.trials)
                row[f"pZeroAtMedian{tag}"] = float((1 - med) ** x.trials)
        rows.append(row)
    d = pd.DataFrame(rows)
    for col in ("pZeroAtMedian", "pZeroAtMedianSameInitial", "pZeroAtP10SameInitial"):
        if col in d:
            d[col.replace("pZero", "q")] = bh(d[col].fillna(1).values)
    d.to_csv(os.path.join(FIGS, "sd_dictionary_suspects.tsv"), sep="\t", index=False, float_format="%.4g")
    dd = d[d.word.isin(set(dead))]  # the named suspects are shown, but only never-accepted words are counted
    r["tested"] = int(len(dd))
    r["impossibleAtMedian"] = int((dd.qAtMedian < 1e-3).sum()) if "qAtMedian" in dd else 0
    r["impossibleAtMedianSameInitial"] = int((dd.qAtMedianSameInitial < 1e-3).sum()) if "qAtMedianSameInitial" in dd else 0
    r["impossibleAtP10SameInitial"] = int((dd.qAtP10SameInitial < 1e-3).sum()) if "qAtP10SameInitial" in dd else 0
    r["named"] = d[d.word.isin(SUSPECTS)].round(6).to_dict("records")
    r["removedOverlap"] = int(dd.removedByFlux.sum())
    r["commonEnglishShare"] = float(dd.commonEnglish.mean())
    big = w[w.trials >= 100]
    r["commonEnglishShareOfComparable"] = float(big[big.finds > 0].index.isin(web2).mean()) if web2 else None
    r["vowelInitialShareDead"] = float(dd.vowelInitial.mean())
    r["vowelInitialShareAll"] = float(big.vi.mean())
    # field-wide vowel-initial suppression, by length
    pr = p.assign(vi=p.word.str[0].isin(list(VOWELS)), k=p.foundPlayer.astype(int) + p.foundOpp.astype(bool).astype(int))
    supp = pr[pr.len.between(3, 8)].groupby(["len", "vi"]).k.mean().unstack() / 2
    r["suppression"] = {int(L): {"consonant": float(v[False]), "vowel": float(v[True]), "ratio": float(v[True] / v[False])} for L, v in supp.iterrows()}
    words = load_wordlist()
    rank = {x: i / len(words) for i, x in enumerate(words)}
    big = big.assign(rank=[rank.get(x, np.nan) for x in big.index], dead=big.finds == 0)
    fl = big.groupby(big.index.str[0]).dead.agg(["mean", "size"])
    r["deadShareByFirstLetter"] = fl[fl["size"] >= 50]["mean"].round(4).sort_values(ascending=False).to_dict()
    # a two-letter-opening view: which openings are dead or suppressed
    big["open2"] = big.index.str[:2]
    o2 = big[big.vi].groupby("open2").agg(n=("rate", "size"), medianRate=("rate", "median"), deadShare=("dead", "mean"))
    r["vowelOpenings"] = o2[o2.n >= 20].sort_values("medianRate").round(4).reset_index().to_dict("records")

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.4))
    Ls = sorted(r["suppression"])
    axes[0].plot(Ls, [r["suppression"][L]["consonant"] for L in Ls], "o-", color=OPP, label="consonant-initial")
    axes[0].plot(Ls, [r["suppression"][L]["vowel"] for L in Ls], "o-", color=STRONG, label="vowel-initial")
    axes[0].set_xlabel("word length")
    axes[0].set_ylabel("field find rate given present")
    axes[0].set_title("Every player finds vowel-initial words less")
    axes[0].legend(fontsize=7.5)
    fl2 = fl[fl["size"] >= 50].sort_values("mean", ascending=False)
    axes[1].bar(range(len(fl2)), fl2["mean"], color=[STRONG if c in VOWELS else OPP for c in fl2.index])
    axes[1].set_xticks(range(len(fl2)))
    axes[1].set_xticklabels(fl2.index, fontsize=7)
    axes[1].set_ylabel("share never accepted")
    axes[1].set_title("Never-accepted share by first letter (100+ trials)")
    xs = np.linspace(0, 1, 21)
    h_all = np.histogram(big["rank"].dropna(), xs)[0]
    h_dead = np.histogram(big[big.dead]["rank"].dropna(), xs)[0]
    axes[2].bar(xs[:-1] + 0.025, h_dead / np.maximum(h_all, 1), width=0.045, color=PLAYER)
    axes[2].set_xlabel("alphabetical position in CSW21 (0 = AA, 1 = ZZZS)")
    axes[2].set_ylabel("share never accepted")
    axes[2].set_title("No contiguous missing block")
    fig.tight_layout()
    viz.save(fig, "sd_dictionary", {"suppression": pd.DataFrame(r["suppression"]).T.reset_index(names="len"),
                                    "byFirstLetter": fl.reset_index(names="letter")},
             "Never-accepted words: vowel-initial suppression field-wide, share by first letter, and by alphabetical position.")
    R["sd"] = r

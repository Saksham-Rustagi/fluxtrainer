"""Old (ruleset v1) against new (ruleset v3) for every table in PHASE1_REPORT.md.

Reads the run directories directly, so every number in the rerun section of the
report can be regenerated. Old runs: runs/m-full, runs/m3-curated, runs/full.
New runs: runs/v3-m-full, runs/v3-m3-curated, runs/v3-full, plus the all-stems
M1 runs (runs/v1-m-full-all, runs/v3-m-full-all, runs/*-gate).

usage: compare_phase1.py > reports/phase1_rerun_tables.md
"""

import csv
import os
import sys

CELLS = [("4x4", "casual"), ("4x4", "goodCasual"), ("4x4", "spam"),
         ("5x5", "casual"), ("5x5", "goodCasual"), ("5x5", "spam")]
NAMES = {"casual": "Casual", "goodCasual": "Good Casual", "spam": "Spam"}


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def cell(grid, tier):
    return f"{grid} {NAMES[tier]}"


def m1_headline(run):
    path = f"runs/{run}/m1_headline.tsv"
    if not os.path.exists(path):
        return None
    return {(r["grid"], r["tier"]): r for r in rows(path)}


def main():
    out = sys.stdout.write

    # --- M1 by affix (4x4 Good Casual, per path), runs/m-full vs v3 ----------
    out("## M1 by affix, 4x4 Good Casual, P(reachable) per stem path\n\n")
    # Like for like: each new run is compared against the v1 run on the same stem sample
    # (m-full is v1 on the alphabetical sample, v1-gate is v1 over all stems).
    for run, base, label in (("v3-m-full", "m-full", "v3 alpha sample vs v1 alpha sample"),
                             ("v3-gate", "v1-gate", "v3 all stems vs v1 all stems")):
        if not os.path.exists(f"runs/{run}/reachability.tsv") or not os.path.exists(f"runs/{base}/reachability.tsv"):
            continue
        old = {r["key"]: r for r in rows(f"runs/{base}/reachability.tsv")
               if r["grid"] == "4x4" and r["tier"] == "goodCasual" and r["breakdown"] == "affix"}
        new = {r["key"]: r for r in rows(f"runs/{run}/reachability.tsv")
               if r["grid"] == "4x4" and r["tier"] == "goodCasual" and r["breakdown"] == "affix"}
        out(f"### {label} ({run})\n\n| affix | old | new | change |\n| --- | --- | --- | --- |\n")
        for key in ["-E", "-S", "S-", "R-", "T-", "-T", "-ES", "-D", "D-", "C-", "-ED", "-ING"]:
            if key in old and key in new:
                o, n = float(old[key]["pPerPath"]), float(new[key]["pPerPath"])
                out(f"| `{key}` | {o:.3f} | {n:.3f} | {100 * (n / o - 1):+.0f}% |\n")
        out("\n")

    # --- M1 headline --------------------------------------------------------
    out("## M1 headline (per cell)\n\n")
    for run in ("v3-m-full", "v1-gate", "v3-gate"):
        h = m1_headline(run)
        if not h:
            continue
        out(f"### {run}\n\n| cell | ext/found stem | free words/board | findable/board | free fraction | gate extra/board |\n"
            "| --- | --- | --- | --- | --- | --- |\n")
        for g, t in CELLS:
            r = h[(g, t)]
            out(f"| {cell(g, t)} | {float(r['extPerFoundStem']):.2f} | {float(r['distinctFreePerBoard']):.1f} | "
                f"{float(r['foundWordsPerBoard']):.1f} | {100 * float(r['freeFraction']):.1f}% | "
                f"{float(r['gateExtraPerBoard']):.2f} |\n")
        out("\n")

    # --- M2 anagram pathability, 4x4 Good Casual -----------------------------
    out("## M2 anagram pathability, 4x4 Good Casual\n\n| length | old | new | change |\n| --- | --- | --- | --- |\n")
    old = {r["len"]: r for r in rows("runs/m-full/cellmate_stats.tsv")
           if r["grid"] == "4x4" and r["tier"] == "goodCasual" and r["relation"] == "anagram"}
    new = {r["len"]: r for r in rows("runs/v3-m-full/cellmate_stats.tsv")
           if r["grid"] == "4x4" and r["tier"] == "goodCasual" and r["relation"] == "anagram"}
    for n in ["3", "4", "5", "6", "7", "8", "9", "10"]:
        if n in old and n in new:
            o, v = float(old[n]["p"]), float(new[n]["p"])
            out(f"| {n} | {o:.3f} | {v:.3f} | {100 * (v / o - 1):+.0f}% (trials {old[n]['trials']} → {new[n]['trials']}) |\n")
    out("\n")

    # --- M3 broad, stem counted (section 4 table) ----------------------------
    out("## M3 broad sample, stem counted as its own member (report section 4)\n\n")
    old = {(r["grid"], r["tier"], r["stemLen"]): r for r in rows("runs/m-full/family_stats.tsv")
           if r["nQuartile"] == "all"}
    new = {(r["grid"], r["tier"], r["stemLen"]): r for r in rows("runs/v3-m-full/family_stats.tsv")
           if r["nQuartile"] == "all" and r["sample"] == "broad"}
    cols = [("4x4", "casual"), ("4x4", "goodCasual"), ("4x4", "spam"), ("5x5", "spam")]
    out("| stem length | " + " | ".join(cell(g, t) for g, t in cols) + " |\n| --- |" + " --- |" * len(cols) + "\n")
    for n in ["2", "3", "4", "5", "6", "7"]:
        parts = []
        for g, t in cols:
            o, v = old.get((g, t, n)), new.get((g, t, n))
            parts.append(f"{float(o['enumerability']):.2f} → {float(v['enumerability']):.2f}" if o and v else "—")
        out(f"| {n} | " + " | ".join(parts) + " |\n")
    out("\n")

    # --- M3 under curation (section 4.1), ex-stem, range across cells --------
    out("## M3 under curation, excluding the stem, range across the six cells (report 4.1)\n\n")
    samples = ["broad", "curated", "curatedTight", "curatedWord"]

    def ranges(path):
        res = {}
        for r in rows(path):
            if r["nQuartile"] != "all":
                continue
            key = (r["sample"], r["stemLen"])
            res.setdefault(key, []).append(float(r["enumerabilityOther"]))
        return res

    old, new = ranges("runs/m3-curated/family_stats.tsv"), ranges("runs/v3-m3-curated/family_stats.tsv")
    out("| stem length | " + " | ".join(samples) + " |\n| --- |" + " --- |" * len(samples) + "\n")
    for n in ["2", "3", "4", "5", "6", "7"]:
        parts = []
        for s in samples:
            o, v = old.get((s, n)), new.get((s, n))
            parts.append(f"{min(o):.2f}–{max(o):.2f} → **{min(v):.2f}–{max(v):.2f}**" if o and v else "—")
        out(f"| {n} | " + " | ".join(parts) + " |\n")
    out("\n")

    # Per-cell detail for the band decision: which cells clear 2 at 4 and 5 letters.
    out("### Per-cell, curatedTight and curatedWord, ex-stem (new)\n\n| cell | len | curatedTight | curatedWord | broad |\n| --- | --- | --- | --- | --- |\n")
    per = {(r["grid"], r["tier"], r["sample"], r["stemLen"]): float(r["enumerabilityOther"])
           for r in rows("runs/v3-m3-curated/family_stats.tsv") if r["nQuartile"] == "all"}
    for g, t in CELLS:
        for n in ["3", "4", "5", "6"]:
            out(f"| {cell(g, t)} | {n} | {per.get((g, t, 'curatedTight', n), float('nan')):.2f} | "
                f"{per.get((g, t, 'curatedWord', n), float('nan')):.2f} | {per.get((g, t, 'broad', n), float('nan')):.2f} |\n")
    out("\n")

    # N-quartile split for 5-letter stems, 4x4 Spam, ex-stem, from the curated runs.
    # (Part B's quoted series, 0.68/0.68/0.71/0.69, is runs/m-full's broad sample
    # with the stem counted -- a different run and column.)
    out("### N-quartile split, 4x4 Spam, 5-letter stems, ex-stem\n\n| sample | old Q1–Q4 | new Q1–Q4 |\n| --- | --- | --- |\n")
    oq = {(r["sample"], r["nQuartile"]): float(r["enumerabilityOther"]) for r in rows("runs/m3-curated/family_stats.tsv")
          if r["grid"] == "4x4" and r["tier"] == "spam" and r["stemLen"] == "5"}
    nq = {(r["sample"], r["nQuartile"]): float(r["enumerabilityOther"]) for r in rows("runs/v3-m3-curated/family_stats.tsv")
          if r["grid"] == "4x4" and r["tier"] == "spam" and r["stemLen"] == "5"}
    for s in samples:
        o = " / ".join(f"{oq.get((s, f'Q{q}'), float('nan')):.2f}" for q in range(1, 5))
        v = " / ".join(f"{nq.get((s, f'Q{q}'), float('nan')):.2f}" for q in range(1, 5))
        out(f"| {s} | {o} | {v} |\n")
    out("\n")

    # --- board_norms ---------------------------------------------------------
    out("## board_norms (report section 5)\n\n| cell | total points (mean [p10–p90]) | words | 5+ words | seeded | mean N |\n| --- | --- | --- | --- | --- | --- |\n")

    def norms(run):
        res = {}
        for r in rows(f"runs/{run}/board_norms.tsv"):
            res[(r["grid"], r["tier"], r["metric"])] = r
        return res

    o, n = norms("full"), norms("v3-full")
    for g, t in CELLS:
        op, np_ = o[(g, t, "points")], n[(g, t, "points")]
        ow, nw = o[(g, t, "words")], n[(g, t, "words")]
        o5, n5 = o[(g, t, "words5plus")], n[(g, t, "words5plus")]
        out(f"| {cell(g, t)} | {float(op['mean']):,.0f} [{float(op['p10']):,.0f}–{float(op['p90']):,.0f}] → "
            f"**{float(np_['mean']):,.0f}** [{float(np_['p10']):,.0f}–{float(np_['p90']):,.0f}] | "
            f"{float(ow['mean']):.0f} → **{float(nw['mean']):.0f}** | {float(o5['mean']):.0f} → **{float(n5['mean']):.0f}** | "
            f"{100 * float(op['seededFrac']):.1f}% → **{100 * float(np_['seededFrac']):.1f}%** | "
            f"{float(op['meanN']):.1f} → **{float(np_['meanN']):.1f}** |\n")
    out("\n")

    out("## Spam N-quartile split, 4x4 (report section 5)\n\n| quartile | old N range | old mean points | old boards | new N range | new mean points | new boards |\n| --- | --- | --- | --- | --- | --- | --- |\n")
    oq = [r for r in rows("runs/full/board_norms_by_n.tsv") if r["grid"] == "4x4" and r["tier"] == "spam" and r["metric"] == "points"]
    nq = [r for r in rows("runs/v3-full/board_norms_by_n.tsv") if r["grid"] == "4x4" and r["tier"] == "spam" and r["metric"] == "points"]
    for a, b in zip(oq, nq):
        out(f"| {a['nQuartile']} | {a['nMin']}–{a['nMax']} | {float(a['mean']):,.0f} | {int(a['boards']):,} | "
            f"{b['nMin']}–{b['nMax']} | {float(b['mean']):,.0f} | {int(b['boards']):,} |\n")
    out("\n")


if __name__ == "__main__":
    main()

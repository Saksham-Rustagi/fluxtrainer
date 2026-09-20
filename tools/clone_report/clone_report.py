#!/usr/bin/env python3
"""Phase 1 gate report from a Flux Clone database export.

    python3 tools/clone_report/clone_report.py fluxclone-YYYYMMDD-HHMMSS.sqlite [--out report.md]

Standard library only, except the potential-matched ranked baseline, which needs pandas
(build-analytics/venv/bin/python has it). Without pandas the baseline section falls back to
the headline numbers (mean 51,900 points, 94.4 words over 9,034 ranked games).

By default only finished, uninterrupted games at ranked mix (no grid/tier override) count.
"""
import argparse
import math
import os
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RANKED_GAMES = os.path.join(ROOT, "data", "ranked", "miningmath", "games.parquet")
BASELINE_SCORE, BASELINE_WORDS, BASELINE_GAMES, BASELINE_OPEN10 = 51_900, 94.4, 9_034, 3.93
GAME_SECONDS = 80.0


def pct(values, q):
    if not values:
        return float("nan")
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def ols(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = st.fmean(xs), st.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    s2 = sum(r * r for r in resid) / (n - 2)
    se_b = math.sqrt(s2 / sxx)
    se_a = math.sqrt(s2 * (1 / n + mx * mx / sxx))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum(r * r for r in resid) / ss_tot if ss_tot else float("nan")
    return a, b, se_a, se_b, r2, n


def mean_ci(values):
    if not values:
        return float("nan"), float("nan")
    m = st.fmean(values)
    half = 1.96 * st.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else float("nan")
    return m, half


def f(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{d}f}"


class Report:
    def __init__(self):
        self.lines = []

    def h(self, text):
        self.lines += ["", f"## {text}", ""]

    def p(self, text=""):
        self.lines.append(text)

    def table(self, header, rows):
        self.lines.append("| " + " | ".join(header) + " |")
        self.lines.append("| " + " | ".join("---" for _ in header) + " |")
        for r in rows:
            self.lines.append("| " + " | ".join(str(c) for c in r) + " |")
        self.lines.append("")


def load(db_path, args):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    where = ["t_end IS NOT NULL", "end_reason = 'timeout'"]
    if not args.include_interrupted:
        where.append("COALESCE(interrupted, 0) = 0")
    if not args.include_overrides:
        where.append("grid_source = 'drawn' AND tier_source = 'drawn'")
    games = [dict(r) for r in con.execute(
        f"SELECT * FROM game WHERE {' AND '.join(where)} ORDER BY t_board_shown")]
    ids = {g["game_id"] for g in games}
    attempts = defaultdict(list)
    for r in con.execute("SELECT * FROM attempt ORDER BY game_id, seq"):
        if r["game_id"] in ids:
            a = dict(r)
            a["cells"] = [int(c) for c in a["cell_sequence"].split(",")] if a["cell_sequence"] else []
            a["times"] = [float(t) for t in a["per_cell_entry_timestamps"].split(",")] if a["per_cell_entry_timestamps"] else []
            attempts[a["game_id"]].append(a)
    samples = defaultdict(list)
    for r in con.execute("SELECT game_id, seq, t, x, y, phase, delivered FROM touch_sample ORDER BY game_id, seq, i"):
        if r["game_id"] in ids:
            samples[(r["game_id"], r["seq"])].append(dict(r))
    return games, attempts, samples


def baseline_model():
    """Per-grid OLS of ranked score and words on board potential, if pandas is present."""
    try:
        import pandas as pd
    except ImportError:
        return None
    if not os.path.exists(RANKED_GAMES):
        return None
    g = pd.read_parquet(RANKED_GAMES, columns=["side", "yourScore", "wordsFoundCount", "potential", "open10"])
    g = g.dropna(subset=["potential"])
    model = {}
    for side, sub in g.groupby("side"):
        x = sub["potential"].astype(float).tolist()
        model[int(side)] = {
            "score": ols(x, sub["yourScore"].astype(float).tolist()),
            "words": ols(x, sub["wordsFoundCount"].astype(float).tolist()),
            "n": len(sub),
            "mean_potential": float(sub["potential"].mean()),
        }
    model["open10"] = float(g["open10"].mean())
    model["n"] = len(g)
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--out")
    ap.add_argument("--include-overrides", action="store_true")
    ap.add_argument("--include-interrupted", action="store_true")
    args = ap.parse_args()

    games, attempts, samples = load(args.db, args)
    R = Report()
    R.p("# Flux Clone: Phase 1 gate report")
    R.p()
    R.p(f"Source: `{os.path.basename(args.db)}`. Games counted: **{len(games)}** "
        f"(finished, {'incl.' if args.include_interrupted else 'excl.'} interrupted, "
        f"{'incl.' if args.include_overrides else 'excl.'} grid/tier overrides).")
    if not games:
        R.p("\nNo games to report.")
        return emit(R, args)
    configs = Counter(g["recognizer_config"] for g in games)
    devices = Counter(f'{g["device"]} @ {g["screen_max_fps"]} Hz' for g in games)
    R.p(f"Devices: {dict(devices)}. Recognizer configs: {len(configs)} "
        f"({'all Flux default' if len(configs) == 1 else 'MIXED, see below'}).")
    if len(configs) > 1:
        for c, n in configs.items():
            R.p(f"- {n} games: `{c}`")

    by_grid = Counter(g["grid"] for g in games)
    by_tier = Counter(g["tier"] for g in games)
    R.p(f"Grid mix: {dict(by_grid)}. Tier mix: {dict(by_tier)}.")

    # ---- Gate: score and words against potential ----
    R.h("Gate: score and words against board potential")
    rows = []
    for side in sorted(by_grid):
        gs = [g for g in games if g["grid"] == side]
        sm, sh = mean_ci([g["score"] for g in gs])
        wm, wh = mean_ci([g["word_count"] for g in gs])
        pm = st.fmean(g["potential_points"] for g in gs)
        rows.append([f"{side}x{side}", len(gs), f(pm, 0), f"{f(sm, 0)} ± {f(sh, 0)}", f"{f(wm, 1)} ± {f(wh, 1)}"])
    sm, sh = mean_ci([g["score"] for g in games])
    wm, wh = mean_ci([g["word_count"] for g in games])
    rows.append(["all", len(games), f(st.fmean(g["potential_points"] for g in games), 0),
                 f"{f(sm, 0)} ± {f(sh, 0)}", f"{f(wm, 1)} ± {f(wh, 1)}"])
    R.table(["grid", "games", "mean potential", "mean score (95% CI)", "mean words (95% CI)"], rows)
    R.p(f"Ranked baseline, headline: mean score {BASELINE_SCORE:,}, {BASELINE_WORDS} words per game "
        f"over {BASELINE_GAMES:,} games.")

    model = baseline_model()
    if model:
        resid_s, resid_w = [], []
        for g in games:
            m = model.get(g["grid"])
            if not m or not m["score"]:
                continue
            a, b = m["score"][0], m["score"][1]
            resid_s.append(g["score"] - (a + b * g["potential_points"]))
            a, b = m["words"][0], m["words"][1]
            resid_w.append(g["word_count"] - (a + b * g["potential_points"]))
        rs, rsh = mean_ci(resid_s)
        rw, rwh = mean_ci(resid_w)
        R.p()
        R.p(f"Potential-matched: a per-grid OLS of your ranked score and words on board potential "
            f"({model['n']:,} ranked games) predicts each clone game from its own potential. "
            f"Mean clone minus prediction: **score {f(rs, 0)} ± {f(rsh, 0)}**, "
            f"**words {f(rw, 1)} ± {f(rwh, 1)}** (95% CI).")
        R.p("A clearly negative residual means the clone yields fewer words or points than Flux "
            "at the same potential: the recognizer is the first suspect. Ranked potential comes "
            "from the export's solutions, which may credit a handful of words the capped Flux "
            "dictionary does not (spec 2.1), so a small positive offset in the clone is expected.")
        for side in (4, 5):
            m = model.get(side)
            if m and m["score"]:
                R.p(f"- {side}x{side} baseline: score = {f(m['score'][0], 0)} + {m['score'][1]:.4f}·potential; "
                    f"words = {f(m['words'][0], 1)} + {m['words'][1]:.6f}·potential (n={m['n']:,}).")
    else:
        R.p("(pandas or the ranked parquet not available: no potential-matched comparison.)")

    all_attempts = [a for g in games for a in attempts[g["game_id"]]]
    nonempty = [a for a in all_attempts if a["cells"]]

    # ---- 1. swipe_a / swipe_b ----
    R.h("1. swipe_a and swipe_b")
    R.p("Entry duration = lift time minus the time the first cell was entered, regressed on path length.")
    rows = []
    for label, pool in [("valid words", [a for a in nonempty if a["result"] == "valid"]),
                        ("all attempts of 3+ cells", [a for a in nonempty if len(a["cells"]) >= 3])]:
        xs = [len(a["cells"]) for a in pool]
        ys = [a["t_submit"] - a["t_first_cell"] for a in pool]
        fit = ols(xs, ys)
        if fit:
            a, b, sa, sb, r2, n = fit
            rows.append([label, n, f"{a:.3f} ± {1.96 * sa:.3f}", f"{b:.3f} ± {1.96 * sb:.3f}", f(r2, 3)])
    R.table(["pool", "n", "swipe_a (s)", "swipe_b (s/letter)", "R²"], rows)
    R.p("SPEC §3.2 placeholder: 0.30 + 0.08n.")
    rows = []
    valid = [a for a in nonempty if a["result"] == "valid"]
    for n in sorted({len(a["cells"]) for a in valid}):
        d = [a["t_submit"] - a["t_first_cell"] for a in valid if len(a["cells"]) == n]
        if len(d) >= 3:
            rows.append([n, len(d), f(st.median(d), 3), f(pct(d, 0.25), 3), f(pct(d, 0.75), 3)])
    R.table(["length", "n", "median (s)", "p25", "p75"], rows)
    inter = [t2 - t1 for a in valid for t1, t2 in zip(a["times"], a["times"][1:])]
    R.p(f"Median time between consecutive cell entries, valid words: {f(st.median(inter) if inter else float('nan'), 3)} s.")

    # ---- 2. Misswipes ----
    R.h("2. Misswipes (invalid attempts)")
    per_game = []
    for g in games:
        inv = [a for a in attempts[g["game_id"]] if a["result"] == "invalid" and a["reason"] == "not_word"]
        allin = sum(a["gap_since_previous_submit"] or 0 for a in inv)
        swipe = sum(a["t_submit"] - a["t_touch_down"] for a in inv)
        per_game.append((len(inv), allin, swipe))
    n_m, n_h = mean_ci([x[0] for x in per_game])
    a_m, a_h = mean_ci([x[1] for x in per_game])
    s_m, s_h = mean_ci([x[2] for x in per_game])
    R.p(f"- Invalid attempts per game (3+ letters, not a word): **{f(n_m, 2)} ± {f(n_h, 2)}**")
    R.p(f"- Seconds lost per game, all-in (gap since previous submit, i.e. decision + swipe): "
        f"**{f(a_m, 1)} ± {f(a_h, 1)} s = {f(100 * a_m / GAME_SECONDS, 1)}% of the clock**")
    R.p(f"- Seconds lost per game, swipe only (touch-down to lift): {f(s_m, 1)} ± {f(s_h, 1)} s")
    R.p("SPEC §3.6 claim to test: 12 to 15 per game, 15 to 20 s (15 to 20% of the clock).")
    short = Counter(a["reason"] for a in all_attempts if a["result"] == "invalid" and a["reason"] != "not_word")
    R.p(f"- Not counted above (per game): too short {f(short['too_short'] / len(games), 2)}, "
        f"empty lifts {f(short['empty'] / len(games), 2)}.")
    inv = [a for a in nonempty if a["result"] == "invalid" and a["reason"] == "not_word"]
    if inv:
        R.p()
        R.p("**By affix pattern** (attempt = real stem + affix):")
        aff = Counter(a["affix"] or "(no affix pattern)" for a in inv)
        R.table(["pattern", "count", "share", "seconds lost (all-in)"],
                [[k, v, f"{100 * v / len(inv):.1f}%",
                  f(sum(a["gap_since_previous_submit"] or 0 for a in inv if (a["affix"] or "(no affix pattern)") == k), 1)]
                 for k, v in aff.most_common(25)])
        lengths = Counter(len(a["letters"]) for a in inv)
        R.p("**By length:** " + ", ".join(f"{k}: {v}" for k, v in sorted(lengths.items())))
        R.p()
        prefix = sum(1 for a in inv if a["is_prefix"])
        shadow_ok = sum(1 for a in inv if a["shadow_valid"])
        R.p(f"- {prefix} of {len(inv)} ({100 * prefix / len(inv):.0f}%) are a prefix of some word "
            f"(lifted early, or a letter dropped at the end).")
        R.p(f"- {shadow_ok} of {len(inv)} would have been a **valid word under segment interpolation** "
            f"(the recognizer, not the player, made these invalid).")
        R.p()
        R.p("**Most repeated invalid strings:**")
        top = Counter(a["letters"] for a in inv).most_common(20)
        R.table(["attempt", "times", "affix", "stem"],
                [[w, n, next((a["affix"] or "" for a in inv if a["letters"] == w), ""),
                  next((a["stem"] or "" for a in inv if a["letters"] == w), "")] for w, n in top])

    # ---- 3. Duplicates ----
    R.h("3. Duplicate re-swipes")
    per_game = []
    for g in games:
        dup = [a for a in attempts[g["game_id"]] if a["result"] == "duplicate"]
        per_game.append((len(dup), sum(a["gap_since_previous_submit"] or 0 for a in dup),
                         sum(a["t_submit"] - a["t_touch_down"] for a in dup)))
    n_m, n_h = mean_ci([x[0] for x in per_game])
    a_m, a_h = mean_ci([x[1] for x in per_game])
    s_m, s_h = mean_ci([x[2] for x in per_game])
    R.p(f"- Duplicates per game: **{f(n_m, 2)} ± {f(n_h, 2)}**")
    R.p(f"- Seconds lost per game, all-in: **{f(a_m, 1)} ± {f(a_h, 1)} s**; swipe only {f(s_m, 1)} s")
    dups = [a for a in nonempty if a["result"] == "duplicate"]
    if dups:
        lengths = Counter(len(a["letters"]) for a in dups)
        R.p("- By length: " + ", ".join(f"{k}: {v}" for k, v in sorted(lengths.items())))

    # ---- 4. Dead time ----
    R.h("4. Dead time: gaps between submissions")
    gaps = [a["gap_since_previous_submit"] for a in nonempty if a["gap_since_previous_submit"] is not None]
    later = [a["gap_since_previous_submit"] for g in games
             for a in [x for x in attempts[g["game_id"]] if x["cells"]][1:]]
    R.table(["", "n", "p10", "p25", "**p40 = baseline_gap**", "p50", "p75", "p90", "p99"],
            [[name, len(v)] + [f(pct(v, q), 3) for q in (0.1, 0.25, 0.4, 0.5, 0.75, 0.9, 0.99)]
             for name, v in [("all gaps", gaps), ("excluding the opening gap", later)]])
    for side in sorted(by_grid):
        v = [a["gap_since_previous_submit"] for g in games if g["grid"] == side
             for a in [x for x in attempts[g["game_id"]] if x["cells"]][1:]]
        R.p(f"- {side}x{side} baseline_gap (p40, excluding opening): {f(pct(v, 0.4), 3)} s")
    for tier in sorted(by_tier):
        v = [a["gap_since_previous_submit"] for g in games if g["tier"] == tier
             for a in [x for x in attempts[g["game_id"]] if x["cells"]][1:]]
        R.p(f"- {tier} baseline_gap: {f(pct(v, 0.4), 3)} s")

    # ---- 5. Opening ----
    R.h("5. Opening latency")
    first_any = [g["t_first_submit"] - g["t_board_shown"] for g in games if g["t_first_submit"]]
    first_valid, first5, first10 = [], defaultdict(list), []
    for g in games:
        v = [a for a in attempts[g["game_id"]] if a["result"] == "valid"]
        if v:
            first_valid.append(v[0]["t_submit"] - g["t_board_shown"])
        for i, a in enumerate(v[:5]):
            first5[i].append(len(a["letters"]))
        first10 += [len(a["letters"]) for a in v[:10]]
    R.p(f"- Board shown to first submission: median {f(st.median(first_any) if first_any else float('nan'), 2)} s, "
        f"mean {f(st.fmean(first_any) if first_any else float('nan'), 2)} s")
    R.p(f"- Board shown to first valid word: median {f(st.median(first_valid) if first_valid else float('nan'), 2)} s")
    R.p("- Mean length of the k-th valid word: "
        + ", ".join(f"#{k + 1}: {f(st.fmean(v), 2)}" for k, v in sorted(first5.items())))
    R.p(f"- **First-10 mean length: {f(st.fmean(first10) if first10 else float('nan'), 2)}** "
        f"(ranked: {BASELINE_OPEN10}). If these differ materially, the clone is not eliciting your real opening.")

    # ---- 6. Sampling ----
    R.h("6. Touch sampling")
    ratio = [a["n_samples"] / a["n_deliveries"] for a in nonempty if a["n_deliveries"]]
    R.p(f"- Samples per touchesMoved delivery (all games): median {f(st.median(ratio) if ratio else float('nan'), 2)}, "
        f"mean {f(st.fmean(ratio) if ratio else float('nan'), 2)}. Above 1 means coalesced samples exist that "
        f"per-delivery hit testing (the ranked baseline's recognizer) never sees.")
    dts, ddts = [], []
    for key, ss in samples.items():
        moved = [s for s in ss if s["phase"] == "moved"]
        dts += [b["t"] - a["t"] for a, b in zip(moved, moved[1:]) if b["t"] > a["t"]]
        dl = [s for s in moved if s["delivered"]]
        ddts += [b["t"] - a["t"] for a, b in zip(dl, dl[1:]) if b["t"] > a["t"]]
    if dts:
        R.p(f"- Raw samples ({len(samples)} swipes with raw data): digitizer interval median "
            f"{1000 * st.median(dts):.2f} ms (**{1 / st.median(dts):.0f} Hz**), delivery interval median "
            f"{1000 * st.median(ddts):.2f} ms ({1 / st.median(ddts):.0f} Hz). p99 digitizer interval "
            f"{1000 * pct(dts, 0.99):.1f} ms.")
    else:
        R.p("- No raw samples in this export.")
    tiles = {g["game_id"]: g["tile_size"] for g in games}
    big = [a for a in nonempty if a["max_step_pt"] and a["max_step_pt"] > 0.86 * tiles[a["game_id"]]]
    R.p(f"- Attempts with a sample step longer than the hit-circle diameter (0.86·tile): {len(big)} of "
        f"{len(nonempty)} ({100 * len(big) / max(1, len(nonempty)):.2f}%).")
    diff = [a for a in nonempty if a["shadow_cells"] is not None]
    R.p(f"- Attempts where a segment-interpolating recognizer on every coalesced sample would have "
        f"selected a different path: **{len(diff)} of {len(nonempty)} ({100 * len(diff) / max(1, len(nonempty)):.2f}%)**.")
    if diff:
        changed = Counter((a["result"], "valid" if a["shadow_valid"] else "not valid") for a in diff)
        R.table(["actual result", "interpolated path", "count"], [[k[0], k[1], v] for k, v in changed.most_common()])
        R.table(["actual", "interpolated"], [[a["letters"], a["shadow_letters"]] for a in diff[:15]])

    return emit(R, args)


def emit(R, args):
    text = "\n".join(R.lines) + "\n"
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

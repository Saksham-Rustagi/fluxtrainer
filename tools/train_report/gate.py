"""Phase 3's gate, and the report around it.

    build-analytics/venv/bin/python tools/train_report/gate.py ~/Downloads/fluxclone-*.sqlite \
        --out reports/phase3_gate.md

**The gate: a hook drilled this week gets found unprompted, on a fresh acquisition board,
next week.** First-attempt find rate with no stem lit, on a board not seen before, at least
seven days after the drill, over the first 10 to 15 hooks drilled.

Two things this deliberately does not do.

It does not grade a drill by what happened during the drill. Finding a branch with the stem
lit is the exercise working, not the training working, and a gate that counted it would
pass by construction.

It does not compare the post-drill rate against zero. The words being drilled were already
present on ranked boards and already taken sometimes -- `myRate` in the hook record is
exactly how often. The gate's number is only meaningful against that baseline, so the
baseline is printed next to it, and a drilled hook whose branches come back at the rate
they went in is a **failure** however high the rate looks.

Only stdlib: this runs against a phone export on any machine, and the point of the gate is
that it is cheap to check.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import statistics
import sys

GATE_DAYS = 7
GATE_HOOKS = 15


def parse_time(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def connect(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    version = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if version is None or int(version[0]) < 2:
        sys.exit(f"{path}: schema {version[0] if version else '?'}; this needs the Phase 3 "
                 "schema (2). Export from a build that has the trainer in it.")
    return db


def hook_record(root):
    """myRate for every branch, from the shipped record. The gate's baseline."""
    path = os.path.join(root, "ios", "FluxClone", "Resources", "training_hooks.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        bundle = json.load(f)
    out = {}
    for hook in bundle["hooks"]:
        fields = hook["branches"]["fields"]
        wi, ri = fields.index("word"), fields.index("myRate")
        for row in hook["branches"]["rows"]:
            if row[ri] is not None:
                out[row[wi]] = row[ri]
    return out


def drills(db):
    """First branch-completion drill per hook, in order."""
    rows = db.execute("""
        SELECT hook, MIN(started_wall) AS first_drill, COUNT(*) AS boards
        FROM exercise
        WHERE kind = 'branch_completion' AND hook IS NOT NULL AND abandoned = 0
        GROUP BY hook ORDER BY first_drill
        """).fetchall()
    return [dict(r) for r in rows]


def first_unprompted_test(db, hook, after, seen_letters):
    """The first sweep of `hook` that qualifies: no stem lit, at least GATE_DAYS after the
    drill, and on a board whose letters have not been served before."""
    rows = db.execute("""
        SELECT exercise_id, started_wall, letters, grid, board_words, degraded
        FROM exercise
        WHERE hook = ? AND kind = 'family_sweep' AND abandoned = 0 AND lit_path IS NULL
        ORDER BY started_wall
        """, (hook,)).fetchall()
    for row in rows:
        started = parse_time(row["started_wall"])
        if started is None or (started - after).days < GATE_DAYS:
            continue
        if row["letters"] in seen_letters:
            continue  # spec 11.4: a repeated grid teaches the grid
        return dict(row)
    return None


def branch_outcomes(db, exercise_id):
    rows = db.execute(
        "SELECT word, found, t_found FROM branch_event WHERE exercise_id = ?",
        (exercise_id,)).fetchall()
    return [dict(r) for r in rows]


def boards_before(db, when):
    rows = db.execute("SELECT letters FROM exercise WHERE started_wall < ? AND letters IS NOT NULL",
                      (when,)).fetchall()
    return {r["letters"] for r in rows}


def run_gate(db, baseline):
    out = []
    for drill in drills(db)[:GATE_HOOKS]:
        drilled_at = parse_time(drill["first_drill"])
        if drilled_at is None:
            continue
        seen = boards_before(db, drill["first_drill"])
        test = first_unprompted_test(db, drill["hook"], drilled_at, seen)
        row = {"hook": drill["hook"], "drilled": drill["first_drill"][:10],
               "drillBoards": drill["boards"]}
        if test is None:
            row["status"] = "not yet due"
            out.append(row)
            continue
        outcomes = branch_outcomes(db, test["exercise_id"])
        if not outcomes:
            row["status"] = "no branches on the test board"
            out.append(row)
            continue
        found = sum(1 for o in outcomes if o["found"])
        base = [baseline[o["word"]] for o in outcomes if o["word"] in baseline]
        row.update({
            "status": "tested",
            "tested": test["started_wall"][:10],
            "days": (parse_time(test["started_wall"]) - drilled_at).days,
            "grid": test["grid"], "boardWords": test["board_words"],
            "targets": len(outcomes), "found": found,
            "rate": found / len(outcomes),
            "baseline": statistics.mean(base) if base else None,
            "degraded": bool(test["degraded"]),
        })
        out.append(row)
    return out


def exposure(db):
    """Secondary, and worth watching from day one: how much time went into the app, and
    what ranked play looked like around it. Too early to attribute; logged anyway."""
    sessions = db.execute("""
        SELECT COUNT(*) n, SUM(boards) boards, SUM(judgements) judgements
        FROM session WHERE ended_wall IS NOT NULL AND abandoned = 0
        """).fetchone()
    grid = db.execute("""
        SELECT COUNT(*) n, AVG(latency) mean_latency,
               AVG(CASE WHEN correct = 1 THEN 1.0 ELSE 0 END) accuracy,
               AVG(CASE WHEN live = 0 AND correct = 1 THEN 1.0
                        WHEN live = 0 THEN 0 END) dead_accuracy
        FROM judgement
        """).fetchone()
    presences = db.execute("SELECT COUNT(*) n, COUNT(DISTINCT word) words FROM presence").fetchone()
    ranked = db.execute("""
        SELECT COUNT(*) n, AVG(score) score, AVG(word_count) words
        FROM game WHERE t_end IS NOT NULL AND COALESCE(purpose, 'ranked') = 'ranked'
        """).fetchone()
    cost = db.execute("""
        SELECT purpose, COUNT(*) n, AVG(degraded) degraded FROM exercise
        WHERE purpose IN ('drill', 'acquisition') GROUP BY purpose
        """).fetchall()
    return {"sessions": dict(sessions), "grid": dict(grid), "presences": dict(presences),
            "ranked": dict(ranked), "boards": [dict(r) for r in cost]}


def render(rows, extra, source):
    L = []
    L.append("# Phase 3 gate\n")
    L.append(f"Source: `{os.path.basename(source)}`, read "
             f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.\n")
    L.append("**The gate: a hook drilled this week gets found unprompted, on a fresh "
             "acquisition board, next week.** First-attempt find rate with no stem lit, on a "
             f"board not seen before, at least {GATE_DAYS} days after the drill, over the "
             f"first {GATE_HOOKS} hooks drilled.\n")

    tested = [r for r in rows if r["status"] == "tested"]
    if not rows:
        L.append("No hooks have been drilled yet. The gate cannot run.\n")
    elif not tested:
        pending = len(rows)
        L.append(f"{pending} hook{'s' if pending != 1 else ''} drilled, none yet re-tested on "
                 f"a fresh board {GATE_DAYS}+ days later. **The gate cannot be called yet.**\n")
    else:
        found = sum(r["found"] for r in tested)
        targets = sum(r["targets"] for r in tested)
        rate = found / targets
        bases = [r["baseline"] for r in tested if r["baseline"] is not None]
        baseline = statistics.mean(bases) if bases else None
        L.append(f"## {rate:.1%} found unprompted ({found} of {targets} branches, "
                 f"{len(tested)} hook{'s' if len(tested) != 1 else ''})\n")
        if baseline is not None:
            L.append(f"Ranked baseline for the same words: **{baseline:.1%}**. "
                     f"The drill is worth {rate - baseline:+.1%} on this evidence.\n")
            if rate <= baseline:
                L.append("> **This does not pass.** The branches came back at the rate they "
                         "went in, so the exercises did not transfer. No amount of scheduling "
                         "in Phase 4 rescues that; the exercises are what have to change.\n")
        if len(tested) < 10:
            L.append(f"> Only {len(tested)} hook{'s' if len(tested) != 1 else ''} "
                     "through the full cycle. The brief asks "
                     "for 10 to 15 before the gate is called; this is a reading, not a "
                     "verdict.\n")

    L.append("| hook | drilled | tested | days | grid | board words | targets | found | rate | "
             "ranked baseline |")
    L.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        if r["status"] != "tested":
            L.append(f"| {r['hook']} | {r['drilled']} | — | | | | | | | *{r['status']}* |")
            continue
        base = f"{r['baseline']:.1%}" if r["baseline"] is not None else "—"
        flag = " ⚠" if r["degraded"] else ""
        L.append(f"| {r['hook']} | {r['drilled']} | {r['tested']}{flag} | {r['days']} | "
                 f"{r['grid']}x{r['grid']} | {r['boardWords']} | {r['targets']} | {r['found']} | "
                 f"{r['rate']:.0%} | {base} |")
    L.append("")
    L.append("⚠ marks a board served short of its constraints (spec 11.1's fallback).\n")

    s, g, p, rk = extra["sessions"], extra["grid"], extra["presences"], extra["ranked"]
    L.append("## Around it\n")
    L.append("Secondary, and too early to attribute. Logged from day one so that when there "
             "is enough of it the question can be asked.\n")
    L.append(f"- Sessions finished: **{s['n'] or 0}**, {s['boards'] or 0} training boards, "
             f"{s['judgements'] or 0} affix judgements.")
    if g["n"]:
        L.append(f"- Affix grid: **{g['accuracy']:.1%}** correct at a **{g['mean_latency']:.2f} s** "
                 f"mean, against the 1.2 s target. Dead branches alone: "
                 f"{(g['dead_accuracy'] or 0):.1%}.")
    L.append(f"- Presences recorded in app: **{p['n']:,}** over {p['words']:,} distinct words. "
             "Every solved word on every full board, not just the drilled hook's branches.")
    if rk["n"]:
        L.append(f"- Ranked games played in the clone since: {rk['n']}, mean score "
                 f"{rk['score']:,.0f} over {rk['words']:.0f} words.")
    for row in extra["boards"]:
        L.append(f"- {row['purpose']} boards: {row['n']}, "
                 f"{(row['degraded'] or 0):.0%} served short of their constraints.")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("database", help="an export from the app (fluxclone-*.sqlite)")
    ap.add_argument("--out", default=None, help="write the report here instead of stdout")
    args = ap.parse_args()

    matches = sorted(glob.glob(os.path.expanduser(args.database)))
    path = matches[-1] if matches else os.path.expanduser(args.database)
    if not os.path.exists(path):
        sys.exit(f"no such database: {path}")

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db = connect(path)
    rows = run_gate(db, hook_record(root))
    text = render(rows, exposure(db), path)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()

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
# Phase 3.5's gate is a human question -- "does review tell me something I did not know and
# would act on" -- over five boards. What a script can do is lay out what review actually
# put on screen so the question can be asked against an export instead of from memory, and
# catch the two failure modes that do not need a human: a review that shows nothing, and a
# ranker stuck on the same handful of stems.
REVIEW_BOARDS = 5


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
    # Schema 3 adds the review log. An older export still answers the Phase 3 gate, and the
    # review section says so rather than failing.
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


def review_composition(db, limit=REVIEW_BOARDS):
    """What review put on screen for the most recent boards, newest first."""
    try:
        games = db.execute("""
            SELECT DISTINCT game_id, wall FROM review_item ORDER BY wall DESC LIMIT ?
            """, (limit,)).fetchall()
    except sqlite3.OperationalError:
        return None   # pre-3.5 export
    out = []
    for g in games:
        items = db.execute("""
            SELECT rank, kind, stem, word, priority, value, covered, missed
            FROM review_item WHERE game_id = ? ORDER BY rank
            """, (g["game_id"],)).fetchall()
        game = db.execute("""
            SELECT score, word_count, grid, tier, COALESCE(purpose, 'ranked') purpose
            FROM game WHERE game_id = ?
            """, (g["game_id"],)).fetchone()
        out.append({"gameId": g["game_id"], "wall": g["wall"],
                    "game": dict(game) if game else {},
                    "items": [dict(i) for i in items]})
    return out


def review_health(db):
    """The two failure modes a script can see without a human."""
    try:
        total = db.execute("SELECT COUNT(DISTINCT game_id) FROM review_item").fetchone()[0]
    except sqlite3.OperationalError:
        return None
    reviewed = db.execute("""
        SELECT COUNT(*) FROM game
        WHERE t_end IS NOT NULL AND interrupted = 0
          AND COALESCE(purpose, 'ranked') IN ('ranked', 'mixed', 'measurement')
        """).fetchone()[0]
    leads = db.execute("""
        SELECT stem, COUNT(*) n FROM review_item WHERE rank = 0
        GROUP BY stem ORDER BY n DESC LIMIT 5
        """).fetchall()
    kinds = db.execute(
        "SELECT kind, COUNT(*) n FROM review_item GROUP BY kind").fetchall()
    priorities = db.execute("""
        SELECT priority, COUNT(*) n FROM review_item
        WHERE kind = 'family' GROUP BY priority ORDER BY priority
        """).fetchall()
    return {"boardsWithItems": total, "boardsReviewable": reviewed,
            "leads": [dict(r) for r in leads], "kinds": [dict(r) for r in kinds],
            "priorities": [dict(r) for r in priorities]}


def waste(db):
    """Misswipes and duplicates per game, the two diagnostics review reports."""
    row = db.execute("""
        SELECT COUNT(DISTINCT game_id) games,
               SUM(CASE WHEN result = 'invalid' AND reason = 'not_word' THEN 1 ELSE 0 END) invalid,
               SUM(CASE WHEN result = 'duplicate' THEN 1 ELSE 0 END) duplicate,
               SUM(CASE WHEN result = 'duplicate'
                        THEN COALESCE(gap_since_previous_submit, 0) ELSE 0 END) dupSeconds
        FROM attempt
        """).fetchone()
    repeated = db.execute("""
        SELECT letters, COUNT(*) n FROM attempt
        WHERE result = 'invalid' AND reason = 'not_word' AND length(letters) >= 3
        GROUP BY letters HAVING n >= 2 ORDER BY n DESC LIMIT 8
        """).fetchall()
    return dict(row), [dict(r) for r in repeated]


def render_review(db):
    health = review_health(db)
    if health is None:
        return ["## Review\n", "This export predates the review log (`review_item`). "
                "Nothing to report.\n"]
    L = ["## Review\n"]
    L.append("**The gate: play five boards. After each, does review tell you something you "
             "did not know and would act on?** That is a judgement, not a query. What "
             "follows is what review actually showed, so the judgement can be made against "
             "the export rather than from memory.\n")
    quiet = health["boardsReviewable"] - health["boardsWithItems"]
    L.append(f"- Boards reviewed: **{health['boardsWithItems']}** of "
             f"{health['boardsReviewable']} playable. "
             + (f"{quiet} showed no item at all." if quiet > 0 else "Every one had something."))
    if health["kinds"]:
        mix = ", ".join(f"{r['n']} {r['kind']}" for r in health["kinds"])
        L.append(f"- Item mix: {mix}.")
    if health["priorities"]:
        # SPEC 7.4's four cases. A review that is all priority 4 is a review about
        # coverage, and coverage is not fixed by learning the words that were missed.
        mix = ", ".join(f"p{r['priority']}: {r['n']}" for r in health["priorities"])
        L.append(f"- Family cases: {mix}.")
    if health["leads"]:
        top = health["leads"][0]
        L.append(f"- Most frequent lead item: **{top['stem']}-**, {top['n']} boards.")
        if top["n"] >= 4 and health["boardsWithItems"] >= 6:
            L.append("> The same stem is leading most boards. Either it really is the "
                     "biggest gap and the drill is not closing it, or the ranker is stuck; "
                     "check whether `myRate` has moved for its branches.")
    L.append("")

    boards = review_composition(db)
    if boards:
        L.append(f"### The last {len(boards)} boards\n")
        for b in boards:
            g = b["game"]
            L.append(f"**{b['wall'][:16].replace('T', ' ')}** · {g.get('score', 0):,} on "
                     f"{g.get('grid')}x{g.get('grid')} {g.get('tier')} "
                     f"({g.get('purpose')}), {g.get('word_count', 0)} words")
            if not b["items"]:
                L.append("- nothing ranked above the floor")
            for i in b["items"]:
                what = f"{i['stem']}-" if i["kind"] == "family" else f"{i['word']} ({i['stem']}-)"
                extra = f", p{i['priority']}, {i['missed']} missed" if i["kind"] == "family" else ""
                L.append(f"- {what} — {i['value']:.1f}/game{extra}")
            L.append("")
    return L


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
    L += extra["review"]
    w, repeated = extra["waste"]
    if w["games"]:
        L.append("## The two diagnostics\n")
        L.append(f"- Invalid attempts: **{(w['invalid'] or 0) / w['games']:.1f}** a game.")
        L.append(f"- Re-swipes of words already found: "
                 f"**{(w['duplicate'] or 0) / w['games']:.1f}** a game, "
                 f"{(w['dupSeconds'] or 0) / w['games']:.1f} s. Pure waste, and nothing "
                 "outside review reports it.")
        if repeated:
            L.append("- Repeated invalid strings: "
                     + ", ".join(f"{r['letters']} ({r['n']}x)" for r in repeated) + ".")
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
    extra = exposure(db)
    extra["review"] = render_review(db)
    extra["waste"] = waste(db)
    text = render(rows, extra, path)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()

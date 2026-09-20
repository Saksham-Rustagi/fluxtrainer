"""The misswipe track: strings swiped two or more times that are not words.

Read straight from the clone's SQLite export, which is the only source in the project with a
per-attempt log. Eight games, so the rates here are provisional and the structure is the
finding: 47.75 invalid attempts a game against SPEC 3.6's estimate of 12 to 15, costing 27.1 s
of an 80 s clock all-in.

Each repeated invalid string is classified by cause, because the four causes are four different
problems and only two of them are learnable:

  affixError      a real stem plus an affix that does not take (HOLERS, NILER, CUER, LUCER).
                  Vocabulary. Fixed by the dead half of the affix grid -> becomes a study item.
  earlyLift       the attempt is a proper prefix of a word that was still reachable from the
                  last cell entered. Motor. Diagnostic only.
  pathError       a valid word sits within one substitution or transposition of the attempted
                  path, or one interior insertion (TOSR against TORS). Motor. Diagnostic only.
  trueNonWord     nothing valid nearby. The player believed it was a word -> becomes a study
                  item, and the most valuable kind in this track.

Precedence is affixError > earlyLift > pathError > trueNonWord. Early lift has to be tested
before the generic edit-one test, because appending the missing last letter is itself an
insertion and a generic test would swallow every early lift into pathError.

SPEC 16.6 and the Phase 2 prompt both warn that some invalid attempts may be how the player
searches -- tracing paths to see what connects. Nothing here is scored, ranked or fed back as
pressure to swipe less; the track reports which strings are not words and stops there.
"""
import os
import sqlite3
from collections import defaultdict

import pandas as pd

import qcommon as Q

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def neighbours(n):
    """8-way adjacency for an n x n grid, cell ids row-major (SPEC 2.1)."""
    adj = defaultdict(list)
    for r in range(n):
        for c in range(n):
            i = r * n + c
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr or dc:
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < n and 0 <= cc < n:
                            adj[i].append(rr * n + cc)
    return adj


class Board:
    def __init__(self, letters, grid):
        self.letters = letters
        self.n = grid
        self.adj = neighbours(grid)
        self.by_letter = defaultdict(list)
        for i, ch in enumerate(letters):
            self.by_letter[ch].append(i)

    def path(self, word, start_cells=None, used=()):
        """Any legal path for `word`; no tile reuse. Returns the cell list or None."""
        used = set(used)
        starts = start_cells if start_cells is not None else self.by_letter.get(word[0], [])
        for s in starts:
            if s in used or self.letters[s] != word[0]:
                continue
            r = self._dfs(word, 1, s, used | {s}, [s])
            if r:
                return r
        return None

    def _dfs(self, word, k, cell, used, acc):
        if k == len(word):
            return acc
        for nx in self.adj[cell]:
            if nx not in used and self.letters[nx] == word[k]:
                r = self._dfs(word, k + 1, nx, used | {nx}, acc + [nx])
                if r:
                    return r
        return None

    def continuable(self, cells, tail):
        """Can `tail` be appended to a path that already used `cells`?"""
        used = set(cells)
        last = cells[-1]
        for nx in self.adj[last]:
            if nx not in used and self.letters[nx] == tail[0]:
                r = self._dfs(tail, 1, nx, used | {nx}, [nx])
                if r:
                    return [nx] + r[1:]
        return None


def edit_one(s, terminal_insert=False):
    """Substitutions, adjacent transpositions and insertions. Terminal appends are the early
    lift case and are excluded unless asked for."""
    out = set()
    for i in range(len(s)):
        for c in ALPHA:
            if c != s[i]:
                out.add(s[:i] + c + s[i + 1:])
    for i in range(len(s) - 1):
        if s[i] != s[i + 1]:
            out.add(s[:i] + s[i + 1] + s[i] + s[i + 2:])
    hi = len(s) + 1 if terminal_insert else len(s)
    for i in range(hi):
        for c in ALPHA:
            out.add(s[:i] + c + s[i:])
    out.discard(s)
    return out


# The clone's own classifier (ios/FluxClone/Data/Affix.swift), reimplemented so the numbers
# here reconcile with reports/clone_gate.md. This is a curated morphological affix list and is
# deliberately NOT the 60 affixes mined for the affix grid: SPEC 7.3 keeps the two apart
# because they do different jobs. "Which affix did he over-apply" needs -ERS and -IEST, not
# the single-letter extensions -E and T- that the reachability table is built on.
SUFFIXES = ["NESSES", "INGS", "IEST", "IERS", "NESS", "LESS", "MENT", "ABLE", "IER", "IES",
            "ING", "ERS", "EST", "ISH", "FUL", "OUS", "IVE", "ITY", "IZE", "ISE", "ED", "ER",
            "EN", "ES", "LY", "AL", "Y", "S"]
PREFIXES = ["OVER", "UNDER", "OUT", "PRE", "DIS", "MIS", "NON", "RE", "UN", "DE", "IN"]


def split_affix(s, lex, affixes=None):
    for suf in SUFFIXES:
        if len(s) > len(suf) + 1 and s.endswith(suf):
            base = s[:-len(suf)]
            cands = [base]
            if suf[0] in "AEIOUY":
                cands.append(base + "E")
            if suf.startswith("I"):
                cands.append(base + "Y")
            if base.endswith("I"):
                cands.append(base[:-1] + "Y")
            if len(base) >= 2 and base[-1] == base[-2]:
                cands.append(base[:-1])
            for c in cands:
                if len(c) >= 2 and c in lex:
                    return c, "-" + suf
    for pre in PREFIXES:
        if len(s) > len(pre) + 2 and s.startswith(pre):
            stem = s[len(pre):]
            if stem in lex:
                return stem, pre + "-"
    return None, None


def run(affixes, db=None):
    lex = Q.lexicon()
    con = sqlite3.connect(db or Q.CLONE_DB)
    games = pd.read_sql("select game_id, grid, tier, letters, potential_points from game "
                        "where interrupted=0", con)
    att = pd.read_sql("select game_id, seq, cell_sequence, letters as attempt, t_touch_down, "
                      "t_submit, result, gap_since_previous_submit from attempt", con)
    con.close()
    att = att[att.game_id.isin(set(games.game_id))]
    boards = {r.game_id: Board(r.letters, int(r.grid)) for r in games.itertuples()}
    ngames = len(games)

    inv = att[(att.result == "invalid") & (att.attempt.str.len() >= 3)].copy()
    inv["cells"] = inv.cell_sequence.map(lambda s: [int(x) for x in s.split(",")])
    inv["swipeSeconds"] = inv.t_submit - inv.t_touch_down
    inv["allInSeconds"] = inv.gap_since_previous_submit

    rows = []
    for s, grp in inv.groupby("attempt"):
        gids = sorted(set(grp.game_id))
        stem, affix = split_affix(s, lex, affixes)
        early, pathv, nbrs = [], [], []
        for r in grp.itertuples():
            b = boards[r.game_id]
            # early lift: a valid word that continues the path already swiped
            for extra in (1, 2):   # 3+ extra letters is not a lift, it is a different word
                found = _continuations(b, r.cells, s, lex, extra)
                if found:
                    early.extend(found)
                    break
            for cand in edit_one(s):
                if cand in lex and b.path(cand) is not None:
                    pathv.append(cand)
        early, pathv = sorted(set(early)), sorted(set(pathv))
        live = _live_branches(stem, affixes, lex) if stem else []
        if affix and stem:
            cause = "affixError"
        elif early:
            cause = "earlyLift"
        elif pathv:
            cause = "pathError"
        else:
            cause = "trueNonWord"
        nbrs = (early + pathv)[:8]
        rows.append(dict(attempt=s, len=len(s), times=len(grp), games=len(gids),
                         secondsAllIn=float(grp.allInSeconds.sum()),
                         secondsSwipe=float(grp.swipeSeconds.sum()),
                         cause=cause, stem=stem or "", affix=affix or "",
                         liveAffixes=",".join(a for _, a in live[:10]) if live else "",
                         nearestValid=",".join(nbrs),
                         isPrefixOfWord=any(w.startswith(s) for w in early),
                         boards=",".join(g[:8] for g in gids),
                         studyItem=cause in ("affixError", "trueNonWord")))
    t = pd.DataFrame(rows).sort_values(["times", "secondsAllIn"], ascending=False)
    totals = {
        "games": ngames,
        "invalidAttempts": int(len(inv)),
        "invalidPerGame": float(len(inv) / ngames),
        "secondsAllInPerGame": float(inv.allInSeconds.sum() / ngames),
        "secondsSwipePerGame": float(inv.swipeSeconds.sum() / ngames),
        "meanAttemptLen": float(inv.attempt.str.len().mean()),
        "byCause": t.groupby("cause").agg(strings=("attempt", "size"), times=("times", "sum"),
                                          secondsAllIn=("secondsAllIn", "sum")).to_dict("index"),
    }
    per_cause_all = _classify_all(inv, boards, lex, affixes)
    totals["byCauseAllAttempts"] = per_cause_all
    return t, totals


def _continuations(b, cells, s, lex, extra):
    out = []
    for suffix in _suffixes(s, lex, extra):
        if b.continuable(cells, suffix):
            out.append(s + suffix)
    return out


_BY_PREFIX = {}


def _suffixes(s, lex, k):
    if not _BY_PREFIX:
        for w in lex:
            for i in range(3, len(w)):
                _BY_PREFIX.setdefault(w[:i], []).append(w)
    return {w[len(s):] for w in _BY_PREFIX.get(s, ()) if len(w) == len(s) + k}


def _live_branches(stem, affixes, lex):
    return [(side, ("-" + a) if side == "back" else (a + "-")) for side, a in affixes
            if ((stem + a) if side == "back" else (a + stem)) in lex]


def _classify_all(inv, boards, lex, affixes):
    """The same classification over every invalid attempt, not just the repeated ones, so the
    share of the 27.1 s a game that each cause carries is measured on the whole log."""
    agg = defaultdict(lambda: {"attempts": 0, "secondsAllIn": 0.0})
    for r in inv.itertuples():
        b = boards[r.game_id]
        stem, affix = split_affix(r.attempt, lex, affixes)
        if affix:
            c = "affixError"
        elif any(_continuations(b, r.cells, r.attempt, lex, k) for k in (1, 2)):
            c = "earlyLift"
        elif any(w in lex and b.path(w) is not None for w in edit_one(r.attempt)):
            c = "pathError"
        else:
            c = "trueNonWord"
        agg[c]["attempts"] += 1
        agg[c]["secondsAllIn"] += float(r.allInSeconds)
    return {k: v for k, v in sorted(agg.items())}


if __name__ == "__main__":
    import hooks
    t, totals = run(hooks.mined_affixes())
    Q.ensure_build()
    t.to_csv(os.path.join(Q.BUILD, "misswipes_repeated.tsv"), sep="\t", index=False, float_format="%.3f")
    Q.dump_json(totals, os.path.join(Q.BUILD, "misswipe_totals.json"))
    print(totals)
    print(t.head(25).to_string())

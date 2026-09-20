"""Hooks: a stem and its branches, which is the unit this queue ranks.

A word taught in isolation is a word that will not be found -- the export puts the 5+ take rate
at 74% when the word extends something already on the board and about 1% otherwise -- so nothing
here is ranked as a bare string. Every study item is a stem plus the branches hanging off it.

Stems are mined, not listed. Every contiguous substring of length 3 to 5 of a word the player
actually meets (present on 20+ of the 2,865 current-regime boards) is a candidate. Its family is
every Flux-dictionary word of 9 letters or fewer that contains it contiguously, which is SPEC
7.3's containment rule and is exactly the path condition: the stem's cells are used, in order,
untouched. Families are taken over the dictionary rather than over the player's own presence
table because enumerability asks how many words are on the board, not how many he has met.

Gates applied:
  * |family| >= 2 and at least one additive branch                       (SPEC 7.2 rules 1, 5)
  * the stem's path present on >= 0.5% of the player's boards            (SPEC 7.2 rule 4)
  * closure: drop a stem if a longer stem has the same member set        (SPEC 7.5 condition 3)

Enumerability (SPEC 7.5 condition 1) is computed per stem and carried on every row, but it is
not a hard gate: SPEC 7.5 is explicit that it "governs whether a stem works as a hunting cue,
and nothing else... It does not decide what is worth studying." It is the browser's default
filter instead. SPEC 7.2 rule 2 (coherence >= 0.65 and len(stem) >= 4) is reported and not
gated: it contradicts the 3-to-4-letter band Phase 1 measured and the build plan's own RAI-
example, and enumerability does the job coherence was there to do.
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd

import qcommon as Q
import reach as Rch

MIN_PRES = 20              # universe for stem mining: 20 of 2,865 current games (0.7%)
STEM_LENS = (3, 4, 5)
MAX_MEMBER_LEN = 9         # beyond this, reachability is below 1e-3 in every cell
BELIEF_UNKNOWN = 0.35      # SPEC 7.5.1
BELIEF_OWNED = 0.65
ENUM_BAND = (2.0, 6.0)     # SPEC 7.5 condition 1
MIN_COPRESENT = 200        # stem-present games needed before the observed reach beats the model
BRANCH_REACH_FLOOR = 0.005  # a branch below this is never there; kept out of the listings
VOWELS = set("AEIOU")


def mined_affixes():
    """The 60 affixes the measure tool mined from the dictionary (SPEC 7.3 mechanism 3)."""
    m = Rch.load_measured()
    m = m[(m.grid == "4x4") & (m.tier == "goodCasual")]
    return [(r.side, r.letters) for _, r in m.iterrows()]


def affix_productivity(lex, affixes):
    """How often a player would plausibly try this affix: the share of 3-7 letter words it
    completes. This is the weight SPEC 7.3 mechanism 3 mines the dead half of the grid with."""
    base = [w for w in lex if 3 <= len(w) <= 7]
    return {(side, a): sum(1 for w in base if ((w + a) if side == "back" else (a + w)) in lex) / len(base)
            for side, a in affixes}


def mutating_candidates(stem, lex):
    """SPEC 7.3: mutation rules survive only to generate related-but-not-containing words."""
    out, bases = set(), []
    tails = ["", "S", "ED", "ER", "ERS", "ES", "ING", "IEST", "IER", "Y", "EST", "D", "R", "INGS"]
    if stem.endswith("E"):
        bases.append(stem[:-1])
    if stem.endswith("Y"):
        bases.append(stem[:-1] + "I")
    if len(stem) >= 3 and stem[-1] not in VOWELS and stem[-2] in VOWELS and stem[-3] not in VOWELS:
        bases.append(stem + stem[-1])
    for b in bases:
        for t in tails:
            w = b + t
            if w != stem and w in lex and stem not in w:
                out.add(w)
    return out


def mine(words, lex):
    """stem -> family, over the dictionary, seeded by the words the player actually meets."""
    uni = words[(words.nCur >= MIN_PRES) & words.inLexicon & ~words.neverAccepted]
    seeds = set()
    for w in uni.index:
        L = len(w)
        for k in STEM_LENS:
            for i in range(L - k + 1):
                if L > k:
                    seeds.add(w[i:i + k])
    fam = defaultdict(set)
    for w in lex:
        L = len(w)
        if L > MAX_MEMBER_LEN or L <= min(STEM_LENS):
            continue
        for k in STEM_LENS:
            if L <= k:
                continue
            for i in range(L - k + 1):
                s = w[i:i + k]
                if s in seeds:
                    fam[s].add(w)
    fam = {s: m for s, m in fam.items() if len(m) >= 2}
    by_members = defaultdict(list)
    for s, m in fam.items():
        by_members[frozenset(m)].append(s)
    drop = {s for stems in by_members.values() if len(stems) > 1
            for s in stems if s != max(stems, key=len)}
    return {s: m for s, m in fam.items() if s not in drop}, len(drop), len(uni)


def copresence(fam, words, exclude):
    """Measured on the player's own current-regime boards.

    P(stem path present) = share of games with at least one family member present. A member's
    path contains the stem's as a contiguous sub-path, so a present member is a present stem.
    P(branch | stem) = co-presence / stem presence, the observed counterpart of the simulator's
    reachability, measured on 2,865 real boards instead of 30,000 synthetic ones.
    """
    g = pd.read_parquet(os.path.join(Q.RANKED, "games.parquet"), columns=["gid", "season", "grid"])
    g = g[g.season >= Q.CURRENT_FROM_SEASON]
    cur = set(g.gid)
    ngames = len(cur)
    grid_of = dict(zip(g.gid, g.grid))
    n_by_grid = g.grid.value_counts().to_dict()
    seen = set(words.index[(words.nCur >= 1) & ~words.index.isin(exclude)])
    stems = sorted(fam)
    scode = {s: i for i, s in enumerate(stems)}
    members = sorted({m for ms in fam.values() for m in ms} & seen)
    wcode = {w: i for i, w in enumerate(members)}
    ls, lw = [], []
    for s, ms in fam.items():
        si = scode[s]
        for m in ms:
            j = wcode.get(m)
            if j is not None:
                ls.append(si)
                lw.append(j)
    link = pd.DataFrame({"s": np.array(ls, np.int32), "w": np.array(lw, np.int32)})

    pres = pd.read_parquet(os.path.join(Q.RANKED, "presence.parquet"), columns=["gid", "word"])
    pres = pres[pres.gid.isin(cur)]
    pres = pres.assign(w=pres.word.map(wcode)).dropna(subset=["w"])
    df = pd.DataFrame({"w": pres.w.to_numpy(np.int32), "gid": pres.gid.to_numpy(np.int32)}).drop_duplicates()

    j = df.merge(link, on="w")
    sg = j[["s", "gid"]].drop_duplicates()
    stem_games = sg.groupby("s").size()
    sg = sg.assign(grid=sg.gid.map(grid_of))
    by_grid = sg.groupby(["s", "grid"]).size().unstack(fill_value=0)
    stem_pres = np.zeros(len(stems))
    stem_pres[stem_games.index.values] = stem_games.values
    co = j.groupby(["s", "w"]).size()
    co_idx = np.array(co.index.tolist(), np.int32) if len(co) else np.zeros((0, 2), np.int32)
    obs = {}
    for (si, wi), c in zip(co_idx, co.values):
        d = stem_pres[si]
        if d > 0:
            obs[(stems[si], members[wi])] = (int(c), float(c / d))
    grids = {}
    for c in ("4x4", "5x5"):
        col = by_grid[c] if c in by_grid else None
        arr = np.zeros(len(stems))
        if col is not None:
            arr[col.index.values] = col.values
        grids[c] = arr / max(n_by_grid.get(c, 1), 1)
    return ({s: stem_pres[i] / ngames for s, i in scode.items()},
            {s: int(stem_pres[i]) for s, i in scode.items()}, obs, ngames,
            {s: {c: float(grids[c][i]) for c in grids} for s, i in scode.items()})

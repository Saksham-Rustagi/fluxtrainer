"""One pass over every solved board: containment, reachability, anagrams, drop-terminal.

For each board, every present word W is scanned for contiguous substrings s (length >= 3)
that are themselves present. Each (s, W) pair is a family relation (spec 7.3: containment
is the additive test). Where s was found by either player, whether W's path actually
extends s's path is checked against the stored paths -- that is reachability (spec 3.5).

Outputs are aggregated per board (or kept as rows only where the rows are few), and
cached to build-analytics/boardpass.pkl.
"""
import collections
import os
import pickle

import numpy as np
import pandas as pd

from common import BUILD, load_solutions, load_wordlist, points

CACHE_DIR = BUILD


def curated_word_stems(words, per_len=2000):
    """Top word-stems per length by weighted productivity over CSW21 (Phase 1 curatedWord analog)."""
    wset = set(words)
    prod = collections.Counter()
    for w in words:
        L = len(w)
        pts = 100 if L == 3 else 400 if L == 4 else 800 if L == 5 else 1400 + 400 * (L - 6)
        seen = set()
        for k in range(3, min(8, L)):
            for st in range(L - k + 1):
                s = w[st:st + k]
                if s in wset and s not in seen:
                    seen.add(s)
                    prod[s] += pts
    out = set()
    for k in range(3, 8):
        ranked = sorted((v, s) for s, v in prod.items() if len(s) == k)[::-1][:per_len]
        out.update(s for _, s in ranked)
    return out


def run(pres, games, tag="voc"):
    """tag names the cache: 'voc' excludes never-accepted words, 'all' keeps them."""
    cache_path = os.path.join(CACHE_DIR, f"boardpass_{tag}.pkl")
    if os.path.exists(cache_path):
        return pickle.load(open(cache_path, "rb"))
    words = load_wordlist()
    wset = set(words)
    akey = collections.Counter("".join(sorted(w)) for w in words)
    curated = curated_word_stems(words)
    sol = load_solutions(["gid", "word", "paths"])
    x = pres.merge(sol, on=["gid", "word"]).sort_values("gid")
    x["fo"] = x.foundOpp.fillna(False).astype(bool)
    wpts = lambda L: 100 if L == 3 else 400 if L == 4 else 800 if L == 5 else 1400 + 400 * (L - 6)  # noqa: E731

    fam_rows, m3_rows, affix_rows, missed_rows, ana_rows, m2_rows, dt_rows = [], [], [], [], [], [], []
    m1_rows = []
    dto_rows = []
    dt_words = collections.Counter()
    dt_words_found = collections.Counter()
    dt_violations = 0
    free_rows = []
    rng = np.random.default_rng(9)
    free_sample = set(rng.choice(games.gid.values, min(600, len(games)), replace=False).tolist())

    for gid, b in x.groupby("gid", sort=False):
        W = b.word.values
        fp = b.foundPlayer.values.astype(bool)
        fo = b.fo.values
        P = b.paths.values
        idx = {w: i for i, w in enumerate(W)}
        cache = {}

        def paths(i):
            v = cache.get(i)
            if v is None:
                v = [tuple(ord(c) - 97 for c in p) for p in P[i].split(",")]
                cache[i] = v
            return v

        def reachable(j, i, st):
            k = len(W[j])
            sp = set(paths(j))
            return any(p[st:st + k] in sp for p in paths(i))

        members = collections.defaultdict(set)
        pairs = []  # (j, i, st) with every occurrence offset
        for i, w in enumerate(W):
            L = len(w)
            for k in range(3, L):
                for st in range(L - k + 1):
                    j = idx.get(w[st:st + k])
                    if j is not None:
                        pairs.append((j, i, st))
                        members[j].add(i)
        # ---- families (4.4): stems of length >= 4 with at least one other present member
        for j, ms in members.items():
            if len(W[j]) >= 4:
                fam = ms | {j}
                nfp = int(sum(fp[m] for m in fam))
                nfo = int(sum(fo[m] for m in fam))
                pts_all = sum(wpts(len(W[m])) for m in fam)
                pts_none = sum(wpts(len(W[m])) for m in fam if not (fp[m] or fo[m]))
                fam_rows.append((gid, W[j], len(W[j]), len(fam), nfp, nfo, bool(fp[j]), pts_all, pts_none))
        # ---- M3-real: word-stems of length 3-7 present on the board, members excluding the stem
        agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        for j in range(len(W)):
            k = len(W[j])
            if 3 <= k <= 7:
                ms = members.get(j, ())
                a = agg[(k, W[j] in curated)]
                a[0] += 1
                a[1] += len(ms)
                a[2] += sum(fp[m] for m in ms)
                if fp[j]:
                    a[3] += 1
                    a[4] += len(ms)
                    a[5] += sum(fp[m] for m in ms)
        for (k, cur), a in agg.items():
            m3_rows.append((gid, k, cur, *a))
        # ---- extensions of found words: reachability (M1-real, 4.5) and drop-terminal
        pair_seen = {}
        for j, i, st in pairs:
            if not (fp[j] or fo[j]):
                continue
            key = (j, i)
            if key in pair_seen and pair_seen[key]:
                continue
            pair_seen[key] = pair_seen.get(key, False) or reachable(j, i, st)
        free_for = collections.defaultdict(lambda: [False, False, 99])  # i -> [free for player, for opp, min ext len]
        stem_stats = collections.defaultdict(lambda: [0, 0])
        for (j, i), reach in pair_seen.items():
            s, w = W[j], W[i]
            ext = len(w) - len(s)
            if reach:
                if fp[j]:
                    free_for[i][0] = True
                    free_for[i][2] = min(free_for[i][2], ext)
                    stem_stats[j][0] += 1
                    stem_stats[j][1] += fp[i]
                if fo[j]:
                    free_for[i][1] = True
            if ext <= 3:
                if w.startswith(s):
                    aff = "-" + w[len(s):]
                elif w.endswith(s):
                    aff = w[:ext] + "-"
                else:
                    aff = None
                if aff:
                    affix_rows.append((gid, s, w, aff, len(s), bool(reach), bool(fp[j]), bool(fo[j]), bool(fp[i]), bool(fo[i])))
        for j, (n, k) in stem_stats.items():
            m1_rows.append((gid, len(W[j]), n, k))
        for j in range(len(W)):
            if fp[j] and j not in stem_stats:
                m1_rows.append((gid, len(W[j]), 0, 0))
        host = {}
        for (j, i), reach in pair_seen.items():
            if reach and fp[j] and len(W[j]) > len(host.get(i, "")):
                host[i] = W[j]
        # cellmates of a word he found on this board, and terminal substrings of one
        groups_ = collections.defaultdict(list)
        for i, w in enumerate(W):
            groups_["".join(sorted(w))].append(i)
        cell_of_found = set()
        for ms in groups_.values():
            if len(ms) > 1 and any(fp[m] for m in ms):
                cell_of_found.update(m for m in ms if not fp[m] or sum(fp[k] for k in ms) > 1)
        dt_of_found = set()
        for i, w in enumerate(W):
            if fp[i]:
                L = len(w)
                for k in range(3, L):
                    for sub in (w[:k], w[L - k:]):
                        j = idx.get(sub)
                        if j is not None:
                            dt_of_found.add(j)
        for i in range(len(W)):
            ff = free_for.get(i)
            missed_rows.append((gid, W[i], len(W[i]), bool(fp[i]), bool(ff and ff[0]), (ff[2] if ff else 0), bool(fo[i]),
                                bool(ff and ff[1]), i in cell_of_found, i in dt_of_found, host.get(i, "")))
        # ---- drop-terminal: terminal substrings of a found word are present by construction
        for i, w in enumerate(W):
            if not fp[i]:
                continue
            L = len(w)
            for k in range(3, L):
                for s in {w[:k], w[L - k:]}:
                    if s in wset:
                        j = idx.get(s)
                        if j is None:
                            dt_violations += 1
                            continue
                        dt_rows.append((gid, k, L, bool(fp[j])))
                        dt_words[s] += 1
                        dt_words_found[s] += fp[j]
        for i, w in enumerate(W):
            if not fo[i]:
                continue
            L = len(w)
            for k in range(3, L):
                for sub in {w[:k], w[L - k:]}:
                    j = idx.get(sub)
                    if j is not None:
                        dto_rows.append((gid, k, L, bool(fo[j])))
        # ---- anagram sets (4.6) and M2-real
        groups = collections.defaultdict(list)
        for i, w in enumerate(W):
            groups["".join(sorted(w))].append(i)
        for key, ms in groups.items():
            dict_others = akey[key] - 1
            if dict_others <= 0:
                continue
            npf = sum(fp[m] for m in ms)
            m2_rows.append((gid, len(key), len(ms), dict_others, int(npf), sum(fo[m] for m in ms)))
            if len(ms) >= 2:
                ana_rows.append((gid, key, len(key), len(ms), int(npf), int(sum(fo[m] for m in ms))))
        # ---- availability of free words with perfect vocabulary (Phase 1's M1 framing), sampled
        if gid in free_sample:
            free = set()
            ext_per = collections.defaultdict(set)
            for j, i, st in pairs:
                if i not in ext_per[j] and reachable(j, i, st):
                    ext_per[j].add(i)
                    free.add(i)
            free_rows.append((gid, len(W), len(free), float(np.mean([len(v) for v in ext_per.values()]) if ext_per else 0),
                              float(np.mean([len(ext_per.get(j, ())) for j in range(len(W))]))))

    out = {
        "fam": pd.DataFrame(fam_rows, columns=["gid", "stem", "stemLen", "size", "foundP", "foundO", "stemFoundP", "ptsAll", "ptsNone"]),
        "m3": pd.DataFrame(m3_rows, columns=["gid", "stemLen", "curated", "stems", "members", "membersFoundP",
                                             "stemsFoundP", "membersIfStemFound", "membersFoundIfStemFound"]),
        "affix": pd.DataFrame(affix_rows, columns=["gid", "stem", "word", "affix", "stemLen", "reachable", "stemFoundP",
                                                   "stemFoundO", "wordFoundP", "wordFoundO"]),
        "m1stem": pd.DataFrame(m1_rows, columns=["gid", "stemLen", "reachableExt", "reachableExtFound"]),
        "missed": pd.DataFrame(missed_rows, columns=["gid", "word", "len", "foundP", "freeForP", "minExt", "foundO", "freeForO",
                                                     "cellmateOfFound", "dtOfFound", "host"]),
        "dtO": pd.DataFrame(dto_rows, columns=["gid", "shortLen", "longLen", "foundO"]),
        "dt": pd.DataFrame(dt_rows, columns=["gid", "shortLen", "longLen", "foundP"]),
        "dtWords": pd.DataFrame({"word": list(dt_words), "opportunities": [dt_words[w] for w in dt_words],
                                 "found": [dt_words_found[w] for w in dt_words]}),
        "dtViolations": dt_violations,
        "ana": pd.DataFrame(ana_rows, columns=["gid", "key", "len", "present", "foundP", "foundO"]),
        "m2": pd.DataFrame(m2_rows, columns=["gid", "len", "presentInSet", "dictOthers", "foundP", "foundO"]),
        "free": pd.DataFrame(free_rows, columns=["gid", "present", "freeWords", "extPerStemWithAny", "extPerPresentWord"]),
        "curatedCount": len(curated),
    }
    for k in ("fam", "affix", "missed", "dt", "dtO", "ana", "m2", "m3", "m1stem", "free"):
        out[k] = out[k].merge(games[["gid", "tier", "grid", "season"]], on="gid")
    pickle.dump(out, open(cache_path, "wb"))
    return out

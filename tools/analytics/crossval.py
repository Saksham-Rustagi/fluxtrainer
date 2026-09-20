"""Cross-validate the two exports on the games they share. Runs after both ingests.

A game between the two players appears once in each export, from each side. Her
yourWordsFound must equal his opponent.wordsFound and vice versa, in order, and both
scores must agree. This is the only independent check on export integrity: every
other opponent word list in either export is seen from one side only.

Shared games are matched on createdAt, not on usernames: a player's username is
stamped at game time, and one of the two changed hers during the overlap.

Writes data/ranked/shared/h2h.parquet (one row per shared game, both gids) and
data/ranked/shared/crossval.json.
"""
import glob
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import PLAYERS, ROOT, SHARED, load  # noqa: E402

A, B = "miningmath", "nicole"


def raw(player):
    out, seen = {}, set()
    for path in sorted(glob.glob(os.path.join(ROOT, "data", f"ranked_data_{PLAYERS[player]}_part*.json"))):
        for g in json.load(open(path))["games"]:
            k = (g["createdAt"], g["opponent"]["username"])
            if k in seen:
                continue
            seen.add(k)
            out.setdefault(g["createdAt"], []).append(g)
    return out


def main():
    ra, rb = raw(A), raw(B)
    shared = sorted(set(ra) & set(rb))
    ga = load("games_raw.parquet", A, columns=["gid", "createdAt", "oppName", "letters", "side", "season", "yourScore", "oppScore"])
    gb = load("games_raw.parquet", B, columns=["gid", "createdAt", "oppName"])
    ga["key"] = ga.createdAt.dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    gb["key"] = gb.createdAt.dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    ida, idb = dict(zip(ga.key, ga.gid)), dict(zip(gb.key, gb.gid))

    rows, mismatches = [], []
    checks = ("board", "aWordsEqualBOpp", "bWordsEqualAOpp", "aScoreEqualBOpp", "bScoreEqualAOpp", "outcome", "wentFirst",
              "completedAt", "season")
    for k in shared:
        if len(ra[k]) != 1 or len(rb[k]) != 1:
            mismatches.append({"createdAt": k, "problem": "createdAt not unique"})
            continue
        a, b = ra[k][0], rb[k][0]
        t = {
            "board": a["board"] == b["board"],
            "aWordsEqualBOpp": a["yourWordsFound"] == b["opponent"]["wordsFound"],
            "bWordsEqualAOpp": b["yourWordsFound"] == a["opponent"]["wordsFound"],
            "aScoreEqualBOpp": a["yourScore"] == b["opponent"]["score"],
            "bScoreEqualAOpp": b["yourScore"] == a["opponent"]["score"],
            "outcome": (a["didWin"] is None and b["didWin"] is None) or (a["didWin"] is not None and b["didWin"] is not None and a["didWin"] != b["didWin"]),
            "wentFirst": a["wentFirst"] != b["wentFirst"],
            "completedAt": a["completedAt"] == b["completedAt"],
            "season": a["season"] == b["season"],
        }
        forfeit = not a["yourWordsFound"] or not b["yourWordsFound"]
        rows.append({"createdAt": k, f"gid_{A}": ida[k], f"gid_{B}": idb[k], "nameInA": a["opponent"]["username"],
                     "nameInB": b["opponent"]["username"], "forfeit": forfeit, "exact": all(t.values()), **t})
        if not all(t.values()):
            mismatches.append({"createdAt": k, f"gid_{A}": ida[k], f"gid_{B}": idb[k], "failed": [c for c in checks if not t[c]]})
    h = pd.DataFrame(rows)
    h["createdAt"] = pd.to_datetime(h.createdAt, utc=True)
    h.to_parquet(os.path.join(SHARED, "h2h.parquet"), index=False)

    # the known corrupt row in A: gid 2309, whose opponent list belongs to another board
    fa = load("finds.parquet", A)
    sol = pd.read_parquet(os.path.join(SHARED, "solutions.parquet"), columns=["letters", "word"])
    ga_i = ga.set_index("gid")
    corrupt = {}
    on_board = set(zip(sol.letters, sol.word))
    for gid in (2309,):
        row = ga_i.loc[gid]
        words = fa[(fa.gid == gid) & (fa.who == "opponent")].word.tolist()
        k = row.key
        # which board, across both exports, holds that opponent list?
        hit = sol[sol.word.isin(set(words))].groupby("letters").word.nunique().sort_values(ascending=False)
        best = hit.index[0]
        in_a = ga[ga.letters == best]
        gbl = load("games_raw.parquet", B, columns=["gid", "createdAt", "letters", "oppName"])
        in_b = gbl[gbl.letters == best]
        corrupt[str(gid)] = {
            "opponent": row.oppName, "createdAt": k, "sharedGame": k in rb,
            "opponentWords": len(words), "offBoardWords": int(sum((row.letters, w) not in on_board for w in words)),
            "bestMatchingBoard": {"wordsPresent": int(hit.iloc[0]), "of": len(set(words)),
                                  f"in_{A}": in_a[["gid", "oppName"]].assign(createdAt=in_a.createdAt.astype(str)).to_dict("records"),
                                  f"in_{B}": in_b[["gid", "oppName"]].assign(createdAt=in_b.createdAt.astype(str)).to_dict("records")},
            f"{B}HasGameAtThisTime": k in rb,
        }

    # never-accepted words (50+ presences in one export, found by nobody there): accepted in the other?
    dead = {}
    pres = {}
    for p in (A, B):
        x = pd.read_parquet(os.path.join(ROOT, "data", "ranked", p, "presence.parquet"), columns=["gid", "word", "foundPlayer", "foundOpp"])
        x["any"] = x.foundPlayer | x.foundOpp.fillna(False).astype(bool)
        w = x.groupby("word")["any"].agg(["size", "sum"])
        pres[p] = w
        dead[p] = set(w[(w["size"] >= 50) & (w["sum"] == 0)].index)
    cross = {}
    for p, q in ((A, B), (B, A)):
        found_in_q = pres[q][pres[q]["sum"] > 0]
        acc = sorted(dead[p] & set(found_in_q.index))
        cross[p] = {"deadWords": len(dead[p]), "acceptedInOther": len(acc),
                    "acceptedInOtherExamples": found_in_q.loc[acc].sort_values("sum", ascending=False).head(30)["sum"].to_dict(),
                    "deadInBoth": len(dead[p] & dead[q]), "presentInOther": len(dead[p] & set(pres[q].index))}
    pooled = pres[A].add(pres[B], fill_value=0)
    cross["pooledDead"] = int(((pooled["size"] >= 50) & (pooled["sum"] == 0)).sum())

    ua = ga.letters.nunique()
    out = {
        "exports": {p: {"games": len(load("games_raw.parquet", p, columns=["gid"]))} for p in (A, B)},
        "sharedGames": len(h),
        "sharedByName": {f"{A}ExportOpponentNames": h.nameInA.value_counts().to_dict(), f"{B}ExportOpponentNames": h.nameInB.value_counts().to_dict()},
        "exactOnAll": int(h.exact.sum()),
        "checks": {c: int(h[c].sum()) for c in checks},
        "mismatches": mismatches,
        "forfeits": h[h.forfeit].assign(createdAt=lambda d: d.createdAt.astype(str))[["createdAt", f"gid_{A}", f"gid_{B}"]].to_dict("records"),
        "contested": int((~h.forfeit).sum()),
        "corruptRows": corrupt,
        "distinctBoards": {"shared": int(len(set(ga.letters) & set(load('games_raw.parquet', B, columns=['letters']).letters))),
                           A: int(ua), B: int(load("games_raw.parquet", B, columns=["letters"]).letters.nunique()),
                           "solvedTotal": int(sol.letters.nunique())},
        "neverAccepted": cross,
    }
    json.dump(out, open(os.path.join(SHARED, "crossval.json"), "w"), indent=2, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ("neverAccepted",)}, indent=1, default=str)[:3000])
    print(json.dumps(cross, indent=1, default=str)[:2000])


if __name__ == "__main__":
    sys.exit(main())

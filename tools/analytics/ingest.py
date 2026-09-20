"""Ingest one player's ranked export (FLUX_PLAYER): merge parts, dedupe, solve new boards.

Writes to data/ranked/<player>/:
  games_raw.parquet   one row per deduplicated game, export fields flattened
  finds.parquet       one row per find (player and opponent), in find order
  ingest.json         counts, overlap, hashes

and adds to data/ranked/shared/solutions.parquet, the solution cache keyed by board
letters: one row per (board, present word) with every stored path. Both players'
exports share it. A board already in the cache is not solved again, and the cache is
rebuilt from scratch if the dictionary or the solver config changes.

Solving goes through tools/solve_boards, the same C++ solver the simulator
uses, so observed and simulated potentials can never disagree about a board.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import NAME, RANKED, ROOT, SHARED  # noqa: E402

DATA = os.path.join(ROOT, "data")
OUT = RANKED
BUILD = os.path.join(ROOT, "build")
DAWG = os.path.join(ROOT, "build-analytics", "csw21.dawg")
CONFIG = os.path.join(ROOT, "config", "ruleset_v1.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def solve_new(letters):
    """Solve boards the shared cache lacks. Returns (cache, boards solved now)."""
    cache_path = os.path.join(SHARED, "solutions.parquet")
    meta_path = os.path.join(SHARED, "solutions_meta.json")
    stamp = {"dawgSha256": sha256(DAWG), "configSha256": sha256(CONFIG)}
    cache = None
    if os.path.exists(cache_path) and os.path.exists(meta_path):
        meta = json.load(open(meta_path))
        if all(meta.get(k) == v for k, v in stamp.items()):
            cache = pd.read_parquet(cache_path)
    have = set() if cache is None else set(cache.letters.unique())
    todo = [x for x in letters if x not in have]
    if todo:
        boards_tsv = os.path.join(SHARED, "boards_todo.tsv")
        solved_tsv = os.path.join(SHARED, "solved.tsv")
        with open(boards_tsv, "w") as f:
            for i, x in enumerate(todo):
                f.write(f"{i}\t{x}\n")
        subprocess.run([os.path.join(BUILD, "tools", "solve_boards", "solve_boards"), CONFIG, DAWG, boards_tsv, solved_tsv],
                       check=True)
        new = pd.read_csv(solved_tsv, sep="\t", dtype={"id": "int32", "word": str, "pathCount": "int32", "paths": str},
                          keep_default_na=False)
        new["letters"] = new.id.map(dict(enumerate(todo)))
        new["len"] = new.word.str.len().astype("int16")
        new = new[["letters", "word", "pathCount", "paths", "len"]]
        cache = new if cache is None else pd.concat([cache, new], ignore_index=True)
        cache.to_parquet(cache_path, index=False)
        os.remove(boards_tsv)
        os.remove(solved_tsv)
    json.dump(stamp | {"boards": int(cache.letters.nunique())}, open(meta_path, "w"), indent=2)
    return cache, len(todo)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(SHARED, exist_ok=True)
    parts = sorted(glob.glob(os.path.join(DATA, f"ranked_data_{NAME}_part*.json")))
    rows, seen, overlap = [], set(), 0
    meta = []
    for path in parts:
        d = json.load(open(path))
        meta.append({k: v for k, v in d.items() if k != "games"} | {"file": os.path.basename(path), "sha256": sha256(path)})
        for g in d["games"]:
            key = (g["createdAt"], g["opponent"]["username"])
            if key in seen:
                overlap += 1
                continue
            seen.add(key)
            rows.append({
                "part": d["part"],
                "season": int(g["season"].split("-")[1]),
                "wentFirst": g["wentFirst"],
                "createdAt": g["createdAt"],
                "completedAt": g["completedAt"],
                "yourScore": g["yourScore"],
                "yourWords": g["yourWordsFound"],
                "wordsFoundCount": g["wordsFoundCount"],
                "eloAtStart": g["eloAtStart"],
                "eloChange": g["eloChange"],
                "didWin": g["didWin"],
                "oppName": g["opponent"]["username"],
                "oppScore": g["opponent"]["score"],
                "oppWords": g["opponent"]["wordsFound"],
                "letters": g["board"]["letters"],
                "side": g["board"]["boardSize"],
                "duration": g["board"]["duration"],
            })
    games = pd.DataFrame(rows)
    games["createdAt"] = pd.to_datetime(games["createdAt"], utc=True)
    games["completedAt"] = pd.to_datetime(games["completedAt"], utc=True)
    games = games.sort_values("createdAt", kind="stable").reset_index(drop=True)
    games["gid"] = games.index.astype("int32")

    finds = []
    for g in games.itertuples():
        for who, words in (("player", g.yourWords), ("opponent", g.oppWords)):
            for pos, w in enumerate(words):
                finds.append((g.gid, who, pos, w))
    finds = pd.DataFrame(finds, columns=["gid", "who", "pos", "word"])
    finds["len"] = finds["word"].str.len().astype("int16")

    sol, solved_now = solve_new(games.letters.unique())

    games.drop(columns=["yourWords", "oppWords"]).to_parquet(os.path.join(OUT, "games_raw.parquet"))
    finds.to_parquet(os.path.join(OUT, "finds.parquet"))
    info = {
        "parts": meta,
        "rowsRead": int(sum(m["gamesInThisPart"] for m in meta)),
        "overlapRowsDropped": overlap,
        "games": int(len(games)),
        "finds": int(len(finds)),
        "solutionRows": int(sol[sol.letters.isin(set(games.letters))].shape[0]),
        "boardsSolvedThisRun": solved_now,
        "dawgSha256": sha256(DAWG),
        "configSha256": sha256(CONFIG),
    }
    json.dump(info, open(os.path.join(OUT, "ingest.json"), "w"), indent=2)
    print(json.dumps({k: v for k, v in info.items() if k != "parts"}, indent=2))


if __name__ == "__main__":
    sys.exit(main())

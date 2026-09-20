"""Shared definitions for the ranked-export analytics."""
import os

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Every stage runs for one player at a time, chosen by FLUX_PLAYER (default miningmath).
# Each player has their own derived data, build cache, figures and report; the solved
# boards are shared, because the exports overlap and a board only needs solving once.
PLAYERS = {"miningmath": "MiningMath", "nicole": "Nicole"}
PLAYER = os.environ.get("FLUX_PLAYER", "miningmath").lower()
if PLAYER not in PLAYERS:
    raise SystemExit(f"FLUX_PLAYER must be one of {sorted(PLAYERS)}")
NAME = PLAYERS[PLAYER]
PEER = next(k for k in PLAYERS if k != PLAYER)
PEER_NAME = PLAYERS[PEER]
RANKED_ROOT = os.path.join(ROOT, "data", "ranked")
SHARED = os.path.join(RANKED_ROOT, "shared")
REPORTS = os.path.join(ROOT, "reports")
BUILD_ROOT = os.path.join(ROOT, "build-analytics")


def ranked_dir(player=PLAYER):
    return os.path.join(RANKED_ROOT, player)


def build_dir(player=PLAYER):
    return os.path.join(BUILD_ROOT, player)


def figs_dir(player=PLAYER):
    return os.path.join(REPORTS, "figures", player)


RANKED = ranked_dir()
BUILD = build_dir()
FIGS = figs_dir()
# CSW21 (bogwords.txt, 279,496 words, sha256 2bf71e79...). Same list the DAWG is built from.
WORDLIST = os.environ.get("FLUX_WORDLIST", os.path.join(os.path.expanduser("~"), "Desktop", "code", "LetterCounter", "bogwords.txt"))

# Spec 2.2. The ranked export reproduces yourScore with exactly this table (report section 0).
def points(n):
    n = np.asarray(n)
    return np.where(n == 3, 100, np.where(n == 4, 400, np.where(n == 5, 800, 1400 + 400 * (n - 6))))


def len_class(n):
    """3, 4, 5, 6, 7 where 7 means 7+."""
    return np.minimum(np.asarray(n), 7)


LEN_CLASSES = [3, 4, 5, 6, 7]
LEN_LABELS = {3: "3", 4: "4", 5: "5", 6: "6", 7: "7+"}

# Board generation changed before season 7 (SPEC 2.5): seasons 7-10 are the current game.
CURRENT_FROM_SEASON = 7
TRAIN_SHARE = 0.7


def add_regime(g):
    """current: season >= 7. split: 'train' / 'test' chronologically 70/30 inside the current
    regime, 'old' before it. Every holdout in the report uses this split."""
    g = g.copy()
    g["current"] = g.season >= CURRENT_FROM_SEASON
    c = g[g.current].sort_values("createdAt")
    cut = c.createdAt.iloc[int(len(c) * TRAIN_SHARE)]
    g["split"] = np.where(~g.current, "old", np.where(g.createdAt < cut, "train", "test"))
    return g


def regime_start(g):
    return g[g.current].createdAt.min()


def trigrams(word):
    return {word[i:i + 3] for i in range(len(word) - 2)}


def shares_stem(a, b):
    """True iff a and b share a contiguous substring of length >= 3.

    Sharing any substring of length >= 3 is equivalent to sharing a trigram.
    """
    return not trigrams(a).isdisjoint(trigrams(b))


def load(name, player=PLAYER, **kw):
    return pd.read_parquet(os.path.join(ranked_dir(player), name), **kw)


def load_solutions(columns=None, player=PLAYER):
    """Per-game solutions for a player: the shared board cache joined on the board letters."""
    games = load("games_raw.parquet", player, columns=["gid", "letters"])
    cols = None if columns is None else ["letters"] + [c for c in columns if c not in ("gid", "letters")]
    sol = pd.read_parquet(os.path.join(SHARED, "solutions.parquet"), columns=cols)
    out = games.merge(sol, on="letters").drop(columns="letters")
    return out if columns is None else out[[c for c in columns]]


def decode_paths(s):
    """'abc,dca' -> [[0,1,2],[3,2,0]]."""
    return [[ord(c) - 97 for c in p] for p in s.split(",")] if s else []


def load_wordlist():
    with open(WORDLIST) as f:
        return [w.strip().upper() for w in f if w.strip()]

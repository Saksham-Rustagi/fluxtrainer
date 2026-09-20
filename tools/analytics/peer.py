"""The other player's data, for the series and checks that set one player against the other.

The peer series in a chart comes from the peer's own export (all their games in the
chart's regime), not only from the games the two played each other. Their games get a
gid offset so they can share frames with the subject's games without colliding.
"""
import json
import os

import pandas as pd

from common import PEER, PEER_NAME, PLAYER, SHARED, add_regime, build_dir, figs_dir, load, ranked_dir

GID_OFFSET = 1_000_000
LABEL = f"{PEER_NAME} (own games)"


def available():
    return os.path.exists(os.path.join(ranked_dir(PEER), "games.parquet"))


def games(cols=None):
    g = add_regime(load("games.parquet", PEER))
    g["gid"] = g.gid + GID_OFFSET
    return g if cols is None else g[cols]


def finds():
    """The peer's own finds (their 'player' rows), relabelled who='peer'."""
    f = load("finds_derived.parquet", PEER)
    f = f[f.who == "player"].copy()
    f["gid"] = f.gid + GID_OFFSET
    f["who"] = "peer"
    return f


def found_words():
    """Every word anyone had accepted in the peer's export."""
    p = pd.read_parquet(os.path.join(ranked_dir(PEER), "presence.parquet"), columns=["word", "foundPlayer", "foundOpp"])
    return set(p.word[p.foundPlayer | p.foundOpp.fillna(False).astype(bool)])


def results():
    path = os.path.join(build_dir(PEER), "results.json")
    return json.load(open(path)) if os.path.exists(path) else None


def fig_tsv(name):
    path = os.path.join(figs_dir(PEER), name + ".tsv")
    return pd.read_csv(path, sep="\t") if os.path.exists(path) else None


def h2h():
    """Shared games, keyed by the subject's gid: gid, peerGid, forfeit, exact."""
    path = os.path.join(SHARED, "h2h.parquet")
    if not os.path.exists(path):
        return None
    h = pd.read_parquet(path)
    return h.rename(columns={f"gid_{PLAYER}": "gid", f"gid_{PEER}": "peerGid"})[["gid", "peerGid", "createdAt", "forfeit", "exact"]]


def crossval():
    path = os.path.join(SHARED, "crossval.json")
    return json.load(open(path)) if os.path.exists(path) else None


def mark(g):
    """Flag the subject's games against the peer (matched on createdAt across exports)."""
    h = h2h()
    g = g.copy()
    g["peerGame"] = g.gid.isin(set(h.gid)) if h is not None else False
    g["peerForfeit"] = g.gid.isin(set(h.gid[h.forfeit])) if h is not None else False
    return g


"""Shared paths, dictionary and constants for the Phase 2 selection engine.

Everything here is read-only against artefacts produced in Phase 0/1. Nothing in this
package re-solves a board or recomputes belief: the ranked tables under data/ranked/ and
the simulation outputs under runs/ are the inputs, per the Phase 2 prompt.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "analytics"))

PLAYER = os.environ.get("FLUX_PLAYER", "miningmath").lower()
RANKED = os.path.join(ROOT, "data", "ranked", PLAYER)
SHARED = os.path.join(ROOT, "data", "ranked", "shared")
FIGS = os.path.join(ROOT, "reports", "figures", PLAYER)
REPORTS = os.path.join(ROOT, "reports")
BUILD = os.path.join(ROOT, "build-queue")

# Phase 1 rerun under ruleset v3. The Phase 2 prompt names runs/full and runs/m3-curated;
# those are the v1 runs, superseded by these (PHASE1_REPORT Part A). See the summary.
SIM_FULL = os.path.join(ROOT, "runs", "v3-full")
SIM_M3 = os.path.join(ROOT, "runs", "v3-m3-curated")

CLONE_DB = os.environ.get(
    "FLUX_CLONE_DB", os.path.join(ROOT, "data", "fluxclone-20260920-004740.sqlite"))

WORDLIST = os.environ.get(
    "FLUX_WORDLIST",
    os.path.join(os.path.expanduser("~"), "Desktop", "code", "LetterCounter", "bogwords.txt"))
REMOVED = os.path.join(ROOT, "data", "flux_removed_words.txt")

CURRENT_FROM_SEASON = 7

# --- measured constants -------------------------------------------------------------------
# reports/clone_gate.md, 8 games, 750 valid swipes. Replaces SPEC 3.2's placeholder 0.30+0.08n.
SWIPE_A = -0.085
SWIPE_B = 0.086
BASELINE_GAP = 0.383          # p40 inter-submission gap, excluding the opening gap
GAME_SECONDS = 80.0
# Everything else about misswipes -- attempts a game, seconds lost, the affix share -- is read
# straight from the clone's SQLite rather than copied here, so it cannot drift from the export.


def points(n):
    n = np.asarray(n)
    return np.where(n == 3, 100, np.where(n == 4, 400, np.where(n == 5, 800, 1400 + 400 * (n - 6))))


def seconds_per_word(n):
    """Marginal clock cost of one more word of length n: decision gap plus swipe."""
    return BASELINE_GAP + SWIPE_A + SWIPE_B * np.asarray(n)


_LEX = None


def lexicon():
    """The Flux dictionary: CSW21 minus the 419 words the client removed (SPEC 2.1)."""
    global _LEX
    if _LEX is None:
        words = {w.strip().upper() for w in open(WORDLIST) if w.strip()}
        removed = {w.strip().upper() for w in open(REMOVED) if w.strip()}
        _LEX = words - removed
    return _LEX


def ensure_build():
    os.makedirs(BUILD, exist_ok=True)
    return BUILD


def dump_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=_default)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(repr(o))

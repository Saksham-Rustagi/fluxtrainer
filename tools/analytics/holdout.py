"""Holdout bookkeeping: chronological 70/30 split inside seasons 7-10, with power.

A finding is validated by recomputing it on the test period. Each entry records the
train and test estimates, the test standard error (bootstrap over games), and the
minimum detectable effect at that n (80% power, two-sided 5%: 2.8 x SE). Verdicts:
  survives      same sign as train and significant on test (or, for descriptive
                'equal' findings, test within 1.96 SE of train)
  underpowered  not confirmed, and the train effect is smaller than the test MDE:
                the test period could not have confirmed it
  does not survive  not confirmed although the test period had the power to
"""
import numpy as np

from viz import RNG

B = 300


def _stat(num, den, gids):
    n = num.reindex(gids).fillna(0).values
    if den is None:
        return float(n.mean()) if len(n) else np.nan
    d = den.reindex(gids).fillna(0).values
    return float(n.sum() / d.sum()) if d.sum() else np.nan


def _se(num, den, gids):
    n = num.reindex(gids).fillna(0).values
    d = None if den is None else den.reindex(gids).fillna(0).values
    w = RNG.poisson(1.0, (B, len(n)))
    if d is None:
        v = (w @ n) / np.maximum(w.sum(axis=1), 1)
    else:
        v = (w @ n) / np.maximum(w @ d, 1e-12)
    return float(np.nanstd(v))


def record(R, name, train, test, se_test, unit, kind="sign", note="", pooled=False):
    mde = 2.8 * se_test if se_test is not None and np.isfinite(se_test) else np.nan
    if train is None or test is None or not np.isfinite(train) or not np.isfinite(test):
        verdict = "no finding to test"
    elif kind == "equal":
        verdict = "survives" if abs(test - train) < 1.96 * se_test * np.sqrt(2) else "does not survive"
    elif np.sign(train) == np.sign(test) and abs(test) > 1.96 * se_test:
        verdict = "survives"
    elif abs(train) < mde:
        verdict = "underpowered"
    else:
        verdict = "does not survive"
    R.setdefault("holdout", []).append({"finding": name, "train": train, "test": test, "seTest": se_test, "mde": mde,
                                        "unit": unit, "verdict": verdict, "survives": verdict == "survives",
                                        "note": note, "pooled": pooled})


def per_game(R, name, g, num, den=None, unit="", kind="sign", note=""):
    """num/den: per-game sums (Series indexed by gid). Statistic = mean(num) or sum(num)/sum(den)."""
    tr = g.gid[g.split == "train"].values
    te = g.gid[g.split == "test"].values
    record(R, name, _stat(num, den, tr), _stat(num, den, te), _se(num, den, te), unit, kind, note)


def by_fn(R, name, g, fn, unit="", kind="sign", note="", b=120):
    """fn(gids) -> float over any subset of games; SE by resampling test games."""
    tr = g.gid[g.split == "train"].values
    te = g.gid[g.split == "test"].values
    rng = np.random.default_rng(11)
    boots = [fn(te[rng.integers(0, len(te), len(te))]) for _ in range(b)]
    record(R, name, fn(tr), fn(te), float(np.nanstd(boots)), unit, kind, note)

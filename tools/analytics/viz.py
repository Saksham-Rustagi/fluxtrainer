"""Figure, TSV and bootstrap helpers for the analytics report.

Every figure is saved twice: as a PNG (embedded base64 in the HTML) and as the
TSV of exactly the numbers plotted, under reports/figures/<name>.tsv.
"""
import base64
import io
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import FIGS  # noqa: E402

# Reference palette (dataviz skill), first three categorical slots validate all-pairs.
PLAYER = "#2a78d6"
STRONG = "#eb6834"
WEAK = "#1baf7a"
OPP = "#8a8984"
PEER = "#4a3aa7"  # the other player's own series
EXTRA = ["#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
SEQ = "Blues"
DIV = "RdBu_r"

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 110, "font.size": 9.5, "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "lines.linewidth": 2, "legend.frameon": False, "legend.fontsize": 8.5, "figure.facecolor": "white",
    "axes.facecolor": "white",
})

FIGURES = {}
RNG = np.random.default_rng(20260918)
B = 400


def save(fig, name, data, caption=""):
    os.makedirs(FIGS, exist_ok=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    FIGURES[name] = {"png": base64.b64encode(buf.getvalue()).decode(), "caption": caption}
    if isinstance(data, dict):
        data = pd.concat([d.assign(block=k) for k, d in data.items()], ignore_index=True)
    data.to_csv(os.path.join(FIGS, name + ".tsv"), sep="\t", index=False, float_format="%.6g")


def poisson_w(n, b=B):
    return RNG.poisson(1.0, (b, n)).astype(np.float32)


def boot_mean(values, b=B):
    """Mean and 95% percentile band by Poisson bootstrap."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return np.nan, np.nan, np.nan, 0
    w = poisson_w(len(v), b)
    m = (w @ v) / np.maximum(w.sum(axis=1), 1)
    return v.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5), len(v)


def boot_by(df, by, col, b=B):
    rows = []
    for k, x in df.groupby(by, observed=True):
        m, lo, hi, n = boot_mean(x[col].values, b)
        rows.append({by if isinstance(by, str) else "key": k, "mean": m, "lo": lo, "hi": hi, "n": n})
    return pd.DataFrame(rows)


def boot_ratio_clustered(df, cluster, bucket, num, den=None, b=B):
    """Ratio of sums per bucket with a bootstrap clustered on `cluster` (e.g. game).

    With den None it is the mean of `num` per bucket, still resampling whole clusters,
    which is the right unit for find-level curves: finds within a game are not independent.
    """
    d = df[[cluster, bucket, num] + ([den] if den else [])].copy()
    if den is None:
        d["_den"] = 1.0
        den = "_den"
    s = d.pivot_table(index=cluster, columns=bucket, values=num, aggfunc="sum", fill_value=0, observed=True)
    c = d.pivot_table(index=cluster, columns=bucket, values=den, aggfunc="sum", fill_value=0, observed=True)
    w = poisson_w(len(s), b)
    S = w @ s.values.astype(np.float32)
    C = w @ c.values.astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = S / C
    est = s.values.sum(axis=0) / c.values.sum(axis=0)
    return pd.DataFrame({bucket: s.columns, "mean": est, "lo": np.nanpercentile(r, 2.5, axis=0),
                         "hi": np.nanpercentile(r, 97.5, axis=0), "n": c.values.sum(axis=0),
                         "clusters": (c.values > 0).sum(axis=0)})


def band(ax, x, t, color, label, ls="-", marker=None):
    ax.fill_between(x, t["lo"], t["hi"], color=color, alpha=0.18, linewidth=0)
    ax.plot(x, t["mean"], color=color, label=label, ls=ls, marker=marker, markersize=4)


def note_n(ax, text):
    ax.text(0.99, 0.02, text, transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK2)


def bh(p):
    """Benjamini-Hochberg adjusted p-values."""
    p = np.nan_to_num(np.asarray(p, dtype=float), nan=1.0)  # untestable (zero-variance) cells count as p = 1
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(adj, 1)
    return out


def regime_line(ax, x, label=True):
    """Mark the board-generation regime break (season 7) on a time-series axis."""
    ax.axvline(x, color="#e34948", lw=1.2, ls="--", zorder=0)
    if label:
        ax.text(x, 0.98, " season 7: current rules", transform=ax.get_xaxis_transform(), color="#e34948",
                fontsize=7, va="top", ha="left")


def month_break(months):
    """x position (between categorical month ticks) where the current regime starts."""
    months = list(months)
    for i, m in enumerate(months):
        if m >= "2026-06":
            return i - 0.5
    return len(months) - 0.5

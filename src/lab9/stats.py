"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _pair(human: Sequence[str], judge: Sequence[str]) -> list[tuple[str, str]]:
    if len(human) != len(judge):
        raise ValueError(f"human/judge length mismatch: {len(human)} != {len(judge)}")
    return [(str(h).strip().upper(), str(j).strip().upper()) for h, j in zip(human, judge)]


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    cm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for h, j in _pair(human, judge):
        if h == POS and j == POS:
            cm["tp"] += 1
        elif h != POS and j == POS:
            cm["fp"] += 1
        elif h == POS and j != POS:
            cm["fn"] += 1
        else:
            cm["tn"] += 1
    return cm


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    # precision = tp/(tp+fp), recall = tp/(tp+fn); 0.0 when the denominator is 0
    cm = confusion(human, judge)
    p_den, r_den = cm["tp"] + cm["fp"], cm["tp"] + cm["fn"]
    return (cm["tp"] / p_den if p_den else 0.0, cm["tp"] / r_den if r_den else 0.0)


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    pairs = _pair(human, judge)
    n = len(pairs)
    if n == 0:
        raise ValueError("cohen_kappa needs at least one pair")
    cm = confusion(*zip(*pairs))
    p_o = (cm["tp"] + cm["tn"]) / n
    h_pos = (cm["tp"] + cm["fn"]) / n
    j_pos = (cm["tp"] + cm["fp"]) / n
    p_e = h_pos * j_pos + (1 - h_pos) * (1 - j_pos)
    if p_e >= 1.0:
        raise ValueError("kappa undefined: p_e == 1 (a constant judge carries no signal)")
    return (p_o - p_e) / (1 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    denom = sensitivity + specificity - 1
    if denom == 0:
        raise ValueError("rogan_gladen undefined: sensitivity + specificity == 1")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / denom))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError(f"paired_bootstrap needs the same items: {a_arr.shape} != {b_arr.shape}")
    if a_arr.size == 0:
        return (0.0, 0.0, 0.0)
    if np.array_equal(a_arr, b_arr):
        return (0.0, 0.0, 0.0)
    diff = float(a_arr.mean() - b_arr.mean())
    res = bootstrap(
        (a_arr, b_arr),
        statistic=lambda x, y: np.mean(x) - np.mean(y),
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        paired=True,
        rng=np.random.default_rng(rng),
    )
    ci = res.confidence_interval
    return (diff, float(ci.low), float(ci.high))


def _comb_trials(n: int, c: int, k: int) -> None:
    """Validate (n, c, k) for the pass@k / pass^k estimators."""
    for name, value in (("n", n), ("c", c), ("k", k)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an int, got {value!r}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if k < 1 or k > n:
        raise ValueError(f"k must satisfy 1 <= k <= n, got k={k}, n={n}")
    if c < 0 or c > n:
        raise ValueError(f"c must satisfy 0 <= c <= n, got c={c}, n={n}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _comb_trials(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _comb_trials(n, c, k)
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)

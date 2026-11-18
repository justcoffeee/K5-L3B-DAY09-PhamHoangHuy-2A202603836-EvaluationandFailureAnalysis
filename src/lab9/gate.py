"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def _threshold_text(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in ("name", "metric")}


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _ratchet_metric(base: dict, cur: dict, problems: list[str]) -> None:
    """A metric threshold may only get tighter on the same eval-set version."""
    mid = base["id"]
    bt, ct = base.get("threshold") or {}, cur.get("threshold") or {}
    if base.get("blocking") and not cur.get("blocking"):
        problems.append(f"{mid}: blocking=false but it was blocking on main (ratchet)")
    for key, worse in (("max", lambda a, b: a > b), ("max_increase", lambda a, b: a > b),
                       ("min", lambda a, b: a < b)):
        if key not in bt:
            continue
        if key not in ct:
            problems.append(f"{mid}: {key} threshold removed (ratchet)")
        elif worse(ct[key], bt[key]):
            problems.append(f"{mid}: {key} {ct[key]} loosens main's {bt[key]} (ratchet)")
    if bt.get("no_significant_drop") and not ct.get("no_significant_drop"):
        problems.append(f"{mid}: no_significant_drop dropped (ratchet)")


def _ratchet_slice(base: dict, cur: dict, problems: list[str]) -> None:
    name = base.get("name")
    if base.get("blocking") and not cur.get("blocking"):
        problems.append(f"slice {name}: blocking=false but it was blocking on main (ratchet)")
    if "min" in base:
        if "min" not in cur:
            problems.append(f"slice {name}: min threshold removed (ratchet)")
        elif cur["min"] < base["min"]:
            problems.append(f"slice {name}: min {cur['min']} loosens main's {base['min']} (ratchet)")
    if base.get("no_significant_drop") and not cur.get("no_significant_drop"):
        problems.append(f"slice {name}: no_significant_drop dropped (ratchet)")


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. A metric that is not a finite number (NaN < min is False: a naive gate lets it through).
    for mid, val in (pr.get("metrics") or {}).items():
        if isinstance(val, float) and not math.isfinite(val):
            problems.append(f"metrics[{mid}] = {val!r} is not finite")

    # 2. The report must contain the full grid the baseline ran.
    want = int(bm.get("items") or 0) * len(bm.get("seeds") or [])
    if want and len(rows) != want:
        problems.append(f"{len(rows)} row(s), want {want} (items x seeds): dropped or duplicated rows")
    if pm and bm and (pm.get("items") != bm.get("items") or list(pm.get("seeds") or []) != list(bm.get("seeds") or [])):
        problems.append(f"manifest grid {pm.get('items')}x{pm.get('seeds')} != baseline "
                        f"{bm.get('items')}x{bm.get('seeds')} (cherry-picked items/seeds)")

    # 3. Same (item, seed) population as main: no silently dropped or swapped trials.
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    pr_keys = {(r.get("item_id"), r.get("seed")) for r in rows}
    missing = sorted(base_keys - pr_keys)
    extra = sorted(pr_keys - base_keys)
    if missing:
        problems.append(f"{len(missing)} baseline (item, seed) missing from PR, e.g. {missing[:3]}")
    if extra:
        problems.append(f"{len(extra)} (item, seed) in PR not in baseline, e.g. {extra[:3]}")

    # 4. A grader that crashed must not be reported as a green run.
    failures = pr.get("evaluator_failures") or []
    if failures:
        problems.append(f"{len(failures)} evaluator failure(s), e.g. {failures[0]}")

    # 5. A graded spec metric may not be None in any row: None drops out of the mean.
    present = {k for r in rows[:1] for k in r}
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in present]
    for mid in graded:
        bad = sum(1 for r in rows if r.get(mid) is None)
        if bad:
            problems.append(f"{bad} row(s) have {mid}=null (a crashed grader silently disappears)")

    # 6. Ratchet: same eval-set version => only stricter thresholds.
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        sm = {m["id"]: m for m in spec.get("metrics") or []}
        for b in base_spec.get("metrics") or []:
            if b["id"] not in sm:
                problems.append(f"metric {b['id']} removed (ratchet)")
            else:
                _ratchet_metric(b, sm[b["id"]], problems)
        ss = {s.get("name"): s for s in spec.get("slices") or []}
        for b in base_spec.get("slices") or []:
            if b.get("name") not in ss:
                problems.append(f"slice {b.get('name')} removed (ratchet)")
            else:
                _ratchet_slice(b, ss[b["name"]], problems)

    # 7. Slice tags are part of the label: they may not be edited in the report.
    base_slices: dict[str, list[str]] = {}
    for r in base_rows:
        base_slices.setdefault(r.get("item_id"), sorted(r.get("slices") or []))
    pr_slices: dict[str, list[str]] = {}
    for r in rows:
        pr_slices.setdefault(r.get("item_id"), sorted(r.get("slices") or []))
    for iid in sorted(set(base_slices) & set(pr_slices)):
        if pr_slices[iid] != base_slices[iid]:
            problems.append(f"{iid}: slice tags {pr_slices[iid]} != baseline {base_slices[iid]} "
                            f"(moved out of a slice)")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl.get("name"), sl.get("metric")
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        keys = sorted(set(a) & set(b))
        val = sum(a[k] for k in keys) / len(keys) if keys else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and keys:
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000),
                                               rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        sid = f"slice:{name}/{metric}"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<30} {_fmt(val):<8} {json.dumps(_threshold_text(sl)):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

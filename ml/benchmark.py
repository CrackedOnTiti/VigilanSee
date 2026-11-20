# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas==3.1.1", "numpy==2.5.5"]
# ///
"""The ML benchmark: every evaluation we have, for every profile configuration, in one table (issue #32).

Rows (--only):
  lomo       leave-one-match-out, strict: the query's match leaves every profile, z-scoring and prior
  chrono     chronological, past: all maps: every profile built only from maps played before the query
  xteam      cross-team, strict: the true player's profile from his maps with another team only
  teammate   teammate impostor (issue #33): placeholder, not implemented yet
  zhang-a    Zhang Test A: one map against one map, no profile (the same for every configuration)
  zhang-b    Zhang Test B, K = 1, 3, 5: his mean-LLR (the same for every configuration) and our profile

Configurations (--configs): how a candidate's profile is built.
  global     one profile from all his maps (evaluate.py without --context-k)
  k2         per-map profile, the global one pulled toward his maps on the query's map with w = n / (n + 2)
  straub     per-map profile, one k per feature from the exact Bühlmann-Straub estimator

Metrics: AUC, detect@5% (impostors flagged at 5% false alarms) and, for Zhang's tests, AP. Every value
comes with its 95% bootstrap interval: clusters of query players and of query matches for the first three
rows (metrics.cluster_bootstrap), identity clusters for Zhang's tests (zhang.measure).

Usage (repo root): uv run ml/benchmark.py [features] [--configs global,k2,straub] [--only lomo,...]
                                          [--fast] [--seed 0] [--ci player|match]
Writes experiments/benchmark/results/<date>_<features>.csv (one row per evaluation x configuration x
metric) and a .json with the run settings next to it.
"""
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from functools import cache
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate as ev
import zhang
from metrics import FALSE_ALARMS, auc, cluster_bootstrap, detection_at, split_scores

OUT = Path("experiments/benchmark/results")
RESAMPLES, FAST_RESAMPLES = 1000, 200
SEED = 0
WORKERS = min(8, os.cpu_count() or 1)
CONFIGS: dict[str, ev.Context | None] = {
    "global": None, "k2": ev.Context(2.0), "straub": ev.Context(ev.buhlmann_straub_k)}
ANY = "any"  # config of a row that doesn't depend on the profile (Zhang Test A, mean-LLR)
METRIC_NAMES = {"auc": "AUC", "detect": f"detect@{FALSE_ALARMS:.0%}", "ap": "AP"}


@dataclass(frozen=True)
class Settings:
    features: str
    seed: int
    resamples: int


class Data:
    """One feature set, loaded and standardised the way evaluate.py's main does."""

    def __init__(self, features: str):
        self.features, self.match_of, self.who = ev.load_fingerprints(features.split(","))
        self.z = ev.standardise(self.features)
        self.features = self.features.loc[:, self.z.columns]
        self.days = self.who["played_on"].to_numpy(dtype="datetime64[D]")


@cache
def data_of(features: str) -> Data:
    return Data(features)


def verification(evaluation: str, config: str, results: list, data: Data, s: Settings) -> list[dict]:
    """AUC and detect@5% of evaluate.py trials, with 95% intervals over query players and query matches."""
    genuine, impostor = split_scores(results)
    point = {"auc": auc(genuine, impostor), "detect": detection_at(genuine, impostor)}
    units = {"player": [player for player, _ in results],
             "match": [data.match_of[d.name] for _, d in results]}
    intervals = {unit: np.percentile(cluster_bootstrap(results, of, s.resamples, s.seed), [2.5, 97.5], axis=0)
                 for unit, of in units.items()}
    column = {"auc": 0, "ap": 1, "detect": 2}  # cluster_bootstrap's columns
    return [{"evaluation": evaluation, "config": config, "metric": metric, "value": value,
             **{f"{unit}_{side}": bounds[i, column[metric]]
                for unit, bounds in intervals.items() for i, side in enumerate(("lo", "hi"))},
             "queries": len(results), "players": len(set(units["player"]))}
            for metric, value in point.items()]


def lomo(data: Data, context: ev.Context | None) -> list:
    return ev.held_out_trials(data.features, data.match_of, ev.other_matches(data.z, data.match_of),
                              ev.DEFAULT_SCORING, context)


def chrono(data: Data, context: ev.Context | None) -> list:
    pick = ev.maps_between(data.features, data.days, 1, ev.TIME_GAPS["> 90"][1])
    return ev.past_trials(data.features, data.days, pick, ev.DEFAULT_SCORING, context)


def xteam(data: Data, context: ev.Context | None) -> list:
    return ev.held_out_trials(data.features, data.match_of, ev.other_team(data.z, data.who),
                              ev.DEFAULT_SCORING, context)


@dataclass(frozen=True)
class Row:
    """One evaluation of the table. `trials`: evaluate.py trials per configuration; None for the Zhang rows
    (run together, see zhang_rows) and for a placeholder."""
    label: str
    trials: Callable[[Data, ev.Context | None], list] | None = None
    pending: str | None = None  # why the row is empty


ROWS = {
    "lomo": Row("Leave-one-match-out, strict", lomo),
    "chrono": Row("Chronological (past: all maps)", chrono),
    "xteam": Row("Cross-team, strict", xteam),
    "teammate": Row("Teammate impostor", pending="issue #33"),
    "zhang-a": Row("Zhang Test A (pairwise, no profile)"),
    "zhang-b": Row("Zhang Test B"),
}


def trial_task(task: tuple[str, str, Settings]) -> tuple[list[dict], float]:
    """One evaluate.py row under one configuration (runs in a worker)."""
    key, config, s = task
    start, data = time.perf_counter(), data_of(s.features)
    results = ROWS[key].trials(data, CONFIGS[config])
    return verification(ROWS[key].label, config, results, data, s), time.perf_counter() - start


def zhang_record(evaluation: str, config: str, table: pd.DataFrame, reps: np.ndarray) -> list[dict]:
    mean = zhang.rows_of({}, table, reps)[-1]
    return [{"evaluation": evaluation, "config": config, "metric": metric, "value": mean[metric],
             "player_lo": mean[f"{metric}_lo"], "player_hi": mean[f"{metric}_hi"],
             "positives": mean["pos"], "negatives": mean["neg"]}
            for metric in zhang.METRICS]


def zhang_task(task: tuple[tuple[str, ...], tuple[str, ...], Settings]) -> tuple[list[dict], float]:
    """Zhang's tests A and B on one fold partition (seed), for the asked configurations."""
    keys, configs, s = task
    start = time.perf_counter()
    run = zhang.Protocol.build(s.seed, names=(s.features,))
    fits: dict = {}
    scored = zhang.scored_pairs(run, s.features, fits, ev.buhlmann_straub_k)
    records = []
    if "zhang-a" in keys:
        parts = {fold: (similarity, kept["same"].to_numpy(), run.data.player[kept["a"].to_numpy()],
                        run.data.player[kept["b"].to_numpy()]) for fold, (kept, similarity) in scored.items()}
        records += zhang_record(ROWS["zhang-a"].label, ANY, *zhang.measure(parts, run.pair_draws(s.seed,
                                                                                               s.resamples)))
    if "zhang-b" in keys:
        draws = run.group_draws(s.seed, s.resamples)
        k2 = {key: replace(fit, k=np.full(len(fit.k), CONFIGS["k2"].k)) for key, fit in fits.items()}
        for k in zhang.HISTORIES:
            label = f"{ROWS['zhang-b'].label}, K = {k}"
            parts = zhang.history_parts(run, fits, s.features, k)
            records += zhang_record(f"{label}, mean-LLR", ANY, *zhang.measure(parts["mean-LLR"], draws))
            per_config = {"global": parts["profile global"], "straub": parts["profile per-map"]}
            if "k2" in configs:
                per_config["k2"] = zhang.history_parts(run, k2, s.features, k)["profile per-map"]
            for config in configs:
                records += zhang_record(f"{label}, our profile", config,
                                        *zhang.measure(per_config[config], draws))
    return records, time.perf_counter() - start


def cell(record: pd.Series | None, unit: str) -> str:
    if record is None:
        return ""
    value, lo, hi = record["value"], record.get(f"{unit}_lo"), record.get(f"{unit}_hi")
    if pd.isna(lo):  # Zhang rows have no match clusters: fall back on players
        lo, hi = record["player_lo"], record["player_hi"]
    if record["metric"] == "detect":
        return f"{value:.1%} ({lo:.1%}-{hi:.1%})"
    digits = 4 if record["metric"] == "auc" else 3
    return f"{value:.{digits}f} ({lo:.{digits}f}-{hi:.{digits}f})"


def table(records: pd.DataFrame, keys: list[str], configs: list[str], unit: str) -> str:
    """Rows = evaluation and metric, columns = configuration. A row that doesn't depend on the profile is
    shown once, in the first column."""
    lines = []
    for key in keys:
        if ROWS[key].pending:
            lines.append({"evaluation": ROWS[key].label, "metric": "",
                          **{c: f"pending ({ROWS[key].pending})" for c in configs}})
            continue
        prefix = ROWS[key].label
        own = records[records["evaluation"].str.startswith(prefix)]
        for evaluation in own["evaluation"].unique():
            rows = own[own["evaluation"] == evaluation]
            for metric, shown in METRIC_NAMES.items():
                found = rows[rows["metric"] == metric]
                if found.empty:
                    continue
                line = {"evaluation": evaluation, "metric": shown}
                for i, config in enumerate(configs):
                    match = found[found["config"].isin([config] if i else [config, ANY])]
                    line[config] = cell(match.iloc[0] if len(match) else None, unit)
                lines.append(line)
    frame = pd.DataFrame(lines)
    widths = {c: max(len(c), frame[c].str.len().max()) for c in frame.columns}
    return "\n".join("  ".join(str(v).ljust(widths[c]) for c, v in row.items()).rstrip()
                     for row in [dict(zip(frame.columns, frame.columns, strict=True)),
                                 *frame.to_dict("records")])


def git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return git("rev-parse", "HEAD") + (" (uncommitted changes)" if dirty else "")


def main() -> None:
    cli = ev.vectors_cli("The ML benchmark: every evaluation, every profile configuration, one table.")
    cli.add_argument("--configs", default=",".join(CONFIGS), type=lambda s: s.split(","),
                     help="comma-separated, among %(default)s")
    cli.add_argument("--only", type=lambda s: s.split(","), help=f"rows to run, among {','.join(ROWS)}")
    cli.add_argument("--fast", action="store_true",
                     help=f"{FAST_RESAMPLES} bootstrap resamples instead of {RESAMPLES}")
    cli.add_argument("--seed", type=int, default=SEED, help="folds and bootstrap (default: %(default)s)")
    cli.add_argument("--ci", choices=["player", "match"], default="player",
                     help="interval shown in the table (both are in the CSV; Zhang rows: players only)")
    args = cli.parse_args()
    keys, configs = args.only or list(ROWS), args.configs
    for name, chosen, known in (("row", keys, ROWS), ("config", configs, CONFIGS)):
        if unknown := [c for c in chosen if c not in known]:
            cli.error(f"unknown {name}: {', '.join(unknown)} (known: {', '.join(known)})")
    features = ",".join(args.vectors)
    s = Settings(features, args.seed, FAST_RESAMPLES if args.fast else RESAMPLES)

    start = time.perf_counter()
    tasks = [(key, config, s) for key in keys if ROWS[key].trials for config in configs]
    zhang_keys = tuple(k for k in keys if k.startswith("zhang"))
    records, timings = [], {}
    with ProcessPoolExecutor(WORKERS) as pool:
        zhang_future = pool.submit(zhang_task, (zhang_keys, tuple(configs), s)) if zhang_keys else None
        for (key, config, _), (found, seconds) in zip(tasks, pool.map(trial_task, tasks), strict=True):
            records += found
            timings[f"{key}/{config}"] = round(seconds, 1)
            print(f"  {key}/{config}: {seconds:.0f}s", file=sys.stderr, flush=True)
        if zhang_future:
            found, seconds = zhang_future.result()
            records += found
            timings["zhang"] = round(seconds, 1)
            print(f"  zhang: {seconds:.0f}s", file=sys.stderr, flush=True)
    elapsed = time.perf_counter() - start

    frame = pd.DataFrame(records)
    print(f"\nBenchmark: {features}, {s.resamples} bootstrap resamples, seed {s.seed}, "
          f"95% intervals over {args.ci}s\n")
    print(table(frame, keys, configs, args.ci))
    print(f"\n'{ANY}' rows don't depend on the profile and are shown in the first column only. "
          f"Run time: {elapsed / 60:.1f} min.")

    today = dt.date.today().isoformat()
    name = f"{today}_{features.replace(',', '+')}"
    name += "_fast" if args.fast else ""
    name += f"_only-{'+'.join(keys)}" if args.only else ""
    OUT.mkdir(parents=True, exist_ok=True)
    frame.insert(0, "features", features)
    counts = [c for c in ("queries", "players", "positives", "negatives") if c in frame]
    frame[counts] = frame[counts].astype("Int64")
    frame.round(6).to_csv(OUT / f"{name}.csv", index=False)
    run = {"date": today, "features": features, "configs": configs, "rows": keys,
           "pending_rows": {k: ROWS[k].pending for k in keys if ROWS[k].pending},
           "seed": s.seed, "bootstrap_resamples": s.resamples, "fast": args.fast,
           "zhang_folds": zhang.FOLDS, "git_commit": git_commit(),
           "python": platform.python_version(), "numpy": version("numpy"), "pandas": version("pandas"),
           "runtime_s": round(elapsed, 1), "task_runtime_s": timings}
    (OUT / f"{name}.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"Written: {OUT / name}.csv and .json")


if __name__ == "__main__":
    main()

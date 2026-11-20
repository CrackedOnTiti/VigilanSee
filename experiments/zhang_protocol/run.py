# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas==3.1.1", "numpy==2.5.5"]
# ///
"""Zhang (2026) evaluation protocol on our fingerprints: our features and scores, his folds and pairs.

Usage (repo root): uv run experiments/zhang_protocol/run.py
Writes results.csv, slices.csv, history.csv, counts.csv, paired.csv, aim.csv and partitions.csv next to
this file. The protocol itself (folds, pairs, cohorts, fits, bootstrap) lives in ml/zhang.py, shared with
ml/benchmark.py; this file adds the slices, aim, counts, paired differences and other partitions.

Six folds split by identity. Everything fitted (z-scoring, pooled variance, Bühlmann-Straub k, LLR bins)
comes from the fold's training identities only. Test A: one observation against one observation. Test B:
one query against K earlier observations of one identity, on one cohort fixed at K = 5. The higher a
`similarity`, the more likely the same player: pair scores and profile scores are negated distances.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
import evaluate as ev  # noqa: E402
from metrics import Ranked, auc, detection_at  # noqa: E402
from zhang import (  # noqa: E402
    AIM_SET, FULL_SET, HISTORIES, MAIN_SET, METRICS, SEED, Observations, Part, Protocol,
    history_parts, measure, pair_kept, rows_of, scored_pairs)

OUT = Path(__file__).parent
OTHER_PARTITIONS = [1, 2, 3, 4, 5]  # fold seeds of the sensitivity check
RESAMPLES = 1000
GAPS = {"same day": (0, 0), "1-7 days": (1, 7), "8-30 days": (8, 30), ">=31 days": (31, 10_000)}


def check_metrics() -> None:
    """Ranked against metrics.py: plain, with ties, and with repeated pairs."""
    rng = np.random.default_rng(SEED)
    score = rng.integers(0, 40, 600).astype(float)
    same = rng.random(600) < 0.2 + 0.01 * score
    weights = rng.integers(0, 4, 600)
    for w in (np.ones(600), weights.astype(float)):
        got = Ranked(score, same).metrics(w)
        distance, repeat = np.repeat(-score, w.astype(int)), np.repeat(same, w.astype(int))
        genuine, impostor = distance[repeat], distance[~repeat]
        assert np.isclose(got[0], auc(genuine, impostor))
        assert np.isclose(got[2], detection_at(genuine, impostor))


def delta_row(test: str, what: str, against: str, first: tuple, second: tuple) -> dict:
    """Paired difference of two scores on the same resamples: `first` minus `second`."""
    (table_a, reps_a), (table_b, reps_b) = first, second
    row = {"test": test, "config": what, "against": against}
    low, high = np.percentile(reps_a - reps_b, [2.5, 97.5], axis=0)
    for i, metric in enumerate(METRICS):
        row |= {metric: table_a[metric].mean() - table_b[metric].mean(),
                f"{metric}_lo": low[i], f"{metric}_hi": high[i]}
    return row


def pair_slices(data: Observations, a: np.ndarray, b: np.ndarray, same: np.ndarray,
                same_demo: np.ndarray) -> dict[str, np.ndarray]:
    """Mask of each slice. A gap or map slice restricts positives and negatives alike."""
    gap = np.abs((data.day[a] - data.day[b]).astype(int))
    same_map = data.map[a] == data.map[b]
    masks = {"all pairs": np.ones(len(a), dtype=bool), "same-map": same_map, "cross-map": ~same_map}
    masks |= {name: (gap >= lo) & (gap <= hi) for name, (lo, hi) in GAPS.items()}
    return masks | {"excluding same-demo negatives": same | ~same_demo}


def aim_table(raw: pd.DataFrame, pairs: dict[int, pd.DataFrame], fits: dict) -> pd.DataFrame:
    """Each aim feature alone on Test A, with its missing and zero shares."""
    usable = raw.notna().any(axis=1).to_numpy()
    table = []
    for name in raw.columns:
        values = []
        for fold, pair in pairs.items():
            kept, fit = pair_kept(pair, usable), fits[AIM_SET, fold]
            z = fit.z[:, fit.columns.get_loc(name)]
            gap, same = np.abs(z[kept["a"]] - z[kept["b"]]), kept["same"].to_numpy()
            values.append(auc(gap[same], gap[~same]))
        table.append({"feature": name, "missing_rows": int(raw[name].isna().sum()),
                      "zero_share": float((raw[name][usable] == 0).mean()),
                      "auc_alone": float(np.mean(values))})
    return pd.DataFrame(table)


def counts_table(data: Observations, pairs: dict, lost: dict, groups: dict) -> pd.DataFrame:
    table = []
    for fold, pair in pairs.items():
        a, b = pair["a"].to_numpy(), pair["b"].to_numpy()
        rows = data.fold == fold
        cohort = groups[fold]
        table.append({
            "fold": fold, "players": len(np.unique(data.player[rows])), "observations": int(rows.sum()),
            "pos": int(pair["same"].sum()), "neg": int((~pair["same"]).sum()),
            "same_demo_neg": int(pair["same_demo"].sum()),
            "same_map": int((data.map[a] == data.map[b]).sum()),
            "cross_map": int((data.map[a] != data.map[b]).sum()),
            "cohort_queries": int(cohort["same"].sum()) if len(cohort) else 0,
            "cohort_players": int(cohort.loc[cohort["same"], "identity"].nunique()) if len(cohort) else 0,
            "queries_lost": lost[fold]})
    return pd.DataFrame(table)


def test_a(run: Protocol, fits: dict, draws: dict[int, np.ndarray], straub) -> tuple[list, list, list]:
    """Pairwise surface of every feature set: fills `fits`; returns result, slice and paired rows."""
    data, results, slices, surfaces = run.data, [], [], {}
    for name in run.sets:
        parts: dict[str, dict[int, Part]] = {}
        for fold, (kept, similarity) in scored_pairs(run, name, fits, straub).items():
            a, b = kept["a"].to_numpy(), kept["b"].to_numpy()
            same, same_demo = kept["same"].to_numpy(), kept["same_demo"].to_numpy()
            for slice_name, mask in pair_slices(data, a, b, same, same_demo).items():
                if same[mask].any() and (~same[mask]).any():
                    parts.setdefault(slice_name, {})[fold] = (
                        similarity[mask], same[mask], data.player[a][mask], data.player[b][mask])
        for slice_name, slice_parts in parts.items():
            table, reps = measure(slice_parts, draws)
            slices += rows_of({"test": "A", "vectors": name, "slice": slice_name}, table, reps)
            if slice_name == "all pairs":
                surfaces[name] = table, reps
                results += rows_of({"test": "A", "vectors": name}, table, reps)
    paired = [delta_row("A", other, MAIN_SET, surfaces[other], surfaces[MAIN_SET])
              for other in (FULL_SET, AIM_SET)]
    return results, slices, paired


def test_b(run: Protocol, fits: dict, draws: dict[int, np.ndarray]) -> tuple[list, list]:
    """History aggregation: returns history and paired rows."""
    history, paired, measured = [], [], {}
    for name in (MAIN_SET, FULL_SET):
        for k in HISTORIES:
            for method, parts in history_parts(run, fits, name, k).items():
                measured[name, k, method] = measure(parts, draws)
                history += rows_of({"test": "B", "vectors": name, "k": k, "method": method},
                                   *measured[name, k, method])
            for method in ("mean-LLR", "profile per-map"):
                paired.append(delta_row(f"B K={k} {name}", method, "profile global",
                                        measured[name, k, method], measured[name, k, "profile global"]))
    for k in HISTORIES:
        paired.append(delta_row(f"B K={k} profile per-map", FULL_SET, MAIN_SET,
                                measured[FULL_SET, k, "profile per-map"],
                                measured[MAIN_SET, k, "profile per-map"]))
    return history, paired


def evaluate(run: Protocol, seed: int, resamples: int, straub) -> dict[str, pd.DataFrame]:
    """The whole protocol on one fold partition."""
    data, fits = run.data, {}
    pair_draws, group_draws = run.pair_draws(seed, resamples), run.group_draws(seed, resamples)
    results, slices, paired = test_a(run, fits, pair_draws, straub)
    history, history_paired = test_b(run, fits, group_draws)
    return {"results": pd.DataFrame(results), "slices": pd.DataFrame(slices),
            "history": pd.DataFrame(history), "paired": pd.DataFrame(paired + history_paired),
            "counts": counts_table(data, run.test_pairs, run.lost, run.cohorts),
            "aim": aim_table(run.sets[AIM_SET], run.test_pairs, fits)}


def partition_row(seed: int, tables: dict[str, pd.DataFrame]) -> list[dict]:
    """The headline means of one fold partition."""
    a, b = tables["results"], tables["history"]
    rows = [{"seed": seed, "test": "A", "vectors": r["vectors"], "auc": r["auc"], "ap": r["ap"]}
            for r in a[a["fold"] == "mean"].to_dict("records")]
    return rows + [{"seed": seed, "test": f"B K={r['k']} {r['method']}", "vectors": r["vectors"],
                    "auc": r["auc"], "ap": r["ap"]} for r in b[b["fold"] == "mean"].to_dict("records")]


def main() -> None:
    check_metrics()
    straub = ev.buhlmann_straub_k
    tables = evaluate(Protocol.build(SEED), SEED, RESAMPLES, straub)
    for file, table in tables.items():
        table.round(4).to_csv(OUT / f"{file}.csv", index=False)
    partitions = partition_row(SEED, tables)
    for seed in OTHER_PARTITIONS:
        partitions += partition_row(seed, evaluate(Protocol.build(seed), seed, 1, straub))
    pd.DataFrame(partitions).round(4).to_csv(OUT / "partitions.csv", index=False)
    print(tables["counts"].to_string(index=False), "\n")
    for name in ("results", "history"):
        means = tables[name][tables[name]["fold"] == "mean"].drop(columns=["test", "fold"])
        print(means.round(3).to_string(index=False), "\n")


if __name__ == "__main__":
    main()

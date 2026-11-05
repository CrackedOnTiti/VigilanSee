# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas", "numpy"]
# ///
"""Zhang (2026) evaluation protocol on our fingerprints: our features and scores, his folds and pairs.

Usage (repo root): uv run experiments/zhang_protocol/run.py
Writes results.csv, slices.csv, history.csv, counts.csv, paired.csv, aim.csv and partitions.csv next to
this file.

Six folds split by identity. Everything fitted (z-scoring, pooled variance, Bühlmann-Straub k, LLR bins)
comes from the fold's training identities only. Test A: one observation against one observation. Test B:
one query against K earlier observations of one identity, on one cohort fixed at K = 5. The higher a
`similarity`, the more likely the same player: pair scores and profile scores are negated distances.
"""
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
import evaluate as ev  # noqa: E402
from metrics import FALSE_ALARMS, auc, detection_at  # noqa: E402

OUT = Path(__file__).parent
SEED = 0
OTHER_PARTITIONS = [1, 2, 3, 4, 5]  # fold seeds of the sensitivity check
FOLDS = 6
RESAMPLES = 1000
NEGATIVES_PER_POSITIVE = 9
SAME_DEMO_SHARE = 0.25  # his same-rank 25% moves to random: we have no rank
BINS = 20
ALPHA = 1.0
HISTORIES = [1, 3, 5]
COHORT_K = max(HISTORIES)
NEGATIVE_GROUPS = 4
MAIN_SET, FULL_SET, AIM_SET = "habits,buy", "habits,buy,aim,strafe", "aim"
METHODS = ["mean-LLR", "profile global", "profile per-map"]
METRICS = ["auc", "ap", "detect"]
GAPS = {"same day": (0, 0), "1-7 days": (1, 7), "8-30 days": (8, 30), ">=31 days": (31, 10_000)}


def load_straub():
    """buhlmann_straub_k lives in the shrinkage experiment, whose run.py shares this file's module name."""
    spec = importlib.util.spec_from_file_location("shrinkage_run", ROOT / "experiments/shrinkage_k/run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.buhlmann_straub_k


class Ranked:
    """One set of scored pairs, sorted once so that each bootstrap weighting is a linear pass."""

    def __init__(self, similarity: np.ndarray, same: np.ndarray):
        self.order = np.argsort(-similarity, kind="stable")
        self.similarity, self.same = similarity[self.order], same[self.order]
        self.starts = np.flatnonzero(np.r_[True, self.similarity[1:] != self.similarity[:-1]])

    def metrics(self, weights: np.ndarray) -> tuple[float, float, float]:
        """AUC (ties count half), AP (one step per distinct score), detect@5%. Integer weights give what
        metrics.py would on the pairs repeated that many times."""
        w = weights[self.order]
        positive = np.add.reduceat(w * self.same, self.starts)
        negative = np.add.reduceat(w * ~self.same, self.starts)
        p, n = positive.sum(), negative.sum()
        if p == 0 or n == 0:
            return np.nan, np.nan, np.nan
        tp, fp = np.cumsum(positive), np.cumsum(negative)
        area = (negative * (tp - positive / 2)).sum() / (p * n)
        hit = positive > 0
        precision = (positive[hit] * tp[hit] / (tp[hit] + fp[hit])).sum() / p
        return area, precision, self.detection(w, n)

    def detection(self, w: np.ndarray, negatives: float) -> float:
        """Impostors flagged at the distance np.quantile would give on the repeated genuine distances."""
        genuine = w[self.same] > 0
        distance, count = -self.similarity[self.same][genuine], np.cumsum(w[self.same][genuine])
        position = (count[-1] - 1) * (1 - FALSE_ALARMS)
        low = int(position)
        at = np.minimum(np.searchsorted(count, [low, low + 1], side="right"), len(count) - 1)
        threshold = distance[at[0]] + (position - low) * (distance[at[1]] - distance[at[0]])
        return w[~self.same & (-self.similarity > threshold)].sum() / negatives


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


@dataclass
class Observations:
    """Every demo-player observation, in the row order of the habits,buy table."""
    index: pd.MultiIndex
    player: np.ndarray  # identity code
    demo: np.ndarray
    match: np.ndarray
    map: np.ndarray
    day: np.ndarray
    rank: np.ndarray  # time order: day, then match, then game inside the match
    fold: np.ndarray

    @classmethod
    def load(cls, seed: int) -> "Observations":
        features, match_of, who = ev.load_fingerprints(MAIN_SET.split(","))
        index = features.index
        ids, player = np.unique(index.get_level_values(0), return_inverse=True)
        demo_names = index.get_level_values(1)
        _, demo = np.unique(demo_names, return_inverse=True)
        match = demo_names.map(match_of).to_numpy()
        day = who["played_on"].to_numpy(dtype="datetime64[D]")
        game = demo_names.str.extract(r"-m(\d)-", expand=False).fillna("1").astype(int).to_numpy()
        rank = np.empty(len(index), dtype=int)
        rank[np.lexsort((demo_names.to_numpy(), game, match, day))] = np.arange(len(index))
        shuffled = np.random.default_rng([seed, 1]).permutation(len(ids))
        fold_of = np.empty(len(ids), dtype=int)
        fold_of[shuffled] = np.arange(len(ids)) % FOLDS
        return cls(index, player, demo, match, ev.map_names(index), day, rank, fold_of[player])


def sample_pairs(data: Observations, rows: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    """All same-player pairs of `rows`, and 9 negatives per positive: same-demo up to its quota, the rest
    uniformly among pairs from two different demos."""
    i, j = np.triu_indices(len(rows), 1)
    a, b = rows[i], rows[j]
    same = data.player[a] == data.player[b]
    same_demo = ~same & (data.demo[a] == data.demo[b])
    other = ~same & ~same_demo
    wanted = NEGATIVES_PER_POSITIVE * same.sum()
    demo_pool, other_pool = np.flatnonzero(same_demo), np.flatnonzero(other)
    demo_taken = rng.permutation(demo_pool)[:round(SAME_DEMO_SHARE * wanted)]
    other_taken = rng.permutation(other_pool)[:wanted - len(demo_taken)]
    picked = np.r_[np.flatnonzero(same), demo_taken, other_taken]
    return pd.DataFrame({"a": a[picked], "b": b[picked], "same": same[picked],
                         "same_demo": same_demo[picked]})


def pair_distance(a: np.ndarray, b: np.ndarray, pooled: np.ndarray) -> np.ndarray:
    """Our score with both sides as one-map profiles: each carries the pooled variance, hence the 2."""
    return np.sqrt(np.minimum((a - b) ** 2 / (2 * pooled), ev.GAP_CAP).sum(axis=1))


@dataclass
class Fit:
    """What one fold learns from its training identities, for one feature set."""
    z: np.ndarray  # every observation in training units
    columns: pd.Index
    pooled: np.ndarray
    k: np.ndarray
    edges: np.ndarray
    llr: np.ndarray

    def evidence(self, distance: np.ndarray) -> np.ndarray:
        return self.llr[np.clip(np.searchsorted(self.edges, distance, side="right") - 1, 0, BINS - 1)]


def fit_fold(features: pd.DataFrame, train: np.ndarray, train_pairs: pd.DataFrame, straub) -> Fit:
    """z-scoring, pooled variance, k and LLR bins, from rows and pairs of training identities only.
    Rows absent from this feature set are all-NaN in `features` and never reach a pair."""
    rows = features[train].dropna(how="all")
    mean, std, pooled = ev.past_standard(rows)
    z = ((features[mean.index] - mean) / std).fillna(0).to_numpy()
    k = ev.Context(straub).per_feature(rows, mean.index)
    distance = pair_distance(z[train_pairs["a"]], z[train_pairs["b"]], pooled)
    edges = np.linspace(distance.min(), distance.max(), BINS + 1)
    bins = np.clip(np.searchsorted(edges, distance, side="right") - 1, 0, BINS - 1)
    same = train_pairs["same"].to_numpy()
    with_same = np.bincount(bins[same], minlength=BINS) + ALPHA
    with_other = np.bincount(bins[~same], minlength=BINS) + ALPHA
    llr = np.log(with_same / with_same.sum()) - np.log(with_other / with_other.sum())
    return Fit(z, mean.index, pooled, k, edges, llr)


def build_cohort(data: Observations, fold: int, seed: int) -> tuple[pd.DataFrame, int]:
    """Test B groups of one fold, shared by every K, method and feature set. A history is an identity's
    observations ranked before the query, outside its match, newest last. Negative identities obey the
    same rule as the positive one, so neither side gets same-day maps the other can't have. Returns the
    groups and the number of queries lost for lack of 4 negative identities."""
    rng = np.random.default_rng([seed, 2, fold])
    rows = np.flatnonzero(data.fold == fold)
    rows = rows[np.argsort(data.rank[rows])]
    groups, lost = [], 0

    def history(identity: int, query: int) -> np.ndarray:
        mine = rows[data.player[rows] == identity]
        return mine[(data.rank[mine] < data.rank[query]) & (data.match[mine] != data.match[query])]

    for query in rows:
        player = data.player[query]
        own = history(player, query)
        if len(own) < COHORT_K:
            continue
        others = {p: history(p, query) for p in np.unique(data.player[rows]) if p != player}
        eligible = sorted(p for p, h in others.items() if len(h) >= COHORT_K)
        if len(eligible) < NEGATIVE_GROUPS:
            lost += 1
            continue
        groups.append((query, player, own[-COHORT_K:], True))
        for p in rng.choice(eligible, NEGATIVE_GROUPS, replace=False):
            groups.append((query, p, others[p][-COHORT_K:], False))
    return pd.DataFrame(groups, columns=["query", "identity", "history", "same"]), lost


def check_cohort(data: Observations, groups: pd.DataFrame, fold: int) -> None:
    for query, identity, history, same in groups.itertuples(index=False):
        assert (data.fold[history] == fold).all() and (data.player[history] == identity).all()
        assert (data.rank[history] < data.rank[query]).all()
        assert (data.match[history] != data.match[query]).all()
        assert same == (identity == data.player[query])


def history_scores(data: Observations, fit: Fit, groups: pd.DataFrame, k: int) -> dict[str, np.ndarray]:
    """Every group's similarity with the K latest maps of its history, under the three aggregations."""
    scores = {method: np.empty(len(groups)) for method in METHODS}
    blank = np.zeros((1, fit.z.shape[1])), np.ones((1, fit.z.shape[1]))
    for g, (query, history) in enumerate(zip(groups["query"], groups["history"], strict=True)):
        recent = history[-k:]
        x, past = fit.z[query], fit.z[recent]
        scores["mean-LLR"][g] = fit.evidence(pair_distance(x[None, :], past, fit.pooled)).mean()
        means, variances = ev.own_profile(*blank, 0, past, fit.pooled)
        scores["profile global"][g] = -ev.score(means, variances, x, "own")[0]
        mine = past[data.map[recent] == data.map[query]]
        cell = (*ev.own_profile(*blank, 0, mine, fit.pooled), np.array([len(mine)])) if len(mine) else None
        scores["profile per-map"][g] = -ev.score(*ev.with_context(means, variances, cell, fit.k), x, "own")[0]
    return scores


def resampled(players: np.ndarray, fold: int, stream: int, seed: int, resamples: int) -> np.ndarray:
    """(resamples, identity code) how often each of `players` is drawn; the same draws for every score."""
    rng = np.random.default_rng([seed, stream, fold])
    draws = np.zeros((resamples, players.max() + 1))
    draws[:, players] = rng.multinomial(len(players), np.full(len(players), 1 / len(players)), resamples)
    return draws


Part = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]  # similarity, same, identity a, identity b


def measure(parts: dict[int, Part], draws: dict[int, np.ndarray]) -> tuple[pd.DataFrame, np.ndarray]:
    """Per-fold metrics, and (resample, metric) of their mean over folds. A negative counts as often as
    both its identities are drawn, a positive as often as its one identity is. Positives grow with the
    square of a player's maps, so each resample is scaled back to the fold's ratio: the protocol fixes
    that ratio and AP depends on it (AUC and detect@5% don't)."""
    resamples = next(iter(draws.values())).shape[0]
    rows, reps = {}, np.full((resamples, FOLDS, len(METRICS)), np.nan)
    for fold, (similarity, same, a, b) in parts.items():
        ranked = Ranked(similarity, same)
        rows[fold] = dict(zip(METRICS, ranked.metrics(np.ones(len(same))), strict=True))
        rows[fold] |= {"pos": int(same.sum()), "neg": int((~same).sum())}
        ratio = (~same).sum() / same.sum()
        for r, m in enumerate(draws[fold]):
            weights = m[a] * np.where(same, 1.0, m[b])
            negatives = weights[~same].sum()
            if negatives > 0:
                weights[~same] *= ratio * weights[same].sum() / negatives
            reps[r, fold] = ranked.metrics(weights)
    defined = (~np.isnan(reps)).sum(axis=1)
    return pd.DataFrame(rows).T, np.nansum(reps, axis=1) / np.maximum(defined, 1)


def rows_of(labels: dict, table: pd.DataFrame, reps: np.ndarray) -> list[dict]:
    """One row per fold, then the mean over folds with its 95% interval."""
    out = [{**labels, "fold": fold, **row} for fold, row in table.to_dict("index").items()]
    low, high = np.percentile(reps, [2.5, 97.5], axis=0)
    mean = {**labels, "fold": "mean", "pos": table["pos"].sum(), "neg": table["neg"].sum(),
            "folds": len(table.dropna(subset=["auc"]))}
    for i, metric in enumerate(METRICS):
        mean |= {metric: table[metric].mean(), f"{metric}_lo": low[i], f"{metric}_hi": high[i]}
    return [*out, mean]


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


@dataclass
class Protocol:
    """The sets, pairs and cohorts of one fold partition: identical for every score."""
    data: Observations
    sets: dict[str, pd.DataFrame]
    test_pairs: dict[int, pd.DataFrame]
    train_pairs: dict[int, pd.DataFrame]
    cohorts: dict[int, pd.DataFrame]
    lost: dict[int, int]

    @classmethod
    def build(cls, seed: int) -> "Protocol":
        data = Observations.load(seed)
        sets = {name: ev.load_fingerprints(name.split(","))[0].reindex(data.index)
                for name in (MAIN_SET, FULL_SET, AIM_SET)}
        test_pairs, train_pairs, cohorts, lost = {}, {}, {}, {}
        for fold in range(FOLDS):
            test = data.fold == fold
            rows, others = np.flatnonzero(test), np.flatnonzero(~test)
            test_pairs[fold] = sample_pairs(data, rows, np.random.default_rng([seed, 3, fold]))
            train_pairs[fold] = sample_pairs(data, others, np.random.default_rng([seed, 4, fold]))
            assert test[test_pairs[fold][["a", "b"]].to_numpy()].all()
            assert not test[train_pairs[fold][["a", "b"]].to_numpy()].any()
            assert not set(data.player[test]) & set(data.player[~test])
            cohorts[fold], lost[fold] = build_cohort(data, fold, seed)
            check_cohort(data, cohorts[fold], fold)
        return cls(data, sets, test_pairs, train_pairs, cohorts, lost)


def test_a(run: Protocol, fits: dict, draws: dict[int, np.ndarray], straub) -> tuple[list, list, list]:
    """Pairwise surface of every feature set: fills `fits`; returns result, slice and paired rows."""
    data, results, slices, surfaces = run.data, [], [], {}
    for name, features in run.sets.items():
        usable = features.notna().any(axis=1).to_numpy()
        parts: dict[str, dict[int, Part]] = {}
        for fold, pair in run.test_pairs.items():
            fit = fit_fold(features, data.fold != fold, pair_kept(run.train_pairs[fold], usable), straub)
            fits[name, fold] = fit
            kept = pair_kept(pair, usable)
            a, b = kept["a"].to_numpy(), kept["b"].to_numpy()
            same, same_demo = kept["same"].to_numpy(), kept["same_demo"].to_numpy()
            similarity = -pair_distance(fit.z[a], fit.z[b], fit.pooled)
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


def history_parts(run: Protocol, fits: dict, name: str, k: int) -> dict[str, dict[int, Part]]:
    """Test B scores of one feature set and K, per method and fold."""
    parts: dict[str, dict[int, Part]] = {method: {} for method in METHODS}
    for fold, groups in run.cohorts.items():
        if len(groups):
            same = groups["same"].to_numpy()
            a, b = run.data.player[groups["query"]], groups["identity"].to_numpy()
            for method, similarity in history_scores(run.data, fits[name, fold], groups, k).items():
                parts[method][fold] = similarity, same, a, b
    return parts


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
    pair_draws = {f: resampled(np.unique(data.player[data.fold == f]), f, 5, seed, resamples)
                  for f in range(FOLDS)}
    group_draws = {
        fold: resampled(np.unique(np.r_[groups["identity"], data.player[groups["query"]]]), fold, 6, seed,
                        resamples)
        for fold, groups in run.cohorts.items() if len(groups)}
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
    straub = load_straub()
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


def pair_kept(pairs: pd.DataFrame, usable: np.ndarray) -> pd.DataFrame:
    """Pairs whose two observations exist in this feature set."""
    return pairs[usable[pairs["a"]] & usable[pairs["b"]]]


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas", "numpy"]
# ///
"""Per-map shrinkage on ml/evaluate.py: grid, Bühlmann k, leak-free and chronological runs, paired bootstrap.

Usage (repo root): uv run experiments/shrinkage_k/run.py
Writes results.csv, buhlmann.csv, bootstrap.csv, chronological.csv, variants.csv next to this file.
Every run goes through ml/evaluate.py: this file only loops over its flags and compares the trials.
"""
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
import evaluate as ev  # noqa: E402
from metrics import auc, detection_at, identification, split_scores  # noqa: E402

OUT = Path(__file__).parent
SEED = 0
RESAMPLES = 1000
FOLDS = 5
WORKERS = min(8, os.cpu_count() or 1)
GRID = [0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, np.inf]
PRIORS = [5, 10, 20]
FEATURE_SETS = ["habits,buy", "habits", "habits,buy,strafe", "habits,buy,aim,strafe"]
MAIN_SET = "habits,buy"
BASE = "global"  # no --context-k: his profile


def buhlmann_straub_k(rows: pd.DataFrame) -> pd.Series:
    """Exact Bühlmann-Straub moments. buhlmann_k subtracts s²/n from the cell gaps, but a cell belongs to
    the player mean it is compared with: E[Σ n·gap²] = (C-1)·s² + b·(N - Σn²/N) per player."""
    players, maps, ks = rows.index.get_level_values(0), ev.map_names(rows.index), {}
    for feature in rows.columns:
        d = pd.DataFrame({"p": players, "m": maps, "x": rows[feature].to_numpy()}).dropna()
        cells = d.groupby(["p", "m"])["x"].agg(["mean", "var", "size"]).reset_index()
        repeated = cells[cells["size"] >= 2]
        if repeated.empty:
            ks[feature] = np.inf
            continue
        within = np.average(repeated["var"], weights=repeated["size"] - 1)
        gaps = cells["mean"] - cells["p"].map(d.groupby("p")["x"].mean())
        per_player = cells.assign(ssb=cells["size"] * gaps ** 2, n2=cells["size"] ** 2).groupby("p").agg(
            ssb=("ssb", "sum"), c=("size", "size"), n=("size", "sum"), n2=("n2", "sum"))
        between = ((per_player["ssb"].sum() - within * (per_player["c"] - 1).sum())
                   / (per_player["n"] - per_player["n2"] / per_player["n"]).sum())
        ks[feature] = within / between if between > 0 else np.inf
    return pd.Series(ks)


K_NAMES = {"buhlmann": ev.buhlmann_k, "buhlmann_straub": buhlmann_straub_k}


def context_of(k: float | str) -> ev.Context | None:
    if k == BASE:
        return None
    return ev.Context(K_NAMES.get(k, k))


class Data:
    """One feature set, loaded and standardised the way evaluate.py's main does."""

    def __init__(self, vectors: str):
        self.features, self.match_of, self.who = ev.load_fingerprints(vectors.split(","))
        self.z = ev.standardise(self.features)
        self.features = self.features.loc[:, self.z.columns]
        self.days = self.who["played_on"].to_numpy(dtype="datetime64[D]")

    def scopes(self, who: pd.DataFrame | None = None) -> dict[str, ev.OwnRows]:
        return {"all": ev.other_matches(self.z, self.match_of),
                "xevent": ev.other_event(self.z, self.match_of),
                "xteam": ev.other_team(self.z, self.who if who is None else who)}

    def run(self, mode: str, own: ev.OwnRows, k: float | str) -> list:
        if mode == "strict":
            return ev.held_out_trials(self.features, self.match_of, own, "own", context_of(k))
        return ev.trials(self.z, own, "own", context_of(k), self.features)

    def past(self, k: float | str) -> list:
        pick = ev.maps_between(self.features, self.days, 1, ev.TIME_GAPS["> 90"][1])
        return ev.past_trials(self.features, self.days, pick, "own", context_of(k))


def scores(results: list) -> dict:
    genuine, impostor = split_scores(results)
    return {"auc": auc(genuine, impostor), "det5": detection_at(genuine, impostor),
            "top1": identification(results)["top1"], "queries": len(results),
            "players": len({p for p, _ in results})}


def one_config(task: tuple) -> dict:
    """One row of results.csv (runs in a worker: PRIOR_MAPS is a module constant of evaluate.py)."""
    vectors, mode, k, prior_maps = task
    ev.PRIOR_MAPS = prior_maps
    data = Data(vectors)
    row = {"features": vectors, "mode": mode, "k": k, "prior_maps": prior_maps}
    if mode == "past":
        found = scores(data.past(k))
        return row | {"AUC_all": found["auc"], "det5_all": found["det5"], "top1_all": found["top1"],
                      "n_all": found["queries"]}
    for scope, own in data.scopes().items():
        found = scores(data.run(mode, own, k))
        row |= {f"AUC_{scope}": found["auc"], f"det5_{scope}": found["det5"], f"top1_{scope}": found["top1"],
                f"n_{scope}": found["queries"], f"players_{scope}": found["players"]}
    return row


def grid_tasks() -> list[tuple]:
    ks = [BASE, *GRID, "buhlmann"]
    tasks = [(v, m, k, 10) for v in FEATURE_SETS for m in ("his", "strict") for k in ks]
    tasks += [(MAIN_SET, "strict", "buhlmann_straub", 10)]
    return tasks + [(MAIN_SET, "past", k, 10) for k in [*ks, "buhlmann_straub"]]


def best_k(table: pd.DataFrame, column: str) -> float:
    """The k of the number grid with the highest `column` (habits,buy, strict, his PRIOR_MAPS)."""
    rows = table[(table["features"] == MAIN_SET) & (table["mode"] == "strict") & (table["prior_maps"] == 10)]
    rows = rows[rows["k"].map(lambda k: isinstance(k, float) and np.isfinite(k))]
    return float(rows.loc[rows[column].astype(float).idxmax(), "k"])


class Paired:
    """Two sets of trials on the same queries, grouped by a resampling unit (match or player)."""

    def __init__(self, base: list, other: list, unit_of):
        keyed = {(p, d.name): d for p, d in other}
        self.groups: dict = {}
        for player, d in base:
            pair = keyed[(player, d.name)]
            entry = (d[player], d.drop(player).to_numpy(), pair[player], pair.drop(player).to_numpy())
            self.groups.setdefault(unit_of(player, d.name), []).append(entry)

    def stats(self, units: list) -> tuple:
        rows = [t for u in units for t in self.groups[u]]
        g0, g1 = np.array([r[0] for r in rows]), np.array([r[2] for r in rows])
        i0, i1 = np.concatenate([r[1] for r in rows]), np.concatenate([r[3] for r in rows])
        return (auc(g0, i0), detection_at(g0, i0), auc(g1, i1), detection_at(g1, i1))

    def bootstrap(self) -> dict:
        units, rng = list(self.groups), np.random.default_rng(SEED)
        a0, d0, a1, d1 = self.stats(units)
        drawn = np.array([self.stats(list(rng.choice(np.array(units, dtype=object), len(units))))
                          for _ in range(RESAMPLES)])
        d_auc, d_det = drawn[:, 2] - drawn[:, 0], drawn[:, 3] - drawn[:, 1]
        lo_a, hi_a = np.percentile(d_auc, [2.5, 97.5])
        lo_d, hi_d = np.percentile(d_det, [2.5, 97.5])
        return {"units": len(units), "AUC_base": a0, "AUC_k": a1, "dAUC": a1 - a0,
                "dAUC_lo": lo_a, "dAUC_hi": hi_a,
                "det5_base": d0, "det5_k": d1, "ddet5": d1 - d0, "ddet5_lo": lo_d, "ddet5_hi": hi_d,
                "dAUC_includes_0": lo_a <= 0 <= hi_a, "ddet5_includes_0": lo_d <= 0 <= hi_d}


def same_pool(data: Data, results: list) -> list:
    """Trials keeping only impostors with maps on the query's map outside its match: they all get a
    per-map profile too, so a gain here is not just 'this candidate never plays that map'."""
    index = data.features.index
    rows = pd.DataFrame({"p": index.get_level_values(0), "m": ev.map_names(index),
                         "match": index.get_level_values(1).map(data.match_of)})
    total = rows.groupby(["p", "m"]).size().to_dict()
    inside = rows.groupby(["p", "m", "match"]).size().to_dict()
    kept = []
    for player, d in results:
        name, match = d.name.rsplit("-", 1)[-1], data.match_of[d.name]
        keep = [c for c in d.index if c == player
                or total.get((c, name), 0) - inside.get((c, name, match), 0) > 0]
        kept.append((player, d[keep]))
    return kept


def paired_runs(data: Data, k: float | str, label: str, base_k: float | str = BASE) -> list[dict]:
    """Paired bootstrap of k against base_k: strict all / same map pool / cross-team, and chronological."""
    every = data.run("strict", data.scopes()["all"], base_k), data.run("strict", data.scopes()["all"], k)
    runs = {"strict all maps": every,
            "strict all maps, impostors with a cell": tuple(same_pool(data, r) for r in every),
            "strict cross-team": (data.run("strict", data.scopes()["xteam"], base_k),
                                  data.run("strict", data.scopes()["xteam"], k)),
            "past all maps": (data.past(base_k), data.past(k))}
    out = []
    for name, (base, other) in runs.items():
        units = {"match": lambda _, map_game: data.match_of[map_game], "player": lambda player, _: player}
        for unit, unit_of in units.items():
            out.append({"k": k, "against": base_k, "chosen_by": label, "test": name, "unit": unit}
                       | Paired(base, other, unit_of).bootstrap())
    return out


def cross_fitted(data: Data) -> dict:
    """k chosen on the other folds of matches, scored on the held-out fold: the gain without the optimism
    of picking k and measuring it on the same matches."""
    own = data.scopes()["all"]
    runs = {k: data.run("strict", own, k) for k in GRID}
    base = data.run("strict", own, BASE)
    matches = np.array(sorted(data.match_of.unique()))
    fold_of = dict(zip(np.random.default_rng(SEED).permutation(matches),
                       np.arange(len(matches)) % FOLDS, strict=True))

    def in_fold(results: list, fold: int, inside: bool) -> list:
        return [t for t in results if (fold_of[data.match_of[t[1].name]] == fold) == inside]

    picked, held = [], []
    for fold in range(FOLDS):
        chosen = max(GRID[:-1], key=lambda k: auc(*split_scores(in_fold(runs[k], fold, False))))
        picked.append(chosen)
        held += in_fold(runs[chosen], fold, True)
    base_scores, held_scores = scores(base), scores(held)
    return {"k_per_fold": picked, "AUC_base": base_scores["auc"], "AUC_crossfit": held_scores["auc"],
            "det5_base": base_scores["det5"], "det5_crossfit": held_scores["det5"]}


def buhlmann_table(data: Data) -> pd.DataFrame:
    """k per feature on all maps, the range over the leave-one-match-out fits run.py really uses, and the
    share of a player's own variation explained by the map (effects.py's diagnostic)."""
    matches = data.features.index.get_level_values(1).map(data.match_of).to_numpy()
    folds = pd.DataFrame({m: ev.buhlmann_k(data.features[matches != m]) for m in pd.unique(matches)})
    return pd.DataFrame({"k_f": ev.buhlmann_k(data.features), "k_f_min": folds.min(axis=1),
                         "k_f_max": folds.max(axis=1), "inf_share": np.isinf(folds).mean(axis=1),
                         "k_straub": buhlmann_straub_k(data.features)}).sort_values("k_f")


def variants() -> pd.DataFrame:
    """Hunt for the '~49% after a transfer': cross-team row for every vector set, cap on and off."""
    rows = []
    for size in range(1, 5):
        for vectors in itertools.combinations(["habits", "buy", "aim", "strafe"], size):
            data = Data(",".join(vectors))
            for scoring, cap in [("own", 9.0), ("own", np.inf), ("euclid", 9.0)]:
                ev.GAP_CAP = cap
                results = ev.trials(data.z, data.scopes()["xteam"], scoring)
                rows.append({"features": "+".join(vectors), "score": scoring, "gap_cap": cap}
                            | scores(results))
    ev.GAP_CAP = 9.0
    return pd.DataFrame(rows)


def rebrand_effect(data: Data) -> dict:
    """Cross-team row if Sharks → DENDELE counted as a transfer (the reference did): same roster."""
    raw = pd.concat([pd.read_csv(f, dtype={"player": str}) for f in sorted(ev.FINGERPRINTS.glob("*.csv"))])
    raw["map_game"] = raw["match"] + "/" + raw["map_game"]
    team = raw.groupby(["player", "map_game"])["team"].first().reindex(data.who.index)
    split = data.who.assign(team=data.who["team"].where(team != "Sharks", "Sharks"))
    return scores(data.run("strict", data.scopes(split)["xteam"], BASE))


def check_infinity(data: Data) -> None:
    """k = inf must give back the global profile, distance for distance."""
    own = data.scopes()
    pairs = [(data.run(mode, own[scope], BASE), data.run(mode, own[scope], np.inf))
             for mode in ("his", "strict") for scope in own]
    pairs.append((data.past(BASE), data.past(np.inf)))
    for base, other in pairs:
        assert len(base) == len(other)
        for (p, d), (q, e) in zip(base, other, strict=True):
            assert p == q and d.name == e.name and d.equals(e)
    queries = sum(len(b) for b, _ in pairs)
    print(f"k = inf reproduces the global profile exactly: {queries} queries", flush=True)


def main() -> None:
    with ProcessPoolExecutor(WORKERS) as pool:
        table = pd.DataFrame(pool.map(one_config, grid_tasks()))
        k_auc = best_k(table, "AUC_all")
        k_transfer = best_k(table, "det5_xteam")
        print(f"best k: {k_auc} (overall AUC), {k_transfer} (cross-team detection)", flush=True)
        extra = [(MAIN_SET, m, k, p) for p in PRIORS for k in (BASE, k_auc)
                 for m in ("strict", "past") if p != 10]
        table = pd.concat([table, pd.DataFrame(pool.map(one_config, extra))], ignore_index=True)
    table.to_csv(OUT / "results.csv", index=False)

    data = Data(MAIN_SET)
    check_infinity(data)
    buhlmann_table(data).to_csv(OUT / "buhlmann.csv", index_label="feature")
    pairs = paired_runs(data, k_auc, "overall AUC")
    if k_transfer != k_auc:
        pairs += paired_runs(data, k_transfer, "cross-team detection")
    pairs += paired_runs(data, "buhlmann_straub", "exact per-feature k")
    pairs += paired_runs(data, "buhlmann_straub", "exact per-feature k", base_k=k_auc)
    pd.DataFrame(pairs).to_csv(OUT / "bootstrap.csv", index=False)

    chrono = {str(k): ev.chronological_rows(data.features, data.days, data.match_of, "own", context_of(k))
              for k in (BASE, k_auc)}
    pd.concat({k: pd.DataFrame(rows).T for k, rows in chrono.items()}, names=["k", "row"]).to_csv(
        OUT / "chronological.csv")
    variants().to_csv(OUT / "variants.csv", index=False)
    print("cross-fitted k:", cross_fitted(data))
    print("with Sharks/DENDELE as a transfer:", rebrand_effect(data))
    print("transfer players:", ev.transfers(data.who))


if __name__ == "__main__":
    main()

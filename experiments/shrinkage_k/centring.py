# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas", "numpy"]
# ///
"""Map-centring against per-map shrinkage, leak-free, habits,buy, with run.py's paired bootstrap.

Usage (repo root): uv run experiments/shrinkage_k/centring.py
Writes centring.csv, centring_bootstrap.csv and centring_k.csv next to this file.
"""
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from run import BASE, MAIN_SET, OUT, Data, Paired, buhlmann_straub_k, context_of, ev, scores

STRAUB = "buhlmann_straub"
CONFIGS = {  # name: (k, map-centred)
    "global": (BASE, False), "centred": (BASE, True),
    "k=2": (2.0, False), "Straub": (STRAUB, False),
    "centred + k=2": (2.0, True), "centred + Straub": (STRAUB, True),
}
COMPARISONS = [  # (config, against)
    ("centred", "global"), ("k=2", "global"), ("Straub", "global"),
    ("centred + k=2", "global"), ("centred + Straub", "global"),
    ("k=2", "centred"), ("Straub", "centred"),
    ("centred + k=2", "centred"), ("centred + Straub", "centred"),
    ("centred + k=2", "k=2"), ("centred + Straub", "Straub"),
]
TESTS = {"overall": "all", "cross-team": "xteam", "chronological": "past"}
WORKERS = min(8, os.cpu_count() or 1)

data = Data(MAIN_SET)
SCOPES = data.scopes()
PICK = ev.maps_between(data.features, data.days, 1, ev.TIME_GAPS["> 90"][1])
TRIALS: dict[tuple[str, str], list] = {}


def run_config(task: tuple[str, str]) -> list:
    """Trials of one configuration on one scope ('past' = chronological)."""
    name, scope = task
    k, centred = CONFIGS[name]
    if scope == "past":
        return ev.past_trials(data.features, data.days, PICK, "own", context_of(k), centred=centred)
    return ev.held_out_trials(data.features, data.match_of, SCOPES[scope], "own", context_of(k),
                              centred=centred)


def compare(task: tuple) -> dict:
    """One paired bootstrap; reads the trials forked with the workers."""
    config, against, test, unit = task
    scope = TESTS[test]
    unit_of = {"match": lambda _, map_game: data.match_of[map_game], "player": lambda player, _: player}[unit]
    pair = Paired(TRIALS[(against, scope)], TRIALS[(config, scope)], unit_of)
    return {"config": config, "against": against, "test": test, "unit": unit} | pair.bootstrap()


def check_unchanged() -> None:
    """Centring off must give run.py's rows; k = inf on centred data must give the centred global profile."""
    results = pd.read_csv(OUT / "results.csv")
    row = results[(results["features"] == MAIN_SET) & (results["mode"] == "strict")
                  & (results["k"] == BASE) & (results["prior_maps"] == 10)].iloc[0]
    assert scores(TRIALS[("global", "all")])["auc"] == row["AUC_all"]
    assert scores(TRIALS[("global", "xteam")])["det5"] == row["det5_xteam"]
    for scope in ("all", "xteam"):
        again = ev.held_out_trials(data.features, data.match_of, SCOPES[scope], "own", context_of(np.inf),
                                   centred=True)
        for (p, d), (q, e) in zip(TRIALS[("centred", scope)], again, strict=True):
            assert p == q and d.equals(e)
    print("checks passed: centring off = results.csv, centred k = inf = centred global", flush=True)


def k_table() -> pd.DataFrame:
    centred = ev.map_centred(data.features, np.ones(len(data.features), dtype=bool))
    return pd.DataFrame({"k_straub": buhlmann_straub_k(data.features),
                         "k_straub_centred": buhlmann_straub_k(centred)}).sort_values("k_straub")


def main() -> None:
    tasks = [(name, scope) for name in CONFIGS for scope in ("all", "xteam", "xevent", "past")]
    with ProcessPoolExecutor(WORKERS) as pool:
        TRIALS.update(zip(tasks, pool.map(run_config, tasks), strict=True))
    check_unchanged()
    table = pd.DataFrame([{"config": n, "scope": s} | scores(TRIALS[(n, s)]) for n, s in tasks])
    table.to_csv(OUT / "centring.csv", index=False)
    k_table().to_csv(OUT / "centring_k.csv", index_label="feature")
    jobs = [(c, a, t, u) for c, a in COMPARISONS for t in TESTS for u in ("match", "player")]
    with ProcessPoolExecutor(WORKERS) as pool:  # forked after TRIALS exists
        pd.DataFrame(pool.map(compare, jobs)).to_csv(OUT / "centring_bootstrap.csv", index=False)


if __name__ == "__main__":
    main()

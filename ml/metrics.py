"""Metrics of a set of trials — shared by evaluate.py and effects.py.

A trial = (true player, distance from one query to every candidate profile), a Series indexed by player.
Genuine distance = query ↔ its own player's profile; impostor distances = query ↔ everyone else's.
"""
import numpy as np
import pandas as pd

FALSE_ALARMS = 0.05  # accepted share of the real player's maps flagged (the product's false-alarm budget)
DETECT = f"detect@{FALSE_ALARMS:.0%}FA"  # report column: impostors flagged within that budget
BOOTSTRAP = 100  # resamples of the query players for the 95% intervals
SEED = 0

Trial = tuple[str, pd.Series]


def split_scores(results: list[Trial]) -> tuple[np.ndarray, np.ndarray]:
    """Genuine distances (query ↔ own profile) and impostor distances (query ↔ everyone else)."""
    genuine = np.array([d[player] for player, d in results])
    impostor = np.concatenate([d.drop(player).to_numpy() for player, d in results])
    return genuine, impostor


def auc(genuine: np.ndarray, impostor: np.ndarray) -> float:
    """Probability that a genuine distance is smaller than an impostor one (ties count half)."""
    imp = np.sort(impostor)
    below = np.searchsorted(imp, genuine, side="left")
    ties = np.searchsorted(imp, genuine, side="right") - below
    return float(((len(imp) - below - ties) + 0.5 * ties).sum() / (len(genuine) * len(imp)))


def detection_at(genuine: np.ndarray, impostor: np.ndarray, false_alarms: float = FALSE_ALARMS) -> float:
    """Share of impostors flagged at the distance threshold that flags `false_alarms` of genuine queries."""
    threshold = np.quantile(genuine, 1 - false_alarms)
    return float((impostor > threshold).mean())


def eer(genuine: np.ndarray, impostor: np.ndarray) -> float:
    """Equal error rate: threshold where impostors accepted (FAR) = genuine players rejected (FRR)."""
    thresholds = np.sort(np.concatenate([genuine, impostor]))
    far = np.searchsorted(np.sort(impostor), thresholds, side="right") / len(impostor)
    frr = 1 - np.searchsorted(np.sort(genuine), thresholds, side="right") / len(genuine)
    best = np.argmin(np.abs(far - frr))
    return float((far[best] + frr[best]) / 2)


def identification(results: list[Trial]) -> dict:
    """Share of queries whose true player is the nearest profile (top-1) or among the 3 nearest."""
    ranks = np.array([(d < d[player]).sum() for player, d in results])
    return {"top1": (ranks == 0).mean(), "top3": (ranks < 3).mean()}


def bootstrap_ci(results: list[Trial]) -> dict[str, str]:
    """95% intervals of the detection rate and AUC, resampling query players (all their trials together):
    trials of one player are not independent, so resampling trials would give too narrow intervals."""
    per_player: dict[str, list] = {}
    for player, d in results:
        per_player.setdefault(player, []).append((d[player], d.drop(player).to_numpy()))
    players, rng, stats = list(per_player), np.random.default_rng(SEED), []
    for _ in range(BOOTSTRAP):
        sample = [t for p in rng.choice(players, len(players)) for t in per_player[p]]
        genuine, impostor = np.array([g for g, _ in sample]), np.concatenate([i for _, i in sample])
        stats.append((detection_at(genuine, impostor), auc(genuine, impostor)))
    (d_lo, a_lo), (d_hi, a_hi) = np.percentile(stats, [2.5, 97.5], axis=0)
    return {"detect CI": f"{d_lo:.0%}–{d_hi:.0%}", "auc CI": f"{a_lo:.3f}–{a_hi:.3f}"}


def summary(results: list[Trial]) -> dict:
    """All metrics of one set of trials, plus how many players / query maps they rest on."""
    genuine, impostor = split_scores(results)
    ci = bootstrap_ci(results)
    return {"players": len({p for p, _ in results}), "maps": len(results),
            DETECT: detection_at(genuine, impostor), "detect CI": ci["detect CI"],
            "auc": auc(genuine, impostor), "auc CI": ci["auc CI"],
            "eer": eer(genuine, impostor), **identification(results)}


def report(rows: dict[str, dict], candidates: int) -> None:
    """Print one line per test (rows = {test name: summary}), rates as percentages."""
    table = pd.DataFrame(rows).T
    for col in [DETECT, "eer", "top1", "top3"]:
        table[col] = (table[col] * 100).map("{:.0f}%".format)
    table["auc"] = table["auc"].map("{:.3f}".format)
    table[["players", "maps"]] = table[["players", "maps"]].astype(int)
    print(table.to_string())
    print(f"\n{candidates} candidates → chance top-1 = {1 / candidates:.1%}. 95% intervals: bootstrap over "
          "players. Zhang 2026 (pros): pairwise AUC 0.956, history AUC 0.975 with 5 demos.")

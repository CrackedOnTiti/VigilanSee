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


def cluster_bootstrap(results: list[Trial], unit_of: list, resamples: int, seed: int = SEED) -> np.ndarray:
    """(resample, [AUC, AP, detect@5%]) of `results` with whole clusters redrawn: unit_of[i] is the cluster
    (query player, query match...) of trial i, drawn with replacement as bootstrap_ci draws players. Each
    trial weighs as often as its cluster is drawn, which Ranked turns into one linear pass per resample."""
    similarity = -np.concatenate([np.r_[d[player], d.drop(player).to_numpy()] for player, d in results])
    same = np.concatenate([np.r_[True, np.zeros(len(d) - 1, dtype=bool)] for _, d in results])
    units, cluster = np.unique(np.array(unit_of, dtype=object).astype(str), return_inverse=True)
    entry_cluster = np.repeat(cluster, [len(d) for _, d in results])
    ranked, rng = Ranked(similarity, same), np.random.default_rng(seed)
    drawn = np.empty((resamples, 3))
    for r in range(resamples):
        counts = np.bincount(rng.choice(len(units), len(units)), minlength=len(units)).astype(float)
        drawn[r] = ranked.metrics(counts[entry_cluster])
    return drawn


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

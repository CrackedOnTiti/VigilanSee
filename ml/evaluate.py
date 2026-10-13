# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas", "numpy"]
# ///
"""Level-1 evaluation on data/fingerprints/ — the proof test of ADR 0012, comparable to Zhang 2026.

Every test is a set of *trials*: a held-out map of a player is compared to every candidate profile
(profile = mean and spread of a player's per-map fingerprints). Tests only differ in which maps may
build the profiles — never maps from the same match as the query (same day, same config).

Main criterion = VERIFICATION, the product question (ADR 0007 / 0012): was this map played by the
account's owner? Genuine = query vs its own player's profile, impostor = query vs anyone else's.
  detect@5%FA      impostors flagged when only 5% of the real player's maps raise a false alarm
  AUC / EER        genuine vs impostor distances (Zhang's metric)
Secondary: identification top-1 / top-3 among all players (1:N — who is it, ADR 0013).
Every rate comes with its 95% interval (bootstrap over players, see metrics.py).

Scores (--score):
  euclid           distance to the player's mean map, one scale for everyone
  own              deviation from the player's OWN distribution (ADR 0012 level 1): every feature gap in
                   units of that player's usual spread, pulled toward the average spread when he has few maps,
                   and capped at 3 of his standard deviations per feature

Rows:
  all maps               leave-one-match-out: profile from every other match, past or future
  past: …                the prior art's protocol — every profile built only from maps played BEFORE the
                         query (a real client only has the past):
    all maps             every earlier map
    whole match          same, one decision per query match (distances averaged over its 2–3 maps)
    N matches in a row   one decision on N consecutive matches of the same player — a friend who plays
                         N matches on the account (distances averaged over them)
    last K maps          history of K maps, Zhang's "history@K"                        (cold start)
    N–M days before      only maps played N to M days before the query                  (time drift)
  cross-event            profile from other tournaments only                            (patch / weeks)
  cross-team             profile from the player's old team, query with his new one     (person vs team)

Usage: uv run ml/evaluate.py [vectors] [--score own]   e.g. habits | habits,buy   (default: habits,buy)
"""
import argparse
import itertools
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from metrics import Trial, report, summary

FINGERPRINTS = Path("data/fingerprints")
HISTORY_SIZES = [1, 3, 5, 10]  # "last K maps" rows
STREAKS = [2, 3, 5]  # "N matches in a row" rows
TIME_GAPS = {"1–7": (1, 7), "8–30": (8, 30), "31–90": (31, 90), "> 90": (91, 10_000)}  # days before the query
ENROLMENT_DRAWS = 20  # random enrolment sets per query and size (effects.py)
DEFAULT_VECTORS = ["habits", "buy"]
SCORINGS = ["euclid", "own"]
DEFAULT_SCORING = "own"
PRIOR_MAPS = 10  # shrinkage: the average within-player spread weighs as much as 10 of the player's own maps
GAP_CAP = 9.0  # one feature counts at most 3 of the player's own standard deviations (squared): a few
# features jumping after a real context change (transfer) must not decide alone — tuned 2026-09-30

# own_rows(player, map_game) -> mask of the rows allowed in the true player's profile, or None to skip
OwnRows = Callable[[str, str], np.ndarray | None]
# pick(query day) -> the maps every profile may use for that query (chronological protocol)
Pick = Callable[[np.datetime64], pd.DataFrame]


def load_fingerprints(vectors: list[str]) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Per-map features of the chosen vectors, indexed by (player, map_game), the match of each map,
    and each row's player name, (normalised) team and day played. Demo parts of a map (-p1/-p2) are averaged.
    map_game is made unique as '<match>/<demo name>': the same teams can replay the same map later on."""
    raw = pd.concat([pd.read_csv(f, dtype={"player": str}) for f in sorted(FINGERPRINTS.glob("*.csv"))])
    raw["map_game"] = raw["match"] + "/" + raw["map_game"]
    columns = [c for c in raw.columns if c.split(".")[0] in vectors]
    per_map = raw.groupby(["player", "map_game"])[columns].mean().dropna(how="all")
    match_of = raw.drop_duplicates("map_game").set_index("map_game")["match"]
    who = raw.groupby(["player", "map_game"])[["name", "team", "played_on"]].first().reindex(per_map.index)
    return per_map, match_of, who.assign(team=merge_rebrands(who))


def merge_rebrands(who: pd.DataFrame) -> pd.Series:
    """One team key per roster: names sharing >= 3 players are the same team ('Team Spirit' / 'Spirit',
    rebrand 'Sharks' → 'DENDELE'). A core of 3 moving together to a new org also counts as the same team."""
    rosters = who.groupby("team").apply(lambda rows: set(rows.index.get_level_values(0)))
    key = {team: team for team in rosters.index}
    for a, b in itertools.combinations(rosters.index, 2):
        if len(rosters[a] & rosters[b]) >= 3:
            key[b] = key[a]
    return who["team"].map(key)


def standardise(features: pd.DataFrame) -> pd.DataFrame:
    """z-score each feature; constant features dropped, missing values set to the average (0)."""
    z = (features - features.mean()) / features.std()
    return z.dropna(axis=1, how="all").fillna(0)


def discriminability(z: pd.DataFrame) -> pd.Series:
    """Variance between players / variance within a player, per feature (> 1 = separates people)."""
    per_player = z.groupby(level=0)
    return (per_player.mean().var() / per_player.var().mean()).sort_values(ascending=False)


def event_of(match: str) -> str:
    """Tournament of a match folder: 'iem-cologne-major-2026-vitality-vs-…' → 'iem-cologne-major-2026'."""
    found = re.match(r"^(.*?-20\d\d)-", match)
    return found.group(1) if found else match


def shrink(variance: np.ndarray, maps: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """(players, features) variances pulled toward `prior`, the average within-player variance:
    a player's own variance weighs (maps - 1), the prior PRIOR_MAPS — one map = the prior alone."""
    weight = ((maps - 1) / (maps - 1 + PRIOR_MAPS))[:, None]
    return np.nan_to_num(variance) * weight + prior * (1 - weight)


def profiles(z: pd.DataFrame, prior: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    """Every player's profile from all his maps: mean map and shrunk variance per feature."""
    groups = z.groupby(level=0)
    return groups.mean(), shrink(groups.var().to_numpy(), groups.size().to_numpy(), prior)


def score(means: np.ndarray, variances: np.ndarray, query: np.ndarray, scoring: str) -> np.ndarray:
    """Distance from a query map to every profile: plain euclidean, or in each player's own spread
    (every feature's squared gap capped at GAP_CAP)."""
    gaps = (means - query) ** 2
    if scoring == "own":
        gaps = np.minimum(gaps / variances, GAP_CAP)
    return np.sqrt(gaps.sum(axis=1))


def trials(z: pd.DataFrame, own_rows: OwnRows, scoring: str = DEFAULT_SCORING) -> list[Trial]:
    """For each query map: (true player, distance from the map to every candidate profile).
    Other candidates' profiles use all their maps; the true player's uses only `own_rows`.
    Each distance Series is named after its query map_game."""
    prior = z.groupby(level=0).var().mean().to_numpy()
    means, variances = profiles(z, prior)
    row_of = {player: i for i, player in enumerate(means.index)}
    maps = z.to_numpy()
    results = []
    for q, (player, map_game) in enumerate(z.index):
        own = own_rows(player, map_game)
        if own is None or not own.any():
            continue
        m, v = own_profile(means.to_numpy(), variances, row_of[player], maps[own], prior)
        distances = score(m, v, maps[q], scoring)
        results.append((player, pd.Series(distances, index=means.index, name=map_game)))
    return results


def own_profile(means: np.ndarray, variances: np.ndarray, i: int, mine: np.ndarray,
                prior: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Copies of every profile where player row i is rebuilt from only `mine` (his allowed maps)."""
    means, variances = means.copy(), variances.copy()
    means[i] = mine.mean(axis=0)
    spread = mine.var(axis=0, ddof=1) if len(mine) > 1 else np.full(mine.shape[1], np.nan)
    variances[i] = shrink(spread[None, :], np.array([len(mine)]), prior)[0]
    return means, variances


def other_matches(z: pd.DataFrame, match_of: pd.Series) -> OwnRows:
    """Profile from every map of the player outside the query's match (players with ≥ 2 matches)."""
    players, matches = z.index.get_level_values(0), z.index.get_level_values(1).map(match_of)
    return lambda player, map_game: (players == player) & (matches != match_of[map_game])


def k_random_maps(z: pd.DataFrame, allowed: OwnRows, k: int, rng: np.random.Generator) -> OwnRows:
    """Profile from K random maps among the `allowed` ones (e.g. other_matches); skip if fewer than K."""
    def own(player: str, map_game: str) -> np.ndarray | None:
        pool = allowed(player, map_game)
        candidates = np.flatnonzero(pool) if pool is not None else []
        if len(candidates) < k:
            return None
        chosen = np.zeros(len(z), dtype=bool)
        chosen[rng.choice(candidates, size=k, replace=False)] = True
        return chosen
    return own


def k_map_trials(z: pd.DataFrame, allowed: OwnRows, k: int, rng: np.random.Generator,
                 scoring: str = DEFAULT_SCORING) -> list:
    """ENROLMENT_DRAWS random K-map profiles per query (among the `allowed` maps), all trials pooled."""
    return [t for _ in range(ENROLMENT_DRAWS) for t in trials(z, k_random_maps(z, allowed, k, rng), scoring)]


def other_event(z: pd.DataFrame, match_of: pd.Series) -> OwnRows:
    """Profile from the player's maps of the OTHER tournaments only (patch / weeks apart)."""
    players = z.index.get_level_values(0)
    events = z.index.get_level_values(1).map(match_of).map(event_of)
    return lambda player, map_game: (players == player) & (events != event_of(match_of[map_game]))


def other_team(z: pd.DataFrame, who: pd.DataFrame) -> OwnRows:
    """Profile from the player's maps with ANOTHER team only (transfers): person vs team effect."""
    players, teams = z.index.get_level_values(0), who["team"].to_numpy()
    team_at = who["team"].to_dict()
    return lambda player, map_game: (players == player) & (teams != team_at[(player, map_game)])


Standard = tuple[pd.Series, pd.Series, np.ndarray]  # feature means, stds, average within-player variance


def past_standard(past: pd.DataFrame) -> Standard | None:
    """z-scoring and shrinkage prior measured on past maps only; features without spread so far are
    dropped. None while no player has two past maps (nothing to measure a spread from)."""
    mean, std = past.mean(), past.std()
    usable = std > 0
    z = ((past.loc[:, usable] - mean[usable]) / std[usable]).fillna(0)
    prior = z.groupby(level=0).var().mean()
    kept = prior[prior > 0].index
    if kept.empty:
        return None
    return mean[kept], std[kept], prior[kept].to_numpy()


def past_trials(features: pd.DataFrame, days: np.ndarray, pick: Pick, scoring: str) -> list[Trial]:
    """Chronological trials on raw features: for each query map, every profile — the true player's
    included — is built only from the maps `pick` keeps among those played before the query's day, and
    standardisation and shrinkage prior come from past maps too: nothing from the future leaks in."""
    standards: dict[np.datetime64, Standard | None] = {}
    results = []
    for q, (player, map_game) in enumerate(features.index):
        day, history = days[q], pick(days[q])
        if day not in standards:
            standards[day] = past_standard(features[days < day])
        if standards[day] is None or player not in history.index.get_level_values(0):
            continue
        mean, std, prior = standards[day]
        means, variances = profiles(((history[mean.index] - mean) / std).fillna(0), prior)
        query = ((features.iloc[q][mean.index] - mean) / std).fillna(0).to_numpy()
        distances = score(means.to_numpy(), variances, query, scoring)
        results.append((player, pd.Series(distances, index=means.index, name=map_game)))
    return results


def latest_maps(z: pd.DataFrame, days: np.ndarray, k: int) -> Pick:
    """Each player's k most recent maps before the query day; players with fewer are left out."""
    order = np.argsort(days, kind="stable")
    ordered, ordered_days = z.iloc[order], days[order]

    def pick(day: np.datetime64) -> pd.DataFrame:
        recent = ordered[ordered_days < day].groupby(level=0).tail(k)
        counts = recent.groupby(level=0).size()
        return recent[recent.index.get_level_values(0).isin(counts[counts == k].index)]
    return pick


def maps_between(z: pd.DataFrame, days: np.ndarray, lo: int, hi: int) -> Pick:
    """Every player's maps played lo to hi days before the query day."""
    def pick(day: np.datetime64) -> pd.DataFrame:
        gap = (day - days).astype(int)
        return z[(gap >= lo) & (gap <= hi)]
    return pick


def per_match(results: list[Trial], match_of: pd.Series) -> list[Trial]:
    """One trial per (player, query match): distances averaged over the match's maps — the product
    judges a match, not a map."""
    groups: dict[tuple[str, str], list[pd.Series]] = {}
    for player, d in results:
        groups.setdefault((player, match_of[d.name]), []).append(d)
    return [(player, pd.concat(ds, axis=1).mean(axis=1).rename(ds[0].name))
            for (player, _), ds in groups.items()]


def in_a_row(match_trials: list[Trial], days_of: dict[str, np.datetime64], n: int) -> list[Trial]:
    """One trial per run of n consecutive matches of a player: distances averaged over the run.
    Impostor side: another player plays those n matches on the candidate's account."""
    by_player: dict[str, list[pd.Series]] = {}
    for player, d in sorted(match_trials, key=lambda t: days_of[t[1].name]):
        by_player.setdefault(player, []).append(d)
    return [(player, pd.concat(ds[i:i + n], axis=1).mean(axis=1).rename(ds[i].name))
            for player, ds in by_player.items() for i in range(len(ds) - n + 1)]


def chronological_rows(features: pd.DataFrame, days: np.ndarray, match_of: pd.Series, scoring: str) -> dict:
    """The prior art's protocol on our data: every row uses only maps played before the query."""
    f = features
    every_past_map = past_trials(f, days, maps_between(f, days, 1, TIME_GAPS["> 90"][1]), scoring)
    matches = per_match(every_past_map, match_of)
    rows = {"past: all maps": every_past_map, "past: whole match": matches}
    days_of = dict(zip(f.index.get_level_values(1), days, strict=True))
    for n in STREAKS:
        rows[f"past: {n} matches in a row"] = in_a_row(matches, days_of, n)
    for k in HISTORY_SIZES:
        rows[f"past: last {k} maps"] = past_trials(f, days, latest_maps(f, days, k), scoring)
    for name, (lo, hi) in TIME_GAPS.items():
        rows[f"past: {name} days before"] = past_trials(f, days, maps_between(f, days, lo, hi), scoring)
    return {name: summary(results) for name, results in rows.items() if results}


def transfers(who: pd.DataFrame) -> list[str]:
    """Players seen in several teams, e.g. 'Brollan: HEROIC, MOUZ'."""
    teams = who.groupby("name")["team"].unique()
    return [f"{name}: {', '.join(sorted(t))}" for name, t in teams.items() if len(t) > 1]


def main(vectors: list[str], scoring: str) -> None:
    features, match_of, who = load_fingerprints(vectors)
    z = standardise(features)
    days = who["played_on"].to_numpy(dtype="datetime64[D]")
    print("Most discriminative features (between / within player variance):")
    print(discriminability(z).head(10).round(2).to_string(), "\n")
    print(f"Score: {scoring}\n")

    rows = {"all maps (leave-one-match-out)": summary(trials(z, other_matches(z, match_of), scoring))}
    rows |= chronological_rows(features.loc[:, z.columns], days, match_of, scoring)
    for name, own in {"cross-event": other_event(z, match_of), "cross-team": other_team(z, who)}.items():
        results = trials(z, own, scoring)
        if results:
            rows[name] = summary(results)
    report(rows, candidates=z.index.get_level_values(0).nunique())
    print("Transfers (cross-team row):", "; ".join(transfers(who)) or "none")


def vectors_cli(description: str) -> argparse.ArgumentParser:
    """Command line shared by the evaluation scripts: one optional comma-separated list of vectors."""
    cli = argparse.ArgumentParser(description=description)
    cli.add_argument("vectors", nargs="?", default=",".join(DEFAULT_VECTORS), type=lambda s: s.split(","),
                     help="comma-separated vectors, e.g. habits,buy,strafe (default: %(default)s)")
    return cli


if __name__ == "__main__":
    cli = vectors_cli("Level-1 proof test on data/fingerprints/: verification, identification, robustness.")
    cli.add_argument("--score", choices=SCORINGS, default=DEFAULT_SCORING, help="default: %(default)s")
    args = cli.parse_args()
    main(args.vectors, args.score)

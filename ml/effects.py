# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pandas", "numpy"]
# ///
"""Context effects on a fingerprint: does it measure the player, or his map / team?

  map share      per feature: share of a player's own map-to-map variation explained by the map played
  same / other   identification with a K-map profile taken on the SAME map as the query vs on OTHER maps
                 (same queries in both rows) — a big gap means profiles must be map-aware
  map-centred    evaluate.py's identification after removing each map's average from every feature
  team share     per feature: share of the differences between players explained by their team, vs chance
  mistaken for   when the nearest profile is the wrong player, is it a teammate? (chance ≈ 4 / candidates)
  transfer pull  after a transfer: is the nearest profile a new teammate, an old one, or someone else?

Usage: uv run ml/effects.py [vectors]   (default: habits,buy)
"""
import numpy as np
import pandas as pd

from evaluate import (OwnRows, k_map_trials, load_fingerprints, other_matches, other_team, standardise,
                      trials, vectors_cli)
from metrics import SEED, report, summary

K = 1  # one-map profiles: few players have several maps on the same map
SHUFFLES = 20  # random team assignments averaged for the chance level


def maps_of(z: pd.DataFrame) -> np.ndarray:
    """Map played on each row: '<match>/vitality-vs-mouz-m2-dust2' → 'dust2'."""
    return z.index.get_level_values(1).str.rsplit("-", n=1).str[-1].to_numpy()


def map_shares(z: pd.DataFrame, maps: np.ndarray) -> pd.Series:
    """Remove each player's own average, then: variance of the per-map means / remaining variance.
    0 = the map doesn't move the feature, 1 = its variation within a player is all due to the map."""
    within = z - z.groupby(level=0).transform("mean")
    return (within.groupby(maps).transform("mean").var() / within.var()).sort_values(ascending=False)


def map_split(z: pd.DataFrame, match_of: pd.Series, maps: np.ndarray) -> tuple[OwnRows, OwnRows]:
    """Profile rows on the SAME map as the query / on OTHER maps (both outside the query's match).
    A query is kept only if it has both, so the two rows compare the same queries."""
    allowed = other_matches(z, match_of)
    map_at = dict(zip(z.index, maps, strict=True))

    def rows(player: str, map_game: str, same: bool) -> np.ndarray | None:
        ok, on_map = allowed(player, map_game), maps == map_at[(player, map_game)]
        if not (ok & on_map).any() or not (ok & ~on_map).any():
            return None
        return ok & (on_map if same else ~on_map)
    return (lambda p, m: rows(p, m, True)), (lambda p, m: rows(p, m, False))


def map_centred(z: pd.DataFrame, maps: np.ndarray) -> pd.DataFrame:
    """Every feature minus its average on that map (what's left: the player, not the map)."""
    return z - z.groupby(maps).transform("mean")


def main_team(who: pd.DataFrame) -> pd.Series:
    """Team each player played most maps with."""
    return who["team"].groupby(level=0).agg(lambda teams: teams.mode()[0])


def team_shares(z: pd.DataFrame, who: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Per feature: variance of team averages / variance between players' average profiles, and the same
    with shuffled teams (what 5-player groups give by chance). team >> chance = teammates look alike."""
    players = z.groupby(level=0).mean()
    teams = main_team(who).reindex(players.index).to_numpy()

    def share(labels: np.ndarray) -> pd.Series:
        return players.groupby(labels).transform("mean").var() / players.var()
    chance = pd.concat([share(rng.permutation(teams)) for _ in range(SHUFFLES)], axis=1).mean(axis=1)
    return pd.DataFrame({"team": share(teams), "chance": chance}).sort_values("team", ascending=False)


def nearest_other(results: list) -> list[tuple[str, str, str]]:
    """(true player, query map_game, nearest profile) for every trial."""
    return [(player, d.name, d.idxmin()) for player, d in results]


def mistaken_for_teammate(results: list, who: pd.DataFrame) -> float:
    """Among wrong top-1 answers, share where the nearest profile is a teammate of the query."""
    team = main_team(who)
    wrong = [(who.loc[(p, m), "team"], team[n]) for p, m, n in nearest_other(results) if n != p]
    return float(np.mean([query_team == nearest_team for query_team, nearest_team in wrong]))


def transfer_pull(results: list, who: pd.DataFrame) -> pd.Series:
    """Cross-team trials: share of queries whose nearest profile is the player himself, a teammate
    of his new team (the query's), of his old team(s), or someone else."""
    team = main_team(who)

    def kind(player: str, map_game: str, nearest: str) -> str:
        new_team = who.loc[(player, map_game), "team"]
        old_teams = set(who.loc[player, "team"]) - {new_team}
        if nearest == player:
            return "himself"
        if team[nearest] == new_team:
            return "new teammate"
        return "old teammate" if team[nearest] in old_teams else "someone else"
    return pd.Series([kind(*t) for t in nearest_other(results)]).value_counts(normalize=True).round(2)


def team_report(z: pd.DataFrame, who: pd.DataFrame, match_of: pd.Series, rng: np.random.Generator) -> None:
    """Print the three team diagnostics: team share, mistaken for a teammate, transfer pull."""
    candidates = z.index.get_level_values(0).nunique()
    print("Share of the differences between players explained by their team (top 10):")
    print(team_shares(z, who, rng).head(10).round(2).to_string(), "\n")
    wrong = mistaken_for_teammate(trials(z, other_matches(z, match_of)), who)
    print(f"Wrong top-1 that is a teammate: {wrong:.0%} (chance ≈ {4 / (candidates - 1):.0%})")
    pull = transfer_pull(trials(z, other_team(z, who)), who)
    print("After a transfer, nearest profile is:", pull.to_dict())


def main(vectors: list[str]) -> None:
    features, match_of, who = load_fingerprints(vectors)
    z = standardise(features)
    maps = maps_of(z)
    print(f"Maps: {pd.Series(maps).value_counts().to_dict()}\n")
    print("Share of a player's own variation explained by the map (top 10):")
    print(map_shares(z, maps).head(10).round(2).to_string(), "\n")

    rng = np.random.default_rng(SEED)
    same, other = map_split(z, match_of, maps)
    centred = map_centred(z, maps)
    report({
        f"profile K={K} map, same map": summary(k_map_trials(z, same, K, rng)),
        f"profile K={K} map, other map": summary(k_map_trials(z, other, K, rng)),
        "all maps (evaluate.py)": summary(trials(z, other_matches(z, match_of))),
        "all maps, map-centred": summary(trials(centred, other_matches(centred, match_of))),
    }, candidates=z.index.get_level_values(0).nunique())
    print()
    team_report(z, who, match_of, rng)


if __name__ == "__main__":
    main(vectors_cli("Context effects on the fingerprint: map and team.").parse_args().vectors)

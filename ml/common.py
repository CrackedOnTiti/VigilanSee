"""Shared building blocks: one Demo object, parsed lazily and shared by every measurement vector."""
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser

TICKRATE = 64
PLAYING_TEAMS = [2, 3]  # 2 = T, 3 = CT; 0/1 = unassigned/spectators (coaches, casters)

# Per-tick player state parsed once for the whole match. A vector needing a new prop adds it here.
KEYS = ["FORWARD", "BACK", "LEFT", "RIGHT", "RELOAD", "INSPECT", "USE"]
FLAGS = [*KEYS, "is_walking", "is_airborne", "ducking", "is_alive", "is_freeze_period", "is_warmup_period"]
STATE_PROPS = [*FLAGS, "active_weapon_name", "active_weapon_ammo", "total_rounds_played"]


class Demo:
    """One .dem file. Every event / tick query is parsed at most once and cached on the instance,
    so several vectors can read the same data without paying the parsing cost again."""

    def __init__(self, path: Path):
        self.path = path
        self.match = path.parent.name
        self.map_game = re.sub(r"-p\d+$", "", path.stem)  # -p1/-p2 = same map split in two files
        self.parser = DemoParser(str(path))
        self._cache: dict = {}

    def _cached(self, key: object, parse: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        """Run `parse` the first time `key` is asked for, then serve the stored result."""
        if key not in self._cache:
            self._cache[key] = parse()
        return self._cache[key]

    def event(self, name: str) -> pd.DataFrame:
        """Game event table (player_hurt, weapon_fire, item_pickup…), SteamIDs as strings."""
        return self._cached(("event", name), lambda: self.parser.parse_event(name))

    def ticks(self, props: list[str], ticks: list[int]) -> pd.DataFrame:
        """Selected props on selected ticks, indexed by (steamid, tick)."""
        def parse():
            df = self.parser.parse_ticks(props, ticks=ticks)
            return df.assign(steamid=df["steamid"].astype(str)).set_index(["steamid", "tick"]).sort_index()
        return self._cached(("ticks", tuple(props), tuple(ticks)), parse)

    def state(self) -> pd.DataFrame:
        """STATE_PROPS on every tick outside warmup, indexed by (steamid, tick), flags cleaned to bool."""
        def parse():
            df = self.parser.parse_ticks(STATE_PROPS)
            df[FLAGS] = df[FLAGS].fillna(False).astype(bool)  # None: player disconnected / not spawned
            df = df[~df["is_warmup_period"]]
            return df.assign(steamid=df["steamid"].astype(str)).set_index(["steamid", "tick"]).sort_index()
        return self._cached("state", parse)

    def roster(self) -> pd.DataFrame:
        """The 10 players: name and team at the last tick, indexed by SteamID64 (ground-truth identity)."""
        def parse():
            last = int(self.state().index.get_level_values("tick").max())
            df = self.parser.parse_ticks(["team_num", "team_clan_name"], ticks=[last])
            df = df[df["team_num"].isin(PLAYING_TEAMS)]
            return pd.DataFrame({"name": df["name"].to_numpy(), "team": df["team_clan_name"].to_numpy()},
                                index=pd.Index(df["steamid"].astype(str), name="player"))
        return self._cached("roster", parse)


def rising(flag: pd.Series) -> pd.Series:
    """True on the tick a key/state turns on, per player. `flag` is indexed by (steamid, tick), sorted."""
    previous = flag.groupby(level=0).shift(fill_value=False).astype(bool)
    return flag & ~previous

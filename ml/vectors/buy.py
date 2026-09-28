"""Buy vector: how a player shops during freeze time, order and speed of purchases.
"""
import pandas as pd

from common import TICKRATE, Demo

GROUPS = {  # item_pickup name -> group whose position in the round's buy order we measure
    "vest": "armor", "vesthelm": "armor", "defuser": "defuser",
    "smokegrenade": "smoke", "flashbang": "flash", "molotov": "fire", "incgrenade": "fire", "hegrenade": "he",
}
SPAWN_ITEMS = {"knife", "knife_t", "glock", "hkp2000", "usp_silencer", "c4"}  # given at spawn, not bought


def purchases(demo: Demo) -> pd.DataFrame:
    """Items bought during freeze time with their round and relative rank in that round (0 = first)."""
    freeze = demo.state().loc[lambda s: s["is_freeze_period"], ["total_rounds_played"]]
    buys = demo.event("item_pickup")
    buys = buys[~buys["item"].isin(SPAWN_ITEMS)].rename(columns={"user_steamid": "steamid"})
    buys = buys.join(freeze, on=["steamid", "tick"], how="inner")
    buys = buys.rename(columns={"total_rounds_played": "round"})
    per_round = buys.groupby(["steamid", "round"])
    return buys.assign(rank=per_round.cumcount() / per_round["tick"].transform("size"))


def buy_order(buys: pd.DataFrame) -> pd.DataFrame:
    """Mean rank of each item group in the player's buy order (e.g. armor first, flashes last)."""
    ranks = buys.assign(group=buys["item"].map(GROUPS)).dropna(subset=["group"])
    table = ranks.pivot_table(index="steamid", columns="group", values="rank", aggfunc="mean")
    return table.add_prefix("rank_")


def buy_speed(demo: Demo, buys: pd.DataFrame) -> pd.DataFrame:
    """Delay from freeze start to the first purchase, and time between two purchases (binds ≈ 0.05 s)."""
    freeze = demo.state().loc[lambda s: s["is_freeze_period"]].reset_index()
    freeze_start = freeze.groupby("total_rounds_played")["tick"].min()
    first = buys.groupby(["steamid", "round"])["tick"].min().reset_index()
    first_delay = (first["tick"] - first["round"].map(freeze_start)) / TICKRATE
    gap = buys.groupby(["steamid", "round"])["tick"].diff() / TICKRATE
    return pd.DataFrame({
        "first_delay_s": first_delay.groupby(first["steamid"]).median(),
        "gap_s": gap.groupby(buys["steamid"]).median(),
    })


def extract(demo: Demo) -> pd.DataFrame:
    buys = purchases(demo)
    return buy_order(buys).join(buy_speed(demo, buys), how="outer").rename_axis("player")

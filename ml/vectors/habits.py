"""Habits vector: unconscious out-of-combat tics (ADR 0013) — keys pressed, weapon handling, movement.

Behaviour only: nothing here depends on the account's config/binds (see vectors/buy.py for that).
"""
import pandas as pd

from common import TICKRATE, Demo, rising

KNIVES = "Knife|Bayonet|Karambit|Daggers"
RIFLES_30 = {"AK-47", "M4A4"}  # same 30-round clip → comparable reload habit
MOVE_KEYS = ["FORWARD", "BACK", "LEFT", "RIGHT"]


def playing(state: pd.DataFrame) -> pd.DataFrame:
    """Ticks where the player is alive and the round is live (no freeze time)."""
    return state[state["is_alive"] & ~state["is_freeze_period"]]


def per_minute(events: pd.Series, play: pd.DataFrame) -> pd.Series:
    """Count of True `events` during live play, per player, divided by minutes alive."""
    minutes = play.groupby(level=0).size() / TICKRATE / 60
    return events.reindex(play.index, fill_value=False).groupby(level=0).sum() / minutes


def weapon_switches(state: pd.DataFrame) -> pd.Series:
    """True on ticks where the active weapon changes."""
    weapon = state["active_weapon_name"].fillna("")
    before = weapon.groupby(level=0).shift()
    return weapon.ne(before) & before.notna()


def action_rates(state: pd.DataFrame, play: pd.DataFrame) -> pd.DataFrame:
    """How often per minute alive the player reloads, inspects, uses, jumps, crouches, switches weapon."""
    edges = {
        "reload": rising(state["RELOAD"]),
        "inspect": rising(state["INSPECT"]),
        "use": rising(state["USE"]),
        "jumps": rising(state["is_airborne"]),
        "crouch": rising(state["ducking"]),
        "switch": weapon_switches(state),
    }
    return pd.DataFrame({f"{name}_per_min": per_minute(e, play) for name, e in edges.items()})


def movement_style(play: pd.DataFrame) -> pd.DataFrame:
    """Which movement keys the player combines (share of the ticks where he moves), and knife-out time."""
    moving = play[play[MOVE_KEYS].any(axis=1)]
    strafe = moving["LEFT"] | moving["RIGHT"]
    shares = {
        "walk_frac": moving["is_walking"],
        "back_frac": moving["BACK"],
        "strafe_only_frac": strafe & ~moving["FORWARD"] & ~moving["BACK"],
        "w_plus_strafe_frac": moving["FORWARD"] & strafe,
        "knife_out_frac": play["active_weapon_name"].fillna("").str.contains(KNIVES),  # share of time alive
    }
    return pd.DataFrame({name: s.groupby(level=0).mean() for name, s in shares.items()})


def reload_habit(state: pd.DataFrame) -> pd.Series:
    """Median bullets left in the clip when reloading an AK-47 / M4A4 (0 = empties the clip first)."""
    reloads = rising(state["RELOAD"]) & state["active_weapon_name"].isin(RIFLES_30)
    return state.loc[reloads, "active_weapon_ammo"].groupby(level=0).median().rename("clip_at_reload")


def extract(demo: Demo) -> pd.DataFrame:
    state = demo.state()
    play = playing(state)
    features = pd.concat([action_rates(state, play), movement_style(play), reload_habit(state)], axis=1)
    return features.rename_axis("player")

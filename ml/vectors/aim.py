"""Aim vector: how a player aims in the second before the first shot of each engagement.

The demos' "spotted" data is almost empty, so we can't know when A first *sees* B.
Every feature is anchored on A's first shot of the engagement and looks backwards in time.
"""
import numpy as np
import pandas as pd

from common import TICKRATE, Demo

GAP = 3 * TICKRATE  # a new engagement A→B starts after 3 s without damage A→B
WINDOW = TICKRATE  # look back 1 s before the first shot
MIN_ENGAGEMENTS = 10  # fewer duels in a demo = too noisy, features left empty
ON_TARGET_DEG = 5
NON_GUNS = "knife|grenade|flashbang|molotov|inferno|decoy|taser|c4|^$"
# ponytail: fixed eye/head heights (standing 64, ducking 46); real head bone position if precision matters
EYE, EYE_DUCK = 64.0, 46.0
PROPS = ["X", "Y", "Z", "pitch", "yaw", "velocity_X", "velocity_Y", "ducking", "team_num"]


def view_direction(pitch: np.ndarray, yaw: np.ndarray) -> np.ndarray:
    """Unit vector the player looks at (CS2: positive pitch = looking down)."""
    p, y = np.radians(pitch), np.radians(yaw)
    return np.stack([np.cos(p) * np.cos(y), np.cos(p) * np.sin(y), -np.sin(p)], axis=-1)


def angle_deg(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Angle between two (arrays of) vectors, in degrees."""
    u = u / np.linalg.norm(u, axis=-1, keepdims=True)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip((u * v).sum(-1), -1, 1)))


def engagement_starts(demo: Demo) -> pd.DataFrame:
    """First gun damage of each engagement A→B (no damage A→B during the previous GAP ticks)."""
    hurt = demo.event("player_hurt").dropna(subset=["attacker_steamid"])
    hurt = hurt[~hurt["weapon"].str.contains(NON_GUNS) & (hurt["attacker_steamid"] != hurt["user_steamid"])]
    hurt = hurt.sort_values("tick")
    previous = hurt.groupby(["attacker_steamid", "user_steamid"])["tick"].shift()
    return hurt[previous.isna() | (hurt["tick"] - previous > GAP)]


def with_first_shot(demo: Demo, starts: pd.DataFrame) -> pd.DataFrame:
    """Adds `first_shot`: the attacker's earliest gun shot within WINDOW ticks before the damage."""
    fire = demo.event("weapon_fire")
    fire = fire[~fire["weapon"].str.contains(NON_GUNS)][["user_steamid", "tick"]]
    shots = starts[["attacker_steamid", "tick"]].merge(
        fire, left_on="attacker_steamid", right_on="user_steamid", suffixes=("", "_shot"))
    shots = shots[shots["tick_shot"].between(shots["tick"] - WINDOW, shots["tick"])]
    first = shots.groupby(["attacker_steamid", "tick"])["tick_shot"].min().rename("first_shot")
    return starts.merge(first, on=["attacker_steamid", "tick"])


def windows(demo: Demo, eng: pd.DataFrame, who: str) -> dict[str, np.ndarray]:
    """State of the `who` column's player (attacker / victim) on the WINDOW + 1 ticks ending at each
    first shot: one (n_engagements, WINDOW + 1) float array per prop, NaN where data is missing."""
    offsets = np.arange(-WINDOW, 1)
    ticks = eng["first_shot"].to_numpy(dtype=int)[:, None] + offsets
    state = demo.ticks(PROPS, sorted(set(ticks.ravel().tolist())))
    keys = pd.MultiIndex.from_arrays([np.repeat(eng[who].to_numpy(), len(offsets)), ticks.ravel()])
    rows = state[PROPS].reindex(keys).astype(float)
    return {prop: rows[prop].to_numpy().reshape(ticks.shape) for prop in PROPS}


def aim_errors(attacker: dict, victim: dict) -> tuple[np.ndarray, np.ndarray]:
    """Per engagement and tick: angle between the attacker's aim and the victim's head, and aim vectors."""
    def position(s, z_offset):
        return np.stack([s["X"], s["Y"], s["Z"] + z_offset], axis=-1)

    eye = position(attacker, np.where(attacker["ducking"] > 0.5, EYE_DUCK, EYE))
    head = position(victim, np.where(victim["ducking"] > 0.5, EYE_DUCK, EYE))
    view = view_direction(attacker["pitch"], attacker["yaw"])
    return angle_deg(view, head - eye), view


def ticks_on_target(errors: np.ndarray) -> np.ndarray:
    """How many ticks, counting back from the shot (last column), the aim stayed within ON_TARGET_DEG."""
    off = errors[..., ::-1] > ON_TARGET_DEG
    return np.where(off.any(axis=-1), off.argmax(axis=-1), errors.shape[-1])


def valid(attacker: dict, victim: dict) -> np.ndarray:
    """Engagements with a complete window for both players, between opponents (no team damage)."""
    complete = ~np.isnan(np.stack(list(attacker.values()) + list(victim.values()))).any(axis=(0, 2))
    return complete & (attacker["team_num"][:, -1] != victim["team_num"][:, -1])


def engagements(demo: Demo) -> pd.DataFrame:
    """One row per engagement: attacker SteamID + aim features, all engagements computed at once."""
    eng = with_first_shot(demo, engagement_starts(demo)).reset_index(drop=True)
    attacker, victim = windows(demo, eng, "attacker_steamid"), windows(demo, eng, "user_steamid")
    errors, view = aim_errors(attacker, victim)
    features = pd.DataFrame({
        "player": eng["attacker_steamid"],
        "err_500ms": errors[:, -33],
        "err_250ms": errors[:, -17],
        "err_125ms": errors[:, -9],
        "err_shot": errors[:, -1],
        "on_target_ms": ticks_on_target(errors) * 1000 / TICKRATE,
        "flick_deg_s": angle_deg(view[:, -9], view[:, -1]) * TICKRATE / 8,
        "speed_at_shot": np.hypot(attacker["velocity_X"][:, -1], attacker["velocity_Y"][:, -1]),
        "headshot": (eng["hitgroup"] == "head").astype(float),
    })
    return features[valid(attacker, victim)]


def extract(demo: Demo) -> pd.DataFrame:
    """Median aim features per player (robust to outliers); empty when too few engagements."""
    eng = engagements(demo)
    features = eng.groupby("player").median()
    enough = eng.groupby("player").size() >= MIN_ENGAGEMENTS
    return features.where(enough, np.nan)

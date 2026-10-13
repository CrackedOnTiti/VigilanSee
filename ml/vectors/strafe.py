"""Counter-strafe vector: how a player stops moving before he shoots — motor timing, meant to follow
the person across teams and roles (judge it on evaluate.py's cross-team row first).

Counter-strafing = while moving, tapping the opposite key (A→D, W→S) to stop dead, then shooting.
Anchored on the first shot of each burst; read from Demo.state() only (no extra parsing).
"""
import numpy as np
import pandas as pd

from common import TICKRATE, Demo
from vectors.aim import NON_GUNS

WINDOW = TICKRATE // 2  # look back 0.5 s before the shot
BURST_GAP = TICKRATE // 2  # a shot starts a new burst after 0.5 s without firing
SWITCH = TICKRATE // 4  # the counter key is pressed at most 0.25 s after the opposite key was held
MIN_COUNTERS = 10  # fewer counter-strafes in a demo = too noisy, features left empty
# (counter key, key the player was moving with)
DIRECTIONS = [("LEFT", "RIGHT"), ("RIGHT", "LEFT"), ("FORWARD", "BACK"), ("BACK", "FORWARD")]
MOVE_KEYS = ["FORWARD", "BACK", "LEFT", "RIGHT"]


def first_shots(demo: Demo) -> pd.DataFrame:
    """First gun shot of each burst, on the ground, outside warmup: columns steamid, tick."""
    fire = demo.event("weapon_fire")
    fire = fire[~fire["weapon"].str.contains(NON_GUNS)].rename(columns={"user_steamid": "steamid"})
    fire = fire[["steamid", "tick"]].sort_values(["steamid", "tick"])
    gap = fire.groupby("steamid")["tick"].diff()
    first = fire[gap.isna() | (gap > BURST_GAP)]
    airborne = demo.state()["is_airborne"].reindex(pd.MultiIndex.from_frame(first))
    on_ground = airborne.eq(False).to_numpy()  # NaN (warmup, not in state) counts as not on ground
    return first[on_ground].reset_index(drop=True)


def key_windows(state: pd.DataFrame, shots: pd.DataFrame) -> dict[str, np.ndarray]:
    """Movement keys held on the WINDOW + 1 ticks ending at each shot: one (n_shots, WINDOW + 1) bool
    array per key."""
    ticks = shots["tick"].to_numpy()[:, None] + np.arange(-WINDOW, 1)
    index = pd.MultiIndex.from_arrays([np.repeat(shots["steamid"].to_numpy(), WINDOW + 1), ticks.ravel()])
    rows = state[MOVE_KEYS].reindex(index).fillna(False).astype(bool)
    return {key: rows[key].to_numpy().reshape(ticks.shape) for key in MOVE_KEYS}


def recently(held: np.ndarray, span: int) -> np.ndarray:
    """True at column j if `held` was True in any of the `span` columns ending at j."""
    total = np.cumsum(held, axis=1)
    before = np.pad(total, ((0, 0), (span, 0)))[:, :-span]
    return total - before > 0


def last_counter(counter: np.ndarray, moving: np.ndarray) -> np.ndarray:
    """Column of the last press of `counter` while `moving` was held within SWITCH ticks, -1 if none."""
    press = counter & ~np.pad(counter, ((0, 0), (1, 0)))[:, :-1]
    press[:, 0] = False  # already held when the window starts: not a press we saw
    hits = press & recently(moving, SWITCH)
    return np.where(hits.any(axis=1), hits.shape[1] - 1 - hits[:, ::-1].argmax(axis=1), -1)


def counter_timings(keys: dict[str, np.ndarray]) -> pd.DataFrame:
    """Per shot: was it a counter-strafe, press → shot delay, was the counter key released before the shot
    and after how long (tap), and were both opposite keys held together at the press (overlap)."""
    cols = np.stack([last_counter(keys[c], keys[m]) for c, m in DIRECTIONS])
    best, press = cols.argmax(axis=0), cols.max(axis=0)
    shots = np.arange(len(press))
    counter = np.stack([keys[c] for c, _ in DIRECTIONS])[best, shots]
    moving = np.stack([keys[m] for _, m in DIRECTIONS])[best, shots]
    after = np.arange(WINDOW + 1) >= press[:, None]
    released = (~counter & after).any(axis=1)
    tap = (~counter & after).argmax(axis=1) - press
    found = press >= 0
    return pd.DataFrame({
        "counter": found,
        "press_to_shot_ms": np.where(found, (WINDOW - press) * 1000 / TICKRATE, np.nan),
        "released": np.where(found, released, np.nan),
        "tap_ms": np.where(found & released, tap * 1000 / TICKRATE, np.nan),
        "overlap": np.where(found, moving[shots, press.clip(0)], np.nan),
        "moving": np.any([k.any(axis=1) for k in keys.values()], axis=0),
    })


def extract(demo: Demo) -> pd.DataFrame:
    """Per player: how often he counter-strafes when moving before a shot, and his timings (medians)."""
    shots = first_shots(demo)
    per_shot = counter_timings(key_windows(demo.state(), shots)).assign(player=shots["steamid"])
    by_player = per_shot.groupby("player")
    counters = per_shot[per_shot["counter"]].groupby("player")
    features = pd.DataFrame({
        "still_frac": 1 - by_player["moving"].mean(),
        "counter_frac": counters.size() / per_shot[per_shot["moving"]].groupby("player").size(),
        "press_to_shot_ms": counters["press_to_shot_ms"].median(),
        "released_frac": counters["released"].mean(),
        "tap_ms": counters["tap_ms"].median(),
        "overlap_frac": counters["overlap"].mean(),
    })
    return features.where(counters.size().reindex(features.index) >= MIN_COUNTERS, np.nan)

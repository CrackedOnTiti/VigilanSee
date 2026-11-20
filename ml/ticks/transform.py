"""Pure transformations: demoparser2-shaped DataFrames -> the schema tables (SCHEMA.md).

No demoparser2 import here: everything takes plain DataFrames, so it is tested on fakes.
Every line tagged UNVERIFIED depends on what a real demo contains and must be checked on the first one.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from schema import BUTTONS, DEMO, EVENTS, TICKS

TICKRATE = 64  # same constant as ml/common.py. UNVERIFIED per demo: header has no explicit tick rate.
PLAYING_TEAMS = {2: "T", 3: "CT"}  # team_num; 0/1 = unassigned / spectators (coaches, casters)

# Per-tick props requested from demoparser2.
# VERIFIED = already read by ml/common.py or ml/vectors/aim.py on real demos.
VERIFIED_PROPS = [
    "X", "Y", "Z", "velocity_X", "velocity_Y", "pitch", "yaw",
    "FORWARD", "BACK", "LEFT", "RIGHT", "RELOAD", "INSPECT", "USE",
    "is_walking", "is_airborne", "ducking", "is_alive", "is_freeze_period", "is_warmup_period",
    "active_weapon_name", "active_weapon_ammo", "total_rounds_played", "team_num", "team_clan_name",
]
# UNVERIFIED: listed in demoparser2's docs, never read by our code. The parser drops them if refused.
OPTIONAL_PROPS = ["velocity_Z", "FIRE", "RIGHTCLICK", "WALK", "buttons"]

# CS2 input bitmask (InputBitMask_t), read from the raw `buttons` prop.
# UNVERIFIED: bit values from the Source 2 SDK headers, not checked against a demo.
IN_ATTACK, IN_JUMP, IN_DUCK, IN_ATTACK2, IN_SPEED = 1 << 0, 1 << 1, 1 << 2, 1 << 11, 1 << 16

# Schema button -> ordered sources: a named boolean prop, or a bit of the `buttons` bitmask.
# The first source present in the parsed frame wins; none present = column all False + reported.
BUTTON_SOURCES: dict[str, list[str | int]] = {
    "forward": ["FORWARD"], "back": ["BACK"], "left": ["LEFT"], "right": ["RIGHT"],  # VERIFIED
    "reload": ["RELOAD"], "use": ["USE"], "inspect": ["INSPECT"],  # VERIFIED
    "attack": ["FIRE", IN_ATTACK],  # UNVERIFIED
    "attack2": ["RIGHTCLICK", IN_ATTACK2],  # UNVERIFIED
    "walk": ["WALK", IN_SPEED],  # UNVERIFIED (the verified *state* is `walking`, from is_walking)
    "jump": [IN_JUMP],  # UNVERIFIED: no named prop known; scroll-wheel jumps may not show at all
    "duck": [IN_DUCK],  # UNVERIFIED (the verified *state* is `ducking`)
}

# Game event name -> how its columns map onto the events table (actor, target, weapon...).
# VERIFIED: weapon_fire (user_steamid, weapon), player_hurt (attacker_steamid, user_steamid, weapon,
# hitgroup). Everything else UNVERIFIED (names and columns from the CS2 game-event list).
GAME_EVENTS = {
    "round_start": {"type": "round_start"},
    "round_freeze_end": {"type": "freeze_end"},
    "round_end": {"type": "round_end", "detail": ["winner", "reason"]},
    "weapon_fire": {"type": "shot", "steamid": "user_steamid", "weapon": "weapon"},
    "player_hurt": {"type": "hurt", "steamid": "attacker_steamid", "target_steamid": "user_steamid",
                    "weapon": "weapon", "hitgroup": "hitgroup", "damage": "dmg_health"},
    "player_death": {"type": "kill", "steamid": "attacker_steamid", "target_steamid": "user_steamid",
                     "weapon": "weapon", "headshot": "headshot"},
    "player_jump": {"type": "jump_event", "steamid": "user_steamid"},
    **{name: {"type": name, "steamid": "user_steamid", "detail": ["site"]} for name in (
        "bomb_beginplant", "bomb_planted", "bomb_begindefuse", "bomb_defused", "bomb_exploded",
        "bomb_dropped", "bomb_pickup")},
}


@dataclass(frozen=True)
class DemoId:
    """Where a .dem file sits in our naming conventions (same as ml/extract.py and ml/common.py)."""

    match: str  # parent folder
    map_game: str  # file stem without -pN
    part: int  # N of -pN, 0 when the map is a single file
    demo_id: str  # <match>__<stem>, same key as data/fingerprints/<match>__<stem>.csv

    @classmethod
    def of(cls, path: Path) -> "DemoId":
        found = re.search(r"-p(\d+)$", path.stem)
        return cls(match=path.parent.name, map_game=re.sub(r"-p\d+$", "", path.stem),
                   part=int(found.group(1)) if found else 0, demo_id=f"{path.parent.name}__{path.stem}")

    def output_dir(self, root: Path) -> Path:
        return root / self.match / self.map_game

    def output_path(self, root: Path, table: str) -> Path:
        suffix = f"-p{self.part}" if self.part else ""
        return self.output_dir(root) / f"{table}{suffix}.parquet"


# ---------- ticks ----------

def playing_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Rows of real players outside warmup (drops coaches, casters, spectators, warmup ticks)."""
    warmup = raw["is_warmup_period"].fillna(False).astype(bool)
    return raw[~warmup & raw["team_num"].isin(list(PLAYING_TEAMS))]


def _flag(raw: pd.DataFrame, column: str) -> np.ndarray:
    """Boolean prop, None -> False (player disconnected / not spawned, as in ml/common.py)."""
    return raw[column].fillna(False).astype(bool).to_numpy()


def buttons(raw: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[str]]:
    """One held-flag array per schema button, plus the buttons for which no source was found."""
    mask = raw["buttons"].fillna(0).astype("uint64").to_numpy() if "buttons" in raw else None
    out, missing = {}, []
    for name in BUTTONS:
        for source in BUTTON_SOURCES[name]:
            if isinstance(source, str) and source in raw:
                out[name] = _flag(raw, source)
                break
            if isinstance(source, int) and mask is not None:
                out[name] = (mask & np.uint64(source)) != 0
                break
        else:
            out[name] = np.zeros(len(raw), dtype=bool)
            missing.append(name)
    return out, missing


def phases(raw: pd.DataFrame, round_end_ticks: np.ndarray) -> pd.Series:
    """Phase of every tick: 'freeze' (is_freeze_period), 'post' (after a round_end event and before the
    next freeze time) or 'live'. Returned indexed by tick."""
    freeze = raw.groupby("tick")["is_freeze_period"].agg(lambda s: s.fillna(False).astype(bool).any())
    ticks = freeze.index.to_numpy()
    starts = ticks[freeze.to_numpy() & ~np.r_[False, freeze.to_numpy()[:-1]]]
    bounds = np.r_[starts, np.asarray(round_end_ticks, dtype=ticks.dtype)]
    kinds = np.r_[np.zeros(len(starts), bool), np.ones(len(round_end_ticks), bool)]  # True = round_end
    order = np.argsort(bounds, kind="stable")
    bounds, kinds = bounds[order], kinds[order]
    last = np.searchsorted(bounds, ticks, side="right") - 1
    after_end = np.where(last >= 0, kinds[np.clip(last, 0, None)], False) if len(bounds) else False
    phase = np.where(freeze.to_numpy(), "freeze", np.where(after_end, "post", "live"))
    return pd.Series(phase, index=freeze.index, name="phase")


def ticks_table(raw: pd.DataFrame, demo_id: str, round_end_ticks: np.ndarray | None = None
                ) -> tuple[pd.DataFrame, list[str]]:
    """parse_ticks() output -> the `ticks` table (one row per player per tick), plus missing buttons.

    `round_end_ticks`: ticks of the round_end events (enables the 'post' phase)."""
    raw = playing_rows(raw).sort_values(["steamid", "tick"], kind="stable")
    round_end_ticks = np.array([] if round_end_ticks is None else round_end_ticks, dtype=np.int64)
    held, missing = buttons(raw)
    # Round index = rounds completed so far (0 on the first round), same for every player on a tick.
    # UNVERIFIED: whether total_rounds_played increments at round_end or at the next round start.
    rounds = raw.groupby("tick")["total_rounds_played"].max().fillna(0).astype(int)
    tick = raw["tick"].to_numpy()
    out = pd.DataFrame({
        "demo_id": demo_id,
        "tick": tick.astype(np.int32),
        "round": rounds.reindex(tick).to_numpy().astype(np.int16),
        "phase": phases(raw, round_end_ticks).reindex(tick).to_numpy(),
        "steamid": raw["steamid"].astype(str).to_numpy(),
        "side": raw["team_num"].map(PLAYING_TEAMS).to_numpy(),
        "x": raw["X"].to_numpy(np.float32), "y": raw["Y"].to_numpy(np.float32),
        "z": raw["Z"].to_numpy(np.float32),
        "vx": raw["velocity_X"].to_numpy(np.float32), "vy": raw["velocity_Y"].to_numpy(np.float32),
        "vz": (raw["velocity_Z"].to_numpy(np.float32) if "velocity_Z" in raw
               else np.full(len(raw), np.nan, np.float32)),
        "pitch": raw["pitch"].to_numpy(np.float32), "yaw": raw["yaw"].to_numpy(np.float32),
        **{f"btn_{name}": held[name] for name in BUTTONS},
        "weapon": raw["active_weapon_name"].where(raw["active_weapon_name"].notna(), None).to_numpy(),
        "ammo": pd.array(raw["active_weapon_ammo"].to_numpy(), dtype="Int16"),
        "alive": _flag(raw, "is_alive"), "airborne": _flag(raw, "is_airborne"),
        "ducking": _flag(raw, "ducking"), "walking": _flag(raw, "is_walking"),
    })
    return out.sort_values(["tick", "steamid"], kind="stable").reset_index(drop=True)[TICKS.names], missing


# ---------- events ----------

def _steamid(values: pd.Series) -> pd.Series:
    """SteamIDs as strings, with world / missing attackers as null. UNVERIFIED: world shows as 0 or None."""
    text = values.astype("string")
    bad = text.isna() | text.isin(["0", "None", "nan", ""])
    return text.astype(object).where(~bad.to_numpy(bool), None)


def from_game_event(raw: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """One parse_event() table -> events rows (no demo_id / round yet). Missing columns become null."""
    def column(name: str | None) -> pd.Series:
        return raw[name] if name and name in raw else pd.Series([None] * len(raw), index=raw.index)

    detail = None
    if "detail" in spec:
        parts = [f"{c}=" + raw[c].astype(str) for c in spec["detail"] if c in raw]
        detail = parts[0].str.cat(parts[1:], sep=";") if parts else None
    headshot = column(spec.get("headshot"))
    return pd.DataFrame({
        "tick": raw["tick"].to_numpy(),
        "type": spec["type"],
        "steamid": _steamid(column(spec.get("steamid"))).to_numpy(),
        "target_steamid": _steamid(column(spec.get("target_steamid"))).to_numpy(),
        "weapon": column(spec.get("weapon")).to_numpy(),
        "prev_weapon": None,
        "headshot": pd.array(headshot.to_numpy(), dtype="boolean"),
        "hitgroup": column(spec.get("hitgroup")).to_numpy(),
        "damage": pd.array(pd.to_numeric(column(spec.get("damage"))).to_numpy(), dtype="Int16"),
        "detail": detail.to_numpy() if detail is not None else None,
    })


def rising_edges(ticks: pd.DataFrame, column: str) -> pd.DataFrame:
    """Rows where `column` turns on for a player (ticks sorted by steamid, tick)."""
    flag = ticks[column].to_numpy(bool)
    same = ticks["steamid"].to_numpy() == np.r_[None, ticks["steamid"].to_numpy()[:-1]]
    before = np.r_[False, flag[:-1]] & same
    return ticks[flag & ~before]


def derived_events(ticks: pd.DataFrame) -> pd.DataFrame:
    """Events read from the ticks table: weapon switches, inspect presses, jump presses.

    A weapon switch is any change of the active weapon between two ticks of a live player, so it also
    counts automatic switches (grenade thrown, weapon dropped or picked up). UNVERIFIED how often."""
    t = ticks.sort_values(["steamid", "tick"], kind="stable")
    weapon = t["weapon"].astype(object).to_numpy()
    sid = t["steamid"].astype(str).to_numpy()
    alive = t["alive"].to_numpy(bool)
    prev_weapon = np.r_[None, weapon[:-1]]
    valid = (sid == np.r_[None, sid[:-1]]) & alive & np.r_[False, alive[:-1]]
    valid &= pd.notna(weapon) & pd.notna(prev_weapon)
    switch = valid & (weapon != prev_weapon)
    rows = [pd.DataFrame({"tick": t["tick"].to_numpy()[switch], "type": "weapon_switch",
                          "steamid": sid[switch], "weapon": weapon[switch],
                          "prev_weapon": prev_weapon[switch]})]
    for button, kind in (("btn_inspect", "inspect"), ("btn_jump", "jump")):
        edges = rising_edges(t.assign(steamid=sid), button)
        rows.append(pd.DataFrame({"tick": edges["tick"].to_numpy(), "type": kind,
                                  "steamid": edges["steamid"].to_numpy(),
                                  "weapon": edges["weapon"].to_numpy()}))
    return pd.concat(rows, ignore_index=True)


def events_table(raw_events: dict[str, pd.DataFrame], ticks: pd.DataFrame, demo_id: str) -> pd.DataFrame:
    """Game events (GAME_EVENTS) + events derived from the ticks table -> the `events` table.

    Each event gets the round of the last tick at or before it; events before the first kept tick
    (warmup) are dropped."""
    parts = [from_game_event(raw_events[name], spec) for name, spec in GAME_EVENTS.items()
             if name in raw_events and len(raw_events[name])]
    parts = [p for p in [*parts, derived_events(ticks)] if len(p)]
    events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["tick", "type"])
    events = events.reindex(columns=[c for c in EVENTS.names if c not in ("demo_id", "round")])
    events["tick"] = events["tick"].astype(np.int64)
    rounds = ticks.groupby("tick")["round"].max().reset_index().astype({"tick": np.int64})
    events = pd.merge_asof(events.sort_values("tick", kind="stable"), rounds, on="tick", direction="backward")
    events = events.dropna(subset=["round"])
    events["round"] = events["round"].astype(np.int16)
    events["tick"] = events["tick"].astype(np.int32)
    events["demo_id"] = demo_id
    events["headshot"] = events["headshot"].astype("boolean")
    events["damage"] = events["damage"].astype("Int16")
    for column in ("steamid", "target_steamid", "weapon", "prev_weapon", "hitgroup", "detail"):
        events[column] = events[column].astype(object).where(events[column].notna(), None)
    return events[EVENTS.names].reset_index(drop=True)


# ---------- demo metadata ----------

def demo_table(raw: pd.DataFrame, header: dict, ticks: pd.DataFrame, ident: DemoId, *,
               played_on: str | None, missing_buttons: list[str]) -> pd.DataFrame:
    """One row per player: demo-level metadata + name, team (at the player's last tick), first side.

    `header` is parse_header()'s dict. UNVERIFIED: its map key is `map_name`."""
    rows = playing_rows(raw).sort_values("tick", kind="stable")
    last = rows.groupby(rows["steamid"].astype(str)).last()
    first_side = ticks.groupby("steamid", observed=True)["side"].first()
    players = sorted(first_side.index.astype(str))
    return pd.DataFrame({
        "demo_id": ident.demo_id, "match": ident.match, "map_game": ident.map_game,
        "part": np.int8(ident.part), "map": header.get("map_name"), "tickrate": np.int16(TICKRATE),
        "played_on": played_on, "n_ticks": np.int32(ticks["tick"].nunique()),
        "steamid": players,
        "name": last["name"].reindex(players).to_numpy() if "name" in last else None,
        "team": last["team_clan_name"].reindex(players).to_numpy() if "team_clan_name" in last else None,
        "first_side": first_side.reindex(players).astype(str).to_numpy(),
        "missing_buttons": ",".join(missing_buttons) or None,
    })[DEMO.names]


def round_end_ticks(raw_events: dict[str, pd.DataFrame]) -> np.ndarray:
    end = raw_events.get("round_end")
    return np.array([] if end is None or not len(end) else end["tick"].to_numpy(), dtype=np.int64)


def transform(raw_ticks: pd.DataFrame, raw_events: dict[str, pd.DataFrame], header: dict,
              ident: DemoId, played_on: str | None) -> dict[str, pd.DataFrame]:
    """Everything parsed from one demo -> the three schema tables."""
    ticks, missing = ticks_table(raw_ticks, ident.demo_id, round_end_ticks(raw_events))
    return {
        "ticks": ticks,
        "events": events_table(raw_events, ticks, ident.demo_id),
        "demo": demo_table(raw_ticks, header, ticks, ident, played_on=played_on, missing_buttons=missing),
    }

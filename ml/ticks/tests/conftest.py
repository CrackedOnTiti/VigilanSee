"""Put ml/ticks on sys.path (the modules import each other by bare name, like the other ml/ scripts)
and build small fake frames shaped like demoparser2's output (documented column names)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

P1, P2, P3, COACH = "76561190000000001", "76561190000000002", "76561190000000003", "76561190000000099"


def fake_raw_ticks() -> pd.DataFrame:
    """3 players + 1 coach, ticks 0..39: warmup 0-4, round 0 freeze 5-9 / live 10-24 / post 25-29,
    round 1 freeze 30-34 / live 35-39. P1 and P2 are T, P3 is CT. Anonymised fake SteamIDs."""
    rows = []
    for tick in range(40):
        players = ((P1, 2, "alpha"), (P2, 2, "bravo"), (P3, 3, "charlie"), (COACH, 1, "coach"))
        for sid, team, name in players:
            rows.append({
                "tick": tick, "steamid": int(sid), "name": name,
                "X": float(tick), "Y": 0.0, "Z": 0.0,
                "velocity_X": 200.0, "velocity_Y": 0.0, "velocity_Z": 0.0,
                "pitch": 2.0, "yaw": 0.0,
                "FORWARD": True, "BACK": False, "LEFT": False, "RIGHT": False,
                "RELOAD": sid == P1 and tick in (12, 13), "INSPECT": sid == P1 and tick in (15, 31),
                "USE": False, "FIRE": False, "RIGHTCLICK": False, "WALK": False,
                "buttons": (1 << 1) if (sid == P1 and tick in (16, 18, 20)) else 0,
                "is_walking": False, "is_airborne": None if tick == 3 else False, "ducking": False,
                "is_alive": not (sid == P3 and tick >= 22),
                "is_freeze_period": tick in range(5, 10) or tick in range(30, 35),
                "is_warmup_period": tick < 5,
                "active_weapon_name": "Glock-18" if (sid == P1 and tick >= 14) else "AK-47",
                "active_weapon_ammo": 0 if (sid == P2 and tick >= 20) else 30,
                "total_rounds_played": 0 if tick < 28 else 1,
                "team_num": team, "team_clan_name": "Team A" if team == 2 else "Team B",
            })
    return pd.DataFrame(rows)


def fake_raw_events() -> dict[str, pd.DataFrame]:
    return {
        "round_end": pd.DataFrame({"tick": [25], "winner": [2], "reason": [9]}),
        "round_freeze_end": pd.DataFrame({"tick": [10, 35]}),
        "weapon_fire": pd.DataFrame({"tick": [2, 21], "user_steamid": [P1, P1], "weapon": ["ak47", "ak47"]}),
        "player_hurt": pd.DataFrame({"tick": [21], "attacker_steamid": [P1], "user_steamid": [P3],
                                     "weapon": ["ak47"], "hitgroup": ["head"], "dmg_health": [100]}),
        "player_death": pd.DataFrame({"tick": [22], "attacker_steamid": [P1], "user_steamid": [P3],
                                      "weapon": ["ak47"], "headshot": [True]}),
        "bomb_planted": pd.DataFrame({"tick": [37], "user_steamid": [P2], "site": [1]}),
        "player_jump": pd.DataFrame(columns=["tick", "user_steamid"]),
    }


@pytest.fixture
def raw_ticks() -> pd.DataFrame:
    return fake_raw_ticks()


@pytest.fixture
def raw_events() -> dict[str, pd.DataFrame]:
    return fake_raw_events()


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(0)

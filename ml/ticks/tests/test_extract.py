"""Transformation + validation + Parquet round trip, on fake demoparser2-shaped frames."""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from conftest import P1, P2, P3

import schema
from transform import DemoId, buttons, transform

IDENT = DemoId.of(Path("data/demos/some-match/team-a-vs-team-b-m1-mirage-p2.dem"))


@pytest.fixture
def tables(raw_ticks, raw_events) -> dict[str, pd.DataFrame]:
    return transform(raw_ticks, raw_events, {"map_name": "de_mirage"}, IDENT, "2026-11-20")


def test_demo_id_follows_extract_naming_with_part_suffix():
    assert IDENT.match == "some-match"
    assert IDENT.map_game == "team-a-vs-team-b-m1-mirage"
    assert IDENT.part == 2
    assert IDENT.demo_id == "some-match__team-a-vs-team-b-m1-mirage-p2"
    out = IDENT.output_path(Path("data/ticks"), "ticks")
    assert out == Path("data/ticks/some-match/team-a-vs-team-b-m1-mirage/ticks-p2.parquet")
    single = DemoId.of(Path("x/m/a-vs-b-m1-nuke.dem"))
    assert single.part == 0
    assert single.output_path(Path("o"), "events") == Path("o/m/a-vs-b-m1-nuke/events.parquet")


def test_ticks_drop_warmup_and_non_players(tables):
    ticks = tables["ticks"]
    assert ticks["tick"].min() == 5
    assert set(ticks["steamid"]) == {P1, P2, P3}
    assert len(ticks) == 3 * 35


def test_ticks_phases_follow_freeze_flag_and_round_end(tables):
    phase = tables["ticks"].drop_duplicates("tick").set_index("tick")["phase"]
    assert set(phase.loc[5:9]) == {"freeze"}
    assert set(phase.loc[10:24]) == {"live"}
    assert set(phase.loc[25:29]) == {"post"}
    assert set(phase.loc[30:34]) == {"freeze"}
    assert set(phase.loc[35:39]) == {"live"}


def test_ticks_columns_values_and_sides(tables):
    ticks = tables["ticks"].set_index(["steamid", "tick"])
    assert list(tables["ticks"].columns) == schema.TICKS.names
    assert ticks.loc[(P1, 12), "btn_reload"]
    assert ticks.loc[(P1, 16), "btn_jump"]  # from the buttons bitmask
    assert not ticks.loc[(P1, 17), "btn_jump"]
    assert ticks.loc[(P3, 10), "side"] == "CT"
    assert ticks.loc[(P1, 10), "side"] == "T"
    assert not ticks.loc[(P3, 30), "alive"]
    assert ticks.loc[(P1, 30), "round"] == 1


def test_missing_button_sources_are_reported_and_false(raw_ticks):
    held, missing = buttons(raw_ticks.drop(columns=["buttons", "FIRE"]))
    assert set(missing) == {"jump", "duck", "attack"}
    assert not held["jump"].any()


def test_events_from_game_events_and_ticks(tables):
    events = tables["events"]
    assert list(events.columns) == schema.EVENTS.names
    assert 2 not in set(events["tick"])  # warmup shot dropped
    kill = events[events["type"] == "kill"].iloc[0]
    assert (kill["steamid"], kill["target_steamid"], bool(kill["headshot"])) == (P1, P3, True)
    hurt = events[events["type"] == "hurt"].iloc[0]
    assert hurt["damage"] == 100 and hurt["hitgroup"] == "head"
    switch = events[events["type"] == "weapon_switch"]
    columns = ["tick", "steamid", "prev_weapon", "weapon"]
    assert switch[columns].to_numpy().tolist() == [[14, P1, "AK-47", "Glock-18"]]
    assert sorted(events[events["type"] == "inspect"]["tick"]) == [15, 31]
    assert sorted(events[events["type"] == "jump"]["tick"]) == [16, 18, 20]
    end = events[events["type"] == "round_end"].iloc[0]
    assert end["detail"] == "winner=2;reason=9" and end["round"] == 0
    assert events[events["type"] == "bomb_planted"].iloc[0]["round"] == 1


def test_demo_table_has_one_row_per_player(tables):
    demo = tables["demo"].set_index("steamid")
    assert sorted(demo.index) == sorted([P1, P2, P3])
    assert demo.loc[P3, "first_side"] == "CT"
    assert demo.loc[P1, "team"] == "Team A"
    assert set(demo["map"]) == {"de_mirage"}
    assert set(demo["part"]) == {2}
    assert demo["missing_buttons"].isna().all()


def test_parquet_round_trip_keeps_schema(tables, tmp_path):
    for name, table in tables.items():
        path = IDENT.output_path(tmp_path, name)
        schema.write(table, name, path)
        back = schema.read(path)
        assert list(back.columns) == list(table.columns)
        assert len(back) == len(table)
        pd.testing.assert_frame_equal(
            back.astype(object).where(back.notna(), None).reset_index(drop=True),
            table.astype(object).where(table.notna(), None).reset_index(drop=True), check_dtype=False)
    assert pq.read_schema(IDENT.output_path(tmp_path, "ticks")).equals(schema.TICKS, check_metadata=False)


def test_validation_rejects_duplicate_tick_rows(tables):
    ticks = tables["ticks"]
    with pytest.raises(schema.SchemaError, match="duplicate"):
        schema.to_arrow(pd.concat([ticks, ticks.iloc[:1]], ignore_index=True), "ticks")


def test_validation_rejects_missing_column_and_bad_type_and_bad_value(tables):
    ticks = tables["ticks"]
    with pytest.raises(schema.SchemaError, match="columns"):
        schema.to_arrow(ticks.drop(columns=["yaw"]), "ticks")
    with pytest.raises(schema.SchemaError, match="type"):
        schema.to_arrow(ticks.assign(x="not a number"), "ticks")
    with pytest.raises(schema.SchemaError, match="phase"):
        schema.to_arrow(ticks.assign(phase="halftime"), "ticks")
    with pytest.raises(schema.SchemaError, match="non-nullable"):
        schema.to_arrow(ticks.assign(tick=np.where(ticks.index == 0, np.nan, ticks["tick"])), "ticks")


def test_empty_event_kinds_are_fine(raw_ticks):
    tables = transform(raw_ticks, {}, {}, IDENT, None)
    for name, table in tables.items():
        schema.to_arrow(table, name)
    assert set(tables["events"]["type"]) <= {"weapon_switch", "inspect", "jump"}
    assert P2 in set(tables["demo"]["steamid"])

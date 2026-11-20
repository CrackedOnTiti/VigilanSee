"""Tick-level schema (see SCHEMA.md): column types, validation, Parquet write / read.

Pure pyarrow + pandas, no demoparser2: importable and testable without a demo.
"""
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PHASES = ("freeze", "live", "post")
SIDES = ("T", "CT")
# Schema field -> held flag, one boolean column per button (Parquet bit-packs them, ~free on disk).
BUTTONS = ("forward", "back", "left", "right", "jump", "duck", "walk",
           "attack", "attack2", "reload", "use", "inspect")

_DICT = pa.dictionary(pa.int32(), pa.string())  # low-cardinality strings: ids, names, phases

TICKS = pa.schema([
    pa.field("demo_id", _DICT, nullable=False),
    pa.field("tick", pa.int32(), nullable=False),
    pa.field("round", pa.int16(), nullable=False),
    pa.field("phase", _DICT, nullable=False),
    pa.field("steamid", _DICT, nullable=False),
    pa.field("side", _DICT, nullable=False),
    *[pa.field(c, pa.float32(), nullable=True) for c in ("x", "y", "z", "vx", "vy", "vz", "pitch", "yaw")],
    *[pa.field(f"btn_{b}", pa.bool_(), nullable=False) for b in BUTTONS],
    pa.field("weapon", _DICT, nullable=True),
    pa.field("ammo", pa.int16(), nullable=True),
    pa.field("alive", pa.bool_(), nullable=False),
    pa.field("airborne", pa.bool_(), nullable=False),
    pa.field("ducking", pa.bool_(), nullable=False),
    pa.field("walking", pa.bool_(), nullable=False),
])

EVENT_TYPES = (
    "round_start", "freeze_end", "round_end",
    "shot", "hurt", "kill",
    "weapon_switch", "inspect", "jump", "jump_event",
    "bomb_beginplant", "bomb_planted", "bomb_begindefuse", "bomb_defused", "bomb_exploded",
    "bomb_dropped", "bomb_pickup",
)

EVENTS = pa.schema([
    pa.field("demo_id", _DICT, nullable=False),
    pa.field("tick", pa.int32(), nullable=False),
    pa.field("round", pa.int16(), nullable=False),
    pa.field("type", _DICT, nullable=False),
    pa.field("steamid", _DICT, nullable=True),  # actor: shooter, attacker, killer, switcher, planter
    pa.field("target_steamid", _DICT, nullable=True),  # victim of hurt / kill
    pa.field("weapon", _DICT, nullable=True),  # weapon used, or weapon switched TO
    pa.field("prev_weapon", _DICT, nullable=True),  # weapon switched FROM
    pa.field("headshot", pa.bool_(), nullable=True),
    pa.field("hitgroup", _DICT, nullable=True),
    pa.field("damage", pa.int16(), nullable=True),
    pa.field("detail", _DICT, nullable=True),  # free text: round_end winner / reason, bomb site
])

DEMO = pa.schema([  # one row per player of the demo; the demo-level fields repeat
    pa.field("demo_id", _DICT, nullable=False),
    pa.field("match", _DICT, nullable=False),
    pa.field("map_game", _DICT, nullable=False),
    pa.field("part", pa.int8(), nullable=False),  # 0 = single file, N = the -pN part of a split map
    pa.field("map", _DICT, nullable=True),
    pa.field("tickrate", pa.int16(), nullable=False),
    pa.field("played_on", _DICT, nullable=True),  # ISO date, from the .dem mtime (as ml/common.py)
    pa.field("n_ticks", pa.int32(), nullable=False),
    pa.field("steamid", _DICT, nullable=False),
    pa.field("name", _DICT, nullable=True),
    pa.field("team", _DICT, nullable=True),  # team_clan_name
    pa.field("first_side", _DICT, nullable=False),
    pa.field("missing_buttons", _DICT, nullable=True),  # buttons with no source in this demo (all False)
])

TABLES = {"ticks": TICKS, "events": EVENTS, "demo": DEMO}


class SchemaError(ValueError):
    """A table does not match its schema."""


def to_arrow(df: pd.DataFrame, table: str) -> pa.Table:
    """Validate `df` against TABLES[table] and convert it. Raises SchemaError on any mismatch."""
    schema = TABLES[table]
    expected = list(schema.names)
    if list(df.columns) != expected:
        missing = sorted(set(expected) - set(df.columns))
        extra = sorted(set(df.columns) - set(expected))
        raise SchemaError(f"{table}: columns differ (missing {missing}, extra {extra}, or wrong order)")
    for field in schema:
        if not field.nullable and df[field.name].isna().any():
            raise SchemaError(f"{table}.{field.name}: nulls in a non-nullable column")
    try:
        arrow = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError) as err:
        raise SchemaError(f"{table}: type mismatch: {err}") from err
    _check_values(df, table)
    return arrow


def _check_values(df: pd.DataFrame, table: str) -> None:
    """Content rules the types alone can't express."""
    if table == "ticks":
        if df.duplicated(["demo_id", "tick", "steamid"]).any():
            raise SchemaError("ticks: duplicate (tick, steamid) rows")
        _check_in(df, "ticks", "phase", PHASES)
        _check_in(df, "ticks", "side", SIDES)
    elif table == "events":
        _check_in(df, "events", "type", EVENT_TYPES)
    elif table == "demo":
        if df["steamid"].duplicated().any():
            raise SchemaError("demo: duplicate steamid rows")
        _check_in(df, "demo", "first_side", SIDES)


def _check_in(df: pd.DataFrame, table: str, column: str, allowed: tuple[str, ...]) -> None:
    bad = set(df[column].dropna().astype(str).unique()) - set(allowed)
    if bad:
        raise SchemaError(f"{table}.{column}: unexpected values {sorted(bad)}")


def write(df: pd.DataFrame, table: str, path: Path) -> None:
    """Validate then write one table as a zstd-compressed Parquet file."""
    arrow = to_arrow(df, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(arrow, path, compression="zstd")


def read(path: Path) -> pd.DataFrame:
    """Read one table back (dictionary columns come back as pandas categoricals)."""
    return pq.read_table(path).to_pandas()


def empty(table: str) -> pd.DataFrame:
    """An empty DataFrame with the table's columns (for demos without any event of a kind)."""
    return TABLES[table].empty_table().to_pandas()

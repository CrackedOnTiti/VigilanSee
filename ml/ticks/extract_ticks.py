# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["demoparser2", "pandas", "numpy", "pyarrow"]
# ///
"""Turn demos into tick-level Parquet tables (ticks, events, demo), see SCHEMA.md.

Usage: uv run ml/ticks/extract_ticks.py <demo.dem | folder> [--out data/ticks] [--force] [--workers N]

Writes data/ticks/<match_folder>/<map_game>/{ticks,events,demo}[-pN].parquet. A map split in two files
(-p1 / -p2, same convention as ml/extract.py) lands in the same folder with the part as suffix.
Demos already extracted are skipped unless --force.

UNVERIFIED end to end: written without a demo file. parse_demo() is the only function touching
demoparser2; everything it returns goes through transform.py, which is tested on fake frames.
"""
import argparse
import datetime as dt
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

import schema
from transform import GAME_EVENTS, OPTIONAL_PROPS, VERIFIED_PROPS, DemoId, transform

WORKERS = 2  # a full-tick parse of every prop is heavier than ml/extract.py's (~2 GB per worker there)


def parse_demo(path: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict]:
    """The thin demoparser2 layer: raw per-tick props, raw game events, header. No transformation."""
    from demoparser2 import DemoParser  # noqa: PLC0415  lazy: the rest of the module runs without it

    parser = DemoParser(str(path))
    try:
        raw_ticks = parser.parse_ticks(VERIFIED_PROPS + OPTIONAL_PROPS)
    except Exception as err:  # UNVERIFIED: demoparser2 raises on an unknown prop name
        print(f"WARNING {path.name}: optional props refused ({err}); parsing verified props only")
        raw_ticks = parser.parse_ticks(VERIFIED_PROPS)
    raw_events = {}
    for name in GAME_EVENTS:
        try:
            raw_events[name] = parser.parse_event(name)
        except Exception as err:  # UNVERIFIED: behaviour for an event absent from the demo
            print(f"WARNING {path.name}: event {name} not parsed ({err})")
    return raw_ticks, raw_events, parser.parse_header()


def played_on(path: Path) -> str:
    """Day the match was played = the .dem file's date (same rule as ml/common.py)."""
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).date().isoformat()


def extract_one(dem: Path, out: Path) -> str:
    """Parse, transform, validate and write the three tables of one demo (runs in a worker)."""
    start, ident = time.time(), DemoId.of(dem)
    tables = transform(*parse_demo(dem), ident, played_on(dem))
    for name, table in tables.items():
        schema.to_arrow(table, name)  # validate all three before writing any
    for name, table in tables.items():
        schema.write(table, name, ident.output_path(out, name))
    missing = tables["demo"]["missing_buttons"].iloc[0] if len(tables["demo"]) else None
    note = f", no source for buttons: {missing}" if missing else ""
    return (f"{dem.name}: {len(tables['ticks'])} tick rows, {len(tables['events'])} events, "
            f"{len(tables['demo'])} players{note}, {time.time() - start:.0f}s")


def demos_to_process(target: Path, out: Path, force: bool) -> list[Path]:
    demos = [target] if target.suffix == ".dem" else sorted(target.rglob("*.dem"))
    return [d for d in demos if force or not DemoId.of(d).output_path(out, "ticks").exists()]


def main(target: Path, out: Path, force: bool, workers: int) -> None:
    demos = demos_to_process(target, out, force)
    print(f"{len(demos)} demo(s) to process, {workers} at a time", flush=True)
    with ProcessPoolExecutor(workers) as pool:
        for line in pool.map(extract_one, demos, [out] * len(demos)):
            print(line, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Demos -> tick-level Parquet tables (see SCHEMA.md).")
    cli.add_argument("target", type=Path, help="a .dem file or a folder searched recursively")
    cli.add_argument("--out", type=Path, default=Path("data/ticks"))
    cli.add_argument("--force", action="store_true", help="redo demos already extracted")
    cli.add_argument("--workers", type=int, default=WORKERS)
    args = cli.parse_args()
    main(args.target, args.out, args.force, args.workers)

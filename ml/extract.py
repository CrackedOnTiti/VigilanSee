# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["demoparser2", "pandas", "numpy"]
# ///
"""Run every registered measurement vector on every demo → one fingerprint file per demo.

Usage: uv run ml/extract.py [demos_dir] [--force] [--only VECTOR]   (default: data/demos)
       --only strafe   (re)compute one vector and merge its columns into the existing fingerprints
"""
import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from common import Demo
from vectors import VECTORS

OUT_DIR = Path("data/fingerprints")
WORKERS = 4  # demos parsed in parallel; a big demo takes ~2 GB of RAM per worker


def fingerprint(demo: Demo) -> pd.DataFrame:
    """Roster + every vector's features, one row per player of this demo."""
    parts = [demo.roster()]
    for name, extract in VECTORS.items():
        parts.append(extract(demo).add_prefix(f"{name}."))
    table = pd.concat(parts, axis=1).reindex(demo.roster().index)  # drop non-players (coaches…)
    return table.assign(match=demo.match, map_game=demo.map_game, demo=demo.path.name)


def output_path(dem: Path) -> Path:
    """One file per demo; the match folder is part of the name because demo names repeat across events."""
    return OUT_DIR / f"{dem.parent.name}__{dem.stem}.csv"


def check_roster(table: pd.DataFrame, dem: Path) -> None:
    """Warn when a demo doesn't hold 10 players split into 2 teams (bad ground truth)."""
    if len(table) != 10 or table["team"].nunique() != 2:
        print(f"WARNING {dem.name}: {len(table)} players, teams {sorted(table['team'].unique())}")


def extract_one(dem: Path) -> str:
    """Fingerprint one demo and write it (runs in a worker process)."""
    start = time.time()
    table = fingerprint(Demo(dem))
    check_roster(table, dem)
    table.to_csv(output_path(dem), index_label="player")
    return f"{dem.name}: {len(table)} players, {time.time() - start:.0f}s"


def add_vector(dem: Path, name: str) -> str:
    """Recompute one vector on a demo and swap its columns in the existing fingerprint file."""
    start, out = time.time(), output_path(dem)
    table = pd.read_csv(out, index_col="player", dtype={"player": str})
    table = table.drop(columns=[c for c in table.columns if c.startswith(f"{name}.")])
    table = table.join(VECTORS[name](Demo(dem)).add_prefix(f"{name}."))
    table.to_csv(out, index_label="player")
    return f"{dem.name}: {name} added, {time.time() - start:.0f}s"


def demos_to_process(demos_dir: Path, force: bool, only: str | None) -> list[Path]:
    """Demos to process: without a fingerprint (full run), or with one (--only adds to it)."""
    demos = sorted(demos_dir.rglob("*.dem"))
    if only:
        return [dem for dem in demos if output_path(dem).exists()]
    return [dem for dem in demos if force or not output_path(dem).exists()]


def main(demos_dir: Path, force: bool, only: str | None) -> None:
    """Process the demos in parallel and print one line per demo as it finishes."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    demos = demos_to_process(demos_dir, force, only)
    print(f"{len(demos)} demo(s) to process, {WORKERS} at a time", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool:
        jobs = pool.map(add_vector, demos, [only] * len(demos)) if only else pool.map(extract_one, demos)
        for line in jobs:
            print(line, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Run the measurement vectors on demos → data/fingerprints/.")
    cli.add_argument("demos_dir", nargs="?", type=Path, default=Path("data/demos"))
    cli.add_argument("--force", action="store_true", help="redo demos already extracted")
    cli.add_argument("--only", choices=VECTORS, help="(re)compute one vector into existing fingerprints")
    args = cli.parse_args()
    main(args.demos_dir, args.force, args.only)

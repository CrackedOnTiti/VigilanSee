# ml/ticks: tick-level tables and behavioural features (issue #36)

Groundwork for #37 (aim), #38 (motor habits) and #39 (movement matrix). Written without a demo file:
the demoparser2 call is unverified, everything after it is tested on synthetic data.

| File | What | Verified? |
|---|---|---|
| `SCHEMA.md` | the three tables (`ticks`, `events`, `demo`), sources, size per demo | per-field status in the doc |
| `schema.py` | pyarrow schemas, validation, Parquet write / read | tested |
| `transform.py` | demoparser2-shaped DataFrames -> schema tables (pure) | tested on fake frames |
| `extract_ticks.py` | CLI + `parse_demo()`, the only code calling demoparser2 | **not run on a demo yet** |
| `features.py` | routes, movement matrix, habits, event responses, shrinkage (pure numpy) | tested on synthetic data |
| `tests/` | pytest suite | |

## Run

```bash
# Extract (needs a demo): writes data/ticks/<match_folder>/<map_game>/{ticks,events,demo}[-pN].parquet
uv run ml/ticks/extract_ticks.py data/demos/<match_folder>/<demo>.dem
uv run ml/ticks/extract_ticks.py data/demos --out data/ticks --workers 2 [--force]

# Tests (no demo, no demoparser2 needed)
uv run --with pytest --with numpy --with pandas --with pyarrow pytest ml/ticks

# Lint (same config as the rest of ml/)
uvx ruff check --config ml/ruff.toml ml/ticks
```

The test command lists numpy / pandas / pyarrow because `pytest` does not read the inline script
metadata of the modules it imports.

The modules import each other by bare name (`import schema`), like the other `ml/` scripts. They do
not import `ml/common.py` because it imports demoparser2 at the top; `TICKRATE`, the team codes and
the `-pN` naming rule are repeated in `transform.py` instead.

## Features (`features.py`)

All distributions are returned as **counts** so they add up across matches and can be shrunk toward
the player's global profile with `shrink_counts(c_cell, c_global, k) = (c + k p_global) / (n + k)`.

1. Opening routes: `opening_paths`, `resample_path`, `route_distance`, `route_templates`
   (average-linkage clustering with a distance threshold, medoid templates + usage counts),
   `nearest_template_distance`. Build templates per (player, map, side).
2. Movement matrix: `movement_states` (27 states: speed x turn x direction vs view),
   `player_states`, `transition_counts`, `transition_divergence`.
3. Habits: `pitch_histogram`, `inspect_rhythm`, `jump_bursts`, `switch_signature` (scroll vs number
   keys, see the caveat in its docstring).
4. Event responses: `event_responses` (counts, follow-up rate and latency histogram per
   trigger x action), `player_timeline` (reads triggers and actions from the tables).
5. `shrink_counts`.

Thresholds (`STILL_SPEED`, `WALK_SPEED`, `SLIGHT_TURN`, `SHARP_TURN`, bins, windows) are defaults to
tune on real data.

## Check on the first real demo

1. `parse_ticks` accepts the optional props `velocity_Z`, `FIRE`, `RIGHTCLICK`, `WALK`, `buttons`
   (otherwise the extractor falls back to verified props and prints a warning).
2. `buttons` bitmask: IN_ATTACK `1<<0`, IN_JUMP `1<<1`, IN_DUCK `1<<2`, IN_ATTACK2 `1<<11`,
   IN_SPEED `1<<16`. Check `btn_jump` against `jump_event` (`player_jump`) and `airborne`, and
   `btn_duck` against `ducking`.
3. Do scroll-wheel jumps appear as several presses in the per-tick button state, or merge into one
   held press, or not appear at all (sub-tick only)? This decides whether `jump_bursts` works.
4. Tick rate is 64 for every demo (no explicit field in the header).
5. `parse_header()` has `map_name`.
6. `total_rounds_played` increments at `round_end` or at the next round start (decides the round of
   `post` ticks).
7. Event names and columns: `round_start`, `round_freeze_end`, `round_end` (`winner`, `reason`),
   `player_death` (`attacker_steamid`, `user_steamid`, `weapon`, `headshot`), `player_hurt.dmg_health`,
   `player_jump`, bomb events (`user_steamid`, `site`).
8. How demoparser2 behaves for an event absent from the demo (raises, or returns an empty frame).
9. World damage / unknown attacker SteamID encoding (`0`, `None`, or missing).
10. `yaw` range (-180..180 or 0..360); the code wraps differences either way.
11. `active_weapon_name` strings for pistols, grenades, C4, Zeus (`weapon_slot()` regexes), and the
    Zeus slot.
12. Fast weapon switch: scroll detection only works with it on; check how many switches pass through
    intermediate slots, and how many weapon changes are automatic (grenade thrown, pickup, drop).
13. Ticks numbering in `-p2` files (restarts or continues); rows stay unique either way since
    `demo_id` includes the part.
14. File sizes vs the synthetic estimate in `SCHEMA.md`.
15. Movement thresholds: speed distribution of walking vs running players, yaw change per tick.

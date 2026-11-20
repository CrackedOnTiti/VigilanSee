# Tick-level schema (issue #36)

What one demo becomes. Three Parquet files per demo (zstd), written by `extract_ticks.py`:

```
data/ticks/<match_folder>/<map_game>/ticks.parquet
data/ticks/<match_folder>/<map_game>/events.parquet
data/ticks/<match_folder>/<map_game>/demo.parquet
```

`<match_folder>` and `<map_game>` follow `ml/extract.py` / `ml/common.py`: the parent folder of the
`.dem`, and the file stem without `-pN`. A map split in two files writes `ticks-p1.parquet`,
`ticks-p2.parquet` (same for the other tables) in the same folder. `demo_id` = `<match_folder>__<stem>`,
the same key as `data/fingerprints/<match_folder>__<stem>.csv`.

The column definitions live in `schema.py` (pyarrow schemas); this file explains them.
`schema.to_arrow()` validates every table before it is written: exact columns and order, types,
no nulls in non-nullable columns, allowed values (phase, side, event type), no duplicate
`(demo_id, tick, steamid)` rows.

**Status column.** `verified` = the demoparser2 prop / event is already read by `ml/common.py` or
`ml/vectors/*.py` on real demos. `unverified` = taken from demoparser2's documentation (or the CS2
game-event list) only; to check on the first demo. `derived` = computed by us from other columns.

## `ticks`: one row per player per tick

Rows kept: players with `team_num` 2 (T) or 3 (CT), outside warmup (`is_warmup_period`). Coaches,
casters and spectators are dropped. Dead players keep their rows (`alive = false`).

| Column | Type | Unit / values | Source | Status |
|---|---|---|---|---|
| `demo_id` | dict string | `<match>__<stem>` | file path | derived |
| `tick` | int32 | server tick | `tick` column of `parse_ticks` | verified |
| `round` | int16 | 0 = first round | `total_rounds_played`, max over players on the tick | verified prop; timing of the increment unverified |
| `phase` | dict string | `freeze` / `live` / `post` | `is_freeze_period` + `round_end` event ticks | prop verified, `round_end` unverified |
| `steamid` | dict string | SteamID64 | `steamid` | verified |
| `side` | dict string | `T` / `CT` | `team_num` (2 / 3) | verified |
| `x`, `y`, `z` | float32 | game units | `X`, `Y`, `Z` | verified |
| `vx`, `vy` | float32 | units / s | `velocity_X`, `velocity_Y` | verified |
| `vz` | float32 | units / s | `velocity_Z` (null if refused) | unverified |
| `pitch` | float32 | degrees, positive = looking down | `pitch` | verified |
| `yaw` | float32 | degrees, range unverified (-180..180 assumed, code wraps) | `yaw` | verified |
| `btn_forward`, `btn_back`, `btn_left`, `btn_right` | bool | held | `FORWARD`, `BACK`, `LEFT`, `RIGHT` | verified |
| `btn_reload`, `btn_use`, `btn_inspect` | bool | held | `RELOAD`, `USE`, `INSPECT` | verified |
| `btn_attack` | bool | held | `FIRE`, else bit `1<<0` of `buttons` | unverified |
| `btn_attack2` | bool | held | `RIGHTCLICK`, else bit `1<<11` of `buttons` | unverified |
| `btn_walk` | bool | held | `WALK`, else bit `1<<16` (IN_SPEED) of `buttons` | unverified |
| `btn_jump` | bool | held | bit `1<<1` (IN_JUMP) of `buttons` | unverified |
| `btn_duck` | bool | held | bit `1<<2` (IN_DUCK) of `buttons` | unverified |
| `weapon` | dict string, nullable | e.g. `AK-47`, `Glock-18` | `active_weapon_name` | verified |
| `ammo` | int16, nullable | bullets in clip | `active_weapon_ammo` | verified |
| `alive` | bool | | `is_alive` | verified |
| `airborne` | bool | | `is_airborne` | verified |
| `ducking` | bool | crouched state (not the key) | `ducking` | verified |
| `walking` | bool | shift-walk state (not the key) | `is_walking` | verified |

Boolean props that come back as `None` (player disconnected / not spawned) become `false`, as in
`ml/common.py`. A button with no source in a demo is stored as all `false` and listed in
`demo.missing_buttons`, so feature code can refuse to use it.

Phase rule: `freeze` while `is_freeze_period`; `post` after a `round_end` event until the next freeze
time; `live` otherwise. Without `round_end` events there is no `post` phase.

## `events`: one row per event

| Column | Type | Meaning |
|---|---|---|
| `demo_id` | dict string | as in `ticks` |
| `tick` | int32 | tick of the event |
| `round` | int16 | round of the last `ticks` tick at or before the event; events before the first kept tick (warmup) are dropped |
| `type` | dict string | see below |
| `steamid` | dict string, nullable | actor: shooter, attacker, killer, switcher, planter |
| `target_steamid` | dict string, nullable | victim (hurt, kill) |
| `weapon` | dict string, nullable | weapon used, or weapon switched to |
| `prev_weapon` | dict string, nullable | weapon switched from |
| `headshot` | bool, nullable | kill only |
| `hitgroup` | dict string, nullable | hurt only |
| `damage` | int16, nullable | hurt only, health damage |
| `detail` | dict string, nullable | `winner=..;reason=..` (round_end), `site=..` (bomb) |

| `type` | Source | Columns used | Status |
|---|---|---|---|
| `round_start` | event `round_start` | | unverified |
| `freeze_end` | event `round_freeze_end` | | unverified |
| `round_end` | event `round_end` | `winner`, `reason` | unverified |
| `shot` | event `weapon_fire` | `user_steamid`, `weapon` | verified |
| `hurt` | event `player_hurt` | `attacker_steamid`, `user_steamid`, `weapon`, `hitgroup`, `dmg_health` | verified except `dmg_health` |
| `kill` | event `player_death` | `attacker_steamid`, `user_steamid`, `weapon`, `headshot` | unverified |
| `jump_event` | event `player_jump` | `user_steamid` | unverified (kept to cross-check `btn_jump`) |
| `bomb_beginplant`, `bomb_planted`, `bomb_begindefuse`, `bomb_defused`, `bomb_exploded`, `bomb_dropped`, `bomb_pickup` | events of the same name | `user_steamid`, `site` | unverified |
| `weapon_switch` | `ticks.weapon` changes between two ticks of a live player | `weapon`, `prev_weapon` | derived (same rule as `vectors/habits.py`) |
| `inspect` | rising edge of `ticks.btn_inspect` | | derived from a verified prop |
| `jump` | rising edge of `ticks.btn_jump` | | derived from an unverified bit |

World damage / unknown attackers: SteamID `0` or missing becomes null (unverified how demoparser2
encodes them). Weapon names in game events (`ak47`) differ from `active_weapon_name` (`AK-47`):
they are kept as given.

## `demo`: one row per player

| Column | Type | Source | Status |
|---|---|---|---|
| `demo_id`, `match`, `map_game` | dict string | file path | derived |
| `part` | int8 | `-pN` suffix, 0 if none | derived |
| `map` | dict string, nullable | `parse_header()["map_name"]` | unverified key |
| `tickrate` | int16 | constant 64 (as `ml/common.py`) | unverified per demo |
| `played_on` | dict string | `.dem` mtime, ISO date (rule of `ml/common.py`) | verified rule |
| `n_ticks` | int32 | distinct ticks in `ticks` | derived |
| `steamid` | dict string | | verified |
| `name` | dict string | `name` at the player's last tick | verified |
| `team` | dict string | `team_clan_name` at the player's last tick | verified |
| `first_side` | dict string | `side` at the player's first tick | derived |
| `missing_buttons` | dict string, nullable | comma-separated buttons with no source | derived |

`name` is kept for parity with `data/fingerprints/`; it is not needed by any feature and can be
dropped if the privacy rules require it.

## Size per demo

Rows: 10 players x 64 ticks/s x 40 min = **1.54 M rows** per demo (a full 40 min map; warmup excluded).

Measured on a synthetic 1.54 M-row table with realistic shapes (smooth random-walk positions and view
angles, sparse button presses, weapon and round runs), zstd, via `schema.write()`:

| Columns | Parquet size |
|---|---|
| position `x`, `y`, `z` | 18.8 MB |
| velocity `vx`, `vy`, `vz` | 20.1 MB |
| `pitch`, `yaw` | 12.4 MB |
| 12 button columns | 1.0 MB |
| everything else (ids, round, phase, side, weapon, ammo, flags) | 5.0 MB |
| **total `ticks` per demo** | **57 MB** (253 MB in memory as pandas) |

The float columns are 90% of the file. Our random-walk floats barely compress; real velocities are
often exactly 0 or a constant max speed, and dead players repeat their last values, so a real demo
should come in lower. Treat ~60 MB per 40 min map as the upper estimate and re-measure on the first
real demo. If size matters later, Parquet's `BYTE_STREAM_SPLIT` encoding for the float columns is the
first thing to try. `events` is small (tens of thousands of rows, well under 1 MB) and `demo` is
negligible.

### Is every tick needed?

Yes for anything about aim and motor timing: view-angle speed / acceleration during flicks (#37),
key-tap durations and counter-strafe timing (#38), the movement matrix (#39) all live at tick
resolution, and some already lose information to sub-tick inputs. Buttons and flags cost almost
nothing (Parquet bit-packs and run-length encodes them). Only positions could be downsampled (routes
need about 8 Hz), but positions are also needed at full rate for velocity checks and aim geometry, and
the saving would be a few MB per demo. Recommendation: keep every tick for every column, and
downsample in the feature code where useful.

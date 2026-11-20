"""Behavioural feature functions on the tick schema (SCHEMA.md): routes, movement matrix, habits,
event responses, shrinkage. Pure numpy (pandas only in the thin per-player adapters).

Every distribution is returned as COUNTS (histograms, transition counts), never as probabilities, so
it can be summed across matches and shrunk toward the player's global profile with shrink_counts(),
the same way the per-map profiles work (w = n / (n + k)).
"""
import re

import numpy as np
import pandas as pd

TICKRATE = 64  # UNVERIFIED per demo, see transform.TICKRATE


# ---------- small helpers ----------

def wrap_deg(angle: np.ndarray) -> np.ndarray:
    """Angle(s) wrapped to [-180, 180)."""
    return (np.asarray(angle, dtype=float) + 180.0) % 360.0 - 180.0


def rising(flag: np.ndarray) -> np.ndarray:
    """True where a boolean sequence turns on (index 0 counts if it starts on)."""
    flag = np.asarray(flag, dtype=bool)
    return flag & ~np.r_[False, flag[:-1]]


def histogram(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Integer counts on fixed `edges`; values beyond the outer edges go to the outer bins, NaN dropped."""
    values = np.asarray(values, dtype=float)
    values = np.clip(values[np.isfinite(values)], edges[0], edges[-1])
    return np.histogram(values, bins=edges)[0].astype(np.int64)


def player_rows(ticks: pd.DataFrame, steamid: str) -> pd.DataFrame:
    """One player's rows of the ticks table, sorted by tick."""
    return ticks[ticks["steamid"].astype(str) == steamid].sort_values("tick", kind="stable")


def round_bounds(ticks: pd.DataFrame) -> pd.DataFrame:
    """Per round: first freeze tick (round start) and first live tick (freeze end), indexed by round.
    Read from the ticks table (phase comes from is_freeze_period, verified) rather than from the
    round_start / round_freeze_end events (unverified). The first freeze tick, not the round's first
    tick, because 'post' ticks may already carry the next round number (unverified increment timing).
    A round without freeze time falls back to its first tick."""
    phase = ticks["phase"].astype(str)
    first = ticks.groupby("round")["tick"].min()
    freeze = ticks[phase == "freeze"].groupby("round")["tick"].min()
    first = freeze.reindex(first.index).fillna(first).astype(int).rename("start")
    live = ticks[phase == "live"].groupby("round")["tick"].min().rename("freeze_end")
    return pd.concat([first, live], axis=1)


# ---------- 1. opening routes ----------

def opening_paths(ticks: pd.DataFrame, events: pd.DataFrame, *, limit_s: float = 20.0,
                  tickrate: int = TICKRATE, contact_types: tuple[str, ...] = ("shot", "hurt"),
                  dims: tuple[str, ...] = ("x", "y")) -> dict[tuple[str, int], np.ndarray]:
    """Each player's path from freeze end to first contact, death, or `limit_s` seconds, per round.

    First contact = first `contact_types` event where the player is the actor or the target.
    Returns {(steamid, round): (n_points, len(dims)) array}. Paths with fewer than 2 points are skipped.
    Templates only make sense per (player, map, side): group the paths before calling route_templates."""
    starts = round_bounds(ticks)["freeze_end"].dropna().astype(int)
    contact = events[events["type"].astype(str).isin(contact_types)]
    targets = contact[["tick", "round", "target_steamid"]].rename(columns={"target_steamid": "steamid"})
    who = pd.concat([contact[["tick", "round", "steamid"]], targets])
    who = who.dropna(subset=["steamid"]).astype({"steamid": str})
    live = ticks[ticks["alive"] & (ticks["phase"].astype(str) == "live") & ticks["round"].isin(starts.index)]
    live = live.astype({"steamid": str})
    paths = {}
    for (sid, rnd), rows in live.groupby(["steamid", "round"], observed=True):
        start = int(starts[rnd])
        end = start + int(limit_s * tickrate)
        hits = who[(who["steamid"] == sid) & (who["round"] == rnd) & (who["tick"] >= start)]["tick"]
        if len(hits):
            end = min(end, int(hits.min()))
        window = rows[(rows["tick"] >= start) & (rows["tick"] <= end)].sort_values("tick")
        if len(window) >= 2:
            paths[(sid, int(rnd))] = window[list(dims)].to_numpy(dtype=float)
    return paths


def resample_path(points: np.ndarray, n: int = 32) -> np.ndarray:
    """`n` points evenly spaced along the path's arc length (first and last points kept).
    A path that never moves gives n copies of its point."""
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or len(pts) == 0:
        raise ValueError("points must be a non-empty (m, d) array")
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    keep = np.r_[True, seg > 0]  # repeated points (standing still) break np.interp
    arc = np.r_[0.0, np.cumsum(seg)][keep]
    pts = pts[keep]
    if arc[-1] == 0:
        return np.repeat(pts[:1], n, axis=0)
    target = np.linspace(0.0, arc[-1], n)
    return np.stack([np.interp(target, arc, pts[:, d]) for d in range(pts.shape[1])], axis=1)


def route_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean pointwise Euclidean distance between two resampled paths of the same shape (game units)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"paths must be resampled to the same shape, got {a.shape} and {b.shape}")
    return float(np.linalg.norm(a - b, axis=1).mean())


def distance_matrix(resampled: np.ndarray) -> np.ndarray:
    """Pairwise route_distance between (m, n, d) resampled paths, one row at a time (bounded memory)."""
    m = len(resampled)
    out = np.zeros((m, m))
    for i in range(m):
        out[i] = np.linalg.norm(resampled - resampled[i], axis=2).mean(axis=1)
    return out


def route_templates(paths: list[np.ndarray], threshold: float, n: int = 32
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cluster one player's paths into route templates.

    Average-linkage agglomerative clustering on route_distance, merging until the closest two clusters
    are more than `threshold` game units apart. Each template is the cluster's medoid (a real path).
    Returns (templates (k, n, d), usage counts (k,), label of each path (m,)), most used first."""
    resampled = np.stack([resample_path(p, n) for p in paths])
    dist = distance_matrix(resampled)
    members = [[i] for i in range(len(paths))]
    linkage = dist.copy()
    np.fill_diagonal(linkage, np.inf)
    while len(members) > 1:
        i, j = np.unravel_index(np.argmin(linkage), linkage.shape)
        if linkage[i, j] > threshold:
            break
        i, j = min(i, j), max(i, j)
        ni, nj = len(members[i]), len(members[j])
        merged = (ni * linkage[i] + nj * linkage[j]) / (ni + nj)  # Lance-Williams, average linkage
        linkage[i], linkage[:, i] = merged, merged
        linkage[i, i] = np.inf
        linkage = np.delete(np.delete(linkage, j, axis=0), j, axis=1)
        members[i] = members[i] + members.pop(j)
    medoids = [m[int(np.argmin(dist[np.ix_(m, m)].sum(axis=1)))] for m in members]
    order = sorted(range(len(members)), key=lambda c: (-len(members[c]), medoids[c]))
    labels = np.empty(len(paths), dtype=np.int64)
    for rank, c in enumerate(order):
        labels[members[c]] = rank
    counts = np.array([len(members[c]) for c in order], dtype=np.int64)
    return resampled[[medoids[c] for c in order]], counts, labels


def nearest_template_distance(path: np.ndarray, templates: np.ndarray) -> tuple[float, int]:
    """(distance to the closest template, its index). `path` is resampled to the templates' length."""
    resampled = resample_path(path, templates.shape[1])
    dists = np.linalg.norm(templates - resampled, axis=2).mean(axis=1)
    best = int(np.argmin(dists))
    return float(dists[best]), best


# ---------- 2. movement transition matrix ----------

SPEEDS = ("still", "walk", "run")
TURNS = ("straight", "slight", "sharp")
DIRECTIONS = ("forward", "strafe", "back")
N_STATES = len(SPEEDS) * len(TURNS) * len(DIRECTIONS)  # 27; state = 9 * speed + 3 * turn + direction

# Defaults in game units per second / degrees per tick. CS2 run speed is ~215-250 u/s (weapon
# dependent), shift-walk ~52% of it. UNVERIFIED as good cut points: tune on real demos.
STILL_SPEED, WALK_SPEED = 20.0, 150.0
SLIGHT_TURN, SHARP_TURN = 1.0, 5.0  # deg / tick; at 64 tick: 64 and 320 deg / s


def state_index(speed: int, turn: int, direction: int) -> int:
    return 9 * speed + 3 * turn + direction


def movement_states(vx: np.ndarray, vy: np.ndarray, yaw: np.ndarray, valid: np.ndarray | None = None, *,
                    still: float = STILL_SPEED, walk: float = WALK_SPEED,
                    slight: float = SLIGHT_TURN, sharp: float = SHARP_TURN) -> np.ndarray:
    """One of the 27 states per tick for one player's consecutive ticks, -1 where undefined.

    speed: horizontal speed < still / <= walk / above. turn: |yaw change since previous tick|
    < slight / < sharp / above. direction: velocity heading vs view yaw, within 45 deg = forward,
    beyond 135 = back, else strafe; a still player is 'forward' by convention.
    A tick is undefined if it or the previous tick is not `valid` or has non-finite values, so
    callers mark the tick after a gap (death, missing rows) as invalid."""
    vx, vy, yaw = (np.asarray(a, dtype=float) for a in (vx, vy, yaw))
    ok = np.isfinite(vx) & np.isfinite(vy) & np.isfinite(yaw)
    if valid is not None:
        ok &= np.asarray(valid, dtype=bool)
    ok &= np.r_[False, ok[:-1]]  # the turn needs the previous tick
    speed = np.hypot(vx, vy)
    speed_level = np.where(speed < still, 0, np.where(speed <= walk, 1, 2))
    turn = np.abs(wrap_deg(np.diff(yaw, prepend=np.nan)))
    turn_level = np.where(turn < slight, 0, np.where(turn < sharp, 1, 2))
    rel = np.abs(wrap_deg(np.degrees(np.arctan2(vy, vx)) - yaw))
    direction = np.where(rel <= 45, 0, np.where(rel >= 135, 2, 1))
    direction = np.where(speed_level == 0, 0, direction)
    return np.where(ok, 9 * speed_level + 3 * turn_level + direction, -1).astype(np.int64)


def player_states(ticks: pd.DataFrame, steamid: str, **thresholds: float) -> np.ndarray:
    """movement_states() on one player's live, alive ticks; the tick after any gap is undefined."""
    rows = player_rows(ticks, steamid)
    contiguous = np.r_[False, np.diff(rows["tick"].to_numpy()) == 1]
    valid = rows["alive"].to_numpy(bool) & (rows["phase"].astype(str).to_numpy() == "live") & contiguous
    return movement_states(rows["vx"], rows["vy"], rows["yaw"], valid, **thresholds)


def transition_counts(states: np.ndarray, n_states: int = N_STATES) -> np.ndarray:
    """(n_states, n_states) counts of consecutive state pairs; pairs touching a -1 are skipped."""
    states = np.asarray(states, dtype=np.int64)
    a, b = states[:-1], states[1:]
    keep = (a >= 0) & (b >= 0)
    counts = np.zeros((n_states, n_states), dtype=np.int64)
    np.add.at(counts, (a[keep], b[keep]), 1)
    return counts


def _row_probs(counts: np.ndarray, alpha: float) -> np.ndarray:
    counts = np.asarray(counts, dtype=float) + alpha
    totals = counts.sum(axis=1, keepdims=True)
    return np.divide(counts, totals, out=np.full_like(counts, 1.0 / counts.shape[1]), where=totals > 0)


def transition_divergence(counts_new: np.ndarray, counts_profile: np.ndarray, alpha: float = 0.5) -> float:
    """d = sum_i pi_i * KL(P_new,i || P_profile,i), rows smoothed with additive `alpha`.

    pi_i = share of the new transitions leaving state i. 0 for identical matrices, grows with change.
    NaN if counts_new is empty. alpha = 0 can give inf (a new transition never seen in the profile)."""
    counts_new = np.asarray(counts_new, dtype=float)
    total = counts_new.sum()
    if total == 0:
        return float("nan")
    p, q = _row_probs(counts_new, alpha), _row_probs(counts_profile, alpha)
    pi = counts_new.sum(axis=1) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(p > 0, p * np.log(p / q), 0.0)
    return float((pi * terms.sum(axis=1)).sum())


# ---------- 3. habit vectors ----------

PITCH_EDGES = np.linspace(-30.0, 30.0, 31)  # 2 deg bins; CS2 positive pitch = looking down (vectors/aim.py)
FIRST_INSPECT_EDGES_S = np.array([0, 1, 2, 3, 5, 8, 12, 20, 30, 60, 120], dtype=float)
INSPECT_INTERVAL_EDGES_S = np.array([0, 0.5, 1, 2, 3, 5, 8, 12, 20, 40, 120], dtype=float)
SWITCH_INTERVAL_EDGES_S = np.array([0, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10, 30], dtype=float)


def pitch_histogram(pitch: np.ndarray, moving: np.ndarray, edges: np.ndarray = PITCH_EDGES) -> np.ndarray:
    """Crosshair height while moving: counts of pitch on the ticks where `moving` is True."""
    return histogram(np.asarray(pitch, dtype=float)[np.asarray(moving, dtype=bool)], edges)


def inspect_rhythm(inspect_ticks: np.ndarray, round_starts: np.ndarray, *, tickrate: int = TICKRATE,
                   first_edges: np.ndarray = FIRST_INSPECT_EDGES_S,
                   interval_edges: np.ndarray = INSPECT_INTERVAL_EDGES_S) -> dict[str, np.ndarray]:
    """Time from round start to the first inspect, and between inspects of the same round (seconds).

    Returns additive counts: 'first' and 'interval' histograms, 'rounds' (rounds seen) and
    'rounds_with_inspect'. Inspects before the first round start are ignored."""
    inspect_ticks = np.sort(np.asarray(inspect_ticks, dtype=np.int64))
    round_starts = np.sort(np.asarray(round_starts, dtype=np.int64))
    rnd = np.searchsorted(round_starts, inspect_ticks, side="right") - 1
    inspect_ticks, rnd = inspect_ticks[rnd >= 0], rnd[rnd >= 0]
    new_round = np.r_[True, rnd[1:] != rnd[:-1]]
    first = (inspect_ticks[new_round] - round_starts[rnd[new_round]]) / tickrate
    intervals = np.diff(inspect_ticks)[~new_round[1:]] / tickrate
    return {"first": histogram(first, first_edges), "interval": histogram(intervals, interval_edges),
            "rounds": np.int64(len(round_starts)), "rounds_with_inspect": np.int64(new_round.sum())}


def press_groups(press_ticks: np.ndarray, window: int) -> np.ndarray:
    """Sizes of greedy groups: a group starts at a press and takes every press within `window` ticks
    after it; the next unassigned press starts the next group."""
    press_ticks = np.sort(np.asarray(press_ticks, dtype=np.int64))
    sizes, i = [], 0
    while i < len(press_ticks):
        j = int(np.searchsorted(press_ticks, press_ticks[i] + window, side="right"))
        sizes.append(j - i)
        i = j
    return np.array(sizes, dtype=np.int64)


def jump_bursts(press_ticks: np.ndarray, window: int = 8, min_presses: int = 3, max_len: int = 16
                ) -> dict[str, np.ndarray]:
    """Scroll-wheel jump signature from jump-button press ticks (rising edges of btn_jump).

    A burst = `min_presses` or more presses within `window` ticks (a scroll notch sends one jump input
    each). Returns 'n_bursts', 'n_presses' and 'length_hist' (group sizes 1..max_len, last bin open,
    singles included). UNVERIFIED: whether scroll inputs show up in the per-tick button state at all
    (they may only exist as sub-tick inputs, or merge into one held press across ticks)."""
    sizes = press_groups(press_ticks, window)
    return {"n_bursts": np.int64((sizes >= min_presses).sum()), "n_presses": np.int64(sizes.sum()),
            "length_hist": histogram(sizes, np.arange(1, max_len + 2) - 0.5)}


GRENADES = re.compile(r"grenade|flashbang|molotov|decoy", re.IGNORECASE)
KNIVES = re.compile(r"knife|bayonet|karambit|daggers|zeus", re.IGNORECASE)  # Zeus shares slot 3 in CS2
PISTOLS = re.compile(r"glock|usp|p2000|p250|five-seven|fiveseven|tec-9|tec9|cz75|desert eagle|deagle|"
                     r"dual berettas|elite|r8|revolver", re.IGNORECASE)


def weapon_slot(name: object) -> int:
    """Inventory slot of a weapon name: 1 primary, 2 pistol, 3 knife / zeus, 4 grenade, 5 C4, 0 unknown.
    UNVERIFIED: the exact active_weapon_name strings (only 'AK-47', 'M4A4' and knife names are seen
    in our code), and Zeus placement."""
    if not isinstance(name, str) or not name:
        return 0
    if re.search(r"\bc4\b", name, re.IGNORECASE):
        return 5
    for slot, pattern in ((4, GRENADES), (3, KNIVES), (2, PISTOLS)):
        if pattern.search(name):
            return slot
    return 1


def switch_signature(switch_ticks: np.ndarray, from_weapons: list, to_weapons: list,
                     *, chain_gap: int = 8, tickrate: int = TICKRATE,
                     interval_edges: np.ndarray = SWITCH_INTERVAL_EDGES_S) -> dict[str, np.ndarray]:
    """Weapon-switch habits: slot transitions, intervals, and scroll vs number-key signatures.

    Consecutive switches at most `chain_gap` ticks apart, each starting from the previous one's
    weapon, form a chain. A chain of 2+ switches whose slot steps all go the same way (ignoring
    same-slot steps, e.g. grenade to grenade) passed through intermediate slots in wheel order:
    'scroll'. A lone switch skipping a slot (|slot step| >= 2, e.g. 1 -> 3) is a 'direct' jump
    (number key); a lone switch to an adjacent slot is ambiguous ('adjacent').

    CAVEAT, needs real demos: this only works if the player has CS2's fast weapon switch ON. With it
    off, scrolling only moves the selection HUD and a single switch happens on confirm, so a scroll
    user looks like a number-key user. Scrolling also skips empty slots (inventory not checked) and
    wraps around the wheel (not modelled), and auto-switches (grenade thrown, pickup) add noise."""
    ticks = np.asarray(switch_ticks, dtype=np.int64)
    order = np.argsort(ticks, kind="stable")
    ticks = ticks[order]
    src = np.array([weapon_slot(w) for w in np.asarray(from_weapons, dtype=object)[order]], dtype=np.int64)
    dst = np.array([weapon_slot(w) for w in np.asarray(to_weapons, dtype=object)[order]], dtype=np.int64)
    from_names = np.asarray(from_weapons, dtype=object)[order]
    to_names = np.asarray(to_weapons, dtype=object)[order]
    slots = np.zeros((6, 6), dtype=np.int64)
    np.add.at(slots, (src, dst), 1)
    gaps = np.diff(ticks)
    links = (gaps <= chain_gap) & (from_names[1:] == to_names[:-1])
    out = {"n_switches": np.int64(len(ticks)), "slot_transitions": slots,
           "interval_hist": histogram(gaps / tickrate, interval_edges),
           "n_scroll_chains": np.int64(0), "n_mixed_chains": np.int64(0), "n_direct": np.int64(0),
           "n_adjacent": np.int64(0), "n_same_slot": np.int64(0),
           "chain_length_hist": np.zeros(8, dtype=np.int64)}  # chain sizes 1..8, last bin open
    start = 0
    for end in [*list(np.flatnonzero(~links) + 1), len(ticks)]:
        if end <= start:
            continue
        steps = dst[start:end] - src[start:end]
        out["chain_length_hist"][min(end - start, 8) - 1] += 1
        if end - start == 1:
            key = "n_same_slot" if steps[0] == 0 else "n_adjacent" if abs(steps[0]) == 1 else "n_direct"
        else:
            signs = set(np.sign(steps[steps != 0]).tolist())
            key = "n_scroll_chains" if len(signs) == 1 else "n_mixed_chains"
        out[key] += 1
        start = end
    return out


# ---------- 4. event responses ----------

TRIGGERS = ("round_start", "freeze_end", "own_kill", "teammate_death", "empty_magazine")
ACTIONS = ("reload", "inspect", "weapon_switch", "crouch", "jump", "start_moving")
LATENCY_EDGES = np.array([0, 4, 8, 16, 32, 64, 128, 192, 257], dtype=float)  # ticks; 257 so 256 fits
RESPONSE_WINDOW = 4 * TICKRATE


def event_responses(triggers: dict[str, np.ndarray], actions: dict[str, np.ndarray], *,
                    window: int = RESPONSE_WINDOW, latency_edges: np.ndarray = LATENCY_EDGES,
                    trigger_names: tuple[str, ...] = TRIGGERS, action_names: tuple[str, ...] = ACTIONS
                    ) -> dict[str, np.ndarray]:
    """What a player does in the `window` ticks after each trigger (latency 0 = same tick).

    Returns additive counts, rows = trigger_names, columns = action_names:
    'n_triggers' (T,), 'followed' (T, A) triggers with at least one action, 'occurrences' (T, A)
    every action in the window, 'latency' (T, A, bins) histogram of the FIRST action's delay in ticks."""
    n_t, n_a, n_b = len(trigger_names), len(action_names), len(latency_edges) - 1
    out = {"n_triggers": np.zeros(n_t, np.int64), "followed": np.zeros((n_t, n_a), np.int64),
           "occurrences": np.zeros((n_t, n_a), np.int64), "latency": np.zeros((n_t, n_a, n_b), np.int64)}
    for ti, trig in enumerate(trigger_names):
        t = np.sort(np.asarray(triggers.get(trig, []), dtype=np.int64))
        out["n_triggers"][ti] = len(t)
        for ai, act in enumerate(action_names):
            a = np.sort(np.asarray(actions.get(act, []), dtype=np.int64))
            lo = np.searchsorted(a, t, side="left")
            hi = np.searchsorted(a, t + window, side="right")
            hit = hi > lo
            out["followed"][ti, ai] = hit.sum()
            out["occurrences"][ti, ai] = (hi - lo).sum()
            out["latency"][ti, ai] = histogram(a[lo[hit]] - t[hit], latency_edges)
    return out


def player_timeline(ticks: pd.DataFrame, events: pd.DataFrame, steamid: str,
                    still: float = STILL_SPEED) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """(triggers, actions) tick arrays for one player, read from the schema tables.

    Triggers are kept only while the player is alive. round_start / freeze_end come from the ticks
    table (phase), not from events. crouch = `ducking` state turning on (verified prop) and jump =
    `airborne` turning on (an actual jump, verified) rather than the unverified duck / jump buttons."""
    rows = player_rows(ticks, steamid)
    tick = rows["tick"].to_numpy()
    alive_at = set(tick[rows["alive"].to_numpy(bool)].tolist())
    side = rows.set_index("tick")["side"].astype(str)
    bounds = round_bounds(ticks)
    kills = events[events["type"].astype(str) == "kill"]
    killer, victim = kills["steamid"].astype(str), kills["target_steamid"].astype(str)
    own_kill = kills["tick"][(killer == steamid) & (victim != steamid)].to_numpy()
    others = ticks[ticks["steamid"].astype(str) != steamid].astype({"steamid": str})
    victim_side = others.set_index(["steamid", "tick"])["side"].astype(str)
    teammate = []
    for t, v in zip(kills["tick"].to_numpy(), victim.to_numpy(), strict=True):
        if v != steamid and (v, t) in victim_side.index and t in side.index \
                and victim_side[(v, t)] == side[t]:
            teammate.append(t)
    gun = rows["weapon"].astype(object).map(lambda w: weapon_slot(w) in (1, 2)).to_numpy(bool)
    empty = rising(gun & (rows["ammo"].fillna(-1).to_numpy() == 0))
    triggers = {
        "round_start": bounds["start"].dropna().to_numpy(),
        "freeze_end": bounds["freeze_end"].dropna().to_numpy(),
        "own_kill": own_kill, "teammate_death": np.array(teammate), "empty_magazine": tick[empty],
    }
    triggers = {k: np.array([t for t in v.astype(np.int64) if t in alive_at], dtype=np.int64)
                for k, v in triggers.items()}
    mine = events["steamid"].astype(str) == steamid
    switches = events[(events["type"].astype(str) == "weapon_switch") & mine]
    speed = np.hypot(rows["vx"].to_numpy(float), rows["vy"].to_numpy(float))
    actions = {
        "reload": tick[rising(rows["btn_reload"])], "inspect": tick[rising(rows["btn_inspect"])],
        "weapon_switch": switches["tick"].to_numpy(), "crouch": tick[rising(rows["ducking"])],
        "jump": tick[rising(rows["airborne"])], "start_moving": tick[rising(speed >= still)],
    }
    return triggers, actions


# ---------- 5. shrinkage for distributions ----------

def shrink_counts(counts_cell: np.ndarray, counts_global: np.ndarray, k: float, axis: int = -1) -> np.ndarray:
    """Blended probabilities (c_cell + k * p_global) / (n_cell + k), along `axis`.

    The distribution version of w = n / (n + k): with n_cell >> k the cell's own frequencies win, with
    k >> n_cell the global profile does. Works row-wise on matrices (axis=-1, e.g. the 27 x 27
    transition counts). An empty cell with k = 0 falls back to p_global; an empty global to uniform."""
    cell = np.asarray(counts_cell, dtype=float)
    glob = np.asarray(counts_global, dtype=float)
    g_total = glob.sum(axis=axis, keepdims=True)
    uniform = np.full_like(glob, 1.0 / glob.shape[axis])
    p_global = np.divide(glob, g_total, out=uniform, where=g_total > 0)
    n_cell = cell.sum(axis=axis, keepdims=True)
    denom = n_cell + k
    blended = np.divide(cell + k * p_global, denom, out=np.zeros_like(cell), where=denom > 0)
    return np.where(denom > 0, blended, p_global)

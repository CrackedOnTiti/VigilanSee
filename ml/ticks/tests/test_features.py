"""Feature functions on synthetic data only."""
from pathlib import Path

import numpy as np
import pytest
from conftest import P1, P2, P3

import features as f
from transform import DemoId, transform

# ---------- routes ----------


def test_resampling_a_straight_line_gives_evenly_spaced_points():
    line = np.array([[0.0, 0.0], [1.0, 0.0], [7.0, 0.0], [31.0, 0.0]])
    out = f.resample_path(line, n=32)
    assert out.shape == (32, 2)
    np.testing.assert_allclose(np.diff(out[:, 0]), 1.0)
    np.testing.assert_allclose(out[:, 1], 0.0)


def test_resampling_is_invariant_to_the_original_sampling_rate():
    t_coarse, t_fine = np.linspace(0, 1, 40), np.linspace(0, 1, 4000)
    curve = lambda t: np.stack([100 * t, 50 * np.sin(np.pi * t)], axis=1)  # noqa: E731
    coarse, fine = f.resample_path(curve(t_coarse), 32), f.resample_path(curve(t_fine), 32)
    assert f.route_distance(coarse, fine) < 0.5  # game units, on a ~160 unit long path


def test_resampling_ignores_standing_still_and_handles_a_static_path():
    path = np.array([[0.0, 0.0], [0.0, 0.0], [10.0, 0.0], [10.0, 0.0]])
    np.testing.assert_allclose(f.resample_path(path, 3)[:, 0], [0, 5, 10])
    np.testing.assert_allclose(f.resample_path(np.array([[3.0, 4.0]] * 5), 4), [[3.0, 4.0]] * 4)


def test_route_distance_of_a_path_with_itself_is_zero_and_symmetric(rng):
    a = f.resample_path(rng.normal(size=(50, 2)).cumsum(0))
    b = f.resample_path(rng.normal(size=(30, 2)).cumsum(0))
    assert f.route_distance(a, a) == 0
    assert f.route_distance(a, b) == pytest.approx(f.route_distance(b, a))
    with pytest.raises(ValueError):
        f.route_distance(a, a[:10])


def _noisy_routes(rng, count, end, n=60, noise=15.0):
    t = np.linspace(0, 1, n)[:, None]
    return [t * np.asarray(end, float) + rng.normal(scale=noise, size=(n, 2)) * np.sin(np.pi * t)
            for _ in range(count)]


def test_templates_recover_two_clearly_separated_routes(rng):
    a_long = _noisy_routes(rng, 7, [2000, 0])  # e.g. long A
    b_tunnels = _noisy_routes(rng, 4, [0, 2000])  # e.g. B tunnels
    templates, counts, labels = f.route_templates(a_long + b_tunnels, threshold=300)
    assert counts.tolist() == [7, 4]
    assert labels.tolist() == [0] * 7 + [1] * 4
    dist, idx = f.nearest_template_distance(_noisy_routes(rng, 1, [0, 2000])[0], templates)
    assert idx == 1 and dist < 100
    assert templates.shape == (2, 32, 2)


def test_tight_threshold_keeps_every_path_apart(rng):
    _, counts, _ = f.route_templates(_noisy_routes(rng, 3, [2000, 0], noise=200), threshold=0.0)
    assert counts.tolist() == [1, 1, 1]


def test_opening_paths_stop_at_first_contact(raw_ticks, raw_events):
    t = transform(raw_ticks, raw_events, {}, DemoId.of(Path("m/d.dem")), None)
    paths = f.opening_paths(t["ticks"], t["events"], limit_s=1.0)
    p1 = paths[(P1, 0)]  # live from tick 10, first contact = shot at tick 21; X = tick in the fake
    np.testing.assert_allclose(p1[:, 0], np.arange(10, 22))
    assert len(paths[(P2, 0)]) == 15  # no contact: until round 0's last live tick (24) within 64 ticks
    assert (P3, 1) not in paths  # dead in round 1


# ---------- movement matrix ----------


def test_movement_state_encoding_on_hand_built_ticks():
    vx = np.array([0.0, 250.0, 0.0, -250.0, 100.0])
    vy = np.array([0.0, 0.0, 250.0, 0.0, 0.0])
    yaw = np.array([0.0, 0.0, 3.0, 3.0, 13.0])
    s = f.movement_states(vx, vy, yaw)
    run, walk, still = 2, 1, 0
    assert s.tolist() == [
        -1,  # first tick: no previous yaw
        f.state_index(run, 0, 0),  # straight, forward
        f.state_index(run, 1, 1),  # turned 3 deg (slight), moving sideways (strafe)
        f.state_index(run, 0, 2),  # moving against the view (back)
        f.state_index(walk, 2, 0),  # 10 deg in one tick (sharp)
    ]
    assert f.movement_states([0, 0], [0, 0], [0, 90]).tolist() == [-1, f.state_index(still, 2, 0)]


def test_yaw_wraparound_is_a_small_turn():
    s = f.movement_states([-250, -250], [0, 0], [179.5, -179.5])  # moving along the view, heading 180
    assert s[1] == f.state_index(2, 1, 0)  # 1 deg turn across +-180, not 359


def test_invalid_ticks_break_the_sequence():
    s = f.movement_states([250] * 4, [0] * 4, [0] * 4, valid=[True, True, False, True])
    assert s.tolist() == [-1, 18, -1, -1]


def test_known_state_sequence_gives_expected_transition_counts():
    counts = f.transition_counts(np.array([0, 0, 1, 26, -1, 26, 0, 0]))
    assert counts.sum() == 5
    assert counts[0, 0] == 2 and counts[0, 1] == 1 and counts[1, 26] == 1 and counts[26, 0] == 1
    assert counts.shape == (27, 27)


def test_divergence_is_zero_with_itself_and_grows_with_change(rng):
    base = rng.integers(0, 50, size=(27, 27))
    other = rng.integers(0, 50, size=(27, 27))
    assert f.transition_divergence(base, base) == 0
    d = [f.transition_divergence(np.rint((1 - w) * base + w * other), base) for w in (0.0, 0.25, 0.5, 1.0)]
    assert d[0] == 0 and d[0] < d[1] < d[2] < d[3]
    assert np.isnan(f.transition_divergence(np.zeros((27, 27)), base))


def test_divergence_weights_rows_by_state_frequency():
    profile = np.ones((27, 27))
    rare_change = np.ones((27, 27)) * 100
    rare_change[5] = 0
    rare_change[5, 5] = 1  # a very different row, but almost never visited
    common_change = rare_change.copy()
    common_change[0] = 0
    common_change[0, 0] = 2700  # the same kind of change on a frequent row
    assert f.transition_divergence(common_change, profile) > f.transition_divergence(rare_change, profile)


# ---------- habits ----------


def test_pitch_histogram_counts_only_moving_ticks_and_clips_tails():
    pitch = np.array([0.5, 0.5, 89.0, -89.0, 0.5])
    moving = np.array([True, True, True, True, False])
    h = f.pitch_histogram(pitch, moving)
    assert h.sum() == 4 and h[-1] == 1 and h[0] == 1 and h[15] == 2


def test_inspect_rhythm_first_delay_and_intervals():
    out = f.inspect_rhythm([50, 130, 400, 70], [0, 1000, 2000], tickrate=64,
                           first_edges=np.array([0, 1, 2, 100.0]),
                           interval_edges=np.array([0, 0.5, 2, 100.0]))
    # round 0: first at 50 ticks (0.78 s), intervals 20 (0.31 s), 60 (0.94 s), 270 (4.2 s)
    assert out["first"].tolist() == [1, 0, 0]
    assert out["interval"].tolist() == [1, 1, 1]
    assert out["rounds"] == 3 and out["rounds_with_inspect"] == 1


def test_jump_bursts_find_scroll_bursts():
    presses = [100, 102, 103, 105, 107,  # scroll: 5 presses in 7 ticks
               500,  # a normal jump
               900, 904]  # two jumps in 4 ticks: below min_presses
    out = f.jump_bursts(presses, window=8, min_presses=3, max_len=6)
    assert out["n_bursts"] == 1 and out["n_presses"] == 8
    assert out["length_hist"].tolist() == [1, 1, 0, 0, 1, 0]


def test_jump_burst_window_is_measured_from_the_first_press():
    assert f.press_groups([0, 4, 8, 12, 16], window=8).tolist() == [3, 2]


def test_weapon_slots():
    assert [f.weapon_slot(w) for w in ("AK-47", "Glock-18", "Karambit", "Flashbang", "C4 Explosive",
                                       "Smoke Grenade", "Desert Eagle", None)] == [1, 2, 3, 4, 5, 4, 2, 0]


def test_switch_signature_separates_scroll_chains_from_direct_jumps():
    # scroll: AK -> Glock -> knife -> flash in 6 ticks (passes slots 1, 2, 3, 4 in order)
    # number keys: AK -> knife (1 -> 3) alone, then knife -> Glock (adjacent, ambiguous)
    ticks = [100, 103, 106, 1000, 2000]
    frm = ["AK-47", "Glock-18", "Knife", "AK-47", "Knife"]
    to = ["Glock-18", "Knife", "Flashbang", "Knife", "Glock-18"]
    out = f.switch_signature(ticks, frm, to, chain_gap=8)
    assert out["n_switches"] == 5
    assert out["n_scroll_chains"] == 1 and out["n_direct"] == 1 and out["n_adjacent"] == 1
    assert out["n_mixed_chains"] == 0
    assert out["chain_length_hist"][:3].tolist() == [2, 0, 1]
    assert out["slot_transitions"][1, 3] == 1 and out["slot_transitions"][1, 2] == 1


def test_switch_signature_back_and_forth_is_not_a_scroll():
    out = f.switch_signature([10, 13], ["AK-47", "Glock-18"], ["Glock-18", "AK-47"], chain_gap=8)
    assert out["n_mixed_chains"] == 1 and out["n_scroll_chains"] == 0


# ---------- event responses ----------


def test_event_responses_on_a_hand_built_timeline():
    triggers = {"own_kill": np.array([100, 500]), "round_start": np.array([0])}
    actions = {"reload": np.array([110, 120, 900]), "inspect": np.array([500]), "jump": np.array([])}
    out = f.event_responses(triggers, actions, window=64, latency_edges=np.array([0, 1, 16, 65.0]),
                            trigger_names=("round_start", "own_kill"),
                            action_names=("reload", "inspect", "jump"))
    assert out["n_triggers"].tolist() == [1, 2]
    assert out["followed"].tolist() == [[0, 0, 0], [1, 1, 0]]
    assert out["occurrences"].tolist() == [[0, 0, 0], [2, 1, 0]]
    assert out["latency"][1, 0].tolist() == [0, 1, 0]  # first reload 10 ticks after the kill
    assert out["latency"][1, 1].tolist() == [1, 0, 0]  # inspect on the same tick


def test_player_timeline_reads_triggers_and_actions_from_the_tables(raw_ticks, raw_events):
    t = transform(raw_ticks, raw_events, {}, DemoId.of(Path("m/d.dem")), None)
    trig, act = f.player_timeline(t["ticks"], t["events"], P1)
    assert trig["own_kill"].tolist() == [22]
    assert trig["round_start"].tolist() == [5, 30] and trig["freeze_end"].tolist() == [10, 35]
    assert act["reload"].tolist() == [12] and act["inspect"].tolist() == [15, 31]
    assert act["weapon_switch"].tolist() == [14]
    trig2, _ = f.player_timeline(t["ticks"], t["events"], P2)
    assert trig2["empty_magazine"].tolist() == [20]
    assert trig2["teammate_death"].tolist() == []  # P3 is on the other side
    trig3, _ = f.player_timeline(t["ticks"], t["events"], P3)
    assert trig3["own_kill"].tolist() == [] and trig3["round_start"].tolist() == [5]  # dead in round 1


# ---------- shrinkage ----------


def test_shrink_counts_with_k_zero_gives_the_cell_distribution():
    np.testing.assert_allclose(f.shrink_counts([1, 3, 0], [10, 10, 80], k=0), [0.25, 0.75, 0])


def test_shrink_counts_with_huge_k_gives_the_global_distribution():
    np.testing.assert_allclose(f.shrink_counts([1, 3, 0], [10, 10, 80], k=1e12), [0.1, 0.1, 0.8])


def test_shrink_counts_matches_w_formula_and_works_row_wise():
    cell, glob, k = np.array([2.0, 2.0]), np.array([1.0, 3.0]), 4.0
    w = cell.sum() / (cell.sum() + k)
    expected = w * cell / cell.sum() + (1 - w) * glob / glob.sum()
    np.testing.assert_allclose(f.shrink_counts(cell, glob, k), expected)
    rows = f.shrink_counts(np.array([[1, 0], [0, 0]]), np.array([[1, 1], [1, 3]]), k=1)
    np.testing.assert_allclose(rows, [[0.75, 0.25], [0.25, 0.75]])
    np.testing.assert_allclose(rows.sum(axis=1), 1)
    np.testing.assert_allclose(f.shrink_counts([0, 0], [0, 0], k=0), [0.5, 0.5])


def test_counts_are_additive_across_matches():
    a, b = np.array([0, 0, 1, 2, 2]), np.array([1, 1, 2, 0])
    joined = f.transition_counts(np.r_[a, -1, b])
    np.testing.assert_array_equal(joined, f.transition_counts(a) + f.transition_counts(b))

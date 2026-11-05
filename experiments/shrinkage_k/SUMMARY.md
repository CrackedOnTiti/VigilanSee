# Per-map shrinkage in `ml/evaluate.py`

Branch `exp/shrinkage-k`, from `origin/ml_levelONE_verification` at `b63a101`. Reproduce from the repo root with
`uv run experiments/shrinkage_k/run.py`. It writes the CSVs next to this file; this summary is written by hand from them.

## Result

- **Per-map shrinkage gives a real but small gain on normal queries.** With k = 2, leak-free, detect@5% goes from 87.4% to 90.6% (+3.2 points, 95% CI +0.7 to +5.9) and AUC from 0.9769 to 0.9811 (+0.41 points, CI +0.20 to +0.64).
- **On chronological evaluation, the AUC gain holds but the k = 2 detection gain isn't established** (+0.3 points, CI -1.3 to +4.1).
- **The cross-team gain isn't established for any k.** With k = 2: detect@5% +2.2 points (CI -5.5 to +13.7), AUC -0.26 points (CI -0.69 to +0.16). Team transfers remain unsolved.
- **Recommendation:** use per-map profiles with per-feature Bühlmann-Straub k. If one number is needed, use k = 2. Details are under [Recommendation](#recommendation).

## Dataset

| | |
|---|---|
| Fingerprint files | 161 CSVs (1,614 rows) |
| Matches / maps | 65 / 156, played 2026-03-03 to 2026-09-06 |
| Player-maps used | 1,530 (34 coach rows dropped, 50 rows merged from `-p1`/`-p2` parts) |
| Candidates | 184 players |
| Players who can be queried | 92; the other 92 have one match, so they only ever act as impostors |
| Queries | 1,311 leave-one-match-out, 1,266 cross-event, 1,095 chronological |
| Transfer players | **9** |
| Cross-team queries | **178** |
| (player, map) cells | 670, of which 374 (56%) hold a single map |

The 9 transfers are Brollan, Jimpphat, MartinezSa, jL, kyxsan, malbsMd, r1nkle, soulfly and xfl0ud.

## Step 1: baseline, his code unchanged

`uv run ml/evaluate.py habits,buy --score own` (184 candidates):

| Row | Players | Maps | detect@5% | detect CI | AUC | AUC CI | EER | Top-1 | Top-3 |
|---|---|---|---|---|---|---|---|---|---|
| all maps (leave-one-match-out) | 92 | 1311 | 87% | 83–91% | 0.977 | 0.972–0.981 | 8% | 73% | 85% |
| past: all maps | 92 | 1095 | 81% | 76–84% | 0.964 | 0.955–0.970 | 10% | 71% | 85% |
| past: whole match | 92 | 466 | 92% | 88–94% | 0.984 | 0.976–0.989 | 7% | 87% | 94% |
| past: 2 matches in a row | 64 | 374 | 98% | 96–99% | 0.994 | 0.989–0.997 | 3% | 93% | 98% |
| past: 3 matches in a row | 56 | 310 | 99% | 99–100% | 0.998 | 0.995–0.999 | 2% | 96% | 100% |
| past: 5 matches in a row | 36 | 208 | 100% | 99–100% | 0.999 | 0.999–1.000 | 1% | 99% | 100% |
| past: last 1 maps | 92 | 1095 | 59% | 51–67% | 0.912 | 0.896–0.927 | 17% | 44% | 61% |
| past: last 3 maps | 76 | 990 | 77% | 71–81% | 0.956 | 0.945–0.965 | 11% | 67% | 83% |
| past: last 5 maps | 59 | 809 | 81% | 75–86% | 0.964 | 0.956–0.972 | 10% | 76% | 90% |
| past: last 10 maps | 44 | 533 | 81% | 74–88% | 0.967 | 0.955–0.977 | 9% | 86% | 96% |
| past: 1–7 days before | 72 | 712 | 79% | 74–86% | 0.961 | 0.952–0.972 | 10% | 82% | 94% |
| past: 8–30 days before | 55 | 459 | 74% | 63–83% | 0.951 | 0.935–0.966 | 12% | 76% | 90% |
| past: 31–90 days before | 49 | 500 | 72% | 59–81% | 0.945 | 0.925–0.957 | 13% | 64% | 81% |
| past: > 90 days before | 51 | 546 | 74% | 66–80% | 0.942 | 0.930–0.954 | 14% | 54% | 75% |
| cross-event | 83 | 1266 | 83% | 78–87% | 0.968 | 0.958–0.974 | 9% | 65% | 81% |
| **cross-team** | **9** | **178** | **63%** | 52–79% | **0.924** | 0.906–0.956 | 16% | 42% | 61% |

`uv run ml/effects.py habits,buy`:

| Row | Players | Maps | detect@5% | detect CI | AUC | AUC CI | EER | Top-1 | Top-3 |
|---|---|---|---|---|---|---|---|---|---|
| profile K=1 map, same map | 87 | 23120 | 62% | 55–67% | 0.920 | 0.910–0.933 | 16% | 42% | 59% |
| profile K=1 map, other map | 87 | 23120 | 42% | 36–50% | 0.854 | 0.836–0.873 | 23% | 24% | 38% |
| all maps (evaluate.py) | 92 | 1311 | 87% | 83–91% | 0.977 | 0.972–0.981 | 8% | 73% | 85% |
| all maps, map-centred | 92 | 1311 | 89% | 86–92% | 0.978 | 0.974–0.982 | 7% | 73% | 87% |

Other `effects.py` output:
- The map explains most of a player's own variation for `jumps_per_min` (0.36), then `w_plus_strafe_frac` (0.14), `walk_frac` and `back_frac` (0.13).
- Wrong top-1 answers are a teammate 2% of the time, which is chance level.
- After a transfer, the nearest profile is someone else 53%, the player himself 42%, an old teammate 3%, a new teammate 2%.

### The "~49% after team transfer"

**No row of his code gives 49%.** His cross-team row on this data is **63% detect@5%** (0.924 AUC, 42% top-1). I ran every combination of the four vectors, with `own` scoring (cap on and off) and `euclid` (`variants.csv`). The nearest detect@5% values are:

| Features | Score | detect@5% |
|---|---|---|
| habits+buy+strafe | `own`, no `GAP_CAP` | 50.9% |
| habits+buy+aim+strafe | `own` | 52.1% |
| habits+buy | `own`, no `GAP_CAP` | 53.2% |
| habits+buy+aim | `own`, no `GAP_CAP` | 46.7% |
| habits+buy+strafe | `euclid` | 46.6% |

The source of 49% is unknown. It may predate `GAP_CAP` (its comment says "tuned 2026-09-30" for transfers), or come from an earlier dataset, since 59 matches were mentioned and there are 65 now. Only Aymeric can confirm.

### How his code handles the data

- **Coaches:** there's no name filter. All 34 `Coach|...` rows (7 people) have no feature values, so `dropna(how="all")` removes them in `load_fingerprints` (`ml/evaluate.py`). That accounts for 191 raw players → 184. None of the 7 SteamIDs also appears as a player.
- **Rebrands:** `merge_rebrands` treats two team names sharing at least 3 players as one team. 46 raw names become 36. Nine merges are name variants (for example `Team Spirit`/`Spirit`) and one is a real rebrand, `Sharks` → `DENDELE`.
- **Missing values:** `standardise` and `past_standard` set them to 0 after z-scoring, which means "exactly the average player". They therefore still add distance against a profile. 2.1% of habits+buy cells are missing, mostly `clip_at_reload` (29%) and `rank_defuser` (20%); 566 of 1,530 rows have at least one. Strafe is 17.5% missing and aim 6.6%.
- **`ml/vectors/__init__.py`:** not needed. `evaluate.py` and `effects.py` don't import `vectors`, so I didn't recreate it.

## Steps 2 and 3: what changed in `ml/evaluate.py`

- `--context-k K` adds per-map profiles. K is a number, `inf` or `buhlmann`.
- `--strict` adds leak-free evaluation through `held_out_trials`.
- Both are off by default.

**Checks, all passing:**
- No flags: `evaluate.py` output is identical to Step 1 (`diff`). `effects.py` too.
- `--context-k inf`: identical to Step 1, including every chronological row.
- `run.py` also asserts distance-for-distance equality between k = inf and the global profile on 6,605 trials, across both modes, all three scopes and chronological.

**Leakage effect (habits,buy, global profile):** small.

| | detect@5% | AUC | Cross-team detect@5% | Cross-team AUC |
|---|---|---|---|---|
| His evaluation | 87.43% | 0.9770 | 62.9% | 0.9240 |
| `--strict` | 87.41% | 0.9769 | 63.6% | 0.9238 |

## Baseline vs reference

| | His code | `--strict` | Reference |
|---|---|---|---|
| AUC | 0.9770 | 0.9769 | 0.9776 |
| detect@5% | 87.4% | 87.4% | 87.0% |
| Cross-team AUC | 0.9240 | 0.9238 | 0.9227 |
| Cross-team detect@5% | 62.9% | 63.6% | 65.8% |
| Queries | 1311 | 1311 | 1301 |
| Cross-team queries / players | 178 / 9 | 178 / 9 | 183 / 14 |

I re-ran the reference on this data and its `results.csv` reproduces exactly, so the differences come from method:

1. **Transfers (measured):** the reference has 14 only because its team normalisation misses `Sharks` → `DENDELE`. Those 5 extra "transfers" are one roster under two names. Counting them raises `--strict` cross-team detect@5% from 63.6% to 64.6% (193 queries, 14 players).
2. **`MIN_MAPS = 2` (not isolated):** the reference skips players with one profile map. That explains 1301 vs 1311 and 183 vs 193.
3. **Missing values (not isolated):** the reference skips them with `nansum`; his code scores them as 0.
4. **Variance prior (not isolated):** the reference pools deviations over rows; his code averages per-player variances.
5. **Cell variance (not isolated):** the reference shrinks it toward the player's variance and ignores cells with one map. The port uses `shrink()` inside the cell and then blends, as specified.

The reference "baseline" isn't his evaluation either: it already keeps the query match out of every profile, so it's closest to `--strict`.

### Reference findings

| Finding | Verdict |
|---|---|
| Global AUC 0.978, detect@5% 87.0% | Confirmed (0.977, 87.4%) |
| Cross-team AUC 0.923, detect@5% 65.8% | AUC confirmed. Detection is **62.9–63.6%**, not 65.8% |
| Best at k = 1–5: AUC 0.981, detect ~90% | Confirmed (0.981, 90.2–90.6%) |
| k = 0 hurts cross-team (56.7%) | Confirmed, slightly worse: 53.3% |
| Cross-team never improves meaningfully | Confirmed for every single k |
| Movement habits k = 0.8–7 | Confirmed with the reference formula, but see below |
| Buy/reload/inspect k = infinity | **Mostly an artefact of the formula** |
| Per-feature k no better than k = 2 | True for the reference formula, not clearly true for the exact one |

## Step 4: grid

habits,buy, `--strict`, `PRIOR_MAPS = 10`. "Past" is chronological `past: all maps`.

| k | AUC | detect@5% | Top-1 | Cross-team AUC | Cross-team detect@5% | Past AUC | Past detect@5% |
|---|---|---|---|---|---|---|---|
| global | 0.9769 | 87.4% | 73.4% | 0.9238 | 63.6% | 0.9638 | 80.7% |
| 0 | 0.9755 | 87.1% | 69.3% | 0.9065 | 53.3% | 0.9567 | 77.8% |
| 1 | 0.9805 | 90.5% | 75.1% | 0.9187 | 65.0% | 0.9655 | 81.5% |
| **2** | **0.9811** | **90.6%** | 76.2% | 0.9212 | 65.7% | 0.9663 | 81.0% |
| 5 | 0.9808 | 90.2% | 76.7% | 0.9235 | 66.0% | 0.9662 | 82.3% |
| 10 | 0.9800 | 89.6% | 75.8% | 0.9238 | 64.8% | 0.9656 | 81.6% |
| 20 | 0.9790 | 88.9% | 74.8% | 0.9239 | 64.4% | 0.9649 | 81.3% |
| 50 | 0.9780 | 87.7% | 74.1% | 0.9239 | 64.3% | 0.9643 | 80.8% |
| inf | 0.9769 | 87.4% | 73.4% | 0.9238 | 63.6% | 0.9638 | 80.7% |
| Bühlmann (reference formula) | 0.9800 | 89.7% | 75.8% | 0.9259 | 65.5% | 0.9659 | 81.9% |
| Bühlmann-Straub (exact) | 0.9813 | 90.2% | 76.7% | 0.9260 | 68.7% | 0.9672 | 82.8% |

The selection rule was set before seeing the grid: highest overall AUC under `--strict`, which gives **k = 2**. Best cross-team detection gives k = 5, a difference well inside the noise.

Re-choosing k on 4 of 5 folds of matches and scoring on the fifth picks k = 2 four times and k = 5 once, and gives AUC 0.9808 and detect@5% 90.3%. So the gain isn't an effect of picking k on the same matches.

### `PRIOR_MAPS` (habits,buy, `--strict`, k = 2)

| `PRIOR_MAPS` | AUC | detect@5% | Cross-team detect@5% | Past AUC | Past detect@5% |
|---|---|---|---|---|---|
| 5 | 0.9806 | 91.0% | 66.9% | 0.9660 | 81.5% |
| 10 | 0.9811 | 90.6% | 65.7% | 0.9663 | 81.0% |
| 20 | 0.9809 | 90.4% | 64.5% | 0.9659 | 82.2% |

No clear effect, so keep 10.

### Feature sets (`--strict`)

| Features | Global AUC | Global detect | k = 2 AUC | k = 2 detect | Global cross-team detect | k = 2 cross-team detect |
|---|---|---|---|---|---|---|
| habits,buy | 0.9769 | 87.4% | 0.9811 | 90.6% | 63.6% | 65.7% |
| habits | 0.9333 | 68.2% | 0.9474 | 75.4% | 38.7% | 39.4% |
| habits,buy,strafe | 0.9736 | 86.0% | 0.9779 | 88.1% | 54.5% | 51.7% |
| habits,buy,aim,strafe | 0.9669 | 83.0% | 0.9723 | 85.0% | 52.2% | 51.4% |

His code runs with aim and strafe, with missing values set to the average. Adding them makes every column worse, cross-team most of all, so habits,buy stays the best set. Habits alone gains the most from shrinkage (+7.2 points), which fits movement features being the map-dependent ones.

### Bühlmann k per feature

k_f uses the reference formula. "Fold range" is its range over the 65 leave-one-match-out fits. Straub is the exact estimator.

| Feature | k_f | Fold range | Straub k |
|---|---|---|---|
| habits.jumps_per_min | 0.81 | 0.78–0.83 | 0.56 |
| habits.back_frac | 3.56 | 3.28–4.05 | 1.91 |
| habits.walk_frac | 4.09 | 3.68–4.65 | 2.10 |
| habits.switch_per_min | 4.90 | 3.88–5.97 | 2.37 |
| habits.w_plus_strafe_frac | 5.57 | 4.92–6.42 | 2.57 |
| habits.strafe_only_frac | 7.20 | 6.48–8.66 | 2.99 |
| habits.crouch_per_min | 13.01 | 10.67–17.39 | 3.96 |
| buy.rank_flash | 32.11 | 18.52–293.26 | 5.20 |
| habits.knife_out_frac | 134.96 | 19.36–inf | 6.22 |
| habits.use_per_min | inf | 18.16–inf | 6.91 |
| habits.reload_per_min | inf | 6.85–inf | 10.07 |
| buy.first_delay_s | inf | inf | 10.58 |
| buy.rank_smoke | inf | inf | 10.70 |
| buy.rank_fire | inf | inf | 10.74 |
| habits.inspect_per_min | inf | inf | 17.59 |
| habits.clip_at_reload | inf | inf | 20.06 |
| buy.rank_he | inf | inf | 37.01 |
| buy.rank_armor | inf | inf | inf |
| buy.rank_defuser | inf | inf | inf |
| buy.gap_s | inf | inf | inf |

**The reference formula over-corrects.** It subtracts s²/n from each cell gap, but a cell is part of the player mean it's compared with, so the noise is s²(1/n − 1/N). That pushes the between-cell variance down and k up. With the exact Bühlmann-Straub moments, 3 features are infinite instead of 11, and movement k is 0.6–3 instead of 0.8–7.

The ordering survives: movement depends most on the map, buy and reload least. "No map effect" is too strong for most of them; "weak map effect" (k around 10–40) is accurate.

## Step 5: is the gain real?

Paired bootstrap, 1000 resamples, seed 0. Differences are in points, against the global profile unless stated. I added resampling by player because trials of one player aren't independent, which is the reason `metrics.py` gives for doing the same.

| Comparison | Test | Unit | Δ AUC (95% CI) | Δ detect@5% (95% CI) |
|---|---|---|---|---|
| k = 2 | strict, all maps | match | +0.41 (+0.20, +0.64) | +3.2 (+0.7, +5.9) |
| k = 2 | strict, all maps | player | +0.41 (+0.25, +0.57) | +3.2 (+1.1, +5.8) |
| k = 2 | strict, impostors with a cell | match | +0.43 (+0.21, +0.66) | +3.3 (+0.6, +6.2) |
| k = 2 | strict, cross-team | match | -0.26 (-0.69, +0.16) | +2.2 (-5.5, +13.7) |
| k = 2 | strict, cross-team | player | -0.26 (-1.16, +0.47) | +2.2 (-10.5, +13.9) |
| k = 2 | chronological | match | +0.25 (+0.08, +0.41) | +0.3 (-1.3, +4.1) |
| k = 2 | chronological | player | +0.25 (+0.12, +0.38) | +0.3 (-1.2, +3.7) |
| k = 5 | strict, all maps | match | +0.39 (+0.24, +0.56) | +2.8 (+0.6, +5.2) |
| k = 5 | strict, cross-team | match | -0.03 (-0.29, +0.22) | +2.4 (-4.9, +13.4) |
| k = 5 | chronological | match | +0.24 (+0.13, +0.34) | +1.6 (-0.2, +4.0) |
| Straub | strict, all maps | match | +0.44 (+0.29, +0.63) | +2.8 (+0.6, +5.5) |
| Straub | strict, impostors with a cell | match | +0.46 (+0.30, +0.65) | +2.9 (+0.5, +5.7) |
| Straub | strict, cross-team | match | +0.22 (-0.13, +0.59) | +5.1 (-3.2, +16.9) |
| Straub | strict, cross-team | player | +0.22 (-0.28, +0.74) | +5.1 (-4.9, +15.9) |
| Straub | chronological | match | +0.33 (+0.21, +0.46) | +2.1 (+0.2, +4.7) |
| Straub vs k = 2 | strict, all maps | match | +0.03 (-0.05, +0.11) | -0.4 (-1.5, +0.9) |
| Straub vs k = 2 | strict, cross-team | match | +0.48 (+0.21, +0.81) | +3.0 (-1.2, +6.2) |
| Straub vs k = 2 | strict, cross-team | player | +0.48 (+0.01, +1.06) | +3.0 (-1.1, +7.4) |
| Straub vs k = 2 | chronological | match | +0.08 (0.00, +0.18) | +1.8 (-0.9, +3.3) |

- **Overall (leave-one-match-out):** the gain is established for AUC and detect@5%, for every k tested here. It survives the map-pool check, so it isn't only "this impostor never plays that map".
- **Chronological:** the AUC gain is established. The detect@5% gain **isn't established** for k = 2 or k = 5 (both intervals include 0). It is for Straub, though only just.
- **Cross-team:** **not established** for any configuration, in AUC or in detection. All intervals include 0.

## Recommendation

1. **Adopt per-map profiles, not the global profile alone.** The overall gain is established and k = 0 shows the shrinkage itself is needed.
2. **Use per-feature Bühlmann-Straub k.** It has no free parameter to tune, matches k = 2 overall, is the only option with an established chronological detection gain, and doesn't give up the cross-team AUC that k = 2 loses. It was added after I saw the grid, so confirm it on new matches before treating it as final. If a single number is preferred, use **k = 2**, the result of the rule set in advance.
3. **Don't claim progress on transfers.** Shrinkage doesn't solve that problem, and 9 players can't settle it either way.

## Caveats

- **Cross-team evidence is thin:** 9 players and 178 queries. Its detect@5% intervals are about 20 points wide.
- **Small cells:** 56% of (player, map) cells hold one map, and 92 of 184 candidates have a single match.
- **What the bootstrap covers:** it resamples queries, not profiles, so intervals ignore uncertainty in the profiles themselves. There are 38 intervals in the table above and more in `bootstrap.csv`, with no multiple-comparison correction, so borderline ones like Straub's chronological detection (+0.2 lower bound) are weak evidence.
- **Threshold:** his detect@5% sets the threshold on the same genuine queries it's scored with, so it's optimistic as an operating point.
- **Impostors** are other pros' maps compared to a profile. None is a real friend playing on someone's account, and the data is pro-only, so nothing here shows transfer to ranked play.
- **Possibly simpler alternative:** `effects.py`'s map-centred row reaches 89% and 0.978 with no per-player cell at all. Much of the detection gain may come from the population-level map effect. That row isn't leak-free and I didn't compare it under `--strict`.
- **Observation unit:** one observation is one map, not a half, and there's no T/CT split. Side effects can't be tested from these fingerprints.
- **Missing rosters:** 18 of 161 demos have fewer than 10 players in their fingerprints. Without the demos I can't tell why.
- **Unidentified causes:** reference differences 2–5 above are listed from reading the code, not measured one by one.
- **Environment:** `uv` wasn't installed, so it ran from a temporary install with CPython 3.13.18. `pandas` and `numpy` aren't pinned in his scripts.

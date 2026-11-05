# Our method under Zhang's protocol (arXiv 2608.24893), version 1

Reproduce from the repo root: `uv run experiments/zhang_protocol/run.py` (1-2 minutes, all seeds fixed).
`ml/evaluate.py` is unchanged. Zhang's figures come from the task brief; the paper itself was not re-read.

## Verdict

**On a single map against a single map, we are below his final model and above his behaviour-only model. With a history of maps, we are level with him.**

The rule used below: "above" or "below" means his figure falls outside our 95% interval, and "level" means it falls inside. He publishes an interval only for E5 overall, so most of these comparisons ignore his own uncertainty.

| Comparison (`habits,buy`) | Ours (95% CI) | Zhang | Position |
|---|---|---|---|
| Pairwise AUC vs E5 final | 0.917 (0.902-0.933) | 0.956 (0.948-0.965) | **Below**, intervals don't overlap |
| Pairwise AP vs E5 final | 0.657 (0.611-0.714) | 0.775 | **Below** |
| Pairwise AUC vs E2 behaviour only | 0.917 (0.902-0.933) | 0.874 | **Above** |
| Pairwise AP vs E2 behaviour only | 0.657 (0.611-0.714) | 0.464 | **Above** |
| History K = 1, his mean-LLR | 0.921 (0.900-0.944) | 0.914 | Level |
| History K = 3, his mean-LLR | 0.959 (0.946-0.974) | 0.966 | Level |
| History K = 5, his mean-LLR | 0.962 (0.948-0.977) | 0.975 | Level |
| History K = 5, our per-map profile | 0.972 (0.961-0.982) | 0.975 | Level |
| Aim features only | 0.589 (0.559-0.618) | 0.915 | **Far below** |

How confident:

- **Below E5 on pairs:** confident. The gap is 0.039 AUC and the intervals are separate. It holds on all six fold partitions (0.914-0.919).
- **Above E2:** confident on our data, but it compares different datasets, and the gap could come from the data as much as the method.
- **Level on history:** this means we can't tell us apart, not that we've shown equality. His K = 5 figure sits above our mean-LLR point estimate on all six partitions (0.962-0.968), but well inside the interval.

This is **not a like-for-like comparison**, so none of this says one method is better:

| | Zhang | Ours |
|---|---|---|
| Data | D_PRO, 539 demos, 130 target players | 156 demos, 184 players |
| Features | 245 | 20 (`habits,buy`) |
| Model | Trained (LightGBM pair model, sequence model) | Untrained distance; only scales, pooled variance, k and LLR bins are fitted |
| Rank stratum | Present | None (pro data, moved to random) |
| Same-map share of pairs | 35.6% | 17.3%, so our pair surface is harder on this axis |

## Pair counts and cohorts

| | Ours | Zhang |
|---|---|---|
| Observations | 1,530 (1,498 for `aim`) | not in the brief |
| Positives | 13,565 | 10,769 |
| Negatives | 122,085 | 96,921 |
| Same-map / cross-map pairs | 23,519 / 112,131 | 38,295 / 69,395 |
| K-cohort query-fold instances | 732 | 446 |

| Fold | Players | Observations | Positives | Negatives | Same-demo negatives | Cohort queries | Cohort players | Queries lost |
|---|---|---|---|---|---|---|---|---|
| 0 | 31 | 243 | 1,839 | 16,551 | 150 | 123 | 10 | 0 |
| 1 | 31 | 159 | 869 | 7,821 | 57 | 45 | 4 | 9 |
| 2 | 31 | 237 | 2,177 | 19,593 | 116 | 108 | 8 | 19 |
| 3 | 31 | 218 | 1,508 | 13,572 | 165 | 85 | 8 | 9 |
| 4 | 30 | 241 | 2,229 | 20,061 | 134 | 111 | 8 | 21 |
| 5 | 30 | 432 | 4,943 | 44,487 | 545 | 260 | 16 | 22 |

- **Same-demo quota missed:** only 1,167 negatives (0.96%) are same-demo, against a 25% quota. Person-disjoint folds put about 1.5 of a demo's 10 players in a test fold, so the pool is tiny. The shortfall went to random, as specified.
- **Queries lost:** 80 of 812 eligible queries were dropped because fewer than 4 other identities had 5 earlier maps.
- **Concentration:** the 10 players with the most maps hold 37% of positive pairs, and the top 20 hold 64%. The cohort rests on 54 players. Fold 5 has 36% of the positives but counts for one sixth of the mean.

## Test A: pairwise surface

Mean over 6 folds, 95% CI from a player-cluster bootstrap (1000 resamples). detect@5% is **our** metric; Zhang doesn't report it.

| Features | AUC | AP | detect@5% (ours) |
|---|---|---|---|
| `habits,buy` | 0.917 (0.902-0.933) | 0.657 (0.611-0.714) | 61.5% (55.7-68.0) |
| `habits,buy,aim,strafe` | 0.892 (0.872-0.912) | 0.613 (0.563-0.670) | 50.3% (45.0-57.2) |
| `aim` | 0.589 (0.559-0.618) | 0.143 (0.125-0.167) | 10.1% (7.9-12.6) |
| Zhang E2, behaviour only | 0.874 | 0.464 | |
| Zhang E5, final | 0.956 (0.948-0.965) | 0.775 | |

Adding aim and strafe to `habits,buy` costs 0.024 AUC (paired CI -0.037 to -0.015) and 11.2 points of detection (-15.0 to -7.1).

## Test B: history aggregation

Same cohort for every K, 732 queries, 1 positive and 4 negative groups each. The AP base rate is 0.20.

`habits,buy`:

| K | Aggregation | AUC | AP | detect@5% (ours) | Zhang AUC |
|---|---|---|---|---|---|
| 1 | mean-LLR | 0.921 (0.900-0.944) | 0.767 (0.725-0.834) | 60.1% (47.5-70.3) | 0.914 |
| 1 | profile, global | 0.920 (0.899-0.941) | 0.805 (0.767-0.859) | 62.8% (54.1-73.5) | |
| 1 | profile, per-map | 0.920 (0.899-0.941) | 0.805 (0.767-0.859) | 62.8% (54.1-73.5) | |
| 3 | mean-LLR | 0.959 (0.946-0.974) | 0.880 (0.843-0.926) | 81.0% (75.1-87.6) | 0.966 |
| 3 | profile, global | 0.965 (0.953-0.977) | 0.895 (0.860-0.936) | 82.2% (76.5-89.0) | |
| 3 | profile, per-map | 0.967 (0.956-0.978) | 0.904 (0.874-0.941) | 82.9% (77.1-90.1) | |
| 5 | mean-LLR | 0.962 (0.948-0.977) | 0.887 (0.852-0.935) | 82.1% (75.5-88.5) | 0.975 |
| 5 | profile, global | 0.969 (0.957-0.979) | 0.912 (0.883-0.945) | 84.7% (77.5-89.8) | |
| 5 | profile, per-map | 0.972 (0.961-0.982) | 0.921 (0.893-0.951) | 86.4% (79.8-91.7) | |

`habits,buy,aim,strafe`:

| K | Aggregation | AUC | AP | detect@5% (ours) |
|---|---|---|---|---|
| 1 | mean-LLR | 0.890 (0.859-0.915) | 0.709 (0.658-0.771) | 45.8% (34.5-56.8) |
| 1 | profile, global | 0.890 (0.859-0.916) | 0.753 (0.704-0.809) | 49.6% (41.0-60.9) |
| 1 | profile, per-map | 0.890 (0.859-0.916) | 0.753 (0.704-0.809) | 49.6% (41.0-60.9) |
| 3 | mean-LLR | 0.938 (0.921-0.956) | 0.844 (0.805-0.891) | 69.7% (60.7-78.6) |
| 3 | profile, global | 0.947 (0.929-0.960) | 0.868 (0.831-0.905) | 70.2% (65.4-80.0) |
| 3 | profile, per-map | 0.948 (0.931-0.961) | 0.871 (0.836-0.908) | 71.5% (65.9-80.7) |
| 5 | mean-LLR | 0.945 (0.928-0.961) | 0.861 (0.827-0.905) | 74.7% (65.2-82.3) |
| 5 | profile, global | 0.953 (0.939-0.964) | 0.884 (0.856-0.918) | 75.8% (67.7-82.0) |
| 5 | profile, per-map | 0.956 (0.943-0.967) | 0.890 (0.862-0.922) | 75.5% (69.2-83.0) |

Paired differences on `habits,buy` (`paired.csv`):

| Comparison | K | AUC difference (95% CI) | Reading |
|---|---|---|---|
| Per-map vs global | 3 | +0.002 (+0.001 to +0.004) | Small but established |
| Per-map vs global | 5 | +0.003 (+0.001 to +0.005) | Small but established; detection +1.7 points (+0.4 to +4.4) |
| mean-LLR vs global | 3 | -0.006 (-0.012 to +0.002) | Not established |
| mean-LLR vs global | 5 | -0.007 (-0.014 to +0.001) | Not established |

At K = 1 per-map and global are identical by construction: with one map the cell is that map, with the same mean and the same prior variance. At K = 1 mean-LLR's AP is 0.038 lower than the profile's (-0.051 to -0.016), which fits having only 20 possible scores.

## Slices (Test A, `habits,buy`)

| Slice | Positives / negatives | AUC | AP | Zhang E5 AUC | Zhang E5 AP | Position (AUC) |
|---|---|---|---|---|---|---|
| Same-map | 2,261 / 21,258 | 0.937 (0.921-0.953) | 0.723 (0.680-0.788) | 0.980 | 0.808 | Below |
| Cross-map | 11,304 / 100,827 | 0.913 (0.898-0.931) | 0.645 (0.600-0.704) | 0.942 | 0.768 | Below |
| Same day | 1,300 / 3,450 | 0.920 (0.902-0.942) | 0.860 (0.834-0.897) | 0.989 | | Below |
| 1-7 days | 3,464 / 17,634 | 0.927 (0.913-0.947) | 0.763 (0.724-0.823) | 0.949 | | Below, narrowly |
| 8-30 days | 2,871 / 24,975 | 0.920 (0.895-0.940) | 0.651 (0.592-0.723) | 0.924 | | Level |
| 31 days or more | 5,930 / 76,026 | 0.905 (0.882-0.927) | 0.554 (0.489-0.634) | no figure | | |
| All negatives | 13,565 / 122,085 | 0.917 (0.902-0.933) | 0.657 (0.611-0.714) | 0.956 | 0.775 | Below |
| Excluding same-demo negatives | 13,565 / 120,918 | 0.917 (0.902-0.934) | 0.659 (0.614-0.716) | 0.944 | | Below |

- **Time:** our AUC barely moves with the time gap (0.920 same day, 0.905 at 31+ days), while his drops from 0.989 to 0.924 by 8-30 days. The gap with him is almost all at short range. He has something that works very well within a day and we don't, and by 8-30 days we're level.
- **Map:** being on the same map helps us by 0.024 AUC, less than the 0.038 it gives him.
- **Same-demo:** excluding them changes nothing here, because they are only 1% of our negatives. So this slice does **not** tell us how we do on them. His drop of 0.012 suggests he has more of them or that they matter more for him.
- **AP across time slices:** not comparable, because prevalence goes from 27% (same day) to 7% (31+ days).

The other feature sets are in `slices.csv`.

## Aim

**Aim alone carries real but weak identity signal: AUC 0.589 (0.559-0.618), against 0.915 for Zhang.** The interval excludes chance, but AP is 0.143 against a 0.10 base rate, and detection is 10.1%.

| Feature | AUC alone | Note |
|---|---|---|
| `aim.speed_at_shot` | 0.612 | The only feature clearly above the others |
| `aim.flick_deg_s` | 0.552 | |
| `aim.on_target_ms` | 0.549 | |
| `aim.err_125ms` | 0.549 | |
| `aim.err_250ms` | 0.543 | |
| `aim.err_shot` | 0.541 | |
| `aim.err_500ms` | 0.540 | |
| `aim.headshot` | 0.502 | 96.3% of values are exactly 0, so it's nearly constant |

- **Missing values:** 32 of 1,530 observations (2.1%) have no aim, which is 256 values. All 8 features go missing together, because the player had fewer than 10 engagements on that map.
- **Handling differs by set:** the `aim` run drops those rows (`load_fingerprints` removes all-NaN rows), while `habits,buy,aim,strafe` keeps them and sets them to 0 after z-scoring. Imputation can't explain the weak aim-only result, since none is involved there.
- **Why it's so far from his:** not established. Our aim vector is 8 per-map medians anchored on the first shot of an engagement, scored by an untrained distance. His aim/crosshair block sits inside a trained model and we haven't compared its definition, so the two may not measure the same thing. The best feature being speed at the shot, rather than aim error, suggests movement or weapon choice more than aim. That is a hypothesis, not something tested here.
- **The full-set loss can't be pinned on aim:** the protocol adds aim and strafe together, so the -0.024 AUC isn't split between them.
- **Strafe missingness leaks identity:** 226 observations from 53 players have no strafe values, up to 23 for one player. Both sides are missing in 9.6% of positive pairs against 2.5% of negatives, and imputing 0 makes those gaps exactly 0. The full set is worse despite this cue.

## What could inflate or distort these numbers

- **Team and context (not measured here):** same-player pairs nearly always share a team, and negatives rarely do. Part of this AUC can be team or context rather than the person. Our earlier cross-team result (63.6% detection, against 87.4% overall) points the same way. Zhang may have the same issue.
- **Stale negative histories in Test B:** the newest map of a negative history is a median 16 days before the query, against 2 days for a positive one. The protocol's "K most recent" causes this, and a profile can benefit from freshness. It may flatter our Test B figures, and whether his has the same gap isn't known.
- **Within-day order is arbitrary:** `played_on` has day resolution only, so same-day matches are ordered by folder name. This affects 20 player-days of 630, across 4 dates.
- **Small cohort:** fold 1 has 4 query players. Per-fold AUC at K = 5 (per-map) runs from 0.955 to 0.984.

## Where this differs from the brief

1. **Negative histories** use the same rule as the positive one (ranked before the query, query's match excluded), not strictly "before the query date". Otherwise only positives could contain same-day maps.
2. **Bühlmann-Straub k** is the exact `buhlmann_straub_k` from `experiments/shrinkage_k/run.py`. `--context-k buhlmann` in `evaluate.py` is the approximate formula.
3. **Random negatives exclude same-demo pairs**, so the quota means what it says.
4. **Same pairs for every feature set:** the `aim` run uses the `habits,buy` pairs minus those touching its 32 absent rows (ratio 1:8.96).
5. **The bootstrap holds each fold's positive:negative ratio fixed.** Without this AP intervals lean upward, because positives grow with the square of a player's maps. A negative counts only as often as both its identities are drawn.
6. **Extra outputs:** `counts.csv`, `paired.csv`, `aim.csv`, and `partitions.csv` (five other fold seeds, point estimates only).

## Checks

- `run.py` asserts on every run that test and train identities are disjoint, that no pair crosses the boundary, and that every history is earlier, outside the query's match and of the right identity. Its weighted metrics are also checked against `ml/metrics.py`, plain and with repeated pairs.
- One-off checks, not part of `run.py`:
  - An independent O(n²) recomputation of fold 0 gave AUC 0.9005, matching `results.csv`.
  - With feature rows shuffled across observations (2 seeds), Test A gave AUC 0.493-0.508 and AP 0.098-0.102, and Test B at K = 5 gave AUC 0.484-0.513 and AP 0.205-0.214. Both are at chance.

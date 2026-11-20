# ML benchmark

One command measures the model the same way every time, like CI for the model (issue #32):

```bash
uv run ml/benchmark.py              # habits,buy, all rows, all configurations (about 1 minute; --fast about 30 s)
uv run ml/benchmark.py habits,buy,strafe --fast
uv run ml/benchmark.py --only lomo,xteam --configs global,straub
```

**Rule: every ML change gets a full benchmark run before review.** Commit the CSV and JSON it writes with the
change, and put the table in the PR description next to the previous run's.

## What it runs

Rows (`--only`, comma-separated):

| Key | Evaluation | What it asks |
|---|---|---|
| `lomo` | Leave-one-match-out, strict | Profile from every other match. The query's match also leaves the z-scoring and the shrinkage prior (`evaluate.py --strict`). |
| `chrono` | Chronological (past: all maps) | Every profile built only from maps played before the query, as a real client would. |
| `xteam` | Cross-team, strict | The true player's profile comes only from his maps with another team: does it identify the person or the team? 9 transfer players, so wide intervals. |
| `teammate` | Teammate impostor | Placeholder for issue #33. It prints "pending" until implemented. |
| `zhang-a` | Zhang Test A | One map against one map, no profile, on Zhang's identity-disjoint folds. Doesn't depend on the configuration. |
| `zhang-b` | Zhang Test B, K = 1, 3, 5 | One map against an identity's K earlier maps: his mean-LLR (configuration-independent) and our profile. |

Configurations (`--configs`), how a candidate's profile is built:

| Key | Profile |
|---|---|
| `global` | One profile from all his maps (current `evaluate.py`). |
| `k2` | Per-map: his global profile pulled toward his maps on the query's map, weight n / (n + 2). |
| `straub` | Per-map, one k per feature from the exact Bühlmann-Straub estimator (`ev.buhlmann_straub_k`). |

Other options: `--fast` (200 bootstrap resamples instead of 1000), `--seed` (default 0: Zhang's fold
partition and every bootstrap), `--ci player|match` (which interval the table shows).

## Reading the table

Rows are evaluation and metric, columns are configurations, and each cell is `value (95% CI)`.

- **AUC**: probability that the real player's map is closer to his profile than an impostor's.
- **detect@5%**: share of impostors flagged when 5% of the real player's maps raise a false alarm. This is
  the product number.
- **AP**: average precision, only for Zhang's tests, where the positive:negative ratio is fixed by the
  protocol (1:9 in Test A, 1:4 in Test B).
- **Intervals**: bootstrap over clusters, never over single trials. For the first three rows the table shows
  query-player clusters by default (`--ci match` for query-match clusters; both are in the CSV). Zhang rows
  always use identity clusters with each fold's class ratio held fixed (`zhang.measure`).
- A row that doesn't depend on the profile is shown once, in the first column.
- Compare configurations with care: two intervals overlapping doesn't mean "no difference", since the
  configurations share the same queries. For a paired comparison see `experiments/shrinkage_k/` (paired
  bootstrap) and `experiments/zhang_protocol/paired.csv`.

## Where results go

`experiments/benchmark/results/<YYYY-MM-DD>_<features>.csv`, with `+` in place of commas in the feature list
(`2026-11-20_habits+buy.csv`). One row per evaluation x configuration x metric: the value, the player and
match interval bounds, and the counts behind it (queries and players, or Zhang's positives and negatives). A rerun on the same day overwrites it. `--fast` and `--only`
runs get a `_fast` / `_only-...` suffix so they never replace a full run.

The `.json` next to it records the settings: features, configurations, rows, seed, bootstrap resamples, git
commit (flagged when the tree has uncommitted changes), Python, numpy and pandas versions, and run times.

## Where the code lives

`ml/benchmark.py` only wires things together. The evaluations are the existing ones:

- `ml/evaluate.py`: `held_out_trials`, `past_trials`, `other_matches`, `other_team`, `buhlmann_straub_k`.
- `ml/zhang.py`: Zhang's protocol, shared with `experiments/zhang_protocol/run.py`.
- `ml/metrics.py`: `auc`, `detection_at`, and `cluster_bootstrap` (built on `Ranked`, the weighted metrics of
  the Zhang experiment).

A new evaluation goes into `ROWS` in `ml/benchmark.py`. The teammate-impostor row (#33) is already there as a
placeholder: give it a `trials` function and remove `pending`.

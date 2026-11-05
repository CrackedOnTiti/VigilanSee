"""Leave-one-match-out test of context (per-map) shrinkage on Aymeric's fingerprints.

Re-implements his scoring as Claude Code described it (ml/evaluate.py):
  - per-player profile: mean + variance shrunk toward pooled within-player variance,
    weight (n-1)/(n-1+PRIOR_MAPS), PRIOR_MAPS = 10
  - score(query, profile) = sqrt( sum_f min(gap_f^2 / var_f, GAP_CAP) ), GAP_CAP = 9
  - detect@5%: share of impostors flagged when 5% of genuine queries are flagged
New: per-map context profile with mean (and variance) shrunk toward the player's
global profile, w = n_map / (n_map + k).
"""
import sys
import numpy as np
import pandas as pd

GAP_CAP, PRIOR_MAPS, MIN_MAPS = 9.0, 10, 2
rng = np.random.default_rng(0)

g = pd.read_pickle("obs.pkl")
g = g[~g["name"].str.startswith("Coach|")].copy()


def norm_team(t):
    t = t.lower().replace("team ", "").replace(" esports", "").replace(" gaming", "").strip()
    return {"nip": "ninjas in pyjamas", "liquid": "liquid"}.get(t, t)


g["team_n"] = g["team"].map(norm_team)
FEATS = [c for c in g.columns if c.startswith(("habits.", "buy."))]  # his default set
X_all = g[FEATS].to_numpy(float)


def profiles(X, players, maps, k, kvec=None):
    """Return dict player -> (mu_global, var_global, {map: (mu_ctx, var_ctx)})."""
    out = {}
    # pooled within-player variance (prior for variance shrinkage)
    dev = []
    for p in np.unique(players):
        Xp = X[players == p]
        if len(Xp) >= 2:
            dev.append(Xp - np.nanmean(Xp, 0))
    pooled = np.nanvar(np.vstack(dev), 0) + 1e-6
    kk = kvec if kvec is not None else np.full(X.shape[1], k)
    for p in np.unique(players):
        idx = players == p
        Xp, mp = X[idx], maps[idx]
        n = len(Xp)
        if n < MIN_MAPS:
            continue
        mu = np.nanmean(Xp, 0)
        s2 = np.nanvar(Xp, 0, ddof=1)
        wv = (n - 1) / (n - 1 + PRIOR_MAPS)
        var = np.where(np.isnan(s2), pooled, wv * np.nan_to_num(s2) + (1 - wv) * pooled)
        ctx = {}
        for m in np.unique(mp):
            Xm = Xp[mp == m]
            nm = len(Xm)
            with np.errstate(divide="ignore", invalid="ignore"):
                w = np.where(np.isinf(kk), 0.0, nm / (nm + kk))
            mum = np.where(np.isnan(np.nanmean(Xm, 0)), mu, np.nanmean(Xm, 0)) if nm else mu
            mu_c = w * mum + (1 - w) * mu
            if nm >= 2:
                s2m = np.nanvar(Xm, 0, ddof=1)
                s2m = np.where(np.isnan(s2m), var, s2m)
                wvm = (nm - 1) / (nm - 1 + PRIOR_MAPS)
                var_m = wvm * s2m + (1 - wvm) * var
                var_c = w * var_m + (1 - w) * var
            else:
                var_c = var
            ctx[m] = (mu_c, var_c)
        out[p] = (mu, var, ctx)
    return out


def score(q, mu, var):
    gap2 = (q - mu) ** 2 / var
    return np.sqrt(np.nansum(np.minimum(gap2, GAP_CAP)))


def get(prof, m, use_ctx):
    mu, var, ctx = prof
    return ctx[m] if (use_ctx and m in ctx) else (mu, var)


def run(k, kvec=None, use_ctx=True):
    gen, imp, gen_x, imp_x = [], [], [], []
    for M in g["match"].unique():
        te = (g["match"] == M).to_numpy()
        tr = ~te
        mu_s, sd_s = np.nanmean(X_all[tr], 0), np.nanstd(X_all[tr], 0) + 1e-9
        Z = (X_all - mu_s) / sd_s                          # standardise on profile data only
        P, Mp, T = g["player"].to_numpy(), g["map"].to_numpy(), g["team_n"].to_numpy()
        prof = profiles(Z[tr], P[tr], Mp[tr], k, kvec)
        cand = list(prof)
        for i in np.where(te)[0]:
            p, m, t = P[i], Mp[i], T[i]
            if p not in prof:
                continue
            q = Z[i]
            d_imp = [score(q, *get(prof[c], m, use_ctx)) for c in cand if c != p]
            gen.append(score(q, *get(prof[p], m, use_ctx)))
            imp.extend(d_imp)
            # cross-team: true profile from maps played for OTHER teams only
            other = tr & (P == p) & (T != t)
            if other.sum() >= MIN_MAPS:
                # rebuild with the same pooled prior: profile from other-team maps
                pr = profiles(np.vstack([Z[other], Z[tr & (P != p)]]),
                              np.concatenate([P[other], P[tr & (P != p)]]),
                              np.concatenate([Mp[other], Mp[tr & (P != p)]]), k, kvec)[p]
                gen_x.append(score(q, *get(pr, m, use_ctx)))
                imp_x.extend(d_imp)
    return np.array(gen), np.array(imp), np.array(gen_x), np.array(imp_x)


def auc(gen, imp):
    # P(impostor distance > genuine distance), ties = 0.5
    s = np.concatenate([gen, imp])
    r = pd.Series(s).rank().to_numpy()
    return (r[len(gen):].sum() - len(imp) * (len(imp) + 1) / 2) / (len(gen) * len(imp))


def det5(gen, imp):
    thr = np.quantile(gen, 0.95)                          # 5% of genuine flagged
    return (imp > thr).mean()


def buhlmann():
    Z = (X_all - np.nanmean(X_all, 0)) / (np.nanstd(X_all, 0) + 1e-9)
    df = pd.DataFrame(Z, columns=FEATS)
    df["p"], df["m"] = g["player"].to_numpy(), g["map"].to_numpy()
    ks = {}
    for f in FEATS:
        d = df[["p", "m", f]].dropna()
        d = d[d.groupby("p")[f].transform("size") >= 2]
        gm = d.groupby("p")[f].transform("mean")
        cells = d.groupby(["p", "m"])[f].agg(["mean", "var", "size"]).reset_index()
        cells = cells.merge(d.groupby("p")[f].mean().rename("gm"), left_on="p", right_index=True)
        c2 = cells[cells["size"] >= 2]
        s2w = np.average(c2["var"], weights=c2["size"] - 1)
        dev = cells["mean"] - cells["gm"]
        s2b = np.average(dev ** 2, weights=cells["size"]) - np.average(s2w / cells["size"], weights=cells["size"])
        ks[f] = s2w / s2b if s2b > 0 else np.inf
    return pd.Series(ks)


if __name__ == "__main__":
    print(f"players (no coaches): {g.player.nunique()}, obs: {len(g)}, "
          f"transfer players: {(g.groupby('player').team_n.nunique() > 1).sum()}")
    kb = buhlmann()
    print("\nBühlmann k per feature (n = maps in that player×map cell):")
    print(kb.round(1).sort_values().to_string())
    rows = []
    gen, imp, gx, ix = run(np.inf, use_ctx=False)
    rows.append(("baseline: global profile (his)", "-", auc(gen, imp), det5(gen, imp), auc(gx, ix), det5(gx, ix), len(gen), len(gx)))
    for k in [0, 1, 2, 5, 10, 20, 50]:
        gen, imp, gx, ix = run(float(k))
        rows.append(("per-map shrinkage", k, auc(gen, imp), det5(gen, imp), auc(gx, ix), det5(gx, ix), len(gen), len(gx)))
        print("done k", k, file=sys.stderr)
    gen, imp, gx, ix = run(None, kvec=kb.reindex(FEATS).to_numpy())
    rows.append(("per-map shrinkage", "Bühlmann k_f", auc(gen, imp), det5(gen, imp), auc(gx, ix), det5(gx, ix), len(gen), len(gx)))
    res = pd.DataFrame(rows, columns=["config", "k", "AUC_all", "det5_all", "AUC_xteam", "det5_xteam", "n_gen", "n_gen_xteam"])
    res.to_csv("results.csv", index=False)
    print(res.round(3).to_string(index=False))

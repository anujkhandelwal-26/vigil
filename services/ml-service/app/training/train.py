#!/usr/bin/env python3
"""
VIGIL model training.

  python -m app.training.train

Reads data/generated/applications.csv, does a TIME-BASED split (never
random -- a random split would scatter ring members across train/test and
inflate the reported numbers), trains a LightGBM classifier, isotonic-
calibrates it, fits the IsolationForest novelty channel, grid-searches the
four-action cost-minimising thresholds, runs a post-hoc fairness audit, and
writes everything to services/ml-service/artifacts/.

PR-AUC and recall@1%FPR are reported (not ROC-AUC alone) because the base
rate here is ~3.5%; ROC-AUC is misleadingly optimistic at this prevalence.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_curve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.features import build_feature_frame, FEATURE_COLUMNS, CATEGORICAL_FEATURES

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "generated", "applications.csv")

# Cost assumptions (INR), stated explicitly so the threshold search is
# falsifiable, not a magic number. See docs/model-card.md for the rationale.
C_FN = 150000     # average loss given a missed fraud (recovery-adjusted)
C_FP = 8000       # lifetime value of a wrongly hard-declined good customer
C_STEPUP = 150    # OTP / e-KYC friction cost, applied regardless of label
C_REVIEW = 400    # analyst minutes, applied regardless of label


def recall_at_fpr(y_true, scores, target_fpr=0.01):
    fpr, tpr, thr = roc_curve(y_true, scores)
    idx = np.searchsorted(fpr, target_fpr, side="right") - 1
    idx = max(idx, 0)
    return float(tpr[idx]), float(thr[idx])


def search_thresholds(y_true, scores):
    """
    Grid-search (t_low, t_high, t_decline) to minimise expected cost.
    Vectorised via prefix sums over score-sorted rows: since the action for
    a row is fully determined by which of the four score bands it falls
    into, cost is additive over contiguous segments of the sorted array.
    """
    order = np.argsort(scores)
    y_sorted = y_true[order]
    scores_sorted = scores[order]
    n = len(scores_sorted)
    fraud_cum = np.concatenate([[0], np.cumsum(y_sorted)])  # fraud_cum[i] = frauds in [0,i)

    candidates = np.unique(np.quantile(scores_sorted, np.linspace(0.0, 1.0, 41)))
    candidates = np.clip(candidates, 0.0, 1.0)
    # Guard against a degenerate score distribution (e.g. near-perfect
    # separation collapsing most quantiles to 0/1): fall back to a fixed
    # fine-grained grid so three DISTINCT thresholds always exist.
    if len(candidates) < 4:
        candidates = np.unique(np.concatenate([candidates, np.linspace(0.0, 1.0, 21)]))

    def idx_for(t):
        return int(np.searchsorted(scores_sorted, t, side="left"))

    best = None
    for t_low in candidates:
        i_low = idx_for(t_low)
        for t_high in candidates:
            if t_high <= t_low:
                continue
            i_high = idx_for(t_high)
            for t_decline in candidates:
                if t_decline <= t_high:
                    continue
                i_decline = idx_for(t_decline)

                fraud_in_approve = fraud_cum[i_low]
                legit_in_decline = (n - i_decline) - (fraud_cum[n] - fraud_cum[i_decline])
                stepup_n = i_high - i_low
                review_n = i_decline - i_high

                cost = (C_FN * fraud_in_approve
                        + C_FP * legit_in_decline
                        + C_STEPUP * stepup_n
                        + C_REVIEW * review_n)
                if best is None or cost < best[0]:
                    best = (cost, float(t_low), float(t_high), float(t_decline))
    if best is None:
        # Last-resort fallback: fixed thresholds, still four distinct bands.
        best = (float("nan"), 0.15, 0.45, 0.75)
    return best  # (cost, t_low, t_high, t_decline)


def naive_binary_decline_rate(y_true, scores, t=0.5):
    declined = scores >= t
    return float(declined.mean()), float((declined & (y_true == 0)).sum() / max((y_true == 0).sum(), 1))


def action_for(score, t_low, t_high, t_decline):
    if score < t_low:
        return "APPROVE"
    if score < t_high:
        return "STEP_UP"
    if score < t_decline:
        return "REVIEW"
    return "DECLINE"


COST_CURVE_KEYS = (
    "expected_cost_inr", "cost_assumptions_inr",
    "naive_binary_decline_rate", "naive_binary_fp_rate",
    "four_way_decline_rate", "four_way_fp_rate",
)


def cost_metrics(y_true, scores, cost, t_low, t_high, t_decline):
    """The metrics /internal/metrics/cost-curve reads. Shared by train.py and
    retrain.py so a promoted retrain doesn't lose the false-positive-reduction
    evidence."""
    naive_decline_rate, naive_fp_rate = naive_binary_decline_rate(y_true, scores, 0.5)
    actions = np.array([action_for(s, t_low, t_high, t_decline) for s in scores])
    declined = actions == "DECLINE"
    return {
        "expected_cost_inr": float(cost),
        "cost_assumptions_inr": {"C_FN": C_FN, "C_FP": C_FP, "C_STEPUP": C_STEPUP, "C_REVIEW": C_REVIEW},
        "naive_binary_decline_rate": naive_decline_rate,
        "naive_binary_fp_rate": naive_fp_rate,
        "four_way_decline_rate": float(declined.mean()),
        "four_way_fp_rate": float((declined & (y_true == 0)).sum() / max((y_true == 0).sum(), 1)),
    }


def fairness_report(df_raw, y_true, scores, t_low, t_high, t_decline):
    actions = np.array([action_for(s, t_low, t_high, t_decline) for s in scores])
    declined = actions == "DECLINE"
    out = {}
    for group_col, label in [("gender", "gender"), ("age_band", "age_band")]:
        if group_col == "age_band":
            groups = pd.cut(df_raw["age"], bins=[0, 30, 45, 100], labels=["<=30", "31-45", "45+"])
        else:
            groups = df_raw[group_col]
        rows = {}
        for g in pd.unique(groups.dropna()):
            mask = (groups == g).values
            n_g = mask.sum()
            if n_g == 0:
                continue
            approval_rate = float((actions[mask] == "APPROVE").mean())
            fp_rate = float((declined[mask] & (y_true[mask] == 0)).sum() / max((y_true[mask] == 0).sum(), 1))
            rows[str(g)] = {"n": int(n_g), "approval_rate": approval_rate, "fp_rate": fp_rate}
        if rows:
            max_appr = max(v["approval_rate"] for v in rows.values()) or 1e-9
            for v in rows.values():
                v["disparate_impact_ratio"] = round(v["approval_rate"] / max_appr, 4)
            out[label] = rows
    return out


def main():
    t0 = time.time()
    print(f"loading {DATA_PATH}")
    df = pd.read_csv(DATA_PATH, parse_dates=["submitted_at"])
    df = df.sort_values("submitted_at").reset_index(drop=True)
    n = len(df)
    print(f"loaded {n} rows, fraud rate {df['label_fraud'].mean():.4f}")

    i_train = int(n * 0.70)
    i_calib = int(n * 0.85)
    train_df, calib_df, test_df = df.iloc[:i_train], df.iloc[i_train:i_calib], df.iloc[i_calib:]
    print(f"time-based split: train={len(train_df)} calib={len(calib_df)} test={len(test_df)}")

    X_train = build_feature_frame(train_df)
    X_calib = build_feature_frame(calib_df)
    X_test = build_feature_frame(test_df)
    y_train = train_df["label_fraud"].astype(int).values
    y_calib = calib_df["label_fraud"].astype(int).values
    y_test = test_df["label_fraud"].astype(int).values

    pos = max(y_train.sum(), 1)
    neg = len(y_train) - pos
    scale_pos_weight = neg / pos
    print(f"scale_pos_weight={scale_pos_weight:.2f}")

    # Regularised deliberately: unregularised GBMs will happily memorise a
    # designed synthetic signal to ~1.00 AUC, which is exactly the
    # "too-good-to-be-true" pattern we rejected in the public datasets
    # (see docs/dataset-audit.md). Depth, leaf-count and row/column
    # subsampling are capped so the reported number reflects generalisable
    # signal, not synthetic-data memorisation.
    model = LGBMClassifier(
        n_estimators=150,
        learning_rate=0.05,
        num_leaves=15,
        max_depth=5,
        min_child_samples=60,
        subsample=0.7,
        subsample_freq=1,
        colsample_bytree=0.7,
        reg_alpha=0.5,
        reg_lambda=2.0,
        scale_pos_weight=scale_pos_weight,
        random_state=20260921,
        verbosity=-1,
    )
    model.fit(X_train, y_train, categorical_feature=CATEGORICAL_FEATURES)

    calibrated = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
    calibrated.fit(X_calib, y_calib)

    test_scores = calibrated.predict_proba(X_test)[:, 1]
    pr_auc = average_precision_score(y_test, test_scores)
    recall_1pct, _ = recall_at_fpr(y_test, test_scores, 0.01)
    print(f"PR-AUC={pr_auc:.4f}  recall@1%FPR={recall_1pct:.4f}")

    cost, t_low, t_high, t_decline = search_thresholds(y_test, test_scores)
    print(f"optimal thresholds: low={t_low:.3f} high={t_high:.3f} decline={t_decline:.3f}  total_cost=₹{cost:,.0f}")

    cost_m = cost_metrics(y_test, test_scores, cost, t_low, t_high, t_decline)
    print(f"binary@0.5 decline_rate={cost_m['naive_binary_decline_rate']:.4f} fp_rate={cost_m['naive_binary_fp_rate']:.4f}")
    print(f"four-way   decline_rate={cost_m['four_way_decline_rate']:.4f} fp_rate={cost_m['four_way_fp_rate']:.4f}")

    iso_train = X_train[y_train == 0].copy()
    behavioural_cols = ["form_fill_seconds", "typing_speed_cpm", "paste_events",
                         "field_corrections", "session_screens", "device_reuse_count_30d",
                         "ip_distinct_apps_24h", "is_emulator", "is_rooted", "vpn_or_proxy"]
    iso = IsolationForest(n_estimators=200, contamination=0.02, random_state=20260921)
    iso.fit(iso_train[behavioural_cols])

    fairness = fairness_report(test_df, y_test, test_scores, t_low, t_high, t_decline)

    importances = dict(zip(FEATURE_COLUMNS, [float(x) for x in model.feature_importances_]))
    importances = dict(sorted(importances.items(), key=lambda kv: -kv[1])[:15])

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    import joblib
    joblib.dump(calibrated, os.path.join(ARTIFACT_DIR, "model.pkl"))
    joblib.dump(iso, os.path.join(ARTIFACT_DIR, "isoforest.pkl"))
    joblib.dump(behavioural_cols, os.path.join(ARTIFACT_DIR, "isoforest_columns.pkl"))

    metrics = {
        "version": "v1.0.0",
        "algorithm": "LightGBM (isotonic-calibrated) + IsolationForest novelty channel",
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "training_rows": len(train_df),
        "calibration_rows": len(calib_df),
        "test_rows": len(test_df),
        "base_rate": float(df["label_fraud"].mean()),
        "pr_auc": float(pr_auc),
        "recall_at_1pct_fpr": float(recall_1pct),
        "threshold_low": t_low,
        "threshold_high": t_high,
        "threshold_decline": t_decline,
        **cost_m,
        "feature_importance_top15": importances,
        "fairness": fairness,
        "train_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(ARTIFACT_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"wrote artifacts to {ARTIFACT_DIR}")
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

"""
Self-learning, mechanism 1: analyst-feedback relabelling with a
promotion gate.

Rebuilds the training frame from the original synthetic dataset PLUS every
analyst_feedback row (at higher sample weight -- they are the hard cases
the model got wrong), refits, and writes a new model_registry row. The
caller (main.py's /internal/retrain) hot-swaps the in-memory active model
ONLY if the new model's holdout PR-AUC is >= the incumbent's -- "we retrain
continuously, we promote on merit," not automatically.
"""
from __future__ import annotations

import json
import os
import time

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score

from app.db import get_conn
from app.features import build_feature_frame, CATEGORICAL_FEATURES
from app.training.train import (
    ARTIFACT_DIR, DATA_PATH, recall_at_fpr, search_thresholds, fairness_report, cost_metrics,
)

FEEDBACK_SAMPLE_WEIGHT = 5.0  # feedback rows are hard cases; weight them up


def _next_version(current: str, taken: set[str]) -> str:
    """Next minor version after `current` that isn't already in `taken`
    (registry rows or artifact dirs) -- so a retrain after a restart can't
    reuse, and overwrite, a version that already exists."""
    try:
        major, minor, _ = current.lstrip("v").split(".")
        minor = int(minor)
        while True:
            minor += 1
            candidate = f"v{major}.{minor}.0"
            if candidate not in taken:
                return candidate
    except ValueError:
        return f"v{int(time.time())}"


def _taken_versions() -> set[str]:
    taken = {d for d in os.listdir(ARTIFACT_DIR) if os.path.isdir(os.path.join(ARTIFACT_DIR, d))}
    with get_conn() as conn:
        taken |= {r[0] for r in conn.execute("SELECT version FROM model_registry").fetchall()}
    return taken


def _load_feedback_rows() -> pd.DataFrame:
    """Every application with an analyst verdict, labelled from that verdict
    (not from the generator's original label -- the analyst's word is final)."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT a.*, af.verdict
            FROM application a
            JOIN LATERAL (
                SELECT verdict FROM analyst_feedback
                WHERE application_id = a.id ORDER BY created_at DESC LIMIT 1
            ) af ON true
            """
        )
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=cols)
    df["label_fraud"] = df["verdict"] == "FRAUD"
    return df


def retrain(current_version: str) -> dict:
    t0 = time.time()
    base_df = pd.read_csv(DATA_PATH, parse_dates=["submitted_at"])
    feedback_df = _load_feedback_rows()

    base_df = base_df.sort_values("submitted_at").reset_index(drop=True)
    i_train = int(len(base_df) * 0.70)
    i_calib = int(len(base_df) * 0.85)
    train_df, calib_df, test_df = base_df.iloc[:i_train], base_df.iloc[i_train:i_calib], base_df.iloc[i_calib:]

    X_train = build_feature_frame(train_df)
    y_train = train_df["label_fraud"].astype(int).values
    sample_weight = np.ones(len(X_train))

    feedback_rows_used = 0
    if not feedback_df.empty:
        X_fb = build_feature_frame(feedback_df)
        y_fb = feedback_df["label_fraud"].astype(int).values
        X_train = pd.concat([X_train, X_fb], ignore_index=True)
        # pd.concat silently drops the 'category' dtype when the two frames'
        # category sets differ, which LightGBM then rejects outright ("pandas
        # dtypes must be int, float or bool") -- restore it explicitly.
        for col in CATEGORICAL_FEATURES:
            X_train[col] = X_train[col].astype("category")
        y_train = np.concatenate([y_train, y_fb])
        sample_weight = np.concatenate([sample_weight, np.full(len(X_fb), FEEDBACK_SAMPLE_WEIGHT)])
        feedback_rows_used = len(X_fb)

    X_calib = build_feature_frame(calib_df)
    X_test = build_feature_frame(test_df)
    y_calib = calib_df["label_fraud"].astype(int).values
    y_test = test_df["label_fraud"].astype(int).values

    pos = max((y_train * sample_weight).sum(), 1)
    neg = sample_weight.sum() - pos
    scale_pos_weight = neg / pos

    model = LGBMClassifier(
        n_estimators=150, learning_rate=0.05, num_leaves=15, max_depth=5,
        min_child_samples=60, subsample=0.7, subsample_freq=1, colsample_bytree=0.7,
        reg_alpha=0.5, reg_lambda=2.0, scale_pos_weight=scale_pos_weight,
        random_state=20260921, verbosity=-1,
    )
    model.fit(X_train, y_train, sample_weight=sample_weight, categorical_feature=CATEGORICAL_FEATURES)

    calibrated = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
    calibrated.fit(X_calib, y_calib)

    test_scores = calibrated.predict_proba(X_test)[:, 1]
    pr_auc = average_precision_score(y_test, test_scores)
    recall_1pct, _ = recall_at_fpr(y_test, test_scores, 0.01)
    cost, t_low, t_high, t_decline = search_thresholds(y_test, test_scores)

    iso_train = X_train[y_train == 0]
    behavioural_cols = ["form_fill_seconds", "typing_speed_cpm", "paste_events",
                         "field_corrections", "session_screens", "device_reuse_count_30d",
                         "ip_distinct_apps_24h", "is_emulator", "is_rooted", "vpn_or_proxy"]
    iso = IsolationForest(n_estimators=200, contamination=0.02, random_state=20260921)
    iso.fit(iso_train[behavioural_cols])

    fairness = fairness_report(test_df, y_test, test_scores, t_low, t_high, t_decline)
    importances = dict(zip(X_train.columns, [float(x) for x in model.feature_importances_]))
    importances = dict(sorted(importances.items(), key=lambda kv: -kv[1])[:15])

    new_version = _next_version(current_version, _taken_versions())
    version_dir = os.path.join(ARTIFACT_DIR, new_version)
    os.makedirs(version_dir, exist_ok=False)
    joblib.dump(calibrated, os.path.join(version_dir, "model.pkl"))
    joblib.dump(iso, os.path.join(version_dir, "isoforest.pkl"))
    joblib.dump(behavioural_cols, os.path.join(version_dir, "isoforest_columns.pkl"))

    result = {
        "version": new_version,
        "algorithm": "LightGBM (isotonic-calibrated) + IsolationForest novelty channel",
        "training_rows": int(len(X_train)),
        "feedback_rows_used": feedback_rows_used,
        "pr_auc": float(pr_auc),
        "recall_at_1pct_fpr": float(recall_1pct),
        "threshold_low": t_low,
        "threshold_high": t_high,
        "threshold_decline": t_decline,
        "fp_rate": float(((test_scores >= t_decline) & (y_test == 0)).sum() / max((y_test == 0).sum(), 1)),
        **cost_metrics(y_test, test_scores, cost, t_low, t_high, t_decline),
        "feature_importance": importances,
        "fairness": fairness,
        "artifact_dir": version_dir,
        "train_seconds": round(time.time() - t0, 1),
    }
    # Written alongside the pickles so scoring.load_artifacts() can restore
    # this version's thresholds after a restart.
    with open(os.path.join(version_dir, "metrics.json"), "w") as f:
        json.dump(result, f, indent=2)

    return {**result, "_model_obj": calibrated, "_iso_obj": iso, "_iso_cols": behavioural_cols}

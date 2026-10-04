"""
Inference: LightGBM risk score (isotonic-calibrated), IsolationForest
novelty channel (Tier 2, deliberately NOT blended into risk_score -- see
docs/model-card.md), and SHAP -> reason-code explanation.

Model artifacts are loaded once at process startup (see main.py lifespan),
not per-request -- this is what keeps /score under ~50ms.
"""
from __future__ import annotations

import json
import math
import os

import joblib
import numpy as np
import pandas as pd
import shap

from app.config import settings
from app.features import build_feature_vector, FEATURE_TO_REASON_CODE

_STATE: dict = {}


_ACTION_ORDER = ["APPROVE", "STEP_UP", "REVIEW", "DECLINE"]


def _build_state(model, iso, iso_cols, version: str, metrics: dict) -> dict:
    raw_lgbm = model.calibrated_classifiers_[0].estimator
    return {
        "model": model,
        "iso": iso,
        "iso_cols": iso_cols,
        "metrics": metrics,
        "explainer": shap.TreeExplainer(raw_lgbm),
        "version": version,
        "thresholds": {
            "low": metrics["threshold_low"],
            "high": metrics["threshold_high"],
            "decline": metrics["threshold_decline"],
        },
    }


def _active_registry_row() -> dict | None:
    """The model_registry row marked active, or None if there isn't one (or
    the DB is unreachable at startup -- the base artifacts are then served)."""
    try:
        from app.db import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT version, pr_auc, recall_at_1pct_fpr, fp_rate, threshold_low, "
                "threshold_high, threshold_decline FROM model_registry WHERE active = true "
                "ORDER BY trained_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
        return {k: (float(v) if k != "version" and v is not None else v) for k, v in zip(cols, row)}
    except Exception as e:
        print(f"[scoring] could not read model_registry, serving base artifacts: {e}")
        return None


def load_artifacts():
    """Load the model the registry says is active, so a restart no longer
    silently reverts to the base v1.0.0 artifacts after a promoted retrain.
    Retrained versions live in artifacts/<version>/; the base model lives in
    artifacts/ itself."""
    d = settings.model_dir
    with open(os.path.join(d, "metrics.json")) as f:
        metrics = json.load(f)
    version = metrics.get("version", "v1.0.0")

    active = _active_registry_row()
    if active and active["version"] != version:
        vdir = os.path.join(d, active["version"])
        if os.path.exists(os.path.join(vdir, "model.pkl")):
            d = vdir
            version = active["version"]
            vmetrics = os.path.join(vdir, "metrics.json")
            if os.path.exists(vmetrics):
                with open(vmetrics) as f:
                    metrics = json.load(f)
            else:
                # Older retrains didn't write metrics.json; the registry row
                # carries the numbers that matter for serving.
                metrics = {**active}
        else:
            print(f"[scoring] active registry version {active['version']} has no artifacts "
                  f"at {vdir}; serving {version}")

    model = joblib.load(os.path.join(d, "model.pkl"))
    iso = joblib.load(os.path.join(d, "isoforest.pkl"))
    iso_cols = joblib.load(os.path.join(d, "isoforest_columns.pkl"))

    # One dict.update call: requests see the old bundle or the new, never a mix.
    _STATE.update(_build_state(model, iso, iso_cols, version, metrics))
    return _STATE


def is_loaded() -> bool:
    return "model" in _STATE


def hot_swap(model, iso, iso_cols, version: str, metrics: dict) -> None:
    """Promote a newly retrained model into the live serving path. Called
    only after the caller has checked the promotion gate AND committed the
    registry row -- the gate lives in main.py's /internal/retrain, this
    function just performs the swap."""
    _STATE.update(_build_state(model, iso, iso_cols, version, metrics))


def _action_for(score: float, thresholds: dict) -> str:
    t = thresholds
    if score < t["low"]:
        return "APPROVE"
    if score < t["high"]:
        return "STEP_UP"
    if score < t["decline"]:
        return "REVIEW"
    return "DECLINE"


def _escalate(action: str, floor: str) -> str:
    return action if _ACTION_ORDER.index(action) >= _ACTION_ORDER.index(floor) else floor


def _anomaly_score(X: pd.DataFrame, state: dict) -> float:
    iso = state["iso"]
    cols = state["iso_cols"]
    row = X[cols]
    # decision_function: higher = more normal. Sigmoid-compress the negated
    # value into (0, 1), where 1 = highly anomalous. Scale factor chosen so
    # typical IsolationForest decision_function magnitudes (~-0.2..0.2) map
    # to a usable spread; see docs/model-card.md for the calibration note.
    raw = float(iso.decision_function(row)[0])
    return 1.0 / (1.0 + math.exp(raw * 18.0))


def _shap_value(val):
    """Numbers as float, categorical levels as str, NaN/unseen as None --
    float() on a categorical level ("SALARIED") raises ValueError."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (bool, int, float, np.number)):
        return float(val)
    return str(val)


def score_application(app_dict: dict) -> dict:
    # Snapshot once, so a concurrent hot_swap can't pair the new model's score
    # with the old model's thresholds mid-request.
    state = dict(_STATE)
    X = build_feature_vector(app_dict)
    model = state["model"]

    risk_score = float(model.predict_proba(X)[:, 1][0])
    anomaly_score = _anomaly_score(X, state)
    action = _action_for(risk_score, state["thresholds"])

    # The novelty channel stays out of risk_score, but it can route a case to
    # a human: a pattern the supervised model has never seen can score low
    # risk while being highly anomalous.
    novel = anomaly_score >= settings.anomaly_review_threshold
    if novel:
        action = _escalate(action, "REVIEW")

    explainer = state["explainer"]
    shap_values = explainer.shap_values(X)
    if isinstance(shap_values, list):
        contrib = shap_values[1][0]  # class-1 (fraud) contributions
    else:
        contrib = shap_values[0]

    pairs = list(zip(X.columns, X.iloc[0].values, contrib))
    pairs.sort(key=lambda p: -abs(p[2]))
    top5 = pairs[:5]

    shap_top = []
    reason_codes = []
    for feat, val, c in top5:
        direction = "increases_risk" if c > 0 else "decreases_risk"
        shap_top.append({
            "feature": feat,
            "value": _shap_value(val),
            "contribution": float(c),
            "direction": direction,
        })
        if c > 0:
            code = FEATURE_TO_REASON_CODE.get(feat)
            if code and code not in reason_codes:
                reason_codes.append(code)

    if novel or (action == "DECLINE" and not reason_codes):
        reason_codes.append("NOVEL_PATTERN_UNSCORED")

    return {
        "risk_score": round(risk_score, 5),
        "anomaly_score": round(anomaly_score, 5),
        "action": action,
        "reason_codes": reason_codes,
        "shap_top": shap_top,
        "model_version": state["version"],
    }

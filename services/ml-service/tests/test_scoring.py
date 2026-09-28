"""
Scoring, model-loading and copilot-fallback regressions. No database or
LLM needed: the DB-touching seams are monkeypatched.

  - a highly anomalous case is escalated to at least REVIEW
  - load_artifacts() serves the registry's active version, not always v1.0.0
  - retrain version numbers never collide with an existing version
  - the copilot fallback never exposes label_typology (the answer key)
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import scoring
from app.config import settings
from app.training.retrain import _next_version
from tests.test_features import RAW_ROW

ARTIFACTS = os.path.join(os.path.dirname(__file__), "..", "artifacts")
needs_artifacts = pytest.mark.skipif(
    not os.path.exists(os.path.join(ARTIFACTS, "model.pkl")),
    reason="trained artifacts not present (run app.training.train)",
)


@pytest.fixture
def base_model(monkeypatch):
    monkeypatch.setattr(settings, "model_dir", ARTIFACTS)
    monkeypatch.setattr(scoring, "_active_registry_row", lambda: None)
    scoring._STATE.clear()
    scoring.load_artifacts()
    yield
    scoring._STATE.clear()


@needs_artifacts
def test_high_anomaly_escalates_to_at_least_review(base_model, monkeypatch):
    monkeypatch.setattr(settings, "anomaly_review_threshold", 0.0)  # every case is "novel"
    out = scoring.score_application(dict(RAW_ROW))
    assert out["action"] in ("REVIEW", "DECLINE")
    assert "NOVEL_PATTERN_UNSCORED" in out["reason_codes"]


@needs_artifacts
def test_normal_anomaly_does_not_escalate(base_model, monkeypatch):
    monkeypatch.setattr(settings, "anomaly_review_threshold", 1.01)  # nothing is "novel"
    out = scoring.score_application(dict(RAW_ROW))
    assert out["action"] != "DECLINE"  # a clean applicant
    assert "NOVEL_PATTERN_UNSCORED" not in out["reason_codes"]


@needs_artifacts
def test_load_artifacts_serves_registry_active_version(tmp_path, monkeypatch):
    for f in ("model.pkl", "isoforest.pkl", "isoforest_columns.pkl", "metrics.json"):
        shutil.copy(os.path.join(ARTIFACTS, f), tmp_path / f)
    vdir = tmp_path / "v1.7.0"
    vdir.mkdir()
    for f in ("model.pkl", "isoforest.pkl", "isoforest_columns.pkl"):
        shutil.copy(os.path.join(ARTIFACTS, f), vdir / f)
    (vdir / "metrics.json").write_text(json.dumps(
        {"version": "v1.7.0", "pr_auc": 0.5, "threshold_low": 0.2, "threshold_high": 0.6, "threshold_decline": 0.9}
    ))
    monkeypatch.setattr(settings, "model_dir", str(tmp_path))
    monkeypatch.setattr(scoring, "_active_registry_row", lambda: {"version": "v1.7.0"})
    scoring._STATE.clear()
    try:
        scoring.load_artifacts()
        assert scoring._STATE["version"] == "v1.7.0"
        assert scoring._STATE["thresholds"] == {"low": 0.2, "high": 0.6, "decline": 0.9}
    finally:
        scoring._STATE.clear()


def test_next_version_skips_versions_already_taken():
    assert _next_version("v1.0.0", set()) == "v1.1.0"
    assert _next_version("v1.0.0", {"v1.1.0", "v1.2.0"}) == "v1.3.0"


def test_copilot_fallback_never_uses_ground_truth_label(monkeypatch):
    from app import main
    from app.schemas import CopilotRequest

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): return self
        def commit(self): pass

    class FakeLLM:
        name, model = "fake", "fake"
        def complete(self, *a, **k): return "an answer that fails validation"

    class FakeEmbed:
        def embed(self, text): return [0.0] * 768

    monkeypatch.setattr(main.retrieval, "get_application_by_id",
                        lambda _id: {"label_typology": "MULE_ACCOUNT_RING"})
    monkeypatch.setattr(main, "get_embedding_provider", lambda: FakeEmbed())
    monkeypatch.setattr(main, "classify_intent", lambda q, e: "EXPLAIN_DECISION")
    monkeypatch.setattr(main.ctx, "explain_decision", lambda row, _id: ("decision context", []))
    monkeypatch.setattr(main.ctx, "is_terminal_finding", lambda text: False)
    monkeypatch.setattr(main.ctx, "_get_latest_decision",
                        lambda _id: {"action": "REVIEW", "reason_codes": ["DEVICE_REUSE_HIGH"]})
    monkeypatch.setattr(main.retrieval, "get_reason_code_catalogue",
                        lambda: [{"code": "DEVICE_REUSE_HIGH", "title": "Device reused"}])
    monkeypatch.setattr(main, "get_llm_provider", lambda: FakeLLM())
    monkeypatch.setattr(main, "validate", lambda raw, wl, c: (False, ["forced"]))
    monkeypatch.setattr(main, "get_conn", lambda: FakeConn())

    resp = main.copilot(CopilotRequest(application_id="a1", question="why?"))
    assert "MULE_ACCOUNT_RING" not in resp.answer
    assert "REVIEW" in resp.answer and "[DEVICE_REUSE_HIGH]" in resp.answer

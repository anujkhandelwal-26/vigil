"""
VIGIL ml-service -- stateless FastAPI inference sidecar.

Endpoints:
  GET  /health
  POST /internal/score      LightGBM + SHAP + novelty; <50ms, on the hot path
  POST /internal/narrative  cached LLM case explanation; off the hot path
  POST /internal/copilot    RAG analyst copilot; off the hot path
  POST /internal/embed      utility: text -> embedding
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import json as _json
from app import retrieval, rings, scoring
from app.training import embed_policy, retrain as retrain_module
from app.config import settings
from app.copilot import context as ctx
from app.copilot.guardrails import (
    deterministic_fallback, refusal_text, sanitize_input, validate,
)
from app.copilot.router import classify_intent
from app.db import get_conn
from app.embeddings import get_embedding_provider
from app.features import build_feature_vector
from app.llm.factory import get_llm_provider
from app.schemas import ApplicationIn, CopilotRequest, CopilotResponse, ScoreOut

_RETRAIN_LOCK = threading.Lock()

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name)) as f:
        return f.read()


CASE_EXPLANATION_TEMPLATE = _load_prompt("case_explanation.v1.txt")
COPILOT_TEMPLATE = _load_prompt("copilot_answer.v1.txt")


def _embed_policy_corpus() -> None:
    # Off the startup path: Ollama may still be warming up, and a failure here
    # only degrades POLICY_LOOKUP, never scoring.
    try:
        n = embed_policy.embed_missing_policy_chunks()
        if n:
            print(f"[policy] embedded {n} policy chunk(s)")
    except Exception as e:
        print(f"[policy] could not embed policy corpus: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scoring.load_artifacts()
    threading.Thread(target=_embed_policy_corpus, daemon=True).start()
    yield


app = FastAPI(title="VIGIL ml-service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://localhost:8081"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _behavioural_profile_text(app_dict: dict) -> str:
    """Canonical text for embedding -- behavioural/device facts only, no raw PII."""
    return (
        f"product={app_dict.get('product')} channel={app_dict.get('channel')} "
        f"amount_inr={app_dict.get('amount_inr')} form_fill_seconds={app_dict.get('form_fill_seconds')} "
        f"typing_speed_cpm={app_dict.get('typing_speed_cpm')} paste_events={app_dict.get('paste_events')} "
        f"field_corrections={app_dict.get('field_corrections')} session_screens={app_dict.get('session_screens')} "
        f"device_reuse_count_30d={app_dict.get('device_reuse_count_30d')} is_emulator={app_dict.get('is_emulator')} "
        f"is_rooted={app_dict.get('is_rooted')} vpn_or_proxy={app_dict.get('vpn_or_proxy')} "
        f"ip_distinct_apps_24h={app_dict.get('ip_distinct_apps_24h')} night_application={app_dict.get('night_application')} "
        f"pan_name_match_score={app_dict.get('pan_name_match_score')} penny_drop_name_match={app_dict.get('penny_drop_name_match')} "
        f"salary_credit_regularity={app_dict.get('salary_credit_regularity')} recent_sim_swap_30d={app_dict.get('recent_sim_swap_30d')}"
    )


def _embed_and_store(application_id: str, app_dict: dict) -> None:
    try:
        provider = get_embedding_provider()
        text = _behavioural_profile_text(app_dict)
        vec = provider.embed(text)
        retrieval.upsert_case_embedding(application_id, vec, settings.embed_model)
        # Ring detection runs off the embedding this same background task
        # just wrote -- still off the hot path, still async.
        ring = rings.detect_for_application(application_id)
        if ring:
            print(f"[rings] {application_id} -> ring {ring['ring_id']} "
                  f"({ring['member_count']} members, {ring['detection_method']})")
    except Exception as e:
        # Async lane: never let an embedding/ring failure surface to the caller.
        print(f"[embed_and_store] failed for {application_id}: {e}")


@app.get("/health")
def health():
    return {
        "status": "ok" if scoring.is_loaded() else "model_not_loaded",
        "model_loaded": scoring.is_loaded(),
        "model_version": scoring._STATE.get("version"),
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
    }


@app.get("/health/llm")
def health_llm():
    try:
        provider = get_llm_provider()
        t0 = time.time()
        out = provider.complete("You are a health check.", "Reply with the single word OK.", max_tokens=5)
        return {"status": "ok", "provider": provider.name, "model": provider.model,
                "latency_ms": int((time.time() - t0) * 1000), "response": out}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/internal/score", response_model=ScoreOut)
def score(application: ApplicationIn, background_tasks: BackgroundTasks):
    if not scoring.is_loaded():
        raise HTTPException(503, "model not loaded")
    t0 = time.time()
    app_dict = application.model_dump()
    result = scoring.score_application(app_dict)
    latency_ms = int((time.time() - t0) * 1000)

    if application.application_id:
        background_tasks.add_task(_embed_and_store, application.application_id, app_dict)

    return ScoreOut(**result, latency_ms=latency_ms)


@app.post("/internal/narrative")
def narrative(application_id: str):
    app_row = retrieval.get_application_by_id(application_id)
    if app_row is None:
        raise HTTPException(404, "application not found")

    with get_conn() as conn:
        cur = conn.execute(
            "SELECT narrative, grounded, provider, model, latency_ms, cited_reason_codes, guardrail_violations "
            "FROM llm_explanation WHERE application_id = %s AND template_version = 'case_explanation.v1' "
            "ORDER BY created_at DESC LIMIT 1",
            (application_id,),
        )
        cached = cur.fetchone()
        if cached:
            return {
                "narrative": cached[0], "grounded": cached[1], "provider": cached[2],
                "model": cached[3], "latency_ms": cached[4], "cached": True,
            }

    decision_text, cited_ids = ctx.explain_decision(app_row, application_id)
    similar_text, _ = ctx.similar_cases(application_id, None)
    catalogue = retrieval.get_reason_code_catalogue()
    catalogue_text = "\n".join(f"[{c['code']}] {c['title']}" for c in catalogue)
    whitelisted = {c["code"] for c in catalogue}
    reason_titles = {c["code"]: c["title"] for c in catalogue}

    d = ctx._get_latest_decision(application_id)
    prompt = CASE_EXPLANATION_TEMPLATE.format(
        reason_codes_catalogue=catalogue_text,
        action=d["action"] if d else "UNKNOWN",
        risk_score=d["risk_score"] if d else "unknown",
        reason_codes=", ".join(d["reason_codes"]) if d and d["reason_codes"] else "none",
        shap_top=str(d["shap_top"]) if d else "none",
        similar_cases=similar_text,
    )

    provider = get_llm_provider()
    t0 = time.time()
    try:
        # The prompt template is a fully self-contained "SYSTEM:"-prefixed
        # instruction block; layering a second, generic system message on
        # top of it made qwen2.5:3b default to the rule-3 refusal string
        # regardless of context sufficiency (reproduced directly against
        # Ollama). Pass no separate system prompt here.
        raw = provider.complete("", prompt, max_tokens=250)
    except Exception as e:
        raw = ""
        print(f"[narrative] LLM call failed: {e}")

    grounded, violations = validate(raw, whitelisted, decision_text + " " + similar_text) if raw else (False, ["llm_unavailable"])
    final_text = raw if grounded else deterministic_fallback(
        d["action"] if d else "UNKNOWN", (d["reason_codes"] if d else []) or [], reason_titles,
    )
    latency_ms = int((time.time() - t0) * 1000)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO llm_explanation
               (application_id, template_version, provider, model, narrative,
                cited_reason_codes, grounded, guardrail_violations, latency_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (application_id, "case_explanation.v1", provider.name, provider.model,
             final_text, d["reason_codes"] if d else [], grounded, violations, latency_ms),
        )
        conn.commit()

    return {
        "narrative": final_text, "grounded": grounded, "provider": provider.name,
        "model": provider.model, "latency_ms": latency_ms, "cached": False,
        "guardrail_violations": violations,
    }


@app.post("/internal/copilot", response_model=CopilotResponse)
def copilot(req: CopilotRequest):
    app_row = retrieval.get_application_by_id(req.application_id)
    if app_row is None:
        raise HTTPException(404, "application not found")

    question = sanitize_input(req.question)
    embed_provider = get_embedding_provider()
    intent = classify_intent(question, embed_provider.embed)

    if intent == "EXPLAIN_DECISION":
        context_text, cited_ids = ctx.explain_decision(app_row, req.application_id)
    elif intent == "TOP_SIGNALS":
        context_text, cited_ids = ctx.top_signals(app_row, req.application_id)
    elif intent == "BEHAVIOUR_DELTA":
        context_text, cited_ids = ctx.behaviour_delta(app_row, req.application_id)
    elif intent == "CASE_SUMMARY":
        context_text, cited_ids = ctx.case_summary(app_row, req.application_id)
    elif intent == "ENTITY_LOOKUP":
        context_text, cited_ids = ctx.entity_lookup(app_row, req.application_id, question)
    elif intent == "SIMILAR_CASES":
        try:
            q_emb = embed_provider.embed(_behavioural_profile_text(app_row))
        except Exception:
            q_emb = None
        context_text, cited_ids = ctx.similar_cases(req.application_id, q_emb)
    elif intent == "POLICY_LOOKUP":
        q_emb = embed_provider.embed(question)
        context_text, cited_ids = ctx.policy_lookup(req.application_id, q_emb)
    else:
        context_text, cited_ids = "", []

    catalogue = retrieval.get_reason_code_catalogue()
    catalogue_text = "\n".join(f"[{c['code']}] {c['title']}" for c in catalogue)
    whitelisted = {c["code"] for c in catalogue}

    if not context_text:
        return CopilotResponse(
            answer=refusal_text(), intent=intent, grounded=True, cited_ids=[],
            guardrail_violations=[], provider="none", model="none", latency_ms=0,
        )

    if ctx.is_terminal_finding(context_text):
        return CopilotResponse(
            answer=context_text, intent=intent, grounded=True, cited_ids=cited_ids,
            guardrail_violations=[], provider="none", model="none", latency_ms=0,
        )

    prompt = COPILOT_TEMPLATE.format(
        reason_codes_catalogue=catalogue_text,
        intent=intent,
        retrieved_context=context_text,
        question=question,
    )

    provider = get_llm_provider()
    t0 = time.time()
    try:
        # See the narrative() comment above: no separate system prompt --
        # the template already carries its own SYSTEM: block.
        raw = provider.complete("", prompt, max_tokens=250)
    except Exception as e:
        raw = ""
        print(f"[copilot] LLM call failed: {e}")

    grounded, violations = validate(raw, whitelisted, context_text) if raw else (False, ["llm_unavailable"])
    if grounded:
        answer = raw
    elif not raw:
        answer = refusal_text()
    else:
        # Fall back to what the scoring engine actually decided -- never to
        # label_typology, which is the generator's ground-truth answer key.
        d = ctx._get_latest_decision(req.application_id)
        answer = deterministic_fallback(
            d["action"] if d else "UNKNOWN", (d["reason_codes"] if d else []) or [],
            {c["code"]: c["title"] for c in catalogue},
        )
    latency_ms = int((time.time() - t0) * 1000)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO llm_explanation
               (application_id, template_version, provider, model, narrative,
                cited_reason_codes, grounded, guardrail_violations, latency_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (req.application_id, "copilot_answer.v1", provider.name, provider.model,
             answer, [], grounded, violations, latency_ms),
        )
        conn.commit()

    return CopilotResponse(
        answer=answer, intent=intent, grounded=grounded, cited_ids=cited_ids,
        guardrail_violations=violations, provider=provider.name, model=provider.model,
        latency_ms=latency_ms,
    )


@app.post("/internal/embed")
def embed(text: str):
    provider = get_embedding_provider()
    return {"embedding": provider.embed(text), "model": settings.embed_model}


@app.get("/internal/rings/{application_id}")
def get_ring(application_id: str):
    ring = rings.get_ring_for_application(application_id)
    if ring is None:
        return {"ring": None}
    return {"ring": ring}


@app.get("/internal/metrics/cost-curve")
def cost_curve():
    """
    The false-positive-reduction evidence: naive-binary vs four-way decline
    and FP rates, plus the cost assumptions the threshold search used. Read
    straight from the training run's metrics.json -- no separate
    computation, so this can never drift from what was actually trained.
    """
    metrics = scoring._STATE.get("metrics", {})
    return {
        "naive_binary_decline_rate": metrics.get("naive_binary_decline_rate"),
        "naive_binary_fp_rate": metrics.get("naive_binary_fp_rate"),
        "four_way_decline_rate": metrics.get("four_way_decline_rate"),
        "four_way_fp_rate": metrics.get("four_way_fp_rate"),
        "expected_cost_inr": metrics.get("expected_cost_inr"),
        "cost_assumptions_inr": metrics.get("cost_assumptions_inr"),
        "thresholds": scoring._STATE.get("thresholds"),
        "model_version": scoring._STATE.get("version"),
        "fairness": metrics.get("fairness"),
    }


@app.post("/internal/retrain")
def retrain():
    """
    Self-learning, gated: rebuilds the model from the original dataset plus
    every analyst_feedback row, and hot-swaps the live model ONLY if the
    new holdout PR-AUC is >= the incumbent's. A model_registry row is
    written either way, so a rejected retrain is still visible in the
    registry with promoted_reason explaining why it wasn't promoted.
    """
    if not scoring.is_loaded():
        raise HTTPException(503, "no incumbent model loaded")
    if not _RETRAIN_LOCK.acquire(blocking=False):
        raise HTTPException(409, "a retrain is already running")
    try:
        incumbent_metrics = scoring._STATE["metrics"]
        incumbent_pr_auc = incumbent_metrics.get("pr_auc", 0.0)
        incumbent_version = scoring._STATE["version"]

        result = retrain_module.retrain(current_version=incumbent_version)
        promoted = result["pr_auc"] >= incumbent_pr_auc
        if promoted:
            promoted_reason = f"promoted: PR-AUC {result['pr_auc']:.4f} >= incumbent {incumbent_pr_auc:.4f}"
        else:
            promoted_reason = f"not promoted: PR-AUC {result['pr_auc']:.4f} < incumbent {incumbent_pr_auc:.4f}"

        # Registry first, swap second: if the INSERT fails, the live model is
        # untouched and still matches the registry's active row.
        with get_conn() as conn:
            if promoted:
                conn.execute("UPDATE model_registry SET active = false WHERE active = true")
            conn.execute(
                """INSERT INTO model_registry
                   (version, algorithm, trained_at, training_rows, feedback_rows_used,
                    pr_auc, recall_at_1pct_fpr, fp_rate, threshold_low, threshold_high,
                    threshold_decline, feature_importance, active, promoted_reason)
                   VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (result["version"], result["algorithm"], result["training_rows"], result["feedback_rows_used"],
                 result["pr_auc"], result["recall_at_1pct_fpr"], result["fp_rate"],
                 result["threshold_low"], result["threshold_high"], result["threshold_decline"],
                 _json.dumps(result["feature_importance"]), promoted, promoted_reason),
            )
            conn.commit()

        if promoted:
            metrics = {k: v for k, v in result.items() if not k.startswith("_")}
            scoring.hot_swap(result["_model_obj"], result["_iso_obj"], result["_iso_cols"],
                             result["version"], metrics)
    finally:
        _RETRAIN_LOCK.release()

    return {
        "version": result["version"],
        "promoted": promoted,
        "promoted_reason": promoted_reason,
        "pr_auc": result["pr_auc"],
        "recall_at_1pct_fpr": result["recall_at_1pct_fpr"],
        "training_rows": result["training_rows"],
        "feedback_rows_used": result["feedback_rows_used"],
        "train_seconds": result["train_seconds"],
        "incumbent_version": incumbent_version,
        "incumbent_pr_auc": incumbent_pr_auc,
    }

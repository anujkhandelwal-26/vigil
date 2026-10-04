"""
Per-intent context assembly for the copilot. Every function returns
(context_text, cited_ids) -- context_text is what goes verbatim into the
RETRIEVED CONTEXT slot of the prompt template, and every number in it must
be something the guardrail can verify the narrative against.
"""
from __future__ import annotations

from app import retrieval
from app.copilot.guardrails import sanitize_ref
from app.db import get_conn

_ENTITY_FIELD_KEYWORDS = [
    ("device_hash", ["device"]),
    ("ip_prefix", ["ip address", " ip ", "network address"]),
    ("bank_account_hash", ["bank account", "account"]),
    ("mobile_hash", ["mobile number", "phone number", "mobile"]),
]

# Context builders sometimes retrieve a definitive *absence* of data (no
# priors, no similar cases, no ring, ...). That sentence is already the
# correct, complete answer -- routing it through the LLM for paraphrase is
# where a small local model's refusal reflex tends to fire, discarding a
# real, grounded answer for the generic "I don't have data" line instead.
# Any context_text starting with one of these is passed straight through.
TERMINAL_FINDING_PREFIXES = (
    "No decision found on file",
    "No SHAP contribution data on file",
    "No prior applications on file",
    "No other applications on file share",
    "No behavioural embedding on file",
    "No similar past cases found",
    "No matching policy passages found",
)


def is_terminal_finding(context_text: str) -> bool:
    return context_text.startswith(TERMINAL_FINDING_PREFIXES)


def _get_latest_decision(application_id: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT model_version, risk_score, anomaly_score, action, reason_codes,
                      shap_top, latency_ms, created_at
               FROM decision WHERE application_id = %s
               ORDER BY created_at DESC LIMIT 1""",
            (application_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


def fmt_risk(score) -> str:
    """risk_score is NULL for rules-only decisions (ML was down)."""
    return "n/a (rules-only)" if score is None else str(score)


def _reason_titles() -> dict[str, str]:
    return {rc["code"]: rc["title"] for rc in retrieval.get_reason_code_catalogue()}


def explain_decision(application: dict, application_id: str) -> tuple[str, list[str]]:
    d = _get_latest_decision(application_id)
    if d is None:
        return "No decision found on file for this application.", []
    titles = _reason_titles()
    reasons = ", ".join(f"{c} ({titles.get(c, c)})" for c in (d["reason_codes"] or []))
    text = (
        f"Application {sanitize_ref(application['external_ref'])}: action={d['action']}, "
        f"risk_score={fmt_risk(d['risk_score'])}, model_version={d['model_version']}, "
        f"latency_ms={d['latency_ms']}. Reason codes: {reasons or 'none'}."
    )
    return text, [application_id]


def top_signals(application: dict, application_id: str) -> tuple[str, list[str]]:
    d = _get_latest_decision(application_id)
    if d is None or not d.get("shap_top"):
        return "No SHAP contribution data on file for this application.", []
    lines = []
    for s in d["shap_top"]:
        lines.append(f"{s['feature']}={s['value']} contribution={round(s['contribution'], 4)} ({s['direction']})")
    return "Top contributing signals, ranked: " + "; ".join(lines) + ".", [application_id]


def behaviour_delta(application: dict, application_id: str) -> tuple[str, list[str]]:
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT external_ref, form_fill_seconds, device_hash, amount_inr, submitted_at
               FROM application
               WHERE mobile_hash = %s AND id != %s
               ORDER BY submitted_at DESC LIMIT 5""",
            (application["mobile_hash"], application_id),
        )
        cols = [d.name for d in cur.description]
        priors = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not priors:
        return "No prior applications on file for this applicant to compare against.", [application_id]
    avg_fill = sum(p["form_fill_seconds"] for p in priors) / len(priors)
    device_changed = application["device_hash"] not in {p["device_hash"] for p in priors}
    text = (
        f"This applicant has {len(priors)} prior application(s) on file. "
        f"Average prior form-fill time was {round(avg_fill, 1)} seconds vs "
        f"{application['form_fill_seconds']} seconds this time. "
        f"Device changed since the last application: {device_changed}."
    )
    return text, [application_id] + [p["external_ref"] for p in priors]


def case_summary(application: dict, application_id: str) -> tuple[str, list[str]]:
    d = _get_latest_decision(application_id)
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT verdict, note FROM analyst_feedback WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
            (application_id,),
        )
        fb = cur.fetchone()
    parts = [
        f"Application {sanitize_ref(application['external_ref'])} for INR {application['amount_inr']} "
        f"({application['product']}, {application['tenure_months']} months), "
        f"submitted via {application['channel']}."
    ]
    if d:
        parts.append(f"Decision: {d['action']} at risk_score={fmt_risk(d['risk_score'])}.")
    if fb:
        parts.append(f"Analyst verdict on file: {fb[0]}.")
    return " ".join(parts), [application_id]


def entity_lookup(application: dict, application_id: str, question: str) -> tuple[str, list[str]]:
    q = question.lower()
    field = "device_hash"
    for f, keywords in _ENTITY_FIELD_KEYWORDS:
        if any(kw in q for kw in keywords):
            field = f
            break
    value = application[field]
    rows = retrieval.entity_lookup(field, value, exclude_application_id=application_id)
    if not rows:
        return f"No other applications on file share this {field.replace('_', ' ')}.", [application_id]
    lines = [f"{sanitize_ref(r['external_ref'])} (action={r['action']}, risk_score={fmt_risk(r['risk_score'])})" for r in rows]
    text = f"{len(rows)} other application(s) on file share this {field.replace('_', ' ')}: " + "; ".join(lines) + "."
    return text, [application_id] + [r["external_ref"] for r in rows]


def similar_cases(application_id: str, embedding: list[float] | None) -> tuple[str, list[str]]:
    if embedding is None:
        return "No behavioural embedding on file for this application yet.", [application_id]
    rows = retrieval.similar_cases(embedding, exclude_application_id=application_id, k=5)
    if not rows:
        return "No similar past cases found in the case index.", [application_id]
    lines = [
        f"{sanitize_ref(r['external_ref'])} (distance={round(r['distance'], 3)}, action={r['action']}, "
        f"analyst_verdict={r['analyst_verdict'] or 'none'})"
        for r in rows
    ]
    return "Similar past cases by behavioural embedding: " + "; ".join(lines) + ".", [application_id] + [r["external_ref"] for r in rows]


# What a case's decision and reason codes make relevant, phrased as retrieval
# queries against the policy corpus. Without these, "what policy applies to
# this case?" retrieves only on the question's wording, so a vague question
# gets generic passages the LLM (rightly) can't connect to the case.
_ACTION_POLICY_TOPICS = {
    "APPROVE": "Key Fact Statement before loan execution and the borrower's cooling-off period",
    "STEP_UP": "Aadhaar offline XML e-KYC and video KYC identity verification",
    "REVIEW": "customer due diligence proportionate to risk, enhanced due diligence for higher-risk customers",
    "DECLINE": "suspicious transaction report to FIU-India for suspected fraud",
}
_REASON_POLICY_TOPICS = {
    "AADHAAR_PAN_NOT_LINKED": "Aadhaar offline XML e-KYC identity verification",
    "PAN_NAME_MISMATCH": "Aadhaar offline XML e-KYC identity verification",
    "BUREAU_ENQUIRY_BURST": "burst of credit enquiries across multiple lenders",
    "THIN_OR_NO_BUREAU_FILE": "new-to-credit consumer with no CIBIL score",
    "BANK_ACCOUNT_SHARED": "suspicious transaction report to FIU-India for suspected fraud",
    "DEVICE_REUSE_HIGH": "suspicious transaction report to FIU-India for suspected fraud",
    "IP_MULTI_APPLICANT": "suspicious transaction report to FIU-India for suspected fraud",
    "VELOCITY_MULTI_APP_24H": "suspicious transaction report to FIU-India for suspected fraud",
    "EMULATOR_OR_ROOTED": "enhanced due diligence for higher-risk customers",
    "NOVEL_PATTERN_UNSCORED": "enhanced due diligence for higher-risk customers",
    "SIM_SWAP_RECENT": "video KYC identity verification with a live photograph",
    "MOBILE_NAME_MISMATCH": "video KYC identity verification with a live photograph",
}
# Every case in this system is processed for fraud detection.
_ALWAYS_POLICY_TOPIC = "processing personal data for prevention and detection of fraud as a legitimate use"
_MAX_POLICY_PASSAGES = 5


def _case_policy_topics(decision: dict | None, titles: dict[str, str]) -> list[tuple[str, str]]:
    """(why-it-applies, retrieval query) pairs for this case, deduped by query."""
    topics = []
    if decision:
        if decision["action"] in _ACTION_POLICY_TOPICS:
            topics.append((f"to a {decision['action']} decision",
                           _ACTION_POLICY_TOPICS[decision["action"]]))
        for c in decision["reason_codes"] or []:
            if c in _REASON_POLICY_TOPICS:
                topics.append((f"to the signal {titles.get(c, c)} [{c}]", _REASON_POLICY_TOPICS[c]))
    topics.append(("to every application screened for fraud", _ALWAYS_POLICY_TOPIC))
    seen, unique = set(), []
    for why, query in topics:
        if query not in seen:
            seen.add(query)
            unique.append((why, query))
    return unique[:3]  # bound the embed calls


def policy_lookup(application_id: str, embedding: list[float] | None,
                  embed=None) -> tuple[str, list[str]]:
    """Passages matching this case's decision and reason codes (when `embed`
    is given) plus passages matching the question. Each passage is labelled
    with why it applies, so the LLM can tie the policy to the case instead of
    judging a bare list of passages "unrelated" and refusing."""
    d = _get_latest_decision(application_id)
    labelled: list[tuple[str, dict]] = []
    if embed is not None:
        for why, query in _case_policy_topics(d, _reason_titles()):
            try:
                labelled += [(why, r) for r in retrieval.policy_lookup(embed(query), k=1)]
            except Exception:
                continue  # embedding hiccup: the question's passages still stand
    if embedding is not None:
        labelled += [("to the analyst's question", r) for r in retrieval.policy_lookup(embedding, k=2)]

    seen, unique = set(), []
    for why, r in labelled:
        if r["content"] not in seen:
            seen.add(r["content"])
            unique.append((why, r))
    unique = unique[:_MAX_POLICY_PASSAGES]
    if not unique:
        return "No matching policy passages found.", []

    # The decision came from the scoring engine; state that outright, or a
    # small model reads "policy relevant to a REVIEW decision" as "routed to
    # REVIEW because of this policy".
    header = (f"This application was routed to {d['action']} by the scoring engine, not by policy. "
              f"Policy obligations relevant to it: ") if d else ""
    text = header + " ".join(f"Relevant {why}: [{r['source']}] {r['content']}" for why, r in unique)
    return text, [r["source"] for _, r in unique]

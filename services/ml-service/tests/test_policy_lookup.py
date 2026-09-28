"""
POLICY_LOOKUP context and guardrails. No database or LLM: retrieval and the
decision lookup are monkeypatched.

Regression for: "Is there anything in this case RBI or DPDP policy-wise I
should know?" got "I don't have data on that" -- retrieval matched only the
question's wording, so the LLM saw generic passages with no link to the case.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.copilot import context as ctx
from app.copilot.guardrails import policy_causality_violation, strip_leading_refusal

PASSAGES = {
    "q": {"source": "RBI Digital Lending Directions, 2025", "content": "REs must maintain a public list of LSPs.", "distance": 0.4},
    "review": {"source": "RBI Master Direction on KYC", "content": "Customer Due Diligence proportionate to risk.", "distance": 0.2},
    "fraud": {"source": "DPDP Act, 2023", "content": "Processing for prevention and detection of fraud is a legitimate use.", "distance": 0.2},
    "enquiry": {"source": "CIBIL Act, 2005", "content": "A burst of credit enquiries is a fraud indicator.", "distance": 0.2},
}


def _patch(monkeypatch, decision):
    # Each embedding is just a tag naming the passage it should retrieve.
    def fake_embed(text):
        if "due diligence" in text:
            return "review"
        if "credit enquiries" in text:
            return "enquiry"
        if "fraud as a legitimate use" in text:
            return "fraud"
        return "q"
    monkeypatch.setattr(ctx.retrieval, "policy_lookup", lambda emb, k=3: [PASSAGES[emb]])
    monkeypatch.setattr(ctx, "_get_latest_decision", lambda _id: decision)
    monkeypatch.setattr(ctx, "_reason_titles", lambda: {"BUREAU_ENQUIRY_BURST": "Bureau enquiry burst"})
    return fake_embed


def test_policy_context_is_driven_by_the_case_not_just_the_question(monkeypatch):
    embed = _patch(monkeypatch, {"action": "REVIEW", "reason_codes": ["BUREAU_ENQUIRY_BURST"]})
    text, cited = ctx.policy_lookup("a1", "q", embed)

    assert text.startswith("This application was routed to REVIEW by the scoring engine, not by policy.")
    assert "Relevant to a REVIEW decision: [RBI Master Direction on KYC]" in text
    assert "Relevant to the signal Bureau enquiry burst [BUREAU_ENQUIRY_BURST]: [CIBIL Act, 2005]" in text
    assert "Relevant to every application screened for fraud: [DPDP Act, 2023]" in text
    assert "Relevant to the analyst's question: [RBI Digital Lending Directions, 2025]" in text
    assert len(cited) == 4
    assert not ctx.is_terminal_finding(text)


def test_policy_context_dedupes_passages(monkeypatch):
    embed = _patch(monkeypatch, {"action": "REVIEW", "reason_codes": []})
    text, cited = ctx.policy_lookup("a1", "review", embed)  # question hits the same passage
    assert text.count("Customer Due Diligence") == 1
    assert len(cited) == len(set(cited))


def test_policy_context_without_embedder_falls_back_to_question_only(monkeypatch):
    _patch(monkeypatch, None)
    text, cited = ctx.policy_lookup("a1", "q")
    assert text == "Relevant to the analyst's question: [RBI Digital Lending Directions, 2025] REs must maintain a public list of LSPs."


def test_no_passages_is_a_terminal_finding(monkeypatch):
    _patch(monkeypatch, None)
    monkeypatch.setattr(ctx.retrieval, "policy_lookup", lambda emb, k=3: [])
    text, _ = ctx.policy_lookup("a1", "q")
    assert ctx.is_terminal_finding(text)


def test_leading_refusal_is_stripped_only_when_an_answer_follows():
    assert strip_leading_refusal(
        "I don't have data on that in this case file. However, the DPDP Act applies."
    ) == "The DPDP Act applies."
    assert strip_leading_refusal("I don't have data on that in this case file.") == \
        "I don't have data on that in this case file."
    assert strip_leading_refusal("The DPDP Act applies.") == "The DPDP Act applies."


def test_policy_credited_with_decision_is_caught():
    assert policy_causality_violation("The application was routed to REVIEW based on the RBI Master Direction on KYC.")
    assert policy_causality_violation("It was declined due to DPDP policy.")
    assert not policy_causality_violation("Relevant policies include the DPDP Act, 2023 and the RBI KYC Direction.")
    assert not policy_causality_violation("The scoring engine routed this application to REVIEW.")

"""
Output guardrails for LLM-generated prose. This is the enforcement point
for the architectural invariant: the LLM only renders prose from data that
has already been retrieved and decided. Anything that violates that gets
rejected and replaced with a deterministic fallback -- the LLM never gets
the last word on whether its own output was safe.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

REASON_CODE_PATTERN = re.compile(r"\[([A-Z0-9_]+)\]")
NUMBER_PATTERN = re.compile(r"(?<![\w.])\d[\d,]*\.?\d*%?")
# Blocks the LLM acting as a decision-maker (recommending or advising an
# action) without blocking factual past-tense description of a decision the
# scoring engine already made ("this application was declined") -- the
# copilot is explicitly required to describe that as a fact, not refuse it.
DECISION_VERBS = re.compile(
    r"\b(i\s+recommend|we\s+recommend|recommend(ing|s)?\s+(that\s+)?(you|we)|"
    r"you\s+should|i\s+(would|suggest|advise)|please\s+(approve|decline|reject))\b",
    re.IGNORECASE,
)
# Coarse PII patterns: full PAN (AAAAA9999A), a 12-digit run (Aadhaar-shaped),
# or a 10-digit run (mobile-shaped). These must never appear in output even
# if present in context, because context only ever carries masked forms.
PII_PATTERNS = [
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),          # PAN format
    re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),        # Aadhaar-shaped 12 digits
    re.compile(r"\b[6-9]\d{9}\b"),                    # Indian mobile-shaped 10 digits
]

MAX_LENGTH_CHARS = 1200


def _extract_reason_codes(text: str) -> list[str]:
    return REASON_CODE_PATTERN.findall(text)


def extract_reason_codes(text: str) -> list[str]:
    return _extract_reason_codes(text)


def _extract_numbers(text: str) -> list[str]:
    # Strip thousands separators and a sentence-final '.' ("83." -> "83").
    return [n.replace(",", "").rstrip(".") for n in NUMBER_PATTERN.findall(text)]


def _to_decimal(num: str) -> Decimal | None:
    try:
        return Decimal(num.rstrip("%"))
    except InvalidOperation:
        return None


def _decimals(d: Decimal) -> int:
    return max(-d.as_tuple().exponent, 0)


def _number_supported(num: str, context_values: list[Decimal]) -> bool:
    """Numeric match: equal as numbers, or equal to a context number rounded
    to the narrative's own precision ("0.62" for a context "0.6234")."""
    n = _to_decimal(num)
    if n is None:
        return False
    places = _decimals(n)
    quantum = Decimal(1).scaleb(-places)
    for c in context_values:
        if c == n:
            return True
        try:
            if c.quantize(quantum, rounding=ROUND_HALF_UP) == n:
                return True
        except InvalidOperation:
            continue  # context number too large to quantise: not a match
    return False


def validate(
    narrative: str,
    whitelisted_codes: set[str],
    context_text: str,
) -> tuple[bool, list[str]]:
    """
    Returns (grounded: bool, violations: list[str]).
    grounded=False means the caller MUST discard `narrative` and use the
    deterministic fallback template instead.
    """
    violations = []

    if len(narrative) > MAX_LENGTH_CHARS:
        violations.append("length_exceeded")

    if DECISION_VERBS.search(narrative):
        violations.append("decision_verb_used")

    for pat in PII_PATTERNS:
        if pat.search(narrative):
            violations.append("raw_pii_pattern_detected")
            break

    cited_codes = _extract_reason_codes(narrative)
    for code in cited_codes:
        if code not in whitelisted_codes:
            violations.append(f"non_whitelisted_reason_code:{code}")

    context_values = [v for v in map(_to_decimal, set(_extract_numbers(context_text))) if v is not None]
    narrative_numbers = _extract_numbers(narrative)
    for num in narrative_numbers:
        # Allow small integers (list positions, counts like "3" signals) that
        # commonly appear as prose connective tissue without being a
        # fabricated fact; only flag numbers that look like a genuine
        # data point (2+ digits, or a decimal, or a %) absent from context.
        looks_like_data_point = len(num.replace(".", "").replace("%", "")) >= 2
        if looks_like_data_point and not _number_supported(num, context_values):
            violations.append(f"unsupported_number:{num}")

    return (len(violations) == 0), violations


# Role markers a prompt-injection attempt uses to impersonate a turn:
# "SYSTEM:", "system :", "### system", "assistant:", "user:".
_ROLE_MARKER = re.compile(
    r"(?:#+\s*)?\b(?:system|assistant|user|human)\b\s*:|#+\s*(?:system|assistant|user|human)\b",
    re.IGNORECASE,
)


def sanitize_input(text: str) -> str:
    """
    Input guardrail for analyst free-text (e.g. a note field) before it
    enters a prompt: delimits and strips characters commonly used for
    prompt injection, and caps length.
    """
    if not text:
        return ""
    text = text.replace("```", "")
    text = _ROLE_MARKER.sub(" ", text)
    text = re.sub(r"\bRULES\b", "", text)
    text = re.sub(r"[\r\n]+", " ", text)
    return text[:500]


def sanitize_ref(text) -> str:
    """For applicant-controlled strings (external_ref) that land in LLM
    context: same neutralisation as analyst text, tighter length cap."""
    return sanitize_input(str(text) if text is not None else "")[:64]


def deterministic_fallback(action: str, reason_codes: list[str], reason_titles: dict[str, str]) -> str:
    """Used whenever the LLM output fails validation, or the LLM is unavailable."""
    if not reason_codes:
        return (
            f"This application was routed to {action} by the scoring engine. "
            "No specific reason codes were attached to this decision."
        )
    titles = "; ".join(reason_titles.get(c, c) for c in reason_codes)
    codes_str = " ".join(f"[{c}]" for c in reason_codes)
    return (
        f"This application was routed to {action} by the scoring engine, "
        f"based on the following signals: {titles}. {codes_str}"
    )


_LEADING_REFUSAL = re.compile(
    r"^\s*I don't have data on that in this case(?: file)?\.\s*(?:However,\s*)?", re.IGNORECASE)


def strip_leading_refusal(text: str) -> str:
    """Small local models sometimes open a substantive, grounded answer with
    the refusal sentence and then answer anyway ("I don't have data on that
    in this case file. However, ..."). Drop the contradictory opener; a bare
    refusal is left untouched."""
    rest = _LEADING_REFUSAL.sub("", text, count=1)
    if rest == text or not rest.strip():
        return text
    return rest[0].upper() + rest[1:]


_POLICY_CAUSALITY = re.compile(
    r"\b(?:routed|scored|declined|approved|flagged|decided|sent)\b[^.]{0,60}?"
    r"\b(?:based on|due to|because of|as per|in line with|under|owing to)\b[^.]{0,80}?"
    r"\b(?:RBI|DPDP|Aadhaar|CIBIL|KYC|polic(?:y|ies)|regulation|direction|act)\b",
    re.IGNORECASE,
)


def policy_causality_violation(text: str) -> bool:
    """POLICY_LOOKUP answers must not claim a regulation caused the decision:
    the scoring engine decided, the policy passages are only obligations
    relevant to that decision."""
    return bool(_POLICY_CAUSALITY.search(text))


def refusal_text() -> str:
    return "I don't have data on that in this case file."

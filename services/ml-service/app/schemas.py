"""
Pydantic contracts. ApplicationIn mirrors the raw application fields (the
same shape the generator produces and the `application` table stores) --
this is the cross-language contract decision-api's Java DTOs are written
against (see docs/architecture.md and test_scoring_contract.py).
"""
from typing import Optional

from pydantic import BaseModel, Field


class ApplicationIn(BaseModel):
    application_id: Optional[str] = None
    external_ref: str
    age: int
    gender: str
    employment_type: str
    monthly_income_inr: float
    city_tier: int
    pincode_prefix: str
    residence_type: str

    product: str
    amount_inr: float
    tenure_months: int
    channel: str

    cibil_score: Optional[int] = None
    is_new_to_credit: bool
    active_loans: int
    enquiries_30d: int
    max_dpd_12m: int
    credit_utilisation_pct: Optional[float] = None
    oldest_account_months: Optional[int] = None

    pan_format_valid: bool
    pan_name_match_score: float
    aadhaar_pan_linked: bool
    name_dob_mismatch: bool
    digilocker_docs_fetched: int
    aadhaar_last4: Optional[str] = None

    device_hash: str
    device_reuse_count_30d: int
    is_emulator: bool
    is_rooted: bool
    app_install_age_days: int
    ip_prefix: str
    ip_distinct_apps_24h: int
    ip_pincode_distance_km: Optional[float] = None
    vpn_or_proxy: bool

    form_fill_seconds: float
    typing_speed_cpm: Optional[float] = None
    paste_events: int
    field_corrections: int
    session_screens: int
    night_application: bool
    time_since_prev_app_hours: Optional[float] = None

    bank_account_hash: str
    penny_drop_name_match: Optional[float] = None
    account_age_months: Optional[int] = None
    avg_monthly_credit_inr: Optional[float] = None
    salary_credit_regularity: Optional[float] = None
    bounce_count_6m: int
    account_shared_with_n_applicants: int

    mobile_hash: str
    mobile_age_on_network_days: Optional[int] = None
    recent_sim_swap_30d: bool
    mobile_name_match: Optional[float] = None


class ShapContribution(BaseModel):
    feature: str
    value: float | str | None  # categorical levels are strings; NaN/unseen is null
    contribution: float
    direction: str  # "increases_risk" | "decreases_risk"


class ScoreOut(BaseModel):
    risk_score: float = Field(ge=0, le=1)
    anomaly_score: float = Field(ge=0, le=1)
    action: str
    reason_codes: list[str]
    shap_top: list[ShapContribution]
    model_version: str
    latency_ms: int


class CopilotRequest(BaseModel):
    application_id: str
    question: str


class CopilotResponse(BaseModel):
    answer: str
    intent: str
    grounded: bool
    cited_ids: list[str]
    guardrail_violations: list[str]
    provider: str
    model: str
    latency_ms: int

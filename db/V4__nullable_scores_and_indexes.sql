-- Rules-only decisions (ML unavailable / not consulted) store a NULL risk score.
ALTER TABLE decision ALTER COLUMN risk_score DROP NOT NULL;
ALTER TABLE analyst_feedback ALTER COLUMN original_score DROP NOT NULL;

-- Lookups by application_id (the fraud_ring_member PK is (ring_id, application_id),
-- so it cannot serve application_id-first lookups).
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_application_id ON analyst_feedback (application_id);
CREATE INDEX IF NOT EXISTS idx_fraud_ring_member_application_id ON fraud_ring_member (application_id);

-- At most one active model at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_registry_single_active ON model_registry ((active)) WHERE active;

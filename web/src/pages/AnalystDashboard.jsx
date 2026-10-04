import { useState } from 'react'
import { useSelector } from 'react-redux'
import {
  useListApplicationsQuery, useGetKpisQuery, useGetApplicationDetailQuery, useGetRingQuery,
  useLazyGetNarrativeQuery, useSubmitFeedbackMutation, useListModelsQuery,
  useGetCostCurveQuery, useRetrainModelMutation,
} from '../app/api'
import ActionBadge from '../components/ActionBadge'
import ReasonChips from '../components/ReasonChips'
import ShapWaterfall from '../components/ShapWaterfall'
import KpiTile from '../components/KpiTile'
import CopilotChat from '../components/CopilotChat'
import { Button, Empty, Field, Panel } from '../components/ui'

const inr = (value) =>
  value == null ? '—' : new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0,
  }).format(Number(value))

const score3 = (v) => (v == null ? '—' : Number(v).toFixed(3))

const errorText = (err, fallback) =>
  (typeof err?.data?.detail === 'string' && err.data.detail) || fallback

// Rendered with key={selectedId}, so note, narrative and copilot state are per-case.
// currentData (unlike data) is undefined while a different id is loading, so the
// previous case is never shown under the new id's buttons.
function CaseDetail({ id, onFeedbackDone }) {
  const { currentData: data, isError, error } = useGetApplicationDetailQuery(id, { skip: !id })
  const { currentData: ringData } = useGetRingQuery(id, { skip: !id })
  const [getNarrative, narrativeState] = useLazyGetNarrativeQuery()
  const [submitFeedback, { isLoading: fbLoading }] = useSubmitFeedbackMutation()
  const [note, setNote] = useState('')
  const [feedbackMsg, setFeedbackMsg] = useState(null)

  if (!id) return <Panel><Empty>Select a case from the queue to see details.</Empty></Panel>
  if (isError && !data) {
    return (
      <Panel>
        <p className="py-8 text-center text-[13px] text-[#9c3211]">
          {errorText(error, 'Could not load this case. Select it again to retry.')}
        </p>
      </Panel>
    )
  }
  if (!data) return <Panel><Empty>Loading case…</Empty></Panel>

  const app = data.application
  const decision = data.decision
  let shapTop = null
  try {
    shapTop = decision?.shapTop ? JSON.parse(decision.shapTop) : null
  } catch {
    shapTop = null
  }
  if (!Array.isArray(shapTop)) shapTop = null

  async function handleFeedback(verdict) {
    setFeedbackMsg(null)
    try {
      await submitFeedback({ id, verdict, note }).unwrap()
      setNote('')
      setFeedbackMsg({ ok: true, text: verdict === 'FRAUD' ? 'Marked as fraud. Thank you.' : 'Marked as legitimate. Thank you.' })
      onFeedbackDone?.()
    } catch (err) {
      setFeedbackMsg({ ok: false, text: errorText(err, 'Could not save your verdict. Please try again.') })
    }
  }

  // riskScore is null for rules-only (degraded) decisions: never treat that as 0.
  const noveltyGap = decision?.anomalyScore != null && decision?.riskScore != null
    && Number(decision.anomalyScore) > 0.85 && Number(decision.riskScore) < 0.15

  return (
    <div className="space-y-4">
      <Panel
        title={app.externalRef}
        action={<ActionBadge action={decision?.action} />}
      >
        {noveltyGap && (
          <div className="mb-4 border-l-2 bg-surface px-4 py-3" style={{ borderColor: 'var(--color-riskup)' }}>
            <p className="text-[13px] font-medium" style={{ color: 'var(--color-riskup)' }}>
              Novel pattern detected
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
              The supervised model scores this application as low-risk ({score3(decision.riskScore)}) —
              it has never seen this behavioural signature in training. But the unsupervised novelty
              channel flags it as highly anomalous ({score3(decision.anomalyScore)}). This is
              exactly the gap a purely supervised system would miss: a fraud typology the model was
              never trained on. Confirm with the copilot / feedback loop below and retrain.
            </p>
          </div>
        )}

        {ringData?.ring && (
          <div className="mb-4 border-l-2 bg-surface px-4 py-3" style={{ borderColor: 'var(--color-riskup)' }}>
            <p className="text-[13px] font-medium" style={{ color: 'var(--color-riskup)' }}>
              Fraud ring detected
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
              {ringData.ring.member_count} applications · detected via{' '}
              {ringData.ring.detection_method === 'behavioural_embedding_only'
                ? 'behavioural embedding similarity (no shared identifier)'
                : 'shared identifier + behavioural similarity'} ·{' '}
              {inr(ringData.ring.total_exposure_inr || 0)} distance-weighted exposure
            </p>
          </div>
        )}

        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiTile
            label="Risk score"
            value={score3(decision?.riskScore)}
            sub={decision && decision.riskScore == null ? 'rules-only (ML unavailable)' : undefined}
          />
          <KpiTile label="Anomaly score" value={decision?.anomalyScore != null ? Number(decision.anomalyScore).toFixed(3) : '—'} />
          <KpiTile label="Latency" value={decision?.latencyMs != null ? `${decision.latencyMs}ms` : '—'} />
          <KpiTile label="Model" value={decision?.modelVersion ?? '—'} />
        </div>

        <div className="grid gap-x-10 gap-y-5 lg:grid-cols-2">
          <div>
            <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-faint">Applicant</h3>
            <dl>
              <Field label="Age">{app.age}</Field>
              <Field label="Employment">{app.employmentType}</Field>
              <Field label="Monthly income">{inr(app.monthlyIncomeInr)}</Field>
              <Field label="Residence">{app.residenceType}</Field>
              <Field label="City tier / pincode">Tier {app.cityTier} · {app.pincodePrefix}xx</Field>
            </dl>

            <h3 className="mb-1 mt-4 text-[11px] font-medium uppercase tracking-wide text-ink-faint">Loan</h3>
            <dl>
              <Field label="Product">{app.product}</Field>
              <Field label="Amount">{inr(app.amountInr)}</Field>
              <Field label="Tenure">{app.tenureMonths} months</Field>
              <Field label="Channel">{app.channel}</Field>
            </dl>
          </div>

          <div>
            <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-faint">Device &amp; behaviour</h3>
            <dl>
              <Field label="Device reuse (30d)">{app.deviceReuseCount30d}×</Field>
              <Field label="Device type">{app.isEmulator ? 'Emulator' : 'Real device'}{app.isRooted ? ' · rooted' : ''}</Field>
              <Field label="Form fill time">{app.formFillSeconds}s</Field>
              <Field label="Paste events">{app.pasteEvents}</Field>
              <Field label="IP apps (24h)">{app.ipDistinctApps24h}{app.vpnOrProxy ? ' · VPN/proxy' : ''}</Field>
            </dl>

            <h3 className="mb-1 mt-4 text-[11px] font-medium uppercase tracking-wide text-ink-faint">Banking &amp; mobile</h3>
            <dl>
              <Field label="Penny-drop match">{app.pennyDropNameMatch}</Field>
              <Field label="Account shared with">{app.accountSharedWithNApplicants} applicants</Field>
              <Field label="Recent SIM swap (30d)">{String(app.recentSimSwap30d)}</Field>
            </dl>
          </div>
        </div>
      </Panel>

      <Panel title="Reason codes">
        <ReasonChips codes={decision?.reasonCodes} />
      </Panel>

      {shapTop && (
        <Panel title="SHAP — top contributing signals">
          <ShapWaterfall shapTop={shapTop} />
        </Panel>
      )}

      <Panel
        title="Analyst narrative"
        action={!narrativeState.data && (
          <Button onClick={() => getNarrative(id)} disabled={narrativeState.isFetching}>
            {narrativeState.isFetching ? 'Generating…' : 'Generate narrative'}
          </Button>
        )}
      >
        {narrativeState.data ? (
          <div>
            <p className="font-serif text-[14px] leading-relaxed text-ink">{narrativeState.data.narrative}</p>
            <span
              className="mt-2 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]"
              style={{
                color: narrativeState.data.grounded ? 'var(--color-riskdown)' : 'var(--color-a-stepup)',
                borderColor: narrativeState.data.grounded ? 'var(--color-riskdown)' : 'var(--color-a-stepup)',
              }}
            >
              {narrativeState.data.grounded ? 'grounded ✓' : 'fallback template'} ·{' '}
              {narrativeState.data.provider}/{narrativeState.data.model} ·{' '}
              {narrativeState.data.cached ? 'cached' : `${narrativeState.data.latency_ms}ms`}
            </span>
          </div>
        ) : narrativeState.isError ? (
          <p className="py-8 text-center text-[13px] text-[#9c3211]">
            {errorText(narrativeState.error, 'Could not generate a narrative right now. Try again.')}
          </p>
        ) : (
          <Empty>No narrative generated yet.</Empty>
        )}
      </Panel>

      <Panel title="Copilot">
        <CopilotChat applicationId={id} />
      </Panel>

      <Panel title="Verdict">
        <label className="mb-3 block max-w-sm">
          <span className="text-[12px] text-ink-muted">Note (optional)</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What did you see that the engine did not?"
            className="mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
          />
        </label>
        {feedbackMsg && (
          <p
            role="status"
            className="mb-3 text-[13px]"
            style={{ color: feedbackMsg.ok ? 'var(--color-riskdown)' : '#9c3211' }}
          >
            {feedbackMsg.text}
          </p>
        )}
        <div className="flex gap-2">
          <Button variant="danger" disabled={fbLoading} onClick={() => handleFeedback('FRAUD')}>Confirm fraud</Button>
          <Button variant="success" disabled={fbLoading} onClick={() => handleFeedback('LEGIT')}>Mark legitimate</Button>
        </div>
      </Panel>
    </div>
  )
}

export default function AnalystDashboard() {
  const role = useSelector((s) => s.auth.role)
  const [actionFilter, setActionFilter] = useState('ALL')
  const [selectedId, setSelectedId] = useState(null)
  const { data: kpis } = useGetKpisQuery(undefined, { pollingInterval: 4000 })
  const { data: queue, refetch } = useListApplicationsQuery({ action: actionFilter, limit: 100 }, { pollingInterval: 4000 })
  const { data: models } = useListModelsQuery()
  const { data: costCurve } = useGetCostCurveQuery()
  const [retrainModel, { isLoading: retraining }] = useRetrainModelMutation()
  const [retrainResult, setRetrainResult] = useState(null)

  async function handleRetrain() {
    setRetrainResult(null)
    try {
      const res = await retrainModel().unwrap()
      setRetrainResult(res)
    } catch (err) {
      setRetrainResult({ error: true, message: err?.data?.detail || 'Retrain failed.' })
    }
  }

  const byAction = Object.fromEntries((kpis?.byAction || []).map((r) => [r.action, r.n]))

  return (
    <div className="space-y-4 p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <KpiTile label="Decisions (24h)" value={kpis?.decisionsLast24h ?? '—'} />
        <KpiTile label="p95 latency" value={kpis ? `${Number(kpis.p95LatencyMs).toFixed(0)}ms` : '—'} />
        <KpiTile label="Approve" value={byAction.APPROVE ?? 0} />
        <KpiTile label="KYC" value={byAction.STEP_UP ?? 0} />
        <KpiTile label="Review" value={byAction.REVIEW ?? 0} />
        <KpiTile label="Decline" value={byAction.DECLINE ?? 0} />
      </div>

      {costCurve && costCurve.four_way_decline_rate != null && (
        <Panel title="False-positive reduction — four actions, not two">
          <p className="mb-3 text-[12px] leading-relaxed text-ink-muted">
            We didn't move the threshold. We added two more actions (KYC, review) between
            approve and decline, so borderline applicants face friction instead of rejection.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile label="Binary decline rate (t=0.5)" value={`${(costCurve.naive_binary_decline_rate * 100).toFixed(2)}%`} />
            <KpiTile
              label="Four-way decline rate"
              value={<span style={{ color: 'var(--color-riskdown)' }}>{(costCurve.four_way_decline_rate * 100).toFixed(2)}%</span>}
            />
            <KpiTile label="Binary FP rate" value={`${(costCurve.naive_binary_fp_rate * 100).toFixed(3)}%`} />
            <KpiTile
              label="Four-way FP rate"
              value={<span style={{ color: 'var(--color-riskdown)' }}>{(costCurve.four_way_fp_rate * 100).toFixed(3)}%</span>}
            />
          </div>
          {costCurve.cost_assumptions_inr && (
            <p className="mt-3 border-t border-rule-soft pt-2 text-[11px] leading-relaxed text-ink-faint">
              Cost assumptions: {inr(costCurve.cost_assumptions_inr.C_FN)} per missed fraud ·{' '}
              {inr(costCurve.cost_assumptions_inr.C_FP)} per wrongly-declined good customer ·{' '}
              {inr(costCurve.cost_assumptions_inr.C_STEPUP)} KYC friction ·{' '}
              {inr(costCurve.cost_assumptions_inr.C_REVIEW)} analyst review.
              Thresholds: low={Number(costCurve.thresholds?.low).toFixed(2)},
              high={Number(costCurve.thresholds?.high).toFixed(2)},
              decline={Number(costCurve.thresholds?.decline).toFixed(2)} ({costCurve.model_version}).
            </p>
          )}
          {costCurve.fairness && (
            <div className="mt-4 border-t border-rule-soft pt-3">
              <h3 className="mb-2 text-[12px] text-ink-muted">Fairness — disparate-impact ratio (80% rule)</h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {Object.entries(costCurve.fairness).flatMap(([group, rows]) =>
                  Object.entries(rows).map(([label, v]) => (
                    <KpiTile
                      key={`${group}-${label}`}
                      label={`${group}: ${label}`}
                      value={`${(v.disparate_impact_ratio * 100).toFixed(1)}%`}
                      sub={`n=${v.n} · approval ${(v.approval_rate * 100).toFixed(1)}%`}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <div className="space-y-4">
          <Panel
            title="Queue"
            action={
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className="border border-rule bg-surface px-2 py-1 text-[12px]"
              >
                <option value="ALL">All actions</option>
                <option value="DECLINE">Decline</option>
                <option value="REVIEW">Review</option>
                <option value="STEP_UP">KYC</option>
                <option value="APPROVE">Approve</option>
              </select>
            }
          >
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-rule-soft text-left text-ink-muted">
                  <th className="pb-1.5 font-medium">Ref</th>
                  <th className="pb-1.5 font-medium">Product</th>
                  <th className="pb-1.5 font-medium">Amount</th>
                  <th className="pb-1.5 font-medium">Action</th>
                  <th className="pb-1.5 font-medium">Score</th>
                  <th className="pb-1.5 text-right font-medium">Latency</th>
                </tr>
              </thead>
              <tbody>
                {(queue || []).map((a) => (
                  <tr
                    key={a.id}
                    onClick={() => setSelectedId(a.id)}
                    aria-current={selectedId === a.id}
                    className={`cursor-pointer border-b border-rule-soft/60 hover:bg-paper ${selectedId === a.id ? 'bg-paper' : ''}`}
                  >
                    <td className="hash py-1.5">{a.externalRef}</td>
                    <td className="py-1.5">{a.product}</td>
                    <td className="tnum py-1.5">{inr(a.amountInr)}</td>
                    <td className="py-1.5"><ActionBadge action={a.action} /></td>
                    <td className="tnum py-1.5" title={a.riskScore == null ? 'rules-only decision (ML unavailable)' : undefined}>
                      {a.riskScore != null ? Number(a.riskScore).toFixed(2) : '—'}
                    </td>
                    <td className="tnum py-1.5 text-right text-ink-faint">{a.latencyMs ?? '—'}ms</td>
                  </tr>
                ))}
                {(!queue || queue.length === 0) && (
                  <tr><td colSpan={6} className="py-4 text-center text-ink-faint">No applications yet — submit one from the Application tab.</td></tr>
                )}
              </tbody>
            </table>
          </Panel>

          <Panel
            title="Model registry"
            action={role === 'ADMIN' ? (
              <Button onClick={handleRetrain} disabled={retraining}>
                {retraining ? 'Retraining…' : 'Retrain from feedback'}
              </Button>
            ) : (
              <span className="text-[11px] text-ink-faint">Retrain requires ADMIN role</span>
            )}
          >
            {retrainResult && !retrainResult.error && (
              <p className="mb-3 text-[12px] leading-relaxed text-ink-muted">
                <strong style={{ color: retrainResult.promoted ? 'var(--color-riskdown)' : 'var(--color-a-stepup)' }}>
                  {retrainResult.version}
                </strong>
                {' '}— {retrainResult.promoted_reason} (trained on {retrainResult.training_rows} rows,{' '}
                {retrainResult.feedback_rows_used} from analyst feedback, in {retrainResult.train_seconds}s)
              </p>
            )}
            {retrainResult?.error && (
              <p className="mb-3 text-[13px] text-[#9c3211]">{retrainResult.message}</p>
            )}
            {models && models.length > 0 ? (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-rule-soft text-left text-ink-muted">
                    <th className="pb-1.5 font-medium">Version</th>
                    <th className="pb-1.5 font-medium">Algorithm</th>
                    <th className="pb-1.5 font-medium">PR-AUC</th>
                    <th className="pb-1.5 font-medium">Recall@1%FPR</th>
                    <th className="pb-1.5 text-right font-medium">Active</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.id} className="border-b border-rule-soft/60">
                      <td className="hash py-1.5">{m.version}</td>
                      <td className="py-1.5">{m.algorithm}</td>
                      <td className="tnum py-1.5">{m.prAuc}</td>
                      <td className="tnum py-1.5">{m.recallAt1pctFpr}</td>
                      <td className="py-1.5 text-right">{m.active ? '✓' : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No registered model versions yet.</Empty>
            )}
          </Panel>
        </div>

        <CaseDetail key={selectedId} id={selectedId} onFeedbackDone={refetch} />
      </div>
    </div>
  )
}

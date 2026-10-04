import { useState } from 'react'
import { SCENARIOS } from '../data/scenarios'
import { useSubmitApplicationMutation } from '../app/api'
import ActionBadge from '../components/ActionBadge'
import ReasonChips from '../components/ReasonChips'
import ShapWaterfall from '../components/ShapWaterfall'
import { Button, Panel } from '../components/ui'

const FIELDS = [
  // block, key, label, type
  ['Applicant', 'age', 'Age', 'number'],
  ['Applicant', 'gender', 'Gender', 'select', ['M', 'F']],
  ['Applicant', 'employmentType', 'Employment type', 'select', ['SALARIED', 'SELF_EMPLOYED', 'GIG_WORKER', 'UNEMPLOYED_STUDENT']],
  ['Applicant', 'monthlyIncomeInr', 'Monthly income (₹)', 'number'],
  ['Applicant', 'cityTier', 'City tier', 'select', [1, 2, 3]],
  ['Applicant', 'pincodePrefix', 'Pincode prefix', 'text'],
  ['Applicant', 'residenceType', 'Residence type', 'select', ['OWNED', 'RENTED', 'FAMILY']],

  ['Loan', 'product', 'Product', 'select', ['CONSUMER_DURABLE', 'PERSONAL', 'TWO_WHEELER', 'EDUCATION_TOPUP']],
  ['Loan', 'amountInr', 'Amount (₹)', 'number'],
  ['Loan', 'tenureMonths', 'Tenure (months)', 'number'],
  ['Loan', 'channel', 'Channel', 'select', ['ANDROID_APP', 'IOS_APP', 'WEB', 'PARTNER_POS']],

  ['Bureau', 'cibilScore', 'CIBIL score', 'number'],
  ['Bureau', 'isNewToCredit', 'New to credit', 'boolean'],
  ['Bureau', 'activeLoans', 'Active loans', 'number'],
  ['Bureau', 'enquiries30d', 'Enquiries (30d)', 'number'],
  ['Bureau', 'maxDpd12m', 'Max DPD (12m)', 'number'],
  ['Bureau', 'creditUtilisationPct', 'Credit utilisation %', 'number'],
  ['Bureau', 'oldestAccountMonths', 'Oldest account (months)', 'number'],

  ['KYC', 'panFormatValid', 'PAN format valid', 'boolean'],
  ['KYC', 'panNameMatchScore', 'PAN name match (0-1)', 'number'],
  ['KYC', 'aadhaarPanLinked', 'Aadhaar–PAN linked', 'boolean'],
  ['KYC', 'nameDobMismatch', 'Name/DOB mismatch', 'boolean'],
  ['KYC', 'digilockerDocsFetched', 'DigiLocker docs fetched', 'number'],
  ['KYC', 'aadhaarLast4', 'Aadhaar last 4 digits', 'text'],

  ['Device', 'deviceHash', 'Device hash', 'text'],
  ['Device', 'deviceReuseCount30d', 'Device reuse count (30d)', 'number'],
  ['Device', 'isEmulator', 'Emulator', 'boolean'],
  ['Device', 'isRooted', 'Rooted', 'boolean'],
  ['Device', 'appInstallAgeDays', 'App install age (days)', 'number'],
  ['Device', 'ipPrefix', 'IP prefix', 'text'],
  ['Device', 'ipDistinctApps24h', 'IP distinct apps (24h)', 'number'],
  ['Device', 'ipPincodeDistanceKm', 'IP-pincode distance (km)', 'number'],
  ['Device', 'vpnOrProxy', 'VPN / proxy', 'boolean'],

  ['Behaviour', 'formFillSeconds', 'Form fill time (s)', 'number'],
  ['Behaviour', 'typingSpeedCpm', 'Typing speed (cpm)', 'number'],
  ['Behaviour', 'pasteEvents', 'Paste events', 'number'],
  ['Behaviour', 'fieldCorrections', 'Field corrections', 'number'],
  ['Behaviour', 'sessionScreens', 'Session screens', 'number'],
  ['Behaviour', 'nightApplication', 'Night application', 'boolean'],
  ['Behaviour', 'timeSincePrevAppHours', 'Hours since prev. application', 'number'],

  ['Banking', 'bankAccountHash', 'Bank account hash', 'text'],
  ['Banking', 'pennyDropNameMatch', 'Penny-drop name match (0-1)', 'number'],
  ['Banking', 'accountAgeMonths', 'Account age (months)', 'number'],
  ['Banking', 'avgMonthlyCreditInr', 'Avg monthly credit (₹)', 'number'],
  ['Banking', 'salaryCreditRegularity', 'Salary credit regularity (0-1)', 'number'],
  ['Banking', 'bounceCount6m', 'Bounce count (6m)', 'number'],
  ['Banking', 'accountSharedWithNApplicants', 'Account shared with N applicants', 'number'],

  ['Mobile', 'mobileHash', 'Mobile hash', 'text'],
  ['Mobile', 'mobileAgeOnNetworkDays', 'Mobile age on network (days)', 'number'],
  ['Mobile', 'recentSimSwap30d', 'Recent SIM swap (30d)', 'boolean'],
  ['Mobile', 'mobileNameMatch', 'Mobile owner name match (0-1)', 'number'],
]

const BLOCKS = [...new Set(FIELDS.map((f) => f[0]))]

function FormField({ label, type, options, value, onChange, k }) {
  if (type === 'boolean') {
    return (
      <label className="block">
        <span className="text-[12px] text-ink-muted">{label}</span>
        <select
          value={String(value)}
          onChange={(e) => onChange(k, e.target.value === 'true')}
          className="mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </label>
    )
  }
  if (type === 'select') {
    return (
      <label className="block">
        <span className="text-[12px] text-ink-muted">{label}</span>
        <select
          value={value ?? ''}
          onChange={(e) => onChange(k, e.target.value)}
          className="mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
        >
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    )
  }
  return (
    <label className="block">
      <span className="text-[12px] text-ink-muted">{label}</span>
      <input
        type={type === 'number' ? 'number' : 'text'}
        value={value ?? ''}
        onChange={(e) => onChange(k, type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value)}
        className="tnum mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
      />
    </label>
  )
}

/** Turn an RTK Query error into {message, fieldErrors}; backend 400s are problem+json with fieldErrors. */
function describeSubmitError(err) {
  const detail = typeof err?.data?.detail === 'string' ? err.data.detail : null
  if (err?.status === 409) {
    return { message: 'That application reference has already been used. Change the reference and submit again.' }
  }
  if (err?.status === 400) {
    const fe = err?.data?.fieldErrors
    const fieldErrors = fe && typeof fe === 'object' && !Array.isArray(fe) ? Object.entries(fe) : []
    return { message: detail || 'Submission failed — check the field values.', fieldErrors }
  }
  if (err?.status === 401) return { message: 'Your session has expired. Please sign in again.' }
  if (typeof err?.status === 'number' && err.status >= 500) {
    return { message: detail || 'The service is unavailable right now. Please try again in a moment.' }
  }
  if (err?.status === 'FETCH_ERROR' || err?.status === 'TIMEOUT_ERROR') {
    return { message: 'Could not reach the service. Check your connection and try again.' }
  }
  return { message: detail || 'Submission failed — check the field values.' }
}

export default function ApplyDashboard() {
  const [scenarioKey, setScenarioKey] = useState('CLEAN')
  const [form, setForm] = useState(() => SCENARIOS.CLEAN.build())
  const [submitApplication, { isLoading }] = useSubmitApplicationMutation()
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function applyScenario(key) {
    setScenarioKey(key)
    setForm(SCENARIOS[key].build())
    setResult(null)
    setError(null)
  }

  function updateField(k, v) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setResult(null)
    const t0 = performance.now()
    try {
      const res = await submitApplication(form).unwrap()
      // Don't mutate the response -- RTK Query freezes cached response objects in
      // dev mode to catch exactly this kind of bug.
      setResult({ ...res, _clientRoundTripMs: Math.round(performance.now() - t0) })
    } catch (err) {
      setError(describeSubmitError(err))
    }
  }

  let shapTop = null
  try {
    shapTop = result?.shapTop ? JSON.parse(result.shapTop) : null
  } catch {
    shapTop = null
  }
  if (!Array.isArray(shapTop)) shapTop = null

  // riskScore is null for rules-only (degraded) decisions: never treat that as 0.
  const noveltyGap = result?.anomalyScore != null && result?.riskScore != null
    && Number(result.anomalyScore) > 0.85 && Number(result.riskScore) < 0.15

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-semibold leading-tight">Loan application</h1>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            Every field is editable after picking a scenario.
          </p>
        </div>
        <label className="block w-64">
          <span className="text-[12px] text-ink-muted">Scenario (prefills, all editable)</span>
          <select
            value={scenarioKey}
            onChange={(e) => applyScenario(e.target.value)}
            className="mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
          >
            {Object.entries(SCENARIOS).map(([k, s]) => (
              <option key={k} value={k}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <Panel>
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block max-w-xs">
            <span className="text-[12px] text-ink-muted">Application reference</span>
            <input
              value={form.externalRef}
              onChange={(e) => updateField('externalRef', e.target.value)}
              className="mt-1 w-full border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
            />
          </label>

          {BLOCKS.map((block) => (
            <div key={block} className="border border-rule-soft">
              <header className="border-b border-rule-soft bg-paper px-3 py-1.5">
                <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">{block}</h3>
              </header>
              <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3">
                {FIELDS.filter((f) => f[0] === block).map(([, k, label, type, options]) => (
                  <FormField key={k} k={k} label={label} type={type} options={options}
                             value={form[k]} onChange={updateField} />
                ))}
              </div>
            </div>
          ))}

          <div className="flex justify-end">
            <Button variant="primary" disabled={isLoading}>
              {isLoading ? 'Scoring…' : 'Submit application'}
            </Button>
          </div>
        </form>
      </Panel>

      {error && (
        <div className="border border-[#e3c2b6] bg-[#fdf4f1] px-4 py-3 text-[13px] text-[#9c3211]">
          <p>{error.message}</p>
          {error.fieldErrors?.length > 0 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[12px]">
              {error.fieldErrors.map(([field, msg]) => (
                <li key={field}><span className="hash">{field}</span>: {String(msg)}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {result && (
        <>
          <Panel>
            <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
              <div>
                <p className="text-[12px] text-ink-muted">Risk score (supervised)</p>
                <p className="tnum text-[28px] font-semibold leading-none">
                  {result.riskScore != null ? Number(result.riskScore).toFixed(3) : '—'}
                </p>
                {result.riskScore == null && (
                  <p className="text-[11px] text-ink-faint">rules-only (ML unavailable)</p>
                )}
              </div>
              <div>
                <p className="text-[12px] text-ink-muted">Anomaly score (novelty)</p>
                <p
                  className="tnum text-[18px] font-medium"
                  style={{ color: result.anomalyScore != null && Number(result.anomalyScore) > 0.85 ? 'var(--color-riskup)' : undefined }}
                >
                  {result.anomalyScore != null ? Number(result.anomalyScore).toFixed(3) : '—'}
                </p>
              </div>
              <div>
                <p className="mb-1.5 text-[12px] text-ink-muted">Decision</p>
                <ActionBadge action={result.action} />
              </div>
              <div>
                <p className="text-[12px] text-ink-muted">Server latency</p>
                <p className="tnum text-[18px] font-medium">{result.latencyMs}ms</p>
                <p className="tnum text-[11px] text-ink-faint">round-trip {result._clientRoundTripMs}ms</p>
              </div>
              <div className="ml-auto text-right">
                <p className="text-[12px] text-ink-muted">Degraded</p>
                <p className="text-[13px] font-medium" style={{ color: result.degraded ? 'var(--color-riskup)' : 'var(--color-riskdown)' }}>
                  {result.degraded ? 'yes (rules-only)' : 'no'}
                </p>
              </div>
            </div>
          </Panel>

          {noveltyGap && (
            <div className="border-l-2 bg-surface px-4 py-3" style={{ borderColor: 'var(--color-riskup)' }}>
              <p className="text-[13px] font-medium" style={{ color: 'var(--color-riskup)' }}>
                Novel pattern detected
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
                The supervised model scores this application as low-risk ({Number(result.riskScore).toFixed(3)}) —
                it has never seen this behavioural signature in training. But the unsupervised novelty
                channel flags it as highly anomalous ({Number(result.anomalyScore).toFixed(3)}). This is
                exactly the gap a purely supervised system would miss: a fraud typology the model was
                never trained on. Route to review and use the copilot / feedback loop to confirm and retrain.
              </p>
            </div>
          )}

          <Panel title="Reason codes">
            <ReasonChips codes={result.reasonCodes} />
          </Panel>

          {shapTop && (
            <Panel title="Top contributing signals">
              <ShapWaterfall shapTop={shapTop} />
            </Panel>
          )}

          {result.action === 'STEP_UP' && result.verificationSteps?.length > 0 && (
            <Panel title="KYC verification required (Indian step-up ladder)">
              <ol className="list-decimal space-y-1 pl-4 text-[13px]">
                {result.verificationSteps.map((s) => <li key={s}>{s}</li>)}
              </ol>
            </Panel>
          )}

          {result.action === 'APPROVE' && result.keyFactStatement && (
            <Panel title="Key Fact Statement (RBI Digital Lending Directions, 2025)">
              <p className="font-serif text-[14px] leading-relaxed text-ink">{result.keyFactStatement}</p>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

import { useState } from 'react'
import { Empty } from './ui'

/**
 * Diverging contribution chart: what pushed this score, and which way.
 *
 * Same colour-blind-validated pair as the rest of the ledger (riskup/riskdown,
 * deltaE 18.3 under deuteranopia) rather than a plain red/green. Direction is
 * also carried by which side of the zero axis a bar sits on and by its sign,
 * so the chart never depends on colour alone.
 */
const RISK_UP = 'var(--color-riskup)'
const RISK_DOWN = 'var(--color-riskdown)'

/** Feature value: number, categorical level (string) or null. */
function formatValue(v) {
  if (v == null) return '—'
  if (typeof v === 'number') return Number.isFinite(v) ? String(Number(v.toFixed(3))) : '—'
  return String(v)
}

export default function ShapWaterfall({ shapTop }) {
  const [hovered, setHovered] = useState(null)

  // Payload comes from the server as JSON: tolerate non-arrays and bad rows.
  const rows = Array.isArray(shapTop)
    ? shapTop.filter((s) => s && Number.isFinite(Number(s.contribution))
        && s.contribution !== null && s.contribution !== '')
    : []

  if (rows.length === 0) {
    return <Empty>No SHAP explanation available for this decision.</Empty>
  }

  const max = Math.max(...rows.map((s) => Math.abs(Number(s.contribution))), 1e-6)

  return (
    <div>
      <div className="mb-3 flex items-center gap-4 text-[11px] text-ink-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-[1px]" style={{ background: RISK_DOWN }} />
          lowers risk
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-3 rounded-[1px]" style={{ background: RISK_UP }} />
          raises risk
        </span>
      </div>

      <ul className="space-y-1.5">
        {rows.map((s, i) => {
          const contribution = Number(s.contribution)
          const up = s.direction === 'increases_risk'
          const width = (Math.abs(contribution) / max) * 50
          const active = hovered === s.feature
          return (
            <li
              key={i}
              onMouseEnter={() => setHovered(s.feature)}
              onMouseLeave={() => setHovered(null)}
              className="grid grid-cols-[1fr_auto] items-center gap-3"
            >
              <div>
                <div className="mb-1 flex items-baseline justify-between gap-2">
                  <span className="hash text-ink" title={s.feature}>{s.feature}</span>
                  <span className="tnum text-[11px] text-ink-faint">{formatValue(s.value)}</span>
                </div>
                <div className="relative h-3 bg-rule-soft/60">
                  <div className="absolute inset-y-0 left-1/2 w-px bg-rule" />
                  <div
                    className="absolute inset-y-0 transition-[opacity]"
                    style={{
                      background: up ? RISK_UP : RISK_DOWN,
                      opacity: hovered && !active ? 0.45 : 1,
                      width: `${width}%`,
                      left: up ? '50%' : `${50 - width}%`,
                      borderRadius: up ? '0 3px 3px 0' : '3px 0 0 3px',
                    }}
                  />
                </div>
              </div>
              <span className="tnum w-16 text-right text-[11px] text-ink-muted">
                {contribution > 0 ? '+' : ''}{contribution.toFixed(3)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

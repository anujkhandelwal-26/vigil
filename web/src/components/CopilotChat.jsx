import { useRef, useState } from 'react'
import { useCopilotQueryMutation } from '../app/api'
import { Button } from './ui'

const SUGGESTED = [
  'Why was this flagged?',
  "What changed from this customer's normal behavior?",
  'Summarize this case.',
  'Which signals contributed most to the score?',
  'Show me all cases involving this device.',
  'Have we seen a case like this before?',
]

function GroundedTag({ grounded, provider, model, latencyMs }) {
  return (
    <span
      className="mt-1.5 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]"
      style={{
        color: grounded ? 'var(--color-riskdown)' : 'var(--color-a-stepup)',
        borderColor: grounded ? 'var(--color-riskdown)' : 'var(--color-a-stepup)',
      }}
    >
      {grounded ? 'grounded ✓' : 'fallback template'}
      {provider && model ? ` · ${provider}/${model}` : ''}
      {latencyMs != null ? ` · ${latencyMs}ms` : ''}
    </span>
  )
}

export default function CopilotChat({ applicationId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [copilotQuery, { isLoading }] = useCopilotQueryMutation()
  // Ref (not just isLoading) so a double-click/Enter in the same tick can't start two requests.
  const inFlight = useRef(false)

  async function ask(question) {
    if (!question.trim() || inFlight.current) return
    inFlight.current = true
    setMessages((m) => [...m, { role: 'user', text: question }])
    setInput('')
    try {
      const res = await copilotQuery({ applicationId, question }).unwrap()
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: res.answer,
          grounded: res.grounded,
          provider: res.provider,
          model: res.model,
          latencyMs: res.latency_ms,
        },
      ])
    } catch (err) {
      const detail = typeof err?.data?.detail === 'string' ? err.data.detail : null
      setMessages((m) => [...m, {
        role: 'assistant',
        text: detail || 'The copilot could not answer that right now.',
        error: true,
      }])
    } finally {
      inFlight.current = false
    }
  }

  return (
    <div>
      <div className="mb-3 max-h-80 space-y-2.5 overflow-y-auto">
        {messages.length === 0 && (
          <p className="text-[12px] text-ink-faint">
            Ask about this case — answers are grounded strictly in retrieved case data.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`border px-3 py-2 text-[13px] ${
              m.error
                ? 'max-w-[92%] border-[#e3c2b6] bg-[#fdf4f1] text-[#9c3211]'
                : m.role === 'user'
                ? 'ml-auto max-w-[80%] border-signal/30 bg-[#eef1f8] text-ink'
                : 'max-w-[92%] border-rule-soft bg-paper text-ink'
            }`}
          >
            {m.text}
            {m.role === 'assistant' && !m.error && (
              <div className="mt-1.5">
                <GroundedTag grounded={m.grounded} provider={m.provider} model={m.model} latencyMs={m.latencyMs} />
              </div>
            )}
          </div>
        ))}
        {isLoading && <p className="text-[12px] text-ink-faint">Thinking…</p>}
      </div>

      <div className="mb-2 flex flex-wrap gap-1.5">
        {SUGGESTED.map((q) => (
          <button
            key={q}
            onClick={() => ask(q)}
            disabled={isLoading}
            className="rounded-sm border border-rule bg-paper px-2 py-1 text-[11px] text-ink-muted hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask(input)}
          placeholder="Ask a question about this case…"
          className="min-w-0 flex-1 border border-rule bg-surface px-2.5 py-1.5 text-[13px]"
        />
        <Button onClick={() => ask(input)} disabled={isLoading}>Ask</Button>
      </div>
    </div>
  )
}

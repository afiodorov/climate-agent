import { useState } from 'react'
import type { AskStatus, Step } from '../types'

interface Props {
  steps: Step[]
  status: AskStatus
}

/** Every row here is a StepEvent an agent published on the progress channel. */
export function ProgressLog({ steps, status }: Props) {
  // Once a turn is done its step list collapses to the total, so a long
  // transcript is readable — but the rows stay one click away.
  const [expanded, setExpanded] = useState(false)

  if (steps.length === 0) return null

  // `answer` brackets the SQL steps, so summing every row would double-count.
  // The wall clock is the outermost bracket plus the sidecar that follows it.
  const wall = steps
    .filter((s) => s.status === 'done' && s.step !== 'sql')
    .reduce((sum, s) => sum + (s.ms ?? 0), 0)

  const done = status === 'done'
  const showRows = !done || expanded

  return (
    <div className="progress card">
      {showRows && (
        <ol>
          {steps.map((s, i) => (
            <li key={i} className={`${s.status} step-${s.step}`}>
              <span className="indicator" aria-hidden="true">
                {s.status === 'done' ? '✓' : <span className="spinner" />}
              </span>
              <span className="label">
                {s.label}
                {s.detail && <code title={s.detail}>{s.detail}</code>}
              </span>
              <span className="timing">
                {s.status === 'done' ? `${Math.round(s.ms ?? 0)}ms` : '…'}
              </span>
            </li>
          ))}
        </ol>
      )}
      {done && (
        <button
          type="button"
          className="progress-total"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
        >
          Done in {(wall / 1000).toFixed(1)}s
          <span className="chevron" aria-hidden="true">
            {expanded ? '▴' : '▾'}
          </span>
        </button>
      )}
    </div>
  )
}

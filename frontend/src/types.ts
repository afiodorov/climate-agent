/** Mirrors climate_agent.schemas.Step — one timed stage published on the bus. */
export interface Step {
  step: string
  label: string
  status: 'start' | 'done'
  ms: number | null
  detail: string | null
}

/** Mirrors climate_agent.schemas.Final. */
export interface Final {
  answer: string
  caveats: string[]
}

export type AskStatus = 'idle' | 'running' | 'done' | 'error'

/** A row in the conversation rail. Mirrors GET /api/sessions. */
export interface ConversationSummary {
  id: string
  title: string
  turns: number
  updated_at: number
  /** How many questions are still being answered right now. */
  pending: number
}

/** GET /api/sessions/{id}. `pending` questions have no answer yet — they render
 *  as running turns so a conversation you return to has no hole in it. */
export interface ConversationDetail {
  exchanges: Exchange[]
  pending: string[]
}

/** A stored exchange, as GET /api/sessions/{id} returns it. No step timings —
 *  those are live-only and were never recorded. */
export interface Exchange {
  question: string
  answer: string
  caveats: string[]
}

/** One question and everything that came back for it. The transcript is a list
 *  of these; each one owns its own progress log, so turns never share state. */
export interface Turn {
  id: string
  question: string
  steps: Step[]
  final: Final | null
  error: string | null
  status: AskStatus
}

import type {
  ConversationDetail,
  ConversationSummary,
  Final,
  Step,
} from './types'

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const r = await fetch('/api/sessions')
  if (!r.ok) throw new Error(`sessions: ${r.status}`)
  return r.json()
}

export async function fetchConversation(
  id: string,
): Promise<ConversationDetail> {
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
  if (!r.ok) throw new Error(`session ${id}: ${r.status}`)
  return r.json()
}

/** Forget a conversation server-side. The endpoint is idempotent, so deleting a
 *  row that has already expired succeeds rather than 404ing. */
export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!r.ok) throw new Error(`delete ${id}: ${r.status}`)
}

export interface AskHandlers {
  onStep: (step: Step) => void
  onFinal: (final: Final) => void
  onError: (message: string) => void
  onDone: () => void
}

// EventSource auto-reconnects on an unclosed stream — which would re-ask the
// question and re-bill it — so every terminal event closes the connection.
export function streamAsk(
  question: string,
  sessionId: string,
  h: AskHandlers,
): () => void {
  // The history lives on the server keyed by `session`, so a follow-up sends the
  // same id rather than re-uploading the conversation.
  const es = new EventSource(
    `/api/ask?q=${encodeURIComponent(question)}&session=${encodeURIComponent(sessionId)}`,
  )

  es.addEventListener('step', (e) =>
    h.onStep(JSON.parse((e as MessageEvent).data)),
  )
  es.addEventListener('final', (e) =>
    h.onFinal(JSON.parse((e as MessageEvent).data)),
  )
  es.addEventListener('done', () => {
    es.close()
    h.onDone()
  })
  // Fires both for server-sent "error" events (with data) and transport
  // failures (without).
  es.addEventListener('error', (e) => {
    es.close()
    const data = (e as MessageEvent).data
    h.onError(data ? JSON.parse(data).message : 'Connection lost')
  })

  return () => es.close()
}

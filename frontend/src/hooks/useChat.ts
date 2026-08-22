import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteConversation,
  fetchConversation,
  fetchConversations,
  streamAsk,
} from '../api'
import type { ConversationSummary, Step, Turn } from '../types'

/** A `done` collapses into the matching pending `start`. Several SQL steps share
 *  one `step` key, so this pairs the first still-open one — correct because the
 *  tool runner executes queries one at a time. */
function mergeStep(steps: Step[], ev: Step): Step[] {
  if (ev.status === 'done') {
    const i = steps.findIndex((s) => s.step === ev.step && s.status === 'start')
    if (i >= 0) {
      const next = [...steps]
      next[i] = ev
      return next
    }
  }
  return [...steps, ev]
}

/** How often to re-check a conversation whose answer is landing elsewhere. */
const POLL_MS = 2000

export function useChat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  // State so the rail can highlight the active row; a ref alongside it so the
  // callbacks below read the current id without going stale.
  // Annotated as string: crypto.randomUUID() is typed as a narrow template
  // literal, which a plain session id from the server would not satisfy.
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID())
  const sessionRef = useRef<string>(sessionId)
  const cancelRef = useRef<(() => void) | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const useSession = useCallback((id: string) => {
    sessionRef.current = id
    setSessionId(id)
  }, [])

  /** Must run before anything that owns `turns` — a poll landing on top of a
   *  turn the user just started here would overwrite its live steps. */
  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  /** The rail is decoration: if it fails to load, the chat still works. */
  const refresh = useCallback(() => {
    fetchConversations().then(setConversations, () => {})
  }, [])

  useEffect(refresh, [refresh])

  const running = turns.length > 0 && turns[turns.length - 1].status === 'running'
  // A turn running *here* counts too: a brand-new conversation is not in the
  // rail yet, so waiting for a pending row to appear before polling would wait
  // forever. Keyed on the boolean rather than `conversations` so a refresh does
  // not tear down and rebuild the timer.
  const busy = running || conversations.some((c) => c.pending > 0)

  // Keep the rail current while anything is mid-answer — here or elsewhere — so
  // a new conversation shows up and its spinner clears itself. Self-terminating:
  // with nothing in flight this sets no timer at all.
  useEffect(() => {
    if (!busy) return
    const timer = setInterval(refresh, POLL_MS)
    return () => clearInterval(timer)
  }, [busy, refresh])

  const send = useCallback(
    (question: string) => {
      cancelRef.current?.()
      // This tab owns the transcript from here; a poll would clobber it.
      stopPolling()
      const id = crypto.randomUUID()
      setTurns((prev) => [
        ...prev,
        { id, question, steps: [], final: null, error: null, status: 'running' },
      ])

      // Every handler edits one turn by id, so a slow answer landing after the
      // next question was asked still updates its own turn.
      const patch = (fn: (t: Turn) => Turn) =>
        setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)))

      cancelRef.current = streamAsk(question, sessionRef.current, {
        onStep: (ev) => patch((t) => ({ ...t, steps: mergeStep(t.steps, ev) })),
        onFinal: (final) => patch((t) => ({ ...t, final })),
        onError: (message) =>
          patch((t) => ({ ...t, error: message, status: 'error' })),
        onDone: () => {
          patch((t) => (t.status === 'error' ? t : { ...t, status: 'done' }))
          // The server records the exchange as it answers, so the rail only has
          // this conversation once the turn lands.
          refresh()
        },
      })
      // Often wins the race against the server registering this question, so the
      // rail shows the new conversation immediately rather than a poll later.
      refresh()
    },
    [refresh, stopPolling],
  )

  /** Drop the transcript and mint a new session, so the next question starts
   *  with no history. The previous conversation stays on the server and stays
   *  in the rail — that is what makes it resumable. */
  const reset = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
    stopPolling()
    useSession(crypto.randomUUID())
    setTurns([])
  }, [useSession, stopPolling])

  /** Delete a conversation and drop it from the rail.
   *
   *  The row goes immediately rather than waiting for the round trip — this is
   *  a clearing-out job and a list that lags every click is miserable to use.
   *  `refresh` at the end is the correction if the server disagrees. Deleting
   *  the conversation on screen leaves nothing to show, so that case falls back
   *  to a fresh session. */
  const removeConversation = useCallback(
    async (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (id === sessionRef.current) reset()
      try {
        await deleteConversation(id)
      } finally {
        refresh()
      }
    },
    [refresh, reset],
  )

  /** Load a conversation's turns. Anything still being answered comes back as a
   *  running turn, so returning mid-answer shows the question and a spinner
   *  rather than a hole. Returns whether anything is still in flight. */
  const load = useCallback(async (id: string): Promise<boolean> => {
    const { exchanges, pending } = await fetchConversation(id)
    setTurns([
      ...exchanges.map((e) => ({
        id: crypto.randomUUID(),
        question: e.question,
        // Step timings were live-only and never recorded; ProgressLog renders
        // nothing for an empty list, which is the honest result.
        steps: [],
        final: { answer: e.answer, caveats: e.caveats },
        error: null,
        status: 'done' as const,
      })),
      ...pending.map((question) => ({
        id: crypto.randomUUID(),
        question,
        steps: [],
        final: null,
        error: null,
        status: 'running' as const,
      })),
    ])
    return pending.length > 0
  }, [])

  /** Resume a conversation: restore what was shown, and point the session id
   *  back at it so the model's own memory of it comes along too. */
  const openConversation = useCallback(
    async (id: string) => {
      // Already here and streaming: re-opening would cancel the live stream and
      // fall back to polling, dropping the progress log for no reason.
      if (id === sessionRef.current) return
      cancelRef.current?.()
      cancelRef.current = null
      stopPolling()
      let stillRunning: boolean
      try {
        stillRunning = await load(id)
      } catch {
        // Evicted server-side while it sat in the rail. Drop the stale row
        // rather than leaving a click that does nothing.
        refresh()
        return
      }
      useSession(id)
      // Picks up the spinner on the conversation just left, if it is still busy.
      refresh()
      // Nothing streams to this tab for a turn we did not start, so poll until
      // the answer lands. Cheap, and it stops as soon as it does.
      if (stillRunning) {
        pollRef.current = setInterval(async () => {
          try {
            if (!(await load(id))) {
              stopPolling()
              refresh()
            }
          } catch {
            stopPolling()
          }
        }, POLL_MS)
      }
    },
    [useSession, refresh, load, stopPolling],
  )

  return {
    turns,
    send,
    running,
    reset,
    conversations,
    sessionId,
    openConversation,
    removeConversation,
  }
}

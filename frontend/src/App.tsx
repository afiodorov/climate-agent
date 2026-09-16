import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMe, logout } from './api'
import { AskBar } from './components/AskBar'
import { ConversationPanel } from './components/ConversationPanel'
import { Turn } from './components/Turn'
import { useChat } from './hooks/useChat'
import { useRail } from './hooks/useRail'
import { useTheme } from './hooks/useTheme'
import type { Me } from './types'

const ANONYMOUS: Me = { login: null, admin: false, configured: false }

/** `?q=` is the shareable form of a conversation's opening question. */
function questionFromUrl(): string {
  return new URLSearchParams(location.search).get('q')?.trim() ?? ''
}

function setUrlQuestion(question: string | null) {
  const url = question ? `?q=${encodeURIComponent(question)}` : location.pathname
  history.replaceState({}, '', url)
}

export default function App() {
  const {
    turns,
    send,
    running,
    reset,
    conversations,
    sessionId,
    openConversation,
    removeConversation,
  } = useChat()
  const { theme, toggle } = useTheme()
  const rail = useRail()
  const transcriptRef = useRef<HTMLDivElement>(null)

  // Who is looking. Only admins get delete buttons; everyone else sees the
  // same rail read-only, and a sign-in link when the deployment offers one.
  const [me, setMe] = useState<Me>(ANONYMOUS)
  useEffect(() => {
    fetchMe().then(setMe, () => setMe(ANONYMOUS))
  }, [])
  const signOut = () => logout().then(() => setMe({ ...me, login: null, admin: false }))

  // The address bar carries the opening question, so the page can be shared
  // as a link that asks it again. Follow-ups are a conversation, not a query,
  // so they leave it alone; leaving the conversation clears it. replaceState
  // rather than pushState: Back should not re-ask a question.
  const ask = useCallback(
    (question: string) => {
      if (turns.length === 0) setUrlQuestion(question)
      send(question)
    },
    [turns.length, send],
  )
  const startNew = useCallback(() => {
    setUrlQuestion(null)
    reset()
  }, [reset])
  const open = useCallback(
    (id: string) => {
      setUrlQuestion(null)
      return openConversation(id)
    },
    [openConversation],
  )

  // Arriving with ?q= asks it once, in a fresh session. The ref survives
  // StrictMode's double-invoked effect, which would otherwise ask twice.
  const askedFromUrl = useRef(false)
  useEffect(() => {
    if (askedFromUrl.current) return
    askedFromUrl.current = true
    const q = questionFromUrl()
    if (q) send(q)
  }, [send])

  // Follow the conversation as it grows: a new turn, and each step landing in
  // the running one, should keep the newest content in view.
  useEffect(() => {
    const el = transcriptRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns])

  return (
    <>
      <ConversationPanel
        conversations={conversations}
        activeId={sessionId}
        narrow={rail.narrow}
        open={rail.open}
        onToggle={rail.toggle}
        onClose={rail.close}
        onOpen={open}
        onDelete={removeConversation}
        me={me}
        onSignOut={signOut}
      />

      <div className="layout">
        <header className="header">
          {/* Narrow only: the drawer has no chevron of its own to reopen it,
              so this is the one way back to the conversation list. */}
          {rail.narrow && (
            <button
              type="button"
              className="rail-menu"
              onClick={rail.toggle}
              aria-label="Show conversations"
              aria-expanded={rail.open}
              title="Conversations"
            >
              ☰
            </button>
          )}
          <div className="brand">
            <span className="logo">☀</span>
            <div>
              <h1>Climate Agent</h1>
              <p className="tagline">
                The world's large cities ranked by comfortable daylight hours, from hourly
                UTCI over ERA5 (2010–2024).
              </p>
            </div>
          </div>
          <div className="header-actions">
            {turns.length > 0 && (
              <button
                type="button"
                className="new-chat"
                onClick={startNew}
                title="Start a new conversation — this one stays in the list"
              >
                New chat
              </button>
            )}
            <button
              type="button"
              className="theme-toggle"
              onClick={toggle}
              aria-label="Toggle dark mode"
              title="Toggle dark mode"
            >
              {theme === 'dark' ? '☀' : '☾'}
            </button>
          </div>
        </header>

        {/* is-empty collapses it: with no turns the ask bar belongs under the
            header, not pushed to the bottom of a blank screen. */}
        <main
          className={turns.length ? 'transcript' : 'transcript is-empty'}
          ref={transcriptRef}
        >
          {turns.map((turn) => (
            <Turn key={turn.id} turn={turn} />
          ))}
        </main>

        <div className="composer">
          <AskBar running={running} empty={turns.length === 0} onAsk={ask} />
          <footer>
            climate node (DeepSeek + DuckDB) → caveats node, on a LangGraph
            graph. Every timing above is a step some node emitted.
          </footer>
        </div>
      </div>
    </>
  )
}

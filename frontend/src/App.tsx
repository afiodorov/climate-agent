import { useEffect, useRef, useState } from 'react'
import { fetchMe, logout } from './api'
import { AskBar } from './components/AskBar'
import { ConversationPanel } from './components/ConversationPanel'
import { Turn } from './components/Turn'
import { useChat } from './hooks/useChat'
import { useRail } from './hooks/useRail'
import { useTheme } from './hooks/useTheme'
import type { Me } from './types'

const ANONYMOUS: Me = { login: null, admin: false, configured: false }

/** Two link forms. `?s=<id>` is a conversation: opening it shows the answers
 *  as they were given. `?q=<question>` asks that question afresh, in a new
 *  conversation, and so may answer differently. */
function paramsFromUrl(): { conversation: string; question: string } {
  const params = new URLSearchParams(location.search)
  return {
    conversation: params.get('s')?.trim() ?? '',
    question: params.get('q')?.trim() ?? '',
  }
}

/** replaceState rather than pushState: Back should leave the page, not step
 *  through every conversation that was opened here. */
function setUrlConversation(id: string | null) {
  const search = id ? `?s=${encodeURIComponent(id)}` : ''
  if (location.search === search) return
  history.replaceState({}, '', location.pathname + search)
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

  // Arriving with ?s= opens that conversation; with ?q=, asks it once in a
  // fresh one. The ref survives StrictMode's double-invoked effect, which would
  // otherwise ask twice. Declared before the effect below, which rewrites the
  // URL, so this one reads the link the visitor actually arrived with.
  const arrived = useRef(false)
  useEffect(() => {
    if (arrived.current) return
    arrived.current = true
    const { conversation, question } = paramsFromUrl()
    if (conversation) openConversation(conversation)
    else if (question) send(question)
  }, [openConversation, send])

  // The address bar mirrors whichever conversation is on screen, so the page
  // can be copied as a link that shows the same answers. A first question makes
  // a fresh session shareable; New chat empties the transcript and clears it.
  const shareable = turns.length > 0
  useEffect(() => {
    setUrlConversation(shareable ? sessionId : null)
  }, [shareable, sessionId])

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
        onOpen={openConversation}
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
                onClick={reset}
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
          <AskBar running={running} empty={turns.length === 0} onAsk={send} />
          <footer>
            climate node (DeepSeek + DuckDB) → caveats node, on a LangGraph
            graph. Every timing above is a step some node emitted.
          </footer>
        </div>
      </div>
    </>
  )
}

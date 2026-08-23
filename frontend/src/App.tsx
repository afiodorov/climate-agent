import { useEffect, useRef } from 'react'
import { AskBar } from './components/AskBar'
import { ConversationPanel } from './components/ConversationPanel'
import { Turn } from './components/Turn'
import { useChat } from './hooks/useChat'
import { useRail } from './hooks/useRail'
import { useTheme } from './hooks/useTheme'

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
                1,118 cities ranked by comfortable daylight hours, from hourly
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

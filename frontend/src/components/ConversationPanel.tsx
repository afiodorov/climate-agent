import { useEffect, useState } from 'react'
import type { ConversationSummary, Me } from '../types'

interface Props {
  conversations: ConversationSummary[]
  activeId: string
  /** True when the rail is a drawer over the chat rather than a column beside
   *  it — see useRail. Changes how it opens, closes and dismisses. */
  narrow: boolean
  open: boolean
  onToggle: () => void
  onClose: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  me: Me
  onSignOut: () => void
}

/** "now", "4m", "2h", "3d" — enough to order things at a glance. */
function age(updatedAt: number): string {
  const seconds = Math.max(0, Date.now() / 1000 - updatedAt)
  if (seconds < 60) return 'now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

export function ConversationPanel({
  conversations,
  activeId,
  narrow,
  open,
  onToggle,
  onClose,
  onOpen,
  onDelete,
  me,
  onSignOut,
}: Props) {
  // Ages are relative, so re-render occasionally or "now" sticks forever.
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  if (!open) {
    // Narrow: nothing here at all. The drawer's handle is the ☰ in the header,
    // which is where a phone user looks for it, and a chevron pinned over the
    // transcript would sit on top of the answer.
    if (narrow) return null
    return (
      <aside className="rail collapsed">
        <button
          type="button"
          className="rail-toggle"
          onClick={onToggle}
          title="Show conversations"
        >
          ›
        </button>
      </aside>
    )
  }

  // Opening a conversation is the drawer's whole job, so it stands aside once
  // done; on a wide screen the rail is not in the way and stays put.
  const openThen = (id: string) => {
    onOpen(id)
    if (narrow) onClose()
  }

  return (
    <>
      {narrow && (
        <button
          type="button"
          className="rail-backdrop"
          onClick={onClose}
          aria-label="Close conversations"
          tabIndex={-1}
        />
      )}

      <aside className={narrow ? 'rail drawer' : 'rail'}>
        <div className="rail-head">
          <h2>Conversations</h2>
          <button
            type="button"
            className="rail-toggle"
            onClick={narrow ? onClose : onToggle}
            title="Hide conversations"
          >
            {narrow ? '×' : '‹'}
          </button>
        </div>

        {/* The rail is shared by every visitor, so deleting is for admins.
            A signed-in non-admin sees their name and no delete buttons. */}
        <div className="rail-auth">
          {me.login ? (
            <>
              <span className="rail-user" title={me.admin ? 'admin' : 'signed in'}>
                {me.login}
                {me.admin && <span className="rail-badge">admin</span>}
              </span>
              <button type="button" className="rail-link" onClick={onSignOut}>
                sign out
              </button>
            </>
          ) : me.configured ? (
            <a className="rail-link" href="/auth/login">
              Sign in with GitHub
            </a>
          ) : null}
        </div>

        {conversations.length === 0 ? (
          <p className="rail-empty">
            Nothing yet — a conversation appears here once its first answer
            lands.
          </p>
        ) : (
          <ul className="rail-list">
            {conversations.map((c) => (
              // The row is the li, not the button: a delete button nested inside
              // the open button would be invalid HTML and unreachable by keyboard.
              <li
                key={c.id}
                className={c.id === activeId ? 'active' : undefined}
              >
                <button
                  type="button"
                  className="rail-open"
                  onClick={() => openThen(c.id)}
                  title={c.title}
                >
                  <span className="rail-title">{c.title}</span>
                  <span className="rail-meta">
                    {c.pending > 0 && <span className="spinner" />}
                    {c.turns} {c.turns === 1 ? 'turn' : 'turns'} ·{' '}
                    {age(c.updated_at)}
                  </span>
                </button>
                {me.admin && (
                  <button
                    type="button"
                    className="rail-delete"
                    onClick={() => onDelete(c.id)}
                    aria-label={`Delete conversation: ${c.title}`}
                    title="Delete — this cannot be undone"
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </>
  )
}

import { useCallback, useEffect, useState } from 'react'
import type { ConversationSummary } from '../types'

interface Props {
  conversations: ConversationSummary[]
  activeId: string
  onOpen: (id: string) => void
  onDelete: (id: string) => void
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
  onOpen,
  onDelete,
}: Props) {
  // Same shape as useTheme: read once, persist on change.
  const [open, setOpen] = useState(
    () => localStorage.getItem('rail') !== 'closed',
  )
  useEffect(() => {
    localStorage.setItem('rail', open ? 'open' : 'closed')
  }, [open])

  // Ages are relative, so re-render occasionally or "now" sticks forever.
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  const toggle = useCallback(() => setOpen((o) => !o), [])

  if (!open) {
    return (
      <aside className="rail collapsed">
        <button
          type="button"
          className="rail-toggle"
          onClick={toggle}
          title="Show conversations"
        >
          ›
        </button>
      </aside>
    )
  }

  return (
    <aside className="rail">
      <div className="rail-head">
        <h2>Conversations</h2>
        <button
          type="button"
          className="rail-toggle"
          onClick={toggle}
          title="Hide conversations"
        >
          ‹
        </button>
      </div>

      {conversations.length === 0 ? (
        <p className="rail-empty">
          Nothing yet — a conversation appears here once its first answer lands.
        </p>
      ) : (
        <ul className="rail-list">
          {conversations.map((c) => (
            // The row is the li, not the button: a delete button nested inside
            // the open button would be invalid HTML and unreachable by keyboard.
            <li key={c.id} className={c.id === activeId ? 'active' : undefined}>
              <button
                type="button"
                className="rail-open"
                onClick={() => onOpen(c.id)}
                title={c.title}
              >
                <span className="rail-title">{c.title}</span>
                <span className="rail-meta">
                  {c.pending > 0 && <span className="spinner" />}
                  {c.turns} {c.turns === 1 ? 'turn' : 'turns'} · {age(c.updated_at)}
                </span>
              </button>
              <button
                type="button"
                className="rail-delete"
                onClick={() => onDelete(c.id)}
                aria-label={`Delete conversation: ${c.title}`}
                title="Delete — this cannot be undone"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

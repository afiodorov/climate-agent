import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { ENGLISH } from '../glossary'
import type { GlossaryEntry } from '../types'

const GUTTER = 12
const GAP = 6

interface Props {
  entry: GlossaryEntry
  /** ISO 639-1 code of the language to define the term in; falls back to
   *  English when the glossary has no such translation. */
  lang: string
  children: ReactNode
}

/** A glossary mention: dotted underline, definition on hover (mouse) or tap
 *  (touch), keyboard-reachable. The tip is portalled to <body> and positioned
 *  in viewport coordinates, because answers live inside scrollers (the
 *  transcript, the table wrapper) whose overflow would clip anything
 *  positioned inside them. It closes on scroll rather than following. */
export function Term({ entry, lang, children }: Props) {
  const text = lang === ENGLISH ? entry : (entry.translations[lang] ?? entry)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const anchor = useRef<HTMLElement>(null)
  const tip = useRef<HTMLSpanElement>(null)

  // Measure after the tip has rendered, before paint: keep it inside the
  // viewport horizontally, above the word unless there is no room.
  useLayoutEffect(() => {
    if (!open || !anchor.current || !tip.current) {
      setPos(null)
      return
    }
    const a = anchor.current.getBoundingClientRect()
    const t = tip.current.getBoundingClientRect()
    const maxLeft = window.innerWidth - GUTTER - t.width
    const left = Math.max(GUTTER, Math.min(a.left, maxLeft))
    const above = a.top - GAP - t.height
    const top = above >= GUTTER ? above : a.bottom + GAP
    setPos({ left, top })
  }, [open])

  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e.target instanceof Node && anchor.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  // Hover is a mouse thing; on touch the same events fire around a tap and
  // would fight the toggle, so each handler checks which kind it got.
  const onEnter = (e: PointerEvent) => e.pointerType === 'mouse' && setOpen(true)
  const onLeave = (e: PointerEvent) => e.pointerType === 'mouse' && setOpen(false)
  const onDown = (e: PointerEvent) => {
    if (e.pointerType !== 'mouse') setOpen((o) => !o)
  }

  return (
    <abbr
      ref={anchor}
      className="term"
      tabIndex={0}
      aria-label={text.term}
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
      onPointerDown={onDown}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setOpen((o) => !o)
        }
      }}
    >
      {children}
      {open &&
        createPortal(
          <span
            ref={tip}
            role="tooltip"
            className="tip"
            style={pos ?? { visibility: 'hidden', left: 0, top: 0 }}
          >
            <b>{text.term}</b> {text.definition}
            {entry.column && <code>{entry.column}</code>}
          </span>,
          document.body,
        )}
    </abbr>
  )
}

import { useCallback, useEffect, useState } from 'react'

/** Below this the rail cannot sit beside the 820px column without overlapping
 *  it. Must match the breakpoint the drawer styles use in styles.css. */
const NARROW = '(max-width: 1100px)'

/** Whether the rail is showing, and which of its two shapes it takes.
 *
 *  Wide: a fixed column beside the chat, collapsed or not as the user last
 *  left it. Narrow: a drawer over the chat, which always starts closed —
 *  remembering "open" there would mean every visit begins with the
 *  conversation list covering the answer. */
export function useRail() {
  const remembered = () => localStorage.getItem('rail') !== 'closed'
  const [narrow, setNarrow] = useState(() => matchMedia(NARROW).matches)
  const [open, setOpen] = useState(() => !matchMedia(NARROW).matches && remembered())

  // Rotating a phone, or dragging a desktop window narrow, crosses this: a
  // drawer left open would cover the chat, and a rail closed at phone width
  // should not stay closed once there is room for it again.
  useEffect(() => {
    const mq = matchMedia(NARROW)
    const onChange = (e: MediaQueryListEvent) => {
      setNarrow(e.matches)
      setOpen(e.matches ? false : remembered())
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // Only the wide rail's state is a preference worth keeping; see above.
  useEffect(() => {
    if (!narrow) localStorage.setItem('rail', open ? 'open' : 'closed')
  }, [narrow, open])

  const close = useCallback(() => setOpen(false), [])

  // The drawer floats over everything, so it needs the usual escape hatch.
  useEffect(() => {
    if (!narrow || !open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [narrow, open, close])

  return { narrow, open, close, toggle: useCallback(() => setOpen((o) => !o), []) }
}

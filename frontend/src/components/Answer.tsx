import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AskStatus, Final } from '../types'

/** Answers often come back as a seven-column ranking table, which is wider
 *  than a phone. A table left to itself widens the transcript, and since the
 *  transcript is the scroll container that drags the question, the prose and
 *  the caveats sideways along with it. Give the table its own scroller so only
 *  the table moves. Hoisted so react-markdown is not handed a new object on
 *  every render. */
const COMPONENTS: Components = {
  table: ({ node: _node, ...props }) => (
    <div className="table-scroll">
      <table {...props} />
    </div>
  ),
}

interface Props {
  final: Final | null
  status: AskStatus
}

export function Answer({ final, status }: Props) {
  if (!final) {
    if (status !== 'running') return null
    return (
      <div className="answer card placeholder">
        <span className="spinner" /> Querying the ranking…
      </div>
    )
  }

  return (
    <>
      <div className="answer card">
        <Markdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
          {final.answer}
        </Markdown>
      </div>
      {/* Collapsed by default: the caveats matter, but a five-item block under
          every answer pulls the eye away from the answer itself. The summary
          line still says how many there are, so a reader knows to look. */}
      {final.caveats.length > 0 && (
        <details className="caveats card">
          <summary>
            <span className="chevron" aria-hidden="true">▸</span>
            Caveats
            <span className="count">{final.caveats.length}</span>
            <span className="by">added by the caveats node</span>
          </summary>
          <ul>
            {final.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

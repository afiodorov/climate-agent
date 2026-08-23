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
      {final.caveats.length > 0 && (
        <div className="caveats card">
          <h2>
            Caveats
            <span className="by">added by the caveats node</span>
          </h2>
          <ul>
            {final.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

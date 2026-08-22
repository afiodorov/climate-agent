import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AskStatus, Final } from '../types'

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
        <Markdown remarkPlugins={[remarkGfm]}>{final.answer}</Markdown>
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

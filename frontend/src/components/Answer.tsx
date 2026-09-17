import { useMemo } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { rehypeTerms, segments, useGlossary, type Glossary } from '../glossary'
import type { AskStatus, Final } from '../types'
import { Term } from './Term'

/** Answers often come back as a seven-column ranking table, which is wider
 *  than a phone. A table left to itself widens the transcript, and since the
 *  transcript is the scroll container that drags the question, the prose and
 *  the caveats sideways along with it. Give the table its own scroller so only
 *  the table moves.
 *
 *  `abbr` is what the glossary plugin wraps a term mention in; the Term
 *  component hangs the tooltip on it. Built per glossary so react-markdown is
 *  not handed a new object on every render. */
function components(glossary: Glossary): Components {
  return {
    table: ({ node: _node, ...props }) => (
      <div className="table-scroll">
        <table {...props} />
      </div>
    ),
    abbr: ({ node: _node, children, ...props }) => {
      const mention = (props as Record<string, unknown>)['data-term']
      const entry =
        typeof mention === 'string' ? glossary.lookup(mention) : undefined
      if (!entry) return <abbr {...props}>{children}</abbr>
      return <Term entry={entry}>{children}</Term>
    },
  }
}

/** A caveat is a plain string, not markdown, so it gets the same marking by
 *  hand. */
function Marked({ text, glossary }: { text: string; glossary: Glossary }) {
  return (
    <>
      {segments(text, glossary).map((s, i) => {
        const entry = s.term ? glossary.lookup(s.text) : undefined
        return entry ? (
          <Term key={i} entry={entry}>
            {s.text}
          </Term>
        ) : (
          <span key={i}>{s.text}</span>
        )
      })}
    </>
  )
}

interface Props {
  final: Final | null
  status: AskStatus
}

export function Answer({ final, status }: Props) {
  const glossary = useGlossary()
  const rehype = useMemo(() => [rehypeTerms(glossary)], [glossary])
  const comps = useMemo(() => components(glossary), [glossary])

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
        <Markdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={rehype}
          components={comps}
        >
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
              <li key={i}>
                <Marked text={c} glossary={glossary} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

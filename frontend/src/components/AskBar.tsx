import { useState } from 'react'

interface Props {
  running: boolean
  /** True before the first question, when the examples are still useful. */
  empty: boolean
  onAsk: (v: string) => void
}

const EXAMPLES = [
  'Where is comfortable year-round without being humid?',
  'What is February like in Porto?',
  'Compare Warsaw and Moscow',
  'Best city in Colombia?',
]

export function AskBar({ running, empty, onAsk }: Props) {
  // The composer owns its own text now: on submit the question moves into the
  // transcript, so nothing upstream needs to read it back.
  const [value, setValue] = useState('')

  const ask = (question: string) => {
    if (!question.trim() || running) return
    setValue('')
    onAsk(question)
  }

  return (
    <div className="ask">
      <form
        className="ask-bar"
        onSubmit={(e) => {
          e.preventDefault()
          ask(value)
        }}
      >
        <input
          type="text"
          value={value}
          placeholder={empty ? 'Ask about city comfort…' : 'Ask a follow-up…'}
          onChange={(e) => setValue(e.target.value)}
          autoFocus
        />
        <button type="submit" disabled={running || !value.trim()}>
          {running ? 'Asking…' : 'Ask'}
        </button>
      </form>
      {empty && (
        <div className="examples">
          {EXAMPLES.map((e) => (
            <button key={e} type="button" disabled={running} onClick={() => ask(e)}>
              {e}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

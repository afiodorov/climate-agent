import type { Turn as TurnData } from '../types'
import { Answer } from './Answer'
import { ProgressLog } from './ProgressLog'

interface Props {
  turn: TurnData
}

/** One exchange in the transcript. The progress log and answer are the same
 *  components as before — they just get one turn's slice instead of the app's. */
export function Turn({ turn }: Props) {
  return (
    <article className="turn">
      <p className="turn-question">{turn.question}</p>
      <ProgressLog steps={turn.steps} status={turn.status} />
      {turn.error && <div className="error card">⚠ {turn.error}</div>}
      <Answer final={turn.final} status={turn.status} />
    </article>
  )
}

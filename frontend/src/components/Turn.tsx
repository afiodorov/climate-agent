import type { Turn as TurnData } from '../types'
import { Answer } from './Answer'
import { ProgressLog } from './ProgressLog'

interface Props {
  turn: TurnData
  /** Set only on the last finished turn, and only for admins. */
  onDelete?: () => void
}

/** One exchange in the transcript. The progress log and answer are the same
 *  components as before — they just get one turn's slice instead of the app's. */
export function Turn({ turn, onDelete }: Props) {
  return (
    <article className="turn">
      <div className="turn-head">
        <p className="turn-question">{turn.question}</p>
        {onDelete && (
          <button
            type="button"
            className="turn-delete"
            onClick={onDelete}
            aria-label="Delete this question and answer"
            title="Delete this question and answer, so it can be asked again — no undo"
          >
            ×
          </button>
        )}
      </div>
      <ProgressLog steps={turn.steps} status={turn.status} />
      {turn.error && <div className="error card">⚠ {turn.error}</div>}
      <Answer final={turn.final} status={turn.status} />
    </article>
  )
}

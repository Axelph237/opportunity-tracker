import { StatusCircle } from './icons'
import { titleCase } from '../format'

// Every badge tone in one place so type, status and source badges stay consistent.
const STATUS_TONES = {
  bookmarked: 'border-outline-variant text-on-surface-variant',
  planning_to_apply: 'border-outline-variant text-on-surface',
  applied: 'border-primary/60 text-primary',
  assessment: 'border-primary/60 text-primary',
  interview: 'border-tertiary/70 text-tertiary',
  offer: 'border-tertiary text-tertiary',
  rejected: 'border-error/60 text-error',
  withdrawn: 'border-outline-variant text-on-surface-variant',
  closed: 'border-outline-variant text-on-surface-variant',
}

const TYPE_TONES = {
  internship: 'border-primary/40 text-primary',
  research: 'border-primary/40 text-primary',
  job: 'border-outline-variant text-on-surface',
  grad_program: 'border-tertiary/40 text-tertiary',
  fellowship: 'border-tertiary/40 text-tertiary',
  other: 'border-outline-variant text-on-surface-variant',
}

const SOURCE_TONES = {
  job_board: 'border-outline-variant text-on-surface',
  company_careers: 'border-primary/40 text-primary',
  research_program: 'border-tertiary/40 text-tertiary',
  aggregator: 'border-outline-variant text-on-surface-variant',
  university: 'border-tertiary/40 text-tertiary',
  government: 'border-primary/40 text-primary',
}

const PALETTES = { status: STATUS_TONES, type: TYPE_TONES, source: SOURCE_TONES }

export default function StatusBadge({ value, kind = 'status', title }) {
  if (!value) return <span className="text-on-surface-variant">—</span>
  const tone = PALETTES[kind]?.[value] ?? 'border-outline-variant text-on-surface-variant'
  return (
    <span
      title={title || titleCase(value)}
      className={`inline-block rounded border px-2 py-[2px] font-mono text-data whitespace-nowrap ${tone}`}
    >
      {titleCase(value)}
    </span>
  )
}

/** Compact dot used in dense table rows. */
export function StatusDot({ status }) {
  const tone = status ? STATUS_TONES[status] ?? 'text-on-surface-variant' : 'text-on-surface-variant/60'
  return (
    <span
      title={status ? titleCase(status) : 'Not tracked'}
      className={tone}
      aria-label={status ? titleCase(status) : 'Not tracked'}
    >
      <StatusCircle tracked={Boolean(status)} />
    </span>
  )
}

// Shared formatting helpers for the data-dense views.

export function titleCase(value) {
  if (!value) return ''
  return String(value)
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const HAS_ZONE = /([Zz]|[+-]\d{2}:?\d{2})$/

/**
 * Parse a value from the API into a Date, or null if it is not a date at all.
 *
 * Three shapes arrive and each needs different treatment:
 *
 * - `2026-12-01` — a *calendar date*, not an instant. A deadline of the 1st is
 *   the 1st wherever you are. JavaScript parses the bare form as UTC midnight,
 *   which renders as the 30th anywhere west of Greenwich, so it is built as
 *   local midnight instead.
 * - `2026-09-22 13:02:05` — SQLite's `datetime('now')`. UTC, but it says so
 *   nowhere, and JavaScript reads an offset-less date-time as *local*. Left
 *   alone, a three-hour-old row computes a negative age and reads "just now".
 * - `2026-09-22T13:02:05+00:00` — what the API's own `_now()` writes.
 *   Unambiguous; used as-is.
 */
function parseStamp(value) {
  if (value === null || value === undefined) return null
  const text = String(value).trim()
  if (!text) return null
  if (DATE_ONLY.test(text)) {
    const [year, month, day] = text.split('-').map(Number)
    return new Date(year, month - 1, day)
  }
  const iso = text.replace(' ', 'T')
  const date = new Date(HAS_ZONE.test(iso) ? iso : `${iso}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDate(value) {
  if (!value) return '—'
  const date = parseStamp(value)
  if (!date) return value // Claude sometimes returns a descriptive deadline.
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' })
}

export function formatDateTime(value) {
  if (!value) return '—'
  const date = parseStamp(value)
  if (!date) return value
  return date.toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function relativeTime(value) {
  if (!value) return 'never'
  const date = parseStamp(value)
  if (!date) return value
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  // A clock skew or a stamp written a moment in the future must not fall
  // through the unit ladder and come out as a huge "ago".
  if (seconds < 0) return 'just now'
  if (seconds < 60) return 'just now'
  const units = [
    ['minute', 60],
    ['hour', 60],
    ['day', 24],
    ['week', 7],
  ]
  let amount = seconds
  let label = 'second'
  for (const [name, divisor] of units) {
    if (amount < divisor) break
    amount = Math.round(amount / divisor)
    label = name
  }
  return `${amount} ${label}${amount === 1 ? '' : 's'} ago`
}

/** Days until a deadline, or null when it is not a parseable date. */
export function daysUntil(value) {
  if (!value) return null
  const date = parseStamp(value)
  if (!date) return null
  return Math.ceil((date.getTime() - Date.now()) / 86_400_000)
}

/** Deadlines inside two weeks read amber; past deadlines read danger. */
export function deadlineTone(value) {
  const days = daysUntil(value)
  if (days === null) return 'text-on-surface-variant'
  if (days < 0) return 'text-error'
  if (days <= 14) return 'text-tertiary'
  return 'text-on-surface'
}

export function scoreTone(score) {
  if (score === null || score === undefined) return 'text-on-surface-variant'
  if (score >= 7.5) return 'text-primary'
  if (score >= 5) return 'text-on-surface'
  return 'text-on-surface-variant'
}

export function formatScore(score) {
  if (score === null || score === undefined) return '—'
  return Number(score).toFixed(1)
}

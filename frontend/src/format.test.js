import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import {
  deadlineTone,
  formatDate,
  formatDateTime,
  formatScore,
  relativeTime,
  scoreTone,
  titleCase,
} from './format'

// format.js's `parseStamp` deliberately treats three timestamp shapes
// differently (a bare "YYYY-MM-DD" deadline as local-midnight, a SQLite
// datetime('now') string as UTC, and an ISO+offset string as-is) precisely so
// that all three *display* consistently regardless of the reader's timezone.
// Pin TZ to a concrete negative-UTC-offset zone so that guarantee is actually
// exercised (in UTC itself, a mishandled offset would be invisible) and the
// result is deterministic no matter where `npm test` runs.
let originalTZ
beforeAll(() => {
  originalTZ = process.env.TZ
  process.env.TZ = 'America/Chicago'
})
afterAll(() => {
  process.env.TZ = originalTZ
})

describe('titleCase', () => {
  it('splits snake_case into title-cased words', () => {
    expect(titleCase('job_board')).toBe('Job Board')
    expect(titleCase('grad_program')).toBe('Grad Program')
  })

  it('title-cases a single word', () => {
    expect(titleCase('research')).toBe('Research')
  })

  it('returns an empty string for falsy input', () => {
    expect(titleCase('')).toBe('')
    expect(titleCase(null)).toBe('')
    expect(titleCase(undefined)).toBe('')
  })
})

describe('formatScore', () => {
  it('formats to one decimal place', () => {
    expect(formatScore(7)).toBe('7.0')
    expect(formatScore(8.96)).toBe('9.0')
    expect(formatScore(0)).toBe('0.0')
  })

  it('returns an em dash for null/undefined', () => {
    expect(formatScore(null)).toBe('—')
    expect(formatScore(undefined)).toBe('—')
  })
})

describe('scoreTone', () => {
  it('is primary at and above 7.5', () => {
    expect(scoreTone(7.5)).toBe('text-primary')
    expect(scoreTone(9.9)).toBe('text-primary')
  })

  it('is neutral on-surface between 5 and 7.5', () => {
    expect(scoreTone(5)).toBe('text-on-surface')
    expect(scoreTone(7.49)).toBe('text-on-surface')
  })

  it('is muted below 5', () => {
    expect(scoreTone(4.99)).toBe('text-on-surface-variant')
    expect(scoreTone(0)).toBe('text-on-surface-variant')
  })

  it('is muted for null/undefined', () => {
    expect(scoreTone(null)).toBe('text-on-surface-variant')
    expect(scoreTone(undefined)).toBe('text-on-surface-variant')
  })
})

describe('deadlineTone', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('is muted when there is no parseable deadline', () => {
    expect(deadlineTone(null)).toBe('text-on-surface-variant')
    expect(deadlineTone(undefined)).toBe('text-on-surface-variant')
    expect(deadlineTone('rolling')).toBe('text-on-surface-variant')
  })

  it('is error/danger for a deadline already in the past', () => {
    vi.setSystemTime(new Date('2026-09-22T12:00:00-05:00'))
    expect(deadlineTone('2026-09-01')).toBe('text-error')
  })

  it('is tertiary/amber for a deadline within 14 days', () => {
    vi.setSystemTime(new Date('2026-09-22T12:00:00-05:00'))
    expect(deadlineTone('2026-09-30')).toBe('text-tertiary')
  })

  it('is plain on-surface for a deadline further out than 14 days', () => {
    vi.setSystemTime(new Date('2026-09-22T12:00:00-05:00'))
    expect(deadlineTone('2027-01-01')).toBe('text-on-surface')
  })
})

describe('formatDate', () => {
  it('returns an em dash for falsy input', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('')).toBe('—')
  })

  it('passes through a value it cannot parse as a date', () => {
    // format.js: "Claude sometimes returns a descriptive deadline."
    expect(formatDate('rolling basis')).toBe('rolling basis')
  })

  it('formats an ISO-8601 string with an explicit UTC offset, converted to local time', () => {
    // 12:00 UTC is 07:00 in America/Chicago in September (CDT) -- still the 22nd.
    expect(formatDate('2026-09-22T12:00:00+00:00')).toBe('Sep 22, 2026')
  })

  it('formats a SQLite datetime(\'now\')-shaped string ("YYYY-MM-DD HH:MM:SS") as the UTC instant it is', () => {
    expect(formatDate('2026-09-22 12:00:00')).toBe('Sep 22, 2026')
  })

  it('formats a bare "YYYY-MM-DD" deadline as the same calendar day it stores, not shifted a day back', () => {
    // This is the case format.js's own comment calls out: parsing a date-only
    // string as UTC midnight would render as Nov 30 in any zone west of
    // Greenwich. parseStamp builds it as local midnight instead specifically
    // to avoid that.
    expect(formatDate('2026-12-01')).toBe('Dec 01, 2026')
    expect(formatDate('2026-01-01')).toBe('Jan 01, 2026')
  })
})

describe('formatDateTime', () => {
  it('returns an em dash for falsy input', () => {
    expect(formatDateTime(null)).toBe('—')
  })

  it('passes through an unparseable value', () => {
    expect(formatDateTime('never scheduled')).toBe('never scheduled')
  })

  it('renders an ISO-8601 string with an explicit UTC offset in local time', () => {
    expect(formatDateTime('2026-09-22T12:00:00+00:00')).toBe('Sep 22, 07:00 AM')
  })

  it('renders a SQLite datetime(\'now\')-shaped UTC timestamp identically to the equivalent ISO+offset timestamp', () => {
    // Same instant, two shapes the backend actually produces (see
    // backend/database.py's `datetime('now')` column defaults vs
    // backend/main.py's `datetime.now(timezone.utc).isoformat()`) -- they must
    // agree, which is exactly what parseStamp's `HAS_ZONE` branch guarantees.
    expect(formatDateTime('2026-09-22 12:00:00')).toBe(formatDateTime('2026-09-22T12:00:00+00:00'))
    expect(formatDateTime('2026-09-22 12:00:00')).toBe('Sep 22, 07:00 AM')
  })
})

describe('relativeTime', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "never" for falsy input', () => {
    expect(relativeTime(null)).toBe('never')
    expect(relativeTime(undefined)).toBe('never')
  })

  it('passes through an unparseable value', () => {
    expect(relativeTime('unknown')).toBe('unknown')
  })

  it('says "just now" for anything under a minute old', () => {
    vi.setSystemTime(new Date('2026-09-22T13:00:00+00:00'))
    expect(relativeTime('2026-09-22T12:59:45+00:00')).toBe('just now')
  })

  it('says "just now" instead of a negative duration for a timestamp that is (per clock skew) in the future', () => {
    vi.setSystemTime(new Date('2026-09-22T13:00:00+00:00'))
    expect(relativeTime('2026-09-22T13:05:00+00:00')).toBe('just now')
  })

  it('reports whole minutes, hours and weeks ago for an ISO+offset timestamp', () => {
    vi.setSystemTime(new Date('2026-09-22T13:00:00+00:00'))
    expect(relativeTime('2026-09-22T12:00:00+00:00')).toBe('1 hour ago')
    expect(relativeTime('2026-09-22T11:00:00+00:00')).toBe('2 hours ago')
    expect(relativeTime('2026-09-15T13:00:00+00:00')).toBe('1 week ago')
  })

  it('treats a SQLite datetime(\'now\')-shaped UTC timestamp the same as the equivalent ISO+offset timestamp', () => {
    vi.setSystemTime(new Date('2026-09-22T13:00:00+00:00'))
    // Same wall-clock UTC instant, 1 hour before "now", in both shapes.
    expect(relativeTime('2026-09-22 12:00:00')).toBe('1 hour ago')
    expect(relativeTime('2026-09-22 12:00:00')).toBe(relativeTime('2026-09-22T12:00:00+00:00'))
  })
})

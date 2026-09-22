import { useCallback, useEffect, useState } from 'react'
import { AI_CALL_TITLE, AiSpark, StatusMark } from './icons'
import { api } from '../api'
import { formatDateTime, formatScore, scoreTone, titleCase } from '../format'

// met / partial / gap are the three verdicts Claude returns per requirement.
const STATUS_TONE = {
  met: 'border-primary/60 bg-primary/10 text-primary',
  partial: 'border-tertiary/60 bg-tertiary/10 text-tertiary',
  gap: 'border-error/60 bg-error/10 text-error',
  unknown: 'border-outline-variant text-on-surface-variant',
}
const IMPORTANCE_TONE = {
  required: 'text-on-surface',
  preferred: 'text-on-surface-variant',
  nice_to_have: 'text-on-surface-variant',
}
const PRIORITY_TONE = {
  high: 'border-primary text-primary',
  medium: 'border-tertiary/70 text-tertiary',
  low: 'border-outline-variant text-on-surface-variant',
}

function Requirement({ item }) {
  return (
    <li className="flex items-start gap-3 border-b border-outline-variant/60 py-2 last:border-b-0">
      <span
        title={titleCase(item.status)}
        className={`mt-[2px] inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border ${
          STATUS_TONE[item.status] || STATUS_TONE.unknown
        }`}
      >
        <StatusMark status={item.status} />
      </span>
      <div className="min-w-0">
        <div className={IMPORTANCE_TONE[item.importance] || 'text-on-surface'}>
          {item.requirement}
          {item.importance === 'required' ? (
            <span className="ml-2 font-mono text-data text-on-surface-variant">required</span>
          ) : null}
        </div>
        {item.evidence ? <p className="mt-1 text-on-surface-variant">{item.evidence}</p> : null}
      </div>
    </li>
  )
}

function Adjustment({ item, index }) {
  return (
    <li className="space-y-2 rounded border border-outline-variant bg-surface p-3">
      <div className="flex items-start justify-between gap-3">
        <span className="font-mono text-data text-on-surface-variant">
          {String(index + 1).padStart(2, '0')} · {item.section}
        </span>
        <span className={`shrink-0 rounded border px-2 py-[1px] font-mono text-data ${PRIORITY_TONE[item.priority]}`}>
          {item.priority}
        </span>
      </div>
      {item.current ? (
        <div>
          <div className="label-data block">Currently</div>
          <p className="mt-1 text-on-surface-variant line-through decoration-error/40">{item.current}</p>
        </div>
      ) : null}
      <div>
        <div className="label-data block">{item.current ? 'Change to' : 'Add'}</div>
        <p className="mt-1 whitespace-pre-line text-on-surface">{item.suggested}</p>
      </div>
      {item.rationale ? <p className="text-on-surface-variant">{item.rationale}</p> : null}
    </li>
  )
}

/**
 * Per-listing resume advice. Loads any cached analysis on open and lets the user
 * generate or refresh it — each generation is a headless Claude call.
 */
export default function ResumeFitPanel({ opportunityId }) {
  const [advice, setAdvice] = useState(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  const loadCached = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setAdvice(await api.resumeAdvice(opportunityId))
    } catch {
      setAdvice(null) // 404 simply means nothing has been generated yet
    } finally {
      setLoading(false)
    }
  }, [opportunityId])

  useEffect(() => {
    loadCached()
  }, [loadCached])

  const generate = async (refresh) => {
    setGenerating(true)
    setError(null)
    try {
      setAdvice(await api.generateResumeAdvice(opportunityId, refresh))
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  if (loading) return <p className="font-mono text-data text-on-surface-variant">Checking for saved analysis…</p>

  if (!advice) {
    return (
      <div className="space-y-3 rounded border border-outline-variant bg-surface p-4">
        <p className="text-on-surface-variant">
          Claude reads this listing against your resume: which requirements you meet, which you miss,
          and what to change. Takes up to a minute.
        </p>
        {error ? <p className="text-error">{error}</p> : null}
        <button
          type="button"
          className="btn btn-primary"
          title={AI_CALL_TITLE}
          disabled={generating}
          onClick={() => generate(false)}
        >
          <AiSpark />
          {generating ? 'Analyzing…' : 'Suggest adjustments'}
        </button>
      </div>
    )
  }

  const counts = advice.requirements.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] || 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-4 rounded border border-outline-variant bg-surface p-4">
        <div className="shrink-0 text-center">
          <div className={`font-mono text-2xl font-bold ${scoreTone(advice.fit_score)}`}>
            {formatScore(advice.fit_score)}
          </div>
          <div className="label-data block">fit now</div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-on-surface">{advice.fit_summary}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-data">
            {['met', 'partial', 'gap'].map((status) =>
              counts[status] ? (
                <span key={status} className={`rounded border px-2 py-[1px] ${STATUS_TONE[status]}`}>
                  {counts[status]} {status}
                </span>
              ) : null,
            )}
            <span className="text-on-surface-variant">· {formatDateTime(advice.generated_at)}</span>
          </div>
        </div>
      </div>

      {advice.stale ? (
        <p className="rounded border border-tertiary/60 bg-tertiary/10 px-3 py-2 text-tertiary">
          Generated against <span className="font-mono">{advice.resume_filename}</span>, but a different
          resume is loaded now. Regenerate for current advice.
        </p>
      ) : null}
      {error ? <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p> : null}

      <div>
        <div className="label-data block mb-1">Requirements ({advice.requirements.length})</div>
        <ul>
          {advice.requirements.map((item, index) => (
            <Requirement key={index} item={item} />
          ))}
        </ul>
      </div>

      <div>
        <div className="label-data block mb-2">Recommended resume adjustments ({advice.adjustments.length})</div>
        <ul className="space-y-3">
          {advice.adjustments.map((item, index) => (
            <Adjustment key={index} item={item} index={index} />
          ))}
        </ul>
      </div>

      {advice.keywords.length ? (
        <div>
          <div className="label-data block mb-2">Keywords worth mirroring</div>
          <div className="flex flex-wrap gap-2">
            {advice.keywords.map((keyword) => (
              <span
                key={keyword}
                className="rounded border border-outline-variant bg-surface-container-high px-2 py-[2px] font-mono text-data text-on-surface"
              >
                {keyword}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {advice.talking_points.length ? (
        <div>
          <div className="label-data block mb-2">Talking points</div>
          <ul className="list-disc space-y-1 pl-5 text-on-surface marker:text-primary">
            {advice.talking_points.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <button
        type="button"
        className="btn"
        title={AI_CALL_TITLE}
        disabled={generating}
        onClick={() => generate(true)}
      >
        <AiSpark />
        {generating ? 'Regenerating…' : 'Regenerate'}
      </button>
    </div>
  )
}

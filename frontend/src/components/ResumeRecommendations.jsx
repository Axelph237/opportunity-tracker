import { useCallback, useEffect, useState } from 'react'
import { AI_CALL_TITLE, AiSpark, ChevronIcon, ExternalLinkIcon, StatusMark } from './icons'
import { api } from '../api'
import { formatDate, formatScore, scoreTone, titleCase } from '../format'

const STATUS_TONE = {
  met: 'border-primary/60 bg-primary/10 text-primary',
  partial: 'border-tertiary/60 bg-tertiary/10 text-tertiary',
  gap: 'border-error/60 bg-error/10 text-error',
  unknown: 'border-outline-variant text-on-surface-variant',
}
const PRIORITY_TONE = {
  high: 'border-primary text-primary',
  medium: 'border-tertiary/70 text-tertiary',
  low: 'border-outline-variant text-on-surface-variant',
}

/**
 * One listing's advice, collapsed to its title until opened.
 *
 * The advice is fetched only when the section is expanded. A resume linked to
 * eight listings would otherwise fire eight requests — and eight panels of
 * dense text — for the one the user actually wanted to read.
 */
function ListingAdvice({ listing, onInsert }) {
  const [open, setOpen] = useState(false)
  const [advice, setAdvice] = useState(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setAdvice(await api.resumeAdvice(listing.id))
    } catch {
      setAdvice(null) // 404 just means none has been generated yet
    } finally {
      setLoading(false)
    }
  }, [listing.id])

  useEffect(() => {
    if (open && !advice && !loading) load()
  }, [open, advice, loading, load])

  const generate = async () => {
    setGenerating(true)
    setError(null)
    try {
      setAdvice(await api.generateResumeAdvice(listing.id, Boolean(advice)))
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <li className="border-b border-outline-variant/60 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-container-high"
      >
        <ChevronIcon className={`mt-1 h-3.5 w-3.5 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 block text-on-surface">{listing.title}</span>
          <span className="mt-0.5 block truncate font-mono text-data text-on-surface-variant">
            {listing.organization}
            {listing.deadline ? ` · due ${formatDate(listing.deadline)}` : ''}
          </span>
        </span>
        <span className={`shrink-0 font-mono text-data ${scoreTone(listing.relevance_score)}`}>
          {formatScore(listing.relevance_score)}
        </span>
      </button>

      {open ? (
        <div className="space-y-4 px-4 pb-4">
          {loading ? (
            <p className="font-mono text-data text-on-surface-variant">Loading advice…</p>
          ) : !advice ? (
            <div className="space-y-2">
              <p className="text-on-surface-variant">
                No advice generated for this listing yet.
              </p>
              <button
                type="button"
                className="btn"
                title={AI_CALL_TITLE}
                disabled={generating}
                onClick={generate}
              >
                <AiSpark />
                {generating ? 'Analyzing…' : 'Suggest adjustments'}
              </button>
            </div>
          ) : (
            <>
              <p className="text-on-surface-variant">{advice.fit_summary}</p>

              {advice.stale ? (
                <p className="rounded border border-tertiary/60 bg-tertiary/10 px-2 py-1 text-tertiary">
                  Generated against <span className="font-mono">{advice.resume_filename}</span>.
                  Regenerate once you have finished editing.
                </p>
              ) : null}

              {advice.adjustments.length ? (
                <div>
                  <div className="label-data mb-2 block">Suggested changes</div>
                  <ul className="space-y-2">
                    {advice.adjustments.map((item, index) => (
                      <li key={index} className="rounded border border-outline-variant bg-surface p-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-mono text-data text-on-surface-variant">{item.section}</span>
                          <span
                            className={`shrink-0 rounded border px-1.5 font-mono text-data ${
                              PRIORITY_TONE[item.priority] || PRIORITY_TONE.low
                            }`}
                          >
                            {item.priority}
                          </span>
                        </div>
                        <p className="mt-1.5 whitespace-pre-line text-on-surface">{item.suggested}</p>
                        {item.rationale ? (
                          <p className="mt-1 text-on-surface-variant">{item.rationale}</p>
                        ) : null}
                        {/* The point of having the advice beside the editor: put
                            the wording into the document instead of retyping it. */}
                        <button
                          type="button"
                          className="btn mt-2"
                          onClick={() => onInsert(item.suggested)}
                          title="Insert this wording at the cursor"
                        >
                          Insert at cursor
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {advice.requirements.length ? (
                <div>
                  <div className="label-data mb-1 block">Requirements</div>
                  <ul className="space-y-1">
                    {advice.requirements.map((item, index) => (
                      <li key={index} className="flex items-start gap-2">
                        <span
                          title={titleCase(item.status)}
                          className={`mt-[2px] inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                            STATUS_TONE[item.status] || STATUS_TONE.unknown
                          }`}
                        >
                          <StatusMark status={item.status} />
                        </span>
                        <span className="min-w-0 text-on-surface-variant">{item.requirement}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {advice.keywords.length ? (
                <div>
                  <div className="label-data mb-1.5 block">Keywords worth mirroring</div>
                  <div className="flex flex-wrap gap-1.5">
                    {advice.keywords.map((keyword) => (
                      <button
                        key={keyword}
                        type="button"
                        onClick={() => onInsert(keyword)}
                        title="Insert at cursor"
                        className="rounded border border-outline-variant bg-surface-container-high px-1.5 font-mono text-data text-on-surface transition-colors hover:border-primary hover:text-primary"
                      >
                        {keyword}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="btn"
                  title={AI_CALL_TITLE}
                  disabled={generating}
                  onClick={generate}
                >
                  <AiSpark />
                  {generating ? 'Regenerating…' : 'Regenerate'}
                </button>
                {listing.url ? (
                  <a
                    href={listing.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-on-surface-variant transition-colors hover:text-primary"
                  >
                    Listing
                    <ExternalLinkIcon />
                  </a>
                ) : null}
              </div>
            </>
          )}
          {error ? <p className="text-error">{error}</p> : null}
        </div>
      ) : null}
    </li>
  )
}

/**
 * The recommendations rail beside the editor: every listing this resume is
 * linked to, and what Claude said to change for each.
 */
export default function ResumeRecommendations({ instanceId, links, loading, onInsert }) {
  if (loading) {
    return <p className="px-4 py-4 font-mono text-data text-on-surface-variant">Loading…</p>
  }

  if (!links.length) {
    return (
      <div className="space-y-2 px-4 py-4">
        <p className="text-on-surface-variant">
          No listings use this resume yet.
        </p>
        <p className="text-on-surface-variant">
          Open a listing in Opportunities and pick this resume under{' '}
          <span className="text-on-surface">Tailored resume</span>. Its advice shows up here, next
          to the source you are editing.
        </p>
      </div>
    )
  }

  return (
    <ul key={instanceId}>
      {links.map((listing) => (
        <ListingAdvice key={listing.id} listing={listing} onInsert={onInsert} />
      ))}
    </ul>
  )
}

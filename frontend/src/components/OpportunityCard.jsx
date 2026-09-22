import { useEffect, useState } from 'react'
import StatusBadge from './StatusBadge'
import { ExternalLinkIcon, StarIcon } from './icons'
import { deadlineTone, formatDate, formatScore, scoreTone, titleCase } from '../format'

function Field({ label, children }) {
  return (
    <div>
      <div className="label-data">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function Chip({ children, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-outline-variant bg-surface-container-high px-2 py-[2px] font-mono text-data text-on-surface">
      {children}
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          className="text-on-surface-variant hover:text-error"
          aria-label={`Remove ${children}`}
        >
          ×
        </button>
      ) : null}
    </span>
  )
}

/** Detail card for a single opportunity. Rendered inside the slide-in panel. */
export default function OpportunityCard({ opportunity, application, onTrack, onSaveTags, busy }) {
  const [tags, setTags] = useState(opportunity.tags || [])
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setTags(opportunity.tags || [])
    setDraft('')
    setDirty(false)
  }, [opportunity.id, opportunity.tags])

  const addTag = () => {
    const value = draft.trim()
    if (!value || tags.includes(value)) return
    setTags([...tags, value])
    setDraft('')
    setDirty(true)
  }

  const removeTag = (tag) => {
    setTags(tags.filter((item) => item !== tag))
    setDirty(true)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-5">
        <div className="shrink-0 text-center">
          <div className={`font-mono text-3xl font-bold ${scoreTone(opportunity.relevance_score)}`}>
            {formatScore(opportunity.relevance_score)}
          </div>
          <div className="label-data mt-1">/ 10</div>
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge value={opportunity.type} kind="type" />
            {opportunity.strong_match ? (
              <span className="inline-flex items-center gap-1 rounded border border-primary bg-primary/15 px-2 py-[2px] font-mono text-data text-primary">
                <StarIcon />
                Strong match
              </span>
            ) : null}
            {opportunity.remote ? (
              <span className="rounded border border-outline-variant px-2 py-[2px] font-mono text-data text-on-surface-variant">Remote</span>
            ) : null}
          </div>
          {opportunity.relevance_summary ? (
            <p className="text-on-surface">{opportunity.relevance_summary}</p>
          ) : (
            <p className="text-on-surface-variant">No relevance summary was produced for this listing.</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 border-y border-outline-variant py-4">
        <Field label="Organization">
          <span className="text-on-surface">{opportunity.organization}</span>
        </Field>
        <Field label="Location">
          <span className="text-on-surface">{opportunity.location || '—'}</span>
        </Field>
        <Field label="Deadline">
          <span className={`font-mono ${deadlineTone(opportunity.deadline)}`}>
            {opportunity.deadline ? formatDate(opportunity.deadline) : '—'}
          </span>
        </Field>
        <Field label="Experience level">
          <span className="font-mono text-on-surface">{titleCase(opportunity.experience_level) || '—'}</span>
        </Field>
        <Field label="Source">
          <span className="text-on-surface">{opportunity.source_name || '—'}</span>
        </Field>
        <Field label="Found">
          <span className="font-mono text-on-surface">{formatDate(opportunity.date_found)}</span>
        </Field>
      </div>

      <Field label="Description">
        <p className="whitespace-pre-line text-on-surface">{opportunity.description || 'No description captured.'}</p>
      </Field>

      <Field label={`Skill matches (${opportunity.skill_matches?.length || 0})`}>
        {opportunity.skill_matches?.length ? (
          <div className="flex flex-wrap gap-2">
            {opportunity.skill_matches.map((skill) => (
              <span
                key={skill}
                className="rounded border border-primary/40 bg-primary/10 px-2 py-[2px] font-mono text-data text-primary"
              >
                {skill}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-on-surface-variant">None identified.</span>
        )}
      </Field>

      <Field label="Tags">
        <div className="flex flex-wrap items-center gap-2">
          {tags.map((tag) => (
            <Chip key={tag} onRemove={() => removeTag(tag)}>
              {tag}
            </Chip>
          ))}
          <input
            className="field w-40"
            placeholder="add tag…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                addTag()
              }
            }}
          />
          {dirty ? (
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => {
                onSaveTags(tags)
                setDirty(false)
              }}
            >
              Save
            </button>
          ) : null}
        </div>
      </Field>

      <div className="flex flex-wrap items-center gap-3 pt-2">
        <a href={opportunity.url} target="_blank" rel="noreferrer" className="btn">
          Open listing
          <ExternalLinkIcon />
        </a>
        {application ? (
          <span className="flex items-center gap-2 font-mono text-data text-on-surface-variant">
            Tracked as
            <StatusBadge value={application.status} />
          </span>
        ) : (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={onTrack}>
            {busy ? 'Adding…' : 'Track application'}
          </button>
        )}
      </div>
    </div>
  )
}

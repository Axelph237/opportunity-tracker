import { useState } from 'react'
import { Field, TextArea, TextInput } from './editing'
import { AI_CALL_TITLE, AiSpark } from './icons'

// The three buckets the careers-office material separates, in the order a
// screener reads for them. A bucket with no terms is not rendered at all.
const BUCKETS = [
  { bucket: 'technical', label: 'Technical terms' },
  { bucket: 'verb', label: 'Action verbs' },
  { bucket: 'professional', label: 'Professional skills' },
]

const COVERED = 'border-primary/40 bg-primary/10 text-primary'
const MISSING = 'border-outline-variant text-on-surface-variant'

function Term({ item, onLocate }) {
  const className = `rounded border px-2 py-[2px] font-mono text-data ${
    item.covered ? COVERED : MISSING
  }`
  const where = item.where || []

  // Only a covered term has somewhere to go, so only a covered term is a
  // control. A missing one that looked clickable and did nothing would be
  // worse than a label.
  if (!item.covered || !where.length) {
    return (
      <span className={className} title={item.covered ? 'Used, but not traced to a line' : 'Not used yet'}>
        {item.term}
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={() => onLocate(where[0])}
      title={`Used ${item.hits || where.length}×. Jump to it.`}
      className={`${className} transition-colors hover:border-primary`}
    >
      {item.term}
    </button>
  )
}

/** Paste the ad. There is no job-description text anywhere else in the app. */
export function JobAdForm({ onSave, busy }) {
  const [title, setTitle] = useState('')
  const [organization, setOrganization] = useState('')
  const [url, setUrl] = useState('')
  const [rawText, setRawText] = useState('')

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        onSave({
          title: title.trim(),
          organization: organization.trim() || null,
          url: url.trim() || null,
          raw_text: rawText.trim(),
        })
      }}
    >
      <p className="text-on-surface-variant">
        Paste the ad itself. What the tracker stores for a listing is a two-sentence summary, which
        has no keywords left in it to match against.
      </p>
      <Field label="Role">
        <TextInput value={title} onChange={setTitle} placeholder="Quantum Computing Intern" required />
      </Field>
      <Field label="Organization">
        <TextInput value={organization} onChange={setOrganization} placeholder="ACME Labs" />
      </Field>
      <Field label="Link" hint="Optional. Only so you can find your way back to it.">
        <TextInput value={url} onChange={setUrl} placeholder="https://" />
      </Field>
      <Field label="The ad">
        <TextArea value={rawText} onChange={setRawText} rows={10} placeholder="Paste the full posting…" />
      </Field>
      <button
        type="submit"
        className="btn btn-primary"
        disabled={busy || !title.trim() || !rawText.trim()}
      >
        {busy ? 'Saving…' : 'Save the ad'}
      </button>
    </form>
  )
}

/**
 * Which of the ad's keywords this draft actually uses, live.
 *
 * The verdict comes from the server on every change rather than being
 * recomputed here: the matcher folds suffixes and strips LaTeX, and a second
 * copy of those rules in JavaScript would disagree with the one that counts.
 */
export default function CoveragePanel({
  jobPost,
  coverage = [],
  loading,
  busy,
  extracting,
  generating,
  onAddJobPost,
  onExtract,
  onLocate,
  onTailor,
}) {
  const covered = coverage.filter((item) => item.covered).length

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-outline-variant px-4 py-2">
        <span className="label-data">Keyword coverage</span>
        {coverage.length ? (
          <span className="font-mono text-data text-on-surface-variant">
            {covered}/{coverage.length}
          </span>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {!jobPost ? (
          <div className="space-y-3">
            <p className="text-on-surface-variant">
              Paste the ad you are writing this for and its keywords appear here.
            </p>
            <button type="button" className="btn btn-primary" onClick={onAddJobPost}>
              Paste the job ad
            </button>
          </div>
        ) : (
          <>
            <div>
              <div className="text-on-surface">{jobPost.title}</div>
              {jobPost.organization ? (
                <div className="font-mono text-data text-on-surface-variant">{jobPost.organization}</div>
              ) : null}
            </div>

            {!coverage.length ? (
              <div className="space-y-3 rounded border border-outline-variant bg-surface p-3">
                <p className="text-on-surface-variant">
                  {loading ? 'Checking the draft against the ad…' : 'No keywords pulled out yet.'}
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  title={`${AI_CALL_TITLE}. Up to a minute.`}
                  disabled={extracting || loading}
                  onClick={onExtract}
                >
                  <AiSpark />
                  {extracting ? 'Reading the ad…' : 'Pull out the keywords'}
                </button>
              </div>
            ) : (
              BUCKETS.map(({ bucket, label }) => {
                const items = coverage.filter((item) => item.bucket === bucket)
                if (!items.length) return null
                const hit = items.filter((item) => item.covered).length
                return (
                  <div key={bucket}>
                    <div className="mb-2 flex items-baseline justify-between gap-2">
                      <span className="label-data">{label}</span>
                      <span className="font-mono text-data text-on-surface-variant">
                        {hit}/{items.length}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {items.map((item) => (
                        <Term key={item.term} item={item} onLocate={onLocate} />
                      ))}
                    </div>
                  </div>
                )
              })
            )}
          </>
        )}
      </div>

      {jobPost && coverage.length ? (
        <div className="shrink-0 space-y-2 border-t border-outline-variant px-4 py-3">
          <p className="font-mono text-data text-on-surface-variant">
            Reorders and rewrites your own bullets to close the gaps. It cannot add experience you
            do not have.
          </p>
          <button
            type="button"
            className="btn btn-primary w-full justify-center"
            title={`${AI_CALL_TITLE}. Up to a minute.`}
            disabled={generating}
            onClick={onTailor}
          >
            <AiSpark />
            {generating ? 'Tailoring…' : 'Tailor to this ad'}
          </button>
        </div>
      ) : null}
    </div>
  )
}

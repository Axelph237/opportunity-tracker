import { useState } from 'react'
import StatusBadge from './StatusBadge'
import { AI_CALL_TITLE, AiSpark } from './icons'
import { formatDateTime } from '../format'

function ConfidenceBar({ value }) {
  const percent = Math.round((value ?? 0) * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 w-24 rounded bg-outline-variant">
        <div className="h-1 rounded bg-primary" style={{ width: `${percent}%` }} />
      </div>
      <span className="font-mono text-data text-on-surface-variant">{percent}%</span>
    </div>
  )
}

/** Claude's proposed sources, awaiting approval. */
export default function SourceDiscoveryPanel({
  proposals,
  onDiscover,
  onApprove,
  onReject,
  discovering,
  error,
  busyId,
}) {
  const [focus, setFocus] = useState('')
  const [count, setCount] = useState(12)

  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded border border-outline-variant bg-surface p-4">
        <div className="label-data">Ask Claude for new sources</div>
        <p className="text-on-surface-variant">
          Claude searches for untracked listing pages and explains why each fits. Nothing is scraped
          until you approve it.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            className="field max-w-sm"
            placeholder="Optional focus, e.g. 'superconducting qubit startups'"
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
          />
          <input
            type="number"
            min="1"
            max="25"
            className="field w-20"
            value={count}
            onChange={(event) => setCount(Number(event.target.value))}
          />
          <button
            type="button"
            className="btn btn-primary"
            title={AI_CALL_TITLE}
            disabled={discovering}
            onClick={() => onDiscover({ count, focus: focus.trim() || undefined })}
          >
            <AiSpark />
            {discovering ? 'Searching…' : 'Discover sources'}
          </button>
        </div>
        {discovering ? (
          <p className="font-mono text-data text-tertiary">
            Searching the web — usually one to three minutes.
          </p>
        ) : null}
        {error ? (
          <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p>
        ) : null}
      </section>

      <section className="space-y-3">
        <div className="label-data">Pending proposals ({proposals.length})</div>

        {proposals.length === 0 ? (
          <p className="text-on-surface-variant">
            No proposals waiting. Run a discovery pass to have Claude suggest new boards and programs.
          </p>
        ) : null}

        {proposals.map((proposal) => (
          <article key={proposal.id} className="space-y-3 rounded border border-outline-variant bg-surface p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-on-surface">{proposal.name}</h3>
                <a
                  href={proposal.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate font-mono text-data text-primary hover:underline"
                >
                  {proposal.url}
                </a>
              </div>
              <StatusBadge value={proposal.type} kind="source" />
            </div>

            <p className="text-on-surface-variant">{proposal.rationale}</p>

            <div className="flex flex-wrap items-center gap-4">
              <ConfidenceBar value={proposal.confidence} />
              <span className="font-mono text-data text-on-surface-variant">{proposal.scrape_method}</span>
              <span className="font-mono text-data text-on-surface-variant">{formatDateTime(proposal.date_proposed)}</span>
              <div className="ml-auto flex gap-2">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busyId === proposal.id}
                  onClick={() => onApprove(proposal)}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="btn hover:border-error hover:text-error"
                  disabled={busyId === proposal.id}
                  onClick={() => onReject(proposal)}
                >
                  Reject
                </button>
              </div>
            </div>
          </article>
        ))}
      </section>
    </div>
  )
}

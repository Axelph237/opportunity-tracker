import { useState } from 'react'

/**
 * One line of plain English per operation.
 *
 * A table rather than a chain of conditionals, because the set of operations
 * is closed: the agent may only emit these eight, and every one of them names
 * something that already exists. That closure is what stops a proposal
 * inventing experience, so the review surface enumerates the same eight.
 */
const OPERATIONS = {
  AddEntry: (op, at) => ['Add', `${at.entry(op.entry_id)} to ${op.section || 'the resume'}`],
  DropEntry: (op, at) => ['Remove', `${at.placement(op.placement_id)} from the resume`],
  MoveEntry: (op, at) => ['Move', `${at.placement(op.placement_id)} to position ${(op.position ?? 0) + 1}`],
  RenameSection: (op, at) => ['Rename', `${at.section(op.section_id)} to “${op.label}”`],
  AddBullet: (op, at) => ['Add a bullet', `to ${at.placement(op.placement_id)}`],
  DropBullet: (op, at) => ['Drop a bullet', `from ${at.placement(op.placement_id)}`],
  MoveBullet: (op, at) => ['Move a bullet', `to position ${(op.position ?? 0) + 1} in ${at.placement(op.placement_id)}`],
  RewriteBullet: (op, at) => ['Reword a bullet', `in ${at.placement(op.placement_id)}`],
}

const KIND_HEADING = {
  tailor: 'Tailored for this ad',
  sync: 'Your bank has moved on since this draft',
}

/** Operations carry their own id; an index is the fallback for one that does not. */
const idOf = (op, index) => op.id ?? index

function lookups(body, bank) {
  const sections = new Map()
  const placements = new Map()
  const bullets = new Map()
  for (const section of body?.sections || []) {
    sections.set(section.ref, section.label)
    for (const placement of section.placements || []) {
      placements.set(placement.ref, placement.title)
      for (const bullet of placement.bullets || []) bullets.set(bullet.ref, bullet.text)
    }
  }
  const entries = new Map((bank || []).map((entry) => [entry.id, entry.title]))
  const name = (map) => (key) => map.get(key) || 'a record no longer there'
  return {
    section: (ref) => sections.get(ref) || 'a section',
    placement: name(placements),
    entry: name(entries),
    bullet: (ref) => bullets.get(ref),
  }
}

function Operation({ op, index, checked, onToggle, at }) {
  const describe = OPERATIONS[op.op]
  const [verb, detail] = describe ? describe(op, at) : ['Change', op.op || 'something unrecognised']
  const before = op.bullet_ref ? at.bullet(op.bullet_ref) : null

  return (
    <li className="rounded border border-outline-variant bg-surface p-3">
      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 shrink-0 accent-primary"
          checked={checked}
          onChange={onToggle}
        />
        <span className="min-w-0 flex-1 space-y-2">
          <span className="block">
            <span className="font-mono text-data text-on-surface-variant">
              {String(index + 1).padStart(2, '0')} · {verb}
            </span>
            <span className="ml-2 text-on-surface">{detail}</span>
          </span>

          {op.op === 'RewriteBullet' && before ? (
            <>
              <span className="block">
                <span className="label-data block">Currently</span>
                <span className="mt-1 block text-on-surface-variant line-through decoration-error/40">
                  {before}
                </span>
              </span>
              <span className="block">
                <span className="label-data block">Change to</span>
                <span className="mt-1 block text-on-surface">{op.text}</span>
              </span>
            </>
          ) : null}

          {op.op !== 'RewriteBullet' && op.text ? (
            <span className="block text-on-surface">{op.text}</span>
          ) : null}
          {op.rationale ? <span className="block text-on-surface-variant">{op.rationale}</span> : null}
        </span>
      </label>
    </li>
  )
}

/**
 * Review a proposed set of changes before any of them touch the draft.
 *
 * Rewriting someone's resume without showing them the diff is the thing this
 * app refuses to do, so a tailoring run and a bank that has drifted both land
 * here as the same reviewable list, and only the boxes left ticked are applied.
 */
export default function ProposalReview({ proposal, body, bank, busy, onApply, onDismiss }) {
  const operations = proposal?.operations || []
  const [rejected, setRejected] = useState(() => new Set())
  const at = lookups(body, bank)

  const accepted = operations
    .map((op, index) => idOf(op, index))
    .filter((id) => !rejected.has(id))

  const toggle = (id) =>
    setRejected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  if (!operations.length) {
    return (
      <div className="space-y-3">
        <p className="text-on-surface-variant">
          {proposal?.summary || 'Claude found nothing worth changing in this draft.'}
        </p>
        <button type="button" className="btn" onClick={onDismiss} disabled={busy}>
          Close
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h2>{KIND_HEADING[proposal.kind] || 'Proposed changes'}</h2>
        {proposal.summary ? <p className="mt-1 text-on-surface-variant">{proposal.summary}</p> : null}
      </div>

      <p className="font-mono text-data text-on-surface-variant">
        Every change below only moves or rewords something already in your bank. Untick anything you
        do not want; the rest is applied in one go.
      </p>

      <ul className="space-y-2">
        {operations.map((op, index) => {
          const id = idOf(op, index)
          return (
            <Operation
              key={id}
              op={op}
              index={index}
              at={at}
              checked={!rejected.has(id)}
              onToggle={() => toggle(id)}
            />
          )
        })}
      </ul>

      <div className="flex flex-wrap items-center gap-3 border-t border-outline-variant pt-4">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !accepted.length}
          onClick={() => onApply(accepted)}
        >
          {busy ? 'Applying…' : `Apply ${accepted.length} of ${operations.length}`}
        </button>
        <button type="button" className="btn" onClick={onDismiss} disabled={busy}>
          Discard all
        </button>
      </div>
    </div>
  )
}

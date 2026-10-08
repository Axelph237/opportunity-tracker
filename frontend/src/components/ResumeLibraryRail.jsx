import { NavIcon, PlusIcon, StarIcon } from './icons'

/**
 * Every resume you have, composed or written. Width and framing are the
 * parent's business.
 *
 * Shared by both surfaces so the same list is on screen whichever one you are
 * looking at. A row is always a control; the page decides what opening it
 * means, because a draft nobody pushed has no document to show and a document
 * nobody composed has no canvas.
 */
export default function ResumeLibraryRail({ rows, selectedKey, onSelect, onCreate, busy }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-outline-variant px-3 py-2">
        <span className="label-data">Resumes</span>
        <button type="button" className="btn" onClick={onCreate} disabled={busy} title="New resume">
          <PlusIcon />
          New
        </button>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {rows.map((row) => {
          const selected = row.key === selectedKey
          const frame = `block w-full border-b border-outline-variant/60 px-3 py-2.5 text-left transition-colors ${
            selected
              ? 'border-l-2 border-l-primary bg-secondary-container pl-[10px] text-on-secondary-container'
              : 'border-l-2 border-l-transparent pl-[10px] hover:bg-surface-container-high'
          }`
          const title = (
            <span className="flex items-center gap-1.5">
              <span className="line-clamp-1 flex-1 text-on-surface">{row.name}</span>
              {row.composed ? (
                <NavIcon name="builder" className="h-3.5 w-3.5 shrink-0 text-on-surface-variant" />
              ) : null}
              {row.is_default ? <StarIcon className="h-3.5 w-3.5 shrink-0 text-primary" /> : null}
            </span>
          )
          const caption = row.pushed
            ? [row.linked_count ? `${row.linked_count} linked` : 'unlinked',
               row.has_pdf && !row.compile_ok ? 'errors' : null].filter(Boolean).join(' · ')
            : 'on the canvas, not pushed'

          return (
            <li key={row.key}>
              <button type="button" onClick={() => onSelect(row)} aria-current={selected}
                      className={frame} title={row.pushed ? undefined : 'Nothing pushed from this yet'}>
                {title}
                <span className="mt-0.5 block font-mono text-data text-on-surface-variant">
                  {caption}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

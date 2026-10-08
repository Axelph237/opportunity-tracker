import { ENTRY_KINDS } from './BankEntryForm'
import { AI_CALL_TITLE, AiSpark, EditIcon, PlusIcon } from './icons'

/** "Jun 2026 – Sep 2026", or whatever half of it the record actually has. */
export function entryDates(entry) {
  const end = entry.is_current ? 'Present' : entry.end_date
  if (entry.start_date && end) return `${entry.start_date} – ${end}`
  return entry.start_date || end || ''
}

function Entry({ entry, dragging, onEdit, onDragStart, onDragEnd }) {
  const dates = entryDates(entry)
  const caption = [entry.organization || entry.detail, dates].filter(Boolean).join(' · ')

  return (
    <li
      draggable
      onDragStart={(event) => {
        // Firefox will not start a drag at all unless some data is attached.
        event.dataTransfer?.setData('text/plain', `bank-entry:${entry.id}`)
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copy'
        onDragStart(entry)
      }}
      onDragEnd={onDragEnd}
      className={`group flex cursor-grab items-start gap-2 border-b border-l-2 border-b-outline-variant/60 py-2.5 pl-[10px] pr-3 transition-colors ${
        dragging
          ? 'border-l-primary bg-surface-container-high opacity-40'
          : 'border-l-transparent hover:border-l-primary hover:bg-surface-container-high'
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="line-clamp-2 font-medium text-on-surface">{entry.title}</div>
        <div className="mt-0.5 flex items-center gap-2 font-mono text-data text-on-surface-variant">
          <span className="min-w-0 truncate">{caption || '—'}</span>
          {entry.bullets?.length ? <span className="shrink-0">· {entry.bullets.length}</span> : null}
        </div>
      </div>
      <button
        type="button"
        aria-label={`Edit ${entry.title}`}
        title="Edit this record"
        className="mt-[2px] shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-primary focus-visible:opacity-100 group-hover:opacity-100"
        onClick={onEdit}
      >
        <EditIcon />
      </button>
    </li>
  )
}

/**
 * The repository everything on the canvas is composed from, grouped by kind.
 *
 * An empty bank is the wall in front of this whole feature, so it gets a real
 * explanation and the import button gets the primary treatment until there is
 * something to show.
 */
export default function BankRail({
  entries = [],
  loading,
  importing,
  draggingId,
  onImport,
  onCreate,
  onEdit,
  onDragStart,
  onDragEnd,
}) {
  const empty = !loading && !entries.length

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-outline-variant px-3 py-2">
        <span className="label-data">Experience bank</span>
        <button type="button" className="btn" onClick={() => onCreate()} title="Add a record by hand">
          <PlusIcon />
          New
        </button>
      </div>

      <div className="shrink-0 border-b border-outline-variant px-3 py-2">
        <button
          type="button"
          className={`btn w-full justify-center ${empty ? 'btn-primary' : ''}`}
          // The standing paragraph this replaced was three lines of the rail,
          // permanently, for a button most people press once.
          title={`Reads your current resume and proposes records to confirm. ${AI_CALL_TITLE}. Up to a minute.`}
          disabled={importing}
          onClick={onImport}
        >
          <AiSpark />
          {importing ? 'Reading your resume…' : 'Import from my resume'}
        </button>
      </div>

      <p id="bank-drag-hint" className="sr-only">
        Drag a record onto a section of the resume to add it.
      </p>

      <div aria-describedby="bank-drag-hint" className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <p className="px-3 py-4 font-mono text-data text-on-surface-variant">Loading…</p>
        ) : empty ? (
          <div className="space-y-3 px-3 py-6">
            <p className="text-on-surface-variant">
              Your experience bank is empty. Everything on the resume beside it is composed from
              this list, so there is nothing to build with yet.
            </p>
            <p className="text-on-surface-variant">
              Import from your resume above to fill it in one go, or add the first record yourself.
            </p>
            <button type="button" className="btn" onClick={() => onCreate()}>
              <PlusIcon />
              Add the first record
            </button>
          </div>
        ) : (
          ENTRY_KINDS.map(({ value, label }) => {
            const group = entries.filter((entry) => entry.kind === value)
            if (!group.length) return null
            return (
              <section key={value}>
                <h2 className="label-data sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-outline-variant bg-surface-container-low px-3 py-1.5">
                  <span>{label}</span>
                  <span className="flex items-center gap-2">
                    {/* Decoration. The list below already tells a screen reader
                        how many records are in the group. */}
                    <span aria-hidden="true">{group.length}</span>
                    <button
                      type="button"
                      // Not "add a {kind} record": the kinds start with
                      // vowels often enough that the article would be wrong.
                      aria-label={`Add a record to ${label}`}
                      title={`Add a record to ${label}`}
                      className="shrink-0 text-on-surface-variant transition-colors hover:text-primary"
                      onClick={() => onCreate(value)}
                    >
                      <PlusIcon className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </h2>
                <ul>
                  {group.map((entry) => (
                    <Entry
                      key={entry.id}
                      entry={entry}
                      dragging={draggingId === entry.id}
                      onEdit={() => onEdit(entry)}
                      onDragStart={onDragStart}
                      onDragEnd={onDragEnd}
                    />
                  ))}
                </ul>
              </section>
            )
          })
        )}
      </div>
    </div>
  )
}

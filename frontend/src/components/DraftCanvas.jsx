import { useEffect, useRef, useState } from 'react'
import HighlightedText from './HighlightedText'
import { TrashIcon } from './icons'
import { moved } from './reorder'

/**
 * uuid4 as hex, unique within the draft.
 *
 * Built from `getRandomValues` rather than `crypto.randomUUID`, which Node 18
 * does not have and install.sh still accepts Node 18.
 */
function newRef() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

// The draft body is a tree keyed by ref at every level, so every edit is one
// of these two moves against one list in it.
const mapByRef = (list, ref, update) => list.map((item) => (item.ref === ref ? update(item) : item))
const sortByRef = (list, refs) => refs.map((ref) => list.find((item) => item.ref === ref)).filter(Boolean)

const editSections = (body, update) => ({ ...body, sections: update(body.sections || []) })
const editSection = (body, sectionRef, update) =>
  editSections(body, (sections) => mapByRef(sections, sectionRef, update))
const editPlacement = (body, sectionRef, placementRef, update) =>
  editSection(body, sectionRef, (section) => ({
    ...section,
    placements: mapByRef(section.placements || [], placementRef, update),
  }))

/**
 * Drag-to-reorder a list the server owns.
 *
 * Not `useDragReorder`: that one writes the order to localStorage and
 * reconciles it against a fixed array of everything the app ships, and
 * neither is true of rows that live in the database. The event choreography
 * is copied from it exactly, because each rule in it is load-bearing.
 */
function useServerReorder(refs, onCommit) {
  // Null except during a drag. The list rearranges live under the pointer, so
  // the props order is the pre-drag arrangement, and abandoning a drag is
  // just throwing this away rather than restoring anything.
  const [preview, setPreview] = useState(null)
  const [dragging, setDragging] = useState(null)
  // `onDragEnd` closes over the render the drag began in, which is a dozen
  // `onDragEnter`s out of date by the time it fires.
  const latest = useRef(null)
  // The order as it stood when the drag began. `moved` returns the array it
  // was given when nothing would change, so comparing identity against this
  // is how a drag that ended where it started avoids writing to the server.
  const before = useRef(null)
  const dropped = useRef(false)

  const itemProps = (ref) => ({
    draggable: true,
    onDragStart: (event) => {
      // Bullets sit inside placements, which are draggable too. Without this
      // the placement starts dragging as well and both lists rearrange.
      event.stopPropagation()
      // Firefox will not start a drag at all unless some data is attached.
      event.dataTransfer?.setData('text/plain', ref)
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
      latest.current = refs
      before.current = refs
      dropped.current = false
      setPreview(refs)
      setDragging(ref)
    },
    // On enter rather than on over: `over` fires continuously while the
    // pointer sits still, and re-running the swap at that rate on rows of
    // unequal height makes the list flicker between two arrangements.
    onDragEnter: (event) => {
      if (dragging === null || dragging === ref) return
      event.stopPropagation()
      const current = latest.current
      const next = moved(current, dragging, current.indexOf(ref))
      // `moved` hands back the very array it was given when nothing would
      // change. Setting state anyway re-renders the list on every one of the
      // dozens of events a drag emits.
      if (next === current) return
      latest.current = next
      setPreview(next)
    },
    onDragOver: (event) => {
      // Not ours: let it bubble to the section, which takes bank records.
      if (dragging === null) return
      // A target that does not cancel `dragover` is not a drop target: the
      // browser shows the no-entry cursor and never fires `drop`.
      event.preventDefault()
      event.stopPropagation()
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
    },
    onDrop: (event) => {
      if (dragging === null) return
      event.preventDefault()
      event.stopPropagation()
      dropped.current = true
    },
    onDragEnd: () => {
      const final = latest.current
      const start = before.current
      latest.current = null
      before.current = null
      setDragging(null)
      if (dropped.current && final && final !== start) onCommit(final)
      // Escape, or a drop on something that did not want it. Clearing the
      // preview puts the list back to the order the props still hold.
      setPreview(null)
    },
  })

  const moveBy = (ref, delta) => {
    const next = moved(refs, ref, refs.indexOf(ref) + delta)
    if (next === refs) return false
    onCommit(next)
    return true
  }

  return { order: preview || refs, dragging, itemProps, moveBy }
}

/** Alt-modified, because a bare arrow key on a focused element already scrolls. */
const arrowMove = (ref, moveBy) => (event) => {
  if (!event.altKey) return
  const delta = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0
  if (delta && moveBy(ref, delta)) event.preventDefault()
}

function Bullet({ bullet, inline, terms, drifted, dragging, itemProps, moveBy, onRemove }) {
  const marker = drifted ? (
    <span
      title={`The bank now reads: ${drifted}`}
      className="shrink-0 rounded border border-tertiary/60 bg-tertiary/10 px-1.5 py-[1px] font-mono text-data text-tertiary"
    >
      drift
    </span>
  ) : null

  return (
    <li
      {...itemProps}
      tabIndex={0}
      onKeyDown={arrowMove(bullet.ref, moveBy)}
      className={`group/bullet flex cursor-grab items-start gap-2 rounded px-1 transition-colors hover:bg-surface-container-high ${
        inline ? 'border border-outline-variant py-[2px]' : 'py-0.5'
      } ${dragging ? 'opacity-40' : ''}`}
    >
      <span className={`min-w-0 flex-1 ${inline ? 'font-mono text-data' : ''}`}>
        <HighlightedText text={bullet.text} terms={terms} />
      </span>
      {marker}
      <button
        type="button"
        aria-label={`Remove “${bullet.text}”`}
        className="mt-[3px] shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-error focus-visible:opacity-100 group-hover/bullet:opacity-100"
        onClick={onRemove}
      >
        <TrashIcon className="h-3.5 w-3.5" />
      </button>
    </li>
  )
}

function Placement({ placement, inline, terms, bankText, focused, dragging, itemProps, moveBy, onChange, onRemove }) {
  const bullets = placement.bullets || []
  const refs = bullets.map((bullet) => bullet.ref)
  const byRef = new Map(bullets.map((bullet) => [bullet.ref, bullet]))
  const reorder = useServerReorder(refs, (next) =>
    onChange((current) => ({ ...current, bullets: sortByRef(current.bullets || [], next) })),
  )

  const caption = [placement.organization, placement.location, placement.dates]
    .filter(Boolean)
    .join(' · ')

  return (
    <li
      {...itemProps}
      data-placement={placement.ref}
      tabIndex={0}
      onKeyDown={arrowMove(placement.ref, moveBy)}
      className={`group/placement rounded border px-3 py-2 transition-colors ${
        focused ? 'border-primary ring-1 ring-primary' : 'border-outline-variant/60'
      } ${dragging ? 'opacity-40' : ''}`}
    >
      <div className="flex cursor-grab items-start gap-2">
        <div className="min-w-0 flex-1">
          <span className="text-on-surface">
            <HighlightedText text={placement.title} terms={terms} />
          </span>
          {caption ? (
            <div className="font-mono text-data text-on-surface-variant">{caption}</div>
          ) : null}
          {placement.detail ? (
            <div className="font-mono text-data text-on-surface-variant">
              <HighlightedText text={placement.detail} terms={terms} />
            </div>
          ) : null}
        </div>
        <button
          type="button"
          aria-label={`Remove ${placement.title} from this resume`}
          className="shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-error focus-visible:opacity-100 group-hover/placement:opacity-100"
          onClick={onRemove}
        >
          <TrashIcon />
        </button>
      </div>

      {bullets.length ? (
        <ul className={`mt-1.5 ${inline ? 'flex flex-wrap gap-1.5' : 'space-y-0.5'}`}>
          {reorder.order.map((ref) => {
            const bullet = byRef.get(ref)
            if (!bullet) return null
            const current = bankText.get(bullet.source_bullet_id)
            return (
              <Bullet
                key={ref}
                bullet={bullet}
                inline={inline}
                terms={terms}
                // The snapshot is what renders; this only says the pool it
                // came from has moved on since.
                drifted={current && bullet.source_text && current !== bullet.source_text ? current : null}
                dragging={reorder.dragging === ref}
                itemProps={reorder.itemProps(ref)}
                moveBy={reorder.moveBy}
                onRemove={() =>
                  onChange((currentPlacement) => ({
                    ...currentPlacement,
                    bullets: (currentPlacement.bullets || []).filter((item) => item.ref !== ref),
                  }))
                }
              />
            )
          })}
        </ul>
      ) : null}
    </li>
  )
}

function Section({ section, terms, bankText, focusedPlacement, accepting, onBody, onDropEntry }) {
  const [over, setOver] = useState(false)
  const placements = section.placements || []
  const refs = placements.map((placement) => placement.ref)
  const byRef = new Map(placements.map((placement) => [placement.ref, placement]))
  const inline = section.bullet_style === 'inline'

  const reorder = useServerReorder(refs, (next) =>
    onBody((body) =>
      editSection(body, section.ref, (current) => ({
        ...current,
        placements: sortByRef(current.placements || [], next),
      })),
    ),
  )

  return (
    <section
      onDragOver={(event) => {
        if (!accepting) return
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        if (!accepting) return
        event.preventDefault()
        // The canvas behind this takes the same drop and routes it to the
        // kind's default section. Letting it through would add the record twice.
        event.stopPropagation()
        setOver(false)
        onDropEntry(section.ref)
      }}
      className={`rounded border transition-colors ${
        over ? 'border-primary bg-primary/5' : 'border-outline-variant bg-surface'
      }`}
    >
      <header className="flex items-center gap-2 border-b border-outline-variant px-3 py-1.5">
        <input
          key={section.ref}
          // No width cap: the deck's advice is to rename a section to the ad's
          // own wording, and “Research and Project Experience” was clipped at 18rem.
          className="field label-data min-w-0 flex-1 bg-transparent"
          defaultValue={section.label}
          aria-label={`Rename the ${section.label} section`}
          onBlur={(event) => {
            const label = event.target.value.trim()
            if (!label || label === section.label) return
            onBody((body) => editSection(body, section.ref, (current) => ({ ...current, label })))
          }}
          onKeyDown={(event) => event.key === 'Enter' && event.target.blur()}
        />
        <span className="font-mono text-data text-on-surface-variant">{placements.length}</span>
        <button
          type="button"
          aria-label={`Remove the ${section.label} section`}
          className="shrink-0 text-on-surface-variant transition-colors hover:text-error"
          onClick={() =>
            onBody((body) => editSections(body, (sections) => sections.filter((item) => item.ref !== section.ref)))
          }
        >
          <TrashIcon />
        </button>
      </header>

      {placements.length ? (
        <ul className="space-y-1.5 p-2">
          {reorder.order.map((ref) => {
            const placement = byRef.get(ref)
            if (!placement) return null
            return (
              <Placement
                key={ref}
                placement={placement}
                inline={inline}
                terms={terms}
                bankText={bankText}
                focused={focusedPlacement === ref}
                dragging={reorder.dragging === ref}
                itemProps={reorder.itemProps(ref)}
                moveBy={reorder.moveBy}
                onChange={(update) => onBody((body) => editPlacement(body, section.ref, ref, update))}
                onRemove={() =>
                  onBody((body) =>
                    editSection(body, section.ref, (current) => ({
                      ...current,
                      placements: (current.placements || []).filter((item) => item.ref !== ref),
                    })),
                  )
                }
              />
            )
          })}
        </ul>
      ) : (
        <p className="px-3 py-4 text-center font-mono text-data text-on-surface-variant">
          Drop a record here
        </p>
      )}
    </section>
  )
}

/**
 * The resume being composed: sections, the records placed in them, and the
 * bullets inside those. Everything reorders by drag or by Alt and an arrow.
 *
 * Every edit replaces the whole body and hands it to `onChange`, which is what
 * the server stores. Nothing here is a reference back into the bank: a
 * placement carries its own copy of the text so that editing the bank later
 * cannot silently change a resume that has already gone out.
 */
export default function DraftCanvas({
  body,
  bank = [],
  terms = [],
  droppingEntry,
  focusedPlacement,
  onChange,
  onPlace,
}) {
  const root = useRef(null)
  const sections = body?.sections || []
  const bankText = new Map(
    bank.flatMap((entry) => (entry.bullets || []).map((bullet) => [bullet.id, bullet.text])),
  )

  const onBody = (update) => onChange(update({ ...body, sections }))

  // Jumping here from a keyword chip in the coverage panel.
  useEffect(() => {
    if (!focusedPlacement) return
    root.current
      ?.querySelector(`[data-placement="${focusedPlacement}"]`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focusedPlacement])

  /**
   * `sectionRef` is null when the record was dropped on the canvas rather than
   * on a section, which the server reads as "file it where its kind belongs".
   *
   * The snapshot itself is cut server-side. Building it here was a second
   * copy of the layout registry, the date formatting and the provenance
   * rules, and it had already drifted: it filed an award under "Honors" where
   * the registry says "Honors and Awards".
   */
  const dropEntry = (sectionRef) => {
    if (droppingEntry) onPlace(droppingEntry.id, sectionRef)
  }

  const addSection = () =>
    onBody((current) =>
      editSections(current, (list) => [
        ...list,
        { ref: newRef(), label: 'New section', bullet_style: 'bullets', placements: [] },
      ]),
    )

  return (
    <div className="flex h-full min-h-0 flex-col">
      <p id="canvas-reorder-hint" className="sr-only">
        Sections, records and bullets can be reordered: drag one into place, or focus it and press
        Alt with the up or down arrow key.
      </p>

      <div
        ref={root}
        aria-describedby="canvas-reorder-hint"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4"
        onDragOver={(event) => droppingEntry && event.preventDefault()}
        onDrop={(event) => {
          if (!droppingEntry) return
          event.preventDefault()
          dropEntry(null)
        }}
      >
        {sections.length ? (
          sections.map((section) => (
            <Section
              key={section.ref}
              section={section}
              terms={terms}
              bankText={bankText}
              focusedPlacement={focusedPlacement}
              accepting={Boolean(droppingEntry)}
              onBody={onBody}
              onDropEntry={dropEntry}
            />
          ))
        ) : (
          <div className="rounded border border-dashed border-outline-variant px-6 py-12 text-center">
            <p className="text-on-surface-variant">
              Nothing in this resume yet. Drag a record over from your bank and it will start a
              section for you.
            </p>
          </div>
        )}

        <button type="button" className="btn" onClick={addSection}>
          Add a section
        </button>
      </div>
    </div>
  )
}

import { useState } from 'react'
import ContactBlock from './ContactBlock'
import HighlightedText from './HighlightedText'
import { DragHandleIcon, TrashIcon } from './icons'
import { arrowMove, useServerReorder } from './useServerReorder'

/**
 * The composable regions of a resume, as the document defines them.
 *
 * Unlike the draft canvas this replaces, the structure here is not the
 * composer's to invent. A slot exists because the source says so, so there is
 * no adding, renaming or removing one from this side. What the composer owns
 * is the order and the contents of what sits inside each.
 *
 * A block the parser could not read is shown as its own source and can still
 * be dragged. That is the point of it: the composer does not have to
 * understand a line to avoid destroying it.
 */

const keyOf = (block, index) => `${index}:${block.kind}:${(block.raw || '').slice(0, 24)}`

function Block({ block, index, anchor, terms, dragging, itemProps, moveBy, onRemove }) {
  // The readable form, not the LaTeX. A canvas showing `38\%` is showing
  // the markup rather than the resume.
  const [org, dates, title, where] = block.args_text?.length ? block.args_text : block.args || []
  const bullets = block.bullets_text?.length ? block.bullets_text : block.bullets || []
  const opaque = block.kind !== 'entry'

  return (
    <li
      {...itemProps}
      data-block={anchor}
      tabIndex={0}
      onKeyDown={arrowMove(index, moveBy)}
      className={`group/block rounded border px-3 py-2 transition-colors ${
        opaque ? 'border-dashed border-outline-variant' : 'border-outline-variant/60'
      } ${dragging ? 'opacity-40' : ''}`}
    >
      <div className="flex items-start gap-2">
        <span className="mt-[3px] shrink-0 cursor-grab text-on-surface-variant" aria-hidden="true">
          <DragHandleIcon />
        </span>
        <div className="min-w-0 flex-1">
          {opaque ? (
            <>
              <div className="label-data">Your own LaTeX</div>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap font-code text-data text-on-surface-variant">
                {(block.raw || '').trim()}
              </pre>
            </>
          ) : (
            <>
              <span className="text-on-surface">
                <HighlightedText text={title || org || ''} terms={terms} />
              </span>
              {[org, where, dates].filter(Boolean).length ? (
                <div className="font-mono text-data text-on-surface-variant">
                  {[title ? org : null, where, dates].filter(Boolean).join(' · ')}
                </div>
              ) : null}
              {bullets.length ? (
                <ul className="mt-1.5 space-y-0.5">
                  {bullets.map((text, at) => (
                    <li key={at} className="text-on-surface-variant">
                      <HighlightedText text={text} terms={terms} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </div>
        <button
          type="button"
          aria-label={`Remove ${opaque ? 'this block' : title || org} from this resume`}
          className="shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-error focus-visible:opacity-100 group-hover/block:opacity-100"
          onClick={onRemove}
        >
          <TrashIcon />
        </button>
      </div>
    </li>
  )
}

function Slot({ slot, terms, accepting, onPlace, onBlocks }) {
  const [over, setOver] = useState(false)
  const blocks = slot.blocks || []
  const order = blocks.map((_, index) => index)
  const reorder = useServerReorder(order, (next) => onBlocks(next.map((at) => blocks[at])))

  return (
    <section
      data-slot={slot.key}
      onDragOver={(event) => {
        if (!accepting) return
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        if (!accepting) return
        event.preventDefault()
        event.stopPropagation()
        setOver(false)
        onPlace(blocks.length)
      }}
      className={`rounded border transition-colors ${
        over ? 'border-primary bg-primary/5' : 'border-outline-variant bg-surface-container'
      }`}
    >
      <header className="flex items-center gap-2 border-b border-outline-variant px-3 py-1.5">
        {/* Named by the document, so there is nothing to rename here. */}
        <span className="label-data min-w-0 flex-1 truncate">{slot.name}</span>
        <span className="font-mono text-data text-on-surface-variant">{blocks.length}</span>
      </header>

      {blocks.length ? (
        <ul className="space-y-1.5 p-2">
          {reorder.order.map((at) => {
            const block = blocks[at]
            if (!block) return null
            return (
              <Block
                key={keyOf(block, at)}
                anchor={`${slot.key}:${at}`}
                block={block}
                index={at}
                terms={terms}
                dragging={reorder.dragging === at}
                itemProps={reorder.itemProps(at)}
                moveBy={reorder.moveBy}
                onRemove={() => onBlocks(blocks.filter((_, i) => i !== at))}
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

export default function SlotCanvas({
  slots = [],
  terms = [],
  droppingEntry,
  error,
  contact,
  onPlace,
  onBlocks,
  onEditContact,
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <p id="slot-reorder-hint" className="sr-only">
        Blocks can be reordered: drag one into place, or focus it and press Alt with the up or
        down arrow key.
      </p>
      <div
        aria-describedby="slot-reorder-hint"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4"
      >
        <ContactBlock contact={contact} onEdit={onEditContact} />

        {error ? (
          <div className="rounded border border-error/60 bg-error/10 px-4 py-3 text-error">
            {error}
          </div>
        ) : slots.length ? (
          slots.map((slot) => (
            <Slot
              key={slot.key}
              slot={slot}
              terms={terms}
              accepting={Boolean(droppingEntry)}
              onPlace={(position) => onPlace(slot.key, position)}
              onBlocks={(blocks) => onBlocks(slot.key, blocks)}
            />
          ))
        ) : (
          <div className="rounded border border-dashed border-outline-variant px-6 py-12 text-center">
            <p className="text-on-surface-variant">
              This resume has no slots yet. Mark a region of its source with slot comments and it
              will show up here, ready to compose into.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

import { useRef, useState } from 'react'
import { moved } from './reorder'

/**
 * Drag-to-reorder a list the server owns.
 *
 * Not `useDragReorder`: that one writes the order to localStorage and
 * reconciles it against a fixed array of everything the app ships, and
 * neither is true of rows that live in the database. The event choreography
 * is copied from it exactly, because each rule in it is load-bearing.
 */
export function useServerReorder(refs, onCommit) {
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
export const arrowMove = (ref, moveBy) => (event) => {
  if (!event.altKey) return
  const delta = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0
  if (delta && moveBy(ref, delta)) event.preventDefault()
}

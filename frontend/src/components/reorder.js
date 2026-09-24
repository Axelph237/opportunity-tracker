import { useCallback, useEffect, useRef, useState } from 'react'
import { STORAGE_PREFIX } from './Resizable'

/**
 * Reconcile a remembered order against the list the app actually ships.
 *
 * A saved order outlives the release that wrote it: it can name something that
 * has since been removed, and it will not name anything added after it was
 * written. Both have to be survivable, and the second is the one that matters
 * — without it, shipping a new section would hide it from everyone who had
 * ever rearranged their sidebar, and the only cure would be clearing browser
 * storage.
 *
 * The rule is the least surprising one: whatever was remembered keeps exactly
 * the order it was remembered in, and anything new goes on the end. Slotting a
 * new section in at its shipped index instead would read better on paper, but
 * it means an upgrade silently rearranges a layout the user chose by hand.
 */
export function reconcile(saved, defaults) {
  const known = new Set(defaults)
  const kept = []
  for (const id of Array.isArray(saved) ? saved : []) {
    if (known.has(id) && !kept.includes(id)) kept.push(id)
  }
  return [...kept, ...defaults.filter((id) => !kept.includes(id))]
}

/**
 * `ids` with `id` lifted out and put back at `toIndex`.
 *
 * Returns the array it was given when nothing would change. Dragging fires
 * these by the dozen, and an identical-but-new array would re-render the whole
 * sidebar on every one of them.
 */
export function moved(ids, id, toIndex) {
  const from = ids.indexOf(id)
  if (from === -1 || from === toIndex || toIndex < 0 || toIndex >= ids.length) return ids
  const next = [...ids]
  next.splice(from, 1)
  next.splice(toIndex, 0, id)
  return next
}

/**
 * A drag-to-reorder list, remembered across sessions.
 *
 * Stored in localStorage alongside the pane sizes, for the same reason: the
 * arrangement of one person's screen on one machine is not account state, and
 * a layout that had to round-trip the API would visibly shuffle itself on
 * every page load.
 *
 * `defaults` must be a stable array — define it at module scope, not inline in
 * a component, or every render resets the identity the callbacks depend on.
 *
 * Returns the current order, props to spread onto each item, and `moveBy` for
 * a keyboard path, since a drag is unreachable without a pointer.
 */
export function useDragReorder(key, defaults) {
  const storageKey = `${STORAGE_PREFIX}.${key}`

  // Read synchronously, so a reordered sidebar never renders in the default
  // order for a frame before correcting itself.
  const [order, setOrder] = useState(() => {
    try {
      return reconcile(JSON.parse(localStorage.getItem(storageKey)), defaults)
    } catch {
      /* private mode, no storage, or a value that is not JSON */
      return [...defaults]
    }
  })
  const [dragging, setDragging] = useState(null)

  // The order as it stands right now, for the drag handlers: `onDragEnd` needs
  // the arrangement built up by the `onDragEnter`s before it, and reading
  // `order` from the closure would give it the one from the render the drag
  // started in.
  const latest = useRef(order)
  useEffect(() => {
    latest.current = order
  }, [order])

  // Where the list stood when the drag began, to put back if it is abandoned.
  const before = useRef(null)
  const dropped = useRef(false)

  const save = useCallback(
    (next) => {
      setOrder(next)
      try {
        localStorage.setItem(storageKey, JSON.stringify(next))
      } catch {
        /* not remembering it is not worth failing the drag over */
      }
    },
    [storageKey],
  )

  const moveBy = useCallback((id, delta) => {
    const current = latest.current
    const next = moved(current, id, current.indexOf(id) + delta)
    if (next === current) return false
    latest.current = next
    save(next)
    return true
  }, [save])

  const itemProps = useCallback(
    (id) => ({
      draggable: true,
      onDragStart: (event) => {
        // Firefox will not start a drag at all unless some data is attached.
        event.dataTransfer?.setData('text/plain', String(id))
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
        before.current = latest.current
        dropped.current = false
        setDragging(id)
      },
      // Reordering on enter rather than on over: `over` fires continuously
      // while the pointer sits still, and re-running the swap at that rate on
      // rows of unequal height makes the list flicker between two states.
      onDragEnter: () => {
        if (dragging === null || dragging === id) return
        setOrder((current) => moved(current, dragging, current.indexOf(id)))
      },
      // A target that does not cancel `dragover` is not a drop target: the
      // browser shows the no-entry cursor and never fires `drop`.
      onDragOver: (event) => {
        if (dragging === null) return
        event.preventDefault()
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
      },
      onDrop: (event) => {
        event.preventDefault()
        dropped.current = true
      },
      onDragEnd: () => {
        // Escape, or a drop somewhere that did not want it. The list has been
        // rearranging under the pointer all along, so abandoning the drag has
        // to undo that rather than just stop.
        if (dropped.current) save(latest.current)
        else if (before.current) setOrder(before.current)
        before.current = null
        setDragging(null)
      },
    }),
    [dragging, save],
  )

  return { order, dragging, itemProps, moveBy }
}

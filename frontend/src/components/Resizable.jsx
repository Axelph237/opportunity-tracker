import { useCallback, useEffect, useRef, useState } from 'react'

// Shared with the reorder hook, so every remembered piece of layout — pane
// sizes, section order — lives under one namespace and can be cleared as one.
export const STORAGE_PREFIX = 'opportunity-tracker.layout'

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

/**
 * A panel dimension the user can drag, remembered across sessions.
 *
 * Stored per key in localStorage rather than in the database: it is a property
 * of this screen on this machine, not of the account, and a layout that had to
 * round-trip the API would visibly snap into place on every page load.
 *
 * The stored value is clamped on read, so tightening a minimum in a later
 * version cannot leave someone stuck with a pane too small to use.
 */
export function usePanelSize(key, initial, { min = 120, max = 2000 } = {}) {
  const storageKey = `${STORAGE_PREFIX}.${key}`

  const [size, setSize] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(storageKey))
      if (Number.isFinite(saved) && saved > 0) return clamp(saved, min, max)
    } catch {
      /* private mode, or no storage at all */
    }
    return clamp(initial, min, max)
  })

  const resize = useCallback(
    (next) => {
      const clamped = clamp(next, min, max)
      setSize(clamped)
      try {
        localStorage.setItem(storageKey, String(Math.round(clamped)))
      } catch {
        /* not being able to remember it is not worth failing the drag over */
      }
    },
    [storageKey, min, max],
  )

  const reset = useCallback(() => {
    setSize(clamp(initial, min, max))
    try {
      localStorage.removeItem(storageKey)
    } catch {
      /* nothing to clean up */
    }
  }, [storageKey, initial, min, max])

  return [size, resize, reset]
}

/**
 * The draggable line between two panes.
 *
 * `orientation` describes the handle, following the ARIA separator convention:
 * a `vertical` handle is the upright bar between two side-by-side panes and
 * moves horizontally. `invert` is for a pane that sits to the right of (or
 * below) its handle, where dragging towards the pane has to shrink it.
 *
 * Pointer events rather than mouse events, so a trackpad, a touchscreen and a
 * stylus all work; pointer capture keeps the drag alive when the cursor
 * outruns the handle, which it always does.
 */
export function ResizeHandle({
  orientation = 'vertical',
  value,
  onChange,
  min = 120,
  max = 2000,
  invert = false,
  label,
  onReset,
  step = 16,
}) {
  const drag = useRef(null)
  const [dragging, setDragging] = useState(false)
  const vertical = orientation === 'vertical'

  // While dragging, the pointer sweeps across text in both panes and the
  // browser happily selects all of it. Suppressed on the body so the rule
  // covers whatever the pointer happens to be over.
  useEffect(() => {
    if (!dragging) return undefined
    const previous = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    document.body.style.cursor = vertical ? 'col-resize' : 'row-resize'
    return () => {
      document.body.style.userSelect = previous
      document.body.style.cursor = ''
    }
  }, [dragging, vertical])

  const begin = (event) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = { from: vertical ? event.clientX : event.clientY, value }
    setDragging(true)
  }

  const move = (event) => {
    if (!drag.current) return
    const now = vertical ? event.clientX : event.clientY
    const delta = (now - drag.current.from) * (invert ? -1 : 1)
    onChange(clamp(drag.current.value + delta, min, max))
  }

  const end = (event) => {
    if (!drag.current) return
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    drag.current = null
    setDragging(false)
  }

  const onKeyDown = (event) => {
    const decrease = vertical ? 'ArrowLeft' : 'ArrowUp'
    const increase = vertical ? 'ArrowRight' : 'ArrowDown'
    if (event.key === decrease) {
      event.preventDefault()
      onChange(clamp(value + (invert ? step : -step), min, max))
    } else if (event.key === increase) {
      event.preventDefault()
      onChange(clamp(value + (invert ? -step : step), min, max))
    } else if (event.key === 'Home') {
      event.preventDefault()
      onChange(min)
    } else if (event.key === 'End') {
      event.preventDefault()
      onChange(max)
    }
  }

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onKeyDown={onKeyDown}
      // Double-click to put it back, the convention every split view uses.
      onDoubleClick={onReset}
      className={`group relative shrink-0 ${
        vertical ? 'w-px cursor-col-resize' : 'h-px cursor-row-resize'
      } bg-outline-variant focus:outline-none`}
    >
      {/* The visible line is a hairline, but a hairline is not a hit target.
          This pad widens the grab area without moving anything around it. */}
      <span
        aria-hidden="true"
        className={`absolute z-20 transition-colors ${
          vertical ? '-left-1 -right-1 inset-y-0' : '-top-1 -bottom-1 inset-x-0'
        } ${dragging ? 'bg-primary' : 'bg-transparent group-hover:bg-primary/40 group-focus:bg-primary'}`}
      />
    </div>
  )
}

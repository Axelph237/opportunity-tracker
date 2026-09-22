import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * A small anchored panel hung off an icon button — the composer's attachment and
 * option menus. Distinct from Dropdown, which picks one value from a list; this
 * holds arbitrary content.
 *
 * Closes on outside click and on Escape. Escape is stopped here so it dismisses
 * only this layer and not the panel or dialog behind it.
 */
export default function Popover({
  label,
  icon,
  badge,
  align = 'left',
  disabled,
  panelClassName = 'w-80',
  children,
}) {
  const [open, setOpen] = useState(false)
  const [dropUp, setDropUp] = useState(true)
  const rootRef = useRef(null)
  const triggerRef = useRef(null)

  const close = useCallback((refocus = true) => {
    setOpen(false)
    if (refocus) triggerRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown, true)
    }
  }, [open, close])

  // The composer sits at the bottom of the page, so these normally open upward.
  useLayoutEffect(() => {
    if (!open) return
    const box = triggerRef.current?.getBoundingClientRect()
    if (box) setDropUp(window.innerHeight - box.bottom < 320)
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex items-center gap-1.5 rounded px-2 py-1 transition-colors disabled:opacity-45 ${
          open
            ? 'bg-surface-container-high text-on-surface'
            : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
        }`}
      >
        {icon}
        {badge ? <span className="font-mono text-data text-primary">{badge}</span> : null}
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label={label}
          className={`absolute z-40 rounded border border-outline-variant bg-surface-container p-1.5 shadow-lg shadow-black/40 animate-fade-in ${
            dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          } ${align === 'right' ? 'right-0' : 'left-0'} ${panelClassName}`}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>
      ) : null}
    </div>
  )
}

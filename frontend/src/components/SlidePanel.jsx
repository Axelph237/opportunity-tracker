import { useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** Right-hand detail panel. Slides in on open; Escape closes it. */
export default function SlidePanel({ open, onClose, title, subtitle, children, footer }) {
  const panel = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        // A confirmation sits on top of this panel; Escape belongs to it, and
        // closing the panel underneath would discard whatever it is showing.
        if (document.body.dataset.confirmOpen === 'true') return
        onClose()
        return
      }
      // Keep Tab inside the panel. It declares aria-modal and the scrim blocks
      // the page behind it, so focus escaping into the nav and the table
      // underneath leaves the keyboard somewhere the mouse cannot follow.
      if (event.key !== 'Tab' || document.body.dataset.confirmOpen === 'true') return
      const focusable = panel.current?.querySelectorAll(FOCUSABLE)
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (!panel.current.contains(active)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div
        className="fixed inset-0 z-30 bg-scrim/50 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed right-0 top-0 z-40 flex h-full w-full max-w-xl flex-col border-l border-outline-variant bg-surface-container animate-slide-in"
      >
        <header className="flex items-start justify-between gap-4 border-b border-outline-variant px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate">{title}</h2>
            {subtitle ? <p className="mt-1 truncate text-on-surface-variant">{subtitle}</p> : null}
          </div>
          <button type="button" className="btn shrink-0" onClick={onClose} aria-label="Close panel">
            Close
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

        {footer ? <footer className="border-t border-outline-variant px-6 py-4">{footer}</footer> : null}
      </aside>
    </>
  )
}

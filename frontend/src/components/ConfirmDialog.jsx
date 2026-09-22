import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { TrashIcon, WarnIcon } from './icons'

const STORAGE_KEY = 'opportunity-tracker.suppressed-confirms'

/** Human names for the confirmation kinds, so Settings can list what is suppressed. */
export const CONFIRM_KINDS = {
  'delete-opportunity': 'Deleting a listing',
  'delete-source': 'Deleting a source',
  'delete-application': 'Removing an application from the pipeline',
  'walten-undo': 'Undoing an agent change back to a message',
}

function readSuppressed() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return [] // corrupt or unavailable storage just means "ask every time"
  }
}

function writeSuppressed(keys) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  } catch {
    /* private mode; the choice simply will not persist */
  }
  window.dispatchEvent(new Event('confirm-prefs-changed'))
}

export function suppressedConfirms() {
  return readSuppressed()
}

export function clearSuppressedConfirm(key) {
  writeSuppressed(readSuppressed().filter((entry) => entry !== key))
}

export function clearAllSuppressedConfirms() {
  writeSuppressed([])
}

const ConfirmContext = createContext(null)

/**
 * `window.confirm` replacement. The native dialog cannot be styled, blocks the
 * whole tab, and offers no way to stop asking — so deleting ten junk listings
 * meant ten identical OS popups.
 *
 * `useConfirm()` returns an async function resolving to true/false:
 *
 *   if (!(await confirm({ key: 'delete-source', title: 'Delete this source?' }))) return
 *
 * When a request carries a `key` and the user has ticked "Do not ask again" for
 * it, the promise resolves true straight away without showing anything. Those
 * choices are listed and reversible in Settings.
 */
export function ConfirmProvider({ children }) {
  const [request, setRequest] = useState(null)
  const [remember, setRemember] = useState(false)
  const resolver = useRef(null)
  const cancelButton = useRef(null)
  const dialogRef = useRef(null)

  const confirm = useCallback((options = {}) => {
    if (options.key && readSuppressed().includes(options.key)) return Promise.resolve(true)
    setRemember(false)
    setRequest(options)
    return new Promise((resolve) => {
      resolver.current = resolve
    })
  }, [])

  const settle = useCallback(
    (result) => {
      if (result && remember && request?.key) {
        writeSuppressed([...new Set([...readSuppressed(), request.key])])
      }
      resolver.current?.(result)
      resolver.current = null
      setRequest(null)
      setRemember(false)
    },
    [remember, request],
  )

  useEffect(() => {
    if (!request) return undefined
    document.body.dataset.confirmOpen = 'true'

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        // Captured before any SlidePanel underneath sees it: Escape dismisses the
        // topmost layer only.
        event.stopImmediatePropagation()
        settle(false)
        return
      }
      // Keep Tab inside the dialog; there is nothing useful behind it.
      if (event.key !== 'Tab') return
      const focusable = dialogRef.current?.querySelectorAll('button, input, [href], [tabindex]:not([tabindex="-1"])')
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', onKeyDown, true)
    // Focus Cancel, never the destructive button: a stray Enter or Space arriving
    // right after the dialog opens must not delete anything. Enter is deliberately
    // not bound globally for the same reason — it only activates what is focused.
    cancelButton.current?.focus()
    return () => {
      delete document.body.dataset.confirmOpen
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [request, settle])

  const value = useMemo(() => ({ confirm }), [confirm])
  const danger = request?.tone !== 'neutral'

  return (
    <ConfirmContext.Provider value={value}>
      {children}

      {request ? (
        <>
          <div className="fixed inset-0 z-50 bg-scrim/60 animate-fade-in" onClick={() => settle(false)} aria-hidden="true" />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            ref={dialogRef}
            className="fixed left-1/2 top-1/2 z-50 w-[min(32rem,calc(100vw-3rem))] -translate-x-1/2 -translate-y-1/2 rounded border border-outline-variant bg-surface-container shadow-2xl shadow-black/50 animate-fade-in"
          >
            <div className="flex items-start gap-3 border-b border-outline-variant px-5 py-4">
              <span className={danger ? 'mt-[2px] text-error' : 'mt-[2px] text-primary'}>
                {danger ? <TrashIcon className="h-5 w-5" /> : <WarnIcon className="h-5 w-5" />}
              </span>
              <div className="min-w-0">
                <h2 id="confirm-title">{request.title}</h2>
                {request.body ? <div className="mt-2 text-on-surface-variant">{request.body}</div> : null}
              </div>
            </div>

            <div className="space-y-4 px-5 py-4">
              {request.key ? (
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 accent-primary"
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                  />
                  <span>
                    <span className="text-on-surface">Do not ask again</span>
                    <span className="mt-1 block font-mono text-data text-on-surface-variant">
                      {CONFIRM_KINDS[request.key] || request.key} · reversible in Settings
                    </span>
                  </span>
                </label>
              ) : null}

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => settle(true)}
                  className={`btn ${danger ? 'border-error bg-error/15 text-error hover:border-error hover:bg-error/25 hover:text-error' : 'btn-primary'}`}
                >
                  {request.confirmLabel || 'Confirm'}
                </button>
                <button ref={cancelButton} type="button" className="btn" onClick={() => settle(false)}>
                  {request.cancelLabel || 'Cancel'}
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </ConfirmContext.Provider>
  )
}

export function useConfirm() {
  const context = useContext(ConfirmContext)
  if (!context) throw new Error('useConfirm must be used inside a ConfirmProvider')
  return context.confirm
}

/** Live list of suppressed confirmation keys, for the Settings panel. */
export function useSuppressedConfirms() {
  const [keys, setKeys] = useState(readSuppressed)
  useEffect(() => {
    const sync = () => setKeys(readSuppressed())
    window.addEventListener('confirm-prefs-changed', sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener('confirm-prefs-changed', sync)
      window.removeEventListener('storage', sync)
    }
  }, [])
  return keys
}

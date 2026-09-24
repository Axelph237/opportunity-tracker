import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { MinusIcon, PlusIcon } from './icons'

// Fit-to-width is 1. The floor is low enough to see a whole page at once, the
// ceiling high enough to check kerning on a 9pt footnote.
const ZOOM = { min: 0.4, max: 4, step: 0.25 }
const PAGE_GAP = 12

const clamp = (value) => Math.min(Math.max(value, ZOOM.min), ZOOM.max)

/**
 * pdf.js is ~350 KB gzipped and only this page needs it, so it is imported on
 * demand — Vite splits it into its own chunk and the rest of the app never
 * pays for it. Cached after the first call.
 */
let pdfjsPromise = null
function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import('pdfjs-dist').then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'pdfjs-dist/build/pdf.worker.min.mjs',
        import.meta.url,
      ).href
      return pdfjs
    })
  }
  return pdfjsPromise
}

/**
 * The rendered resume, drawn by us rather than by the browser's PDF plugin.
 *
 * The plugin's own viewer cannot be driven from the page — its scroll position
 * is inside a closed shadow root — so dragging to pan, and keeping your place
 * across a re-render, are only possible once the pages are our own canvases.
 */
export default function PdfPreview({ url, label = 'Resume preview' }) {
  const scroller = useRef(null)
  const canvases = useRef([])
  const drag = useRef(null)
  // Where the user was looking, so a re-render does not throw them back to the
  // top of page one every time they stop typing.
  const anchor = useRef({ top: 0, left: 0 })

  const [pages, setPages] = useState([])
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(0)
  const [panning, setPanning] = useState(false)
  const [error, setError] = useState(null)

  // ----------------------------------------------------------------- loading

  useEffect(() => {
    let cancelled = false
    let task = null

    ;(async () => {
      try {
        const pdfjs = await loadPdfjs()
        if (cancelled) return
        task = pdfjs.getDocument({ url })
        const doc = await task.promise
        if (cancelled) {
          doc.destroy()
          return
        }
        const loaded = await Promise.all(
          Array.from({ length: doc.numPages }, (_, index) => doc.getPage(index + 1)),
        )
        if (cancelled) {
          doc.destroy()
          return
        }
        setPages(loaded)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err?.message || 'Could not read the rendered PDF.')
      }
    })()

    return () => {
      cancelled = true
      task?.destroy?.()
    }
  }, [url])

  // Remember the scroll offset before each reload so it can be put back.
  useEffect(() => {
    const element = scroller.current
    return () => {
      if (element) anchor.current = { top: element.scrollTop, left: element.scrollLeft }
    }
  }, [url])

  // ----------------------------------------------------------- measuring

  useLayoutEffect(() => {
    const element = scroller.current
    if (!element) return undefined
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])

  // ------------------------------------------------------------- rendering

  useEffect(() => {
    if (!pages.length || !width) return undefined
    // Device pixels, not CSS pixels: a canvas sized in CSS pixels on a retina
    // display renders the text at half resolution and looks soft.
    const dpr = window.devicePixelRatio || 1
    const tasks = []
    let cancelled = false

    pages.forEach((page, index) => {
      const canvas = canvases.current[index]
      if (!canvas) return
      const natural = page.getViewport({ scale: 1 })
      const fit = (width - PAGE_GAP * 2) / natural.width
      const viewport = page.getViewport({ scale: fit * zoom * dpr })

      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      canvas.style.width = `${Math.floor(viewport.width / dpr)}px`
      canvas.style.height = `${Math.floor(viewport.height / dpr)}px`

      const task = page.render({
        canvas,
        canvasContext: canvas.getContext('2d'),
        viewport,
      })
      tasks.push(task)
      // A cancelled render is the normal result of typing while one is in
      // flight, not something worth reporting.
      task.promise.catch(() => {})
    })

    // Restore the reading position once the pages have their real height.
    const element = scroller.current
    if (element && (anchor.current.top || anchor.current.left)) {
      requestAnimationFrame(() => {
        if (cancelled) return
        element.scrollTop = anchor.current.top
        element.scrollLeft = anchor.current.left
      })
    }

    return () => {
      cancelled = true
      tasks.forEach((task) => task.cancel())
    }
  }, [pages, zoom, width])

  // ---------------------------------------------------------------- panning

  const onPointerDown = (event) => {
    // Left button only; a right-click belongs to the context menu.
    if (event.button !== 0) return
    const element = scroller.current
    if (!element) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      top: element.scrollTop,
      left: element.scrollLeft,
    }
    setPanning(true)
  }

  const onPointerMove = (event) => {
    const element = scroller.current
    if (!drag.current || !element) return
    // The page follows the cursor, so the scroll offset moves against it.
    element.scrollTop = drag.current.top - (event.clientY - drag.current.y)
    element.scrollLeft = drag.current.left - (event.clientX - drag.current.x)
  }

  const endPan = (event) => {
    if (!drag.current) return
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    drag.current = null
    setPanning(false)
    const element = scroller.current
    if (element) anchor.current = { top: element.scrollTop, left: element.scrollLeft }
  }

  // Ctrl/Cmd + wheel zooms, as it does everywhere else; a plain wheel scrolls.
  const onWheel = useCallback((event) => {
    if (!event.ctrlKey && !event.metaKey) return
    event.preventDefault()
    setZoom((current) => clamp(current - Math.sign(event.deltaY) * 0.1))
  }, [])

  useEffect(() => {
    const element = scroller.current
    if (!element) return undefined
    // Non-passive, or preventDefault cannot stop the browser page-zooming.
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [onWheel])

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-on-surface-variant">
        {error}
      </div>
    )
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div
        ref={scroller}
        data-testid="pdf-scroller"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
        className={`min-h-0 flex-1 overflow-auto overscroll-contain bg-surface-container-lowest ${
          panning ? 'cursor-grabbing select-none' : 'cursor-grab'
        }`}
      >
        {/* `w-max min-w-full` is what makes zooming usable. Centring a flex
            item wider than its scroll container pushes the overflow off the
            left, where scrollLeft 0 is already the end of the scroll range and
            nothing can bring it back. Letting this column grow to the widest
            page means the overflow is all on the right, where it is reachable;
            the min-width keeps a page narrower than the pane centred. */}
        <div className="flex w-max min-w-full flex-col items-center gap-3 p-3">
          {pages.map((page, index) => (
            <canvas
              key={page.pageNumber}
              ref={(node) => {
                canvases.current[index] = node
              }}
              role="img"
              aria-label={`${label}, page ${page.pageNumber} of ${pages.length}`}
              // The pointer belongs to the scroller so a drag that starts on a
              // page still pans, instead of being swallowed here.
              className="pointer-events-none block bg-white shadow-lg shadow-black/30"
            />
          ))}
          {!pages.length ? (
            <p className="py-10 font-mono text-data text-on-surface-variant">Loading preview…</p>
          ) : null}
        </div>
      </div>

      {pages.length ? (
        <div className="pointer-events-none absolute bottom-3 right-3 flex items-center gap-1 rounded border border-outline-variant bg-surface-container/90 p-1 shadow-lg shadow-black/30 backdrop-blur">
          <button
            type="button"
            aria-label="Zoom out"
            title="Zoom out"
            disabled={zoom <= ZOOM.min}
            onClick={() => setZoom((current) => clamp(current - ZOOM.step))}
            className="pointer-events-auto rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface disabled:opacity-40"
          >
            <MinusIcon />
          </button>
          <button
            type="button"
            title="Reset to fit the width"
            onClick={() => setZoom(1)}
            className="pointer-events-auto min-w-[3.5rem] rounded px-1 font-mono text-data text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            title="Zoom in"
            disabled={zoom >= ZOOM.max}
            onClick={() => setZoom((current) => clamp(current + ZOOM.step))}
            className="pointer-events-auto rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface disabled:opacity-40"
          >
            <PlusIcon />
          </button>
        </div>
      ) : null}
    </div>
  )
}

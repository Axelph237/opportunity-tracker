import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PdfPreview from './PdfPreview'

/**
 * A stand-in for pdf.js. The real library needs a worker and a canvas
 * implementation, neither of which jsdom has — and the parts worth testing
 * here are this component's own: how many canvases it makes, how a drag turns
 * into a scroll offset, and what the zoom controls do to the render scale.
 *
 * Panning against real layout is verified separately in a real browser; jsdom
 * reports every element as unscrollable, so the assertions below watch what
 * the component *writes* to the scroll offsets instead.
 */
const render$ = vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }))
const getViewport = vi.fn(({ scale }) => ({ width: 612 * scale, height: 792 * scale }))

function page(pageNumber) {
  return { pageNumber, getViewport, render: render$ }
}

let numPages = 1
let failWith = null

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({
    promise: failWith
      ? Promise.reject(new Error(failWith))
      : Promise.resolve({
          numPages,
          getPage: (n) => Promise.resolve(page(n)),
          destroy: vi.fn(),
        }),
    destroy: vi.fn(),
  }),
}))

const scroller = () => screen.getByTestId('pdf-scroller')

/** Make the scroll offsets writable so what the component sets is observable. */
function trackScroll(element) {
  const state = { top: 0, left: 0 }
  Object.defineProperty(element, 'scrollTop', {
    configurable: true,
    get: () => state.top,
    set: (value) => {
      state.top = value
    },
  })
  Object.defineProperty(element, 'scrollLeft', {
    configurable: true,
    get: () => state.left,
    set: (value) => {
      state.left = value
    },
  })
  return state
}

async function setup({ pages = 1, url = '/api/resumes/1/pdf' } = {}) {
  numPages = pages
  const view = render(<PdfPreview url={url} label="Resume preview" />)
  await waitFor(() => expect(screen.getAllByRole('img').length).toBe(pages))
  return view
}

// jsdom reports every element as zero-width, and the component skips
// rendering a page it cannot size. Give the pane a width for the duration.
beforeEach(() => {
  numPages = 1
  failWith = null
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => 600,
  })
})

afterEach(async () => {
  // The document load resolves over several microtasks. A test that asserts
  // before the last one leaves React updating a still-mounted component after
  // the body has returned, which is exactly the `act(...)` warning. Draining
  // them here keeps every test in this file quiet without each one having to
  // wait for state it does not care about.
  await act(async () => {
    await Promise.resolve()
  })
  delete HTMLElement.prototype.clientWidth
  vi.clearAllMocks()
})

describe('PdfPreview / rendering', () => {
  it('draws one canvas per page', async () => {
    await setup({ pages: 3 })
    expect(screen.getAllByRole('img')).toHaveLength(3)
  })

  it('names each page for assistive technology', async () => {
    await setup({ pages: 2 })
    expect(screen.getByLabelText('Resume preview, page 1 of 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Resume preview, page 2 of 2')).toBeInTheDocument()
  })

  it('says so when the PDF cannot be read', async () => {
    failWith = 'Invalid PDF structure'
    render(<PdfPreview url="/api/resumes/1/pdf" />)
    expect(await screen.findByText('Invalid PDF structure')).toBeInTheDocument()
  })

  it('shows a placeholder until the pages arrive', async () => {
    render(<PdfPreview url="/api/resumes/1/pdf" />)
    expect(screen.getByText('Loading preview…')).toBeInTheDocument()
    // Then it goes away on its own.
    await waitFor(() => expect(screen.queryByText('Loading preview…')).not.toBeInTheDocument())
  })
})

describe('PdfPreview / panning', () => {
  it('scrolls against the drag, so the page follows the cursor', async () => {
    await setup()
    const element = scroller()
    const state = trackScroll(element)

    fireEvent.pointerDown(element, { button: 0, clientX: 300, clientY: 400, pointerId: 1 })
    fireEvent.pointerMove(element, { clientX: 260, clientY: 300, pointerId: 1 })

    // Dragging up by 100 reveals content further down.
    expect(state.top).toBe(100)
    expect(state.left).toBe(40)
  })

  it('keeps tracking as the drag continues', async () => {
    await setup()
    const element = scroller()
    const state = trackScroll(element)

    fireEvent.pointerDown(element, { button: 0, clientX: 300, clientY: 400, pointerId: 1 })
    fireEvent.pointerMove(element, { clientX: 300, clientY: 350, pointerId: 1 })
    expect(state.top).toBe(50)
    fireEvent.pointerMove(element, { clientX: 300, clientY: 250, pointerId: 1 })
    // Measured from where the drag began, not from the last move, so a fast
    // drag cannot accumulate rounding drift.
    expect(state.top).toBe(150)
  })

  it('ignores movement once the button is up', async () => {
    await setup()
    const element = scroller()
    const state = trackScroll(element)

    fireEvent.pointerDown(element, { button: 0, clientX: 300, clientY: 400, pointerId: 1 })
    fireEvent.pointerMove(element, { clientX: 300, clientY: 300, pointerId: 1 })
    fireEvent.pointerUp(element, { clientX: 300, clientY: 300, pointerId: 1 })
    fireEvent.pointerMove(element, { clientX: 300, clientY: 100, pointerId: 1 })

    expect(state.top).toBe(100)
  })

  it('leaves the right button to the context menu', async () => {
    await setup()
    const element = scroller()
    const state = trackScroll(element)

    fireEvent.pointerDown(element, { button: 2, clientX: 300, clientY: 400, pointerId: 1 })
    fireEvent.pointerMove(element, { clientX: 300, clientY: 200, pointerId: 1 })

    expect(state.top).toBe(0)
  })

  it('shows a grabbing cursor only while dragging', async () => {
    await setup()
    const element = scroller()
    expect(element.className).toContain('cursor-grab')
    expect(element.className).not.toContain('cursor-grabbing')

    fireEvent.pointerDown(element, { button: 0, clientX: 10, clientY: 10, pointerId: 1 })
    expect(element.className).toContain('cursor-grabbing')

    fireEvent.pointerUp(element, { clientX: 10, clientY: 10, pointerId: 1 })
    expect(element.className).not.toContain('cursor-grabbing')
  })

  it('captures the pointer so the drag survives leaving the pane', async () => {
    await setup()
    const element = scroller()
    element.setPointerCapture = vi.fn()
    fireEvent.pointerDown(element, { button: 0, clientX: 10, clientY: 10, pointerId: 7 })
    expect(element.setPointerCapture).toHaveBeenCalledWith(7)
  })
})

describe('PdfPreview / zoom', () => {
  it('starts at fit-to-width', async () => {
    await setup()
    expect(screen.getByRole('button', { name: /100%/ })).toBeInTheDocument()
  })

  it('zooms in and out in steps', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByRole('button', { name: /125%/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByRole('button', { name: /100%/ })).toBeInTheDocument()
  })

  it('goes back to fit-to-width when the percentage is clicked', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    await user.click(screen.getByRole('button', { name: /125%/ }))
    expect(screen.getByRole('button', { name: /100%/ })).toBeInTheDocument()
  })

  it('will not zoom past its limits', async () => {
    const user = userEvent.setup()
    await setup()
    for (let i = 0; i < 20; i += 1) {
      await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    }
    expect(screen.getByRole('button', { name: /400%/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled()
  })

  it('renders at the zoomed scale, not just relabelling', async () => {
    const user = userEvent.setup()
    await setup()
    await waitFor(() => expect(render$).toHaveBeenCalled())
    const before = Math.max(...getViewport.mock.calls.map(([args]) => args.scale))
    getViewport.mockClear()

    await user.click(screen.getByRole('button', { name: 'Zoom in' }))

    await waitFor(() => expect(getViewport).toHaveBeenCalled())
    const after = Math.max(...getViewport.mock.calls.map(([args]) => args.scale))
    expect(after).toBeGreaterThan(before)
  })

  it('zooms on ctrl+wheel and leaves a plain wheel to scroll', async () => {
    await setup()
    const element = scroller()

    fireEvent.wheel(element, { deltaY: -100, ctrlKey: true })
    await waitFor(() => expect(screen.getByRole('button', { name: /110%/ })).toBeInTheDocument())

    fireEvent.wheel(element, { deltaY: -100 })
    expect(screen.getByRole('button', { name: /110%/ })).toBeInTheDocument()
  })
})

describe('PdfPreview / reachability when zoomed', () => {
  it('lets the page column grow past the pane instead of centring the overflow away', async () => {
    // A class assertion, because the bug is purely a layout one and jsdom has
    // no layout. Centring a flex item wider than its scroll container pushes
    // the overflow to the left of scrollLeft 0, where nothing can reach it —
    // measured at 400% zoom in a real browser, 705px of the page was
    // unreachable. `w-max` makes the column as wide as its widest page so the
    // overflow lands on the right; `min-w-full` keeps a small page centred.
    await setup()
    const column = scroller().firstElementChild
    expect(column.className).toContain('w-max')
    expect(column.className).toContain('min-w-full')
    expect(column.className).toContain('items-center')
  })
})

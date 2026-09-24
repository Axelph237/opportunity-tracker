import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ResizeHandle, usePanelSize } from './Resizable'

/** A pane whose width is driven by the handle under test. */
function Harness({ storageKey = 'test.pane', initial = 200, min = 100, max = 400, ...rest }) {
  const [size, resize, reset] = usePanelSize(storageKey, initial, { min, max })
  return (
    <div>
      <div data-testid="pane" style={{ width: size }} />
      <ResizeHandle
        label="Resize the pane"
        value={size}
        onChange={resize}
        onReset={reset}
        min={min}
        max={max}
        {...rest}
      />
    </div>
  )
}

const handle = () => screen.getByRole('separator', { name: 'Resize the pane' })
const width = () => Number(handle().getAttribute('aria-valuenow'))

/** jsdom has no PointerEvent, but fireEvent will synthesise one with coords. */
function drag(from, to) {
  fireEvent.pointerDown(handle(), { clientX: from, clientY: from, pointerId: 1 })
  fireEvent.pointerMove(handle(), { clientX: to, clientY: to, pointerId: 1 })
  fireEvent.pointerUp(handle(), { clientX: to, clientY: to, pointerId: 1 })
}

afterEach(() => {
  localStorage.clear()
})

describe('usePanelSize', () => {
  it('starts at the initial size when nothing is stored', () => {
    render(<Harness />)
    expect(width()).toBe(200)
  })

  it('restores a stored size', () => {
    localStorage.setItem('opportunity-tracker.layout.test.pane', '333')
    render(<Harness />)
    expect(width()).toBe(333)
  })

  it('clamps a stored size that a later minimum outgrew', () => {
    // A tightened minimum must not leave someone stuck with an unusable pane.
    localStorage.setItem('opportunity-tracker.layout.test.pane', '20')
    render(<Harness min={100} />)
    expect(width()).toBe(100)
  })

  it('ignores a corrupt stored value', () => {
    localStorage.setItem('opportunity-tracker.layout.test.pane', 'not a number')
    render(<Harness />)
    expect(width()).toBe(200)
  })

  it('keeps different panes apart', () => {
    localStorage.setItem('opportunity-tracker.layout.other', '150')
    render(<Harness storageKey="test.pane" />)
    expect(width()).toBe(200)
  })
})

describe('ResizeHandle / dragging', () => {
  it('widens the pane when dragged right', () => {
    render(<Harness />)
    drag(500, 560)
    expect(width()).toBe(260)
  })

  it('narrows the pane when dragged left', () => {
    render(<Harness />)
    drag(500, 450)
    expect(width()).toBe(150)
  })

  it('stops at the minimum however far it is dragged', () => {
    // The whole point of a minimum: a pane cannot be collapsed to nothing by
    // overshooting, only by the control that is meant to collapse it.
    render(<Harness />)
    drag(500, -2000)
    expect(width()).toBe(100)
  })

  it('stops at the maximum', () => {
    render(<Harness />)
    drag(500, 5000)
    expect(width()).toBe(400)
  })

  it('shrinks when dragged right if the pane is on the other side', () => {
    // A right-hand rail grows leftwards; without `invert` the handle would
    // fight the cursor.
    render(<Harness invert />)
    drag(500, 560)
    expect(width()).toBe(140)
  })

  it('tracks the pointer beyond where the drag started', () => {
    render(<Harness />)
    fireEvent.pointerDown(handle(), { clientX: 500, pointerId: 1 })
    fireEvent.pointerMove(handle(), { clientX: 530, pointerId: 1 })
    expect(width()).toBe(230)
    fireEvent.pointerMove(handle(), { clientX: 560, pointerId: 1 })
    expect(width()).toBe(260)
    fireEvent.pointerUp(handle(), { clientX: 560, pointerId: 1 })
  })

  it('ignores movement once the drag has ended', () => {
    render(<Harness />)
    drag(500, 550)
    fireEvent.pointerMove(handle(), { clientX: 900, pointerId: 1 })
    expect(width()).toBe(250)
  })

  it('persists the result of a drag', () => {
    render(<Harness />)
    drag(500, 550)
    expect(localStorage.getItem('opportunity-tracker.layout.test.pane')).toBe('250')
  })

  it('measures the other axis when horizontal', () => {
    render(<Harness orientation="horizontal" />)
    fireEvent.pointerDown(handle(), { clientX: 0, clientY: 300, pointerId: 1 })
    fireEvent.pointerMove(handle(), { clientX: 999, clientY: 340, pointerId: 1 })
    expect(width()).toBe(240)
  })
})

describe('ResizeHandle / keyboard and reset', () => {
  it('is reachable and adjustable without a mouse', async () => {
    render(<Harness />)
    handle().focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(width()).toBe(216)
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(width()).toBe(184)
  })

  it('jumps to the extremes with Home and End', async () => {
    render(<Harness />)
    handle().focus()
    await userEvent.keyboard('{Home}')
    expect(width()).toBe(100)
    await userEvent.keyboard('{End}')
    expect(width()).toBe(400)
  })

  it('reverses the arrow keys for an inverted handle', async () => {
    render(<Harness invert />)
    handle().focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(width()).toBe(216)
  })

  it('goes back to the default on double click', async () => {
    render(<Harness />)
    drag(500, 560)
    expect(width()).toBe(260)
    await userEvent.dblClick(handle())
    expect(width()).toBe(200)
    expect(localStorage.getItem('opportunity-tracker.layout.test.pane')).toBeNull()
  })

  it('describes its range to assistive technology', () => {
    render(<Harness />)
    expect(handle()).toHaveAttribute('aria-orientation', 'vertical')
    expect(handle()).toHaveAttribute('aria-valuemin', '100')
    expect(handle()).toHaveAttribute('aria-valuemax', '400')
    expect(handle()).toHaveAttribute('tabindex', '0')
  })
})

describe('ResizeHandle / storage failures', () => {
  it('still resizes when localStorage refuses to write', () => {
    // Safari in private mode throws on setItem. Losing the preference is
    // acceptable; losing the ability to drag is not.
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    render(<Harness />)
    drag(500, 550)
    expect(width()).toBe(250)
    setItem.mockRestore()
  })
})

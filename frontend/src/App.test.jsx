import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { api } from './api'

// Only the shell is under test here; every page it can route to is stubbed so
// this stays a test of the sidebar rather than of Opportunities.
vi.mock('./pages/Opportunities', () => ({ default: () => <div>opportunities page</div> }))
vi.mock('./pages/Applications', () => ({ default: () => <div>applications page</div> }))
vi.mock('./pages/Resumes', () => ({ default: () => <div>resumes page</div> }))
vi.mock('./pages/Insights', () => ({ default: () => <div>insights page</div> }))
vi.mock('./pages/Sources', () => ({ default: () => <div>sources page</div> }))
vi.mock('./pages/Settings', () => ({ default: () => <div>settings page</div> }))
vi.mock('./pages/settings/SettingsSection', () => ({ default: () => <div>settings section</div> }))
vi.mock('./pages/Walten', () => ({ default: () => <div>walten page</div> }))
vi.mock('./pages/Onboarding', () => ({ default: () => <div>onboarding</div> }))

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: { ...actual.api, stats: vi.fn(), scrapeStatus: vi.fn() },
  }
})

const STATS = {
  opportunities: 12,
  strong_matches: 3,
  applications: 2,
  resumes: 4,
  pending_proposals: 0,
  walten_name: 'Walten',
  walten_icon: 'Dog',
  onboarding_complete: true,
}

async function setup() {
  api.stats.mockResolvedValue(STATS)
  api.scrapeStatus.mockResolvedValue({ running: false, last_run: null, next_run: null })
  render(
    <MemoryRouter initialEntries={['/opportunities']}>
      <App />
    </MemoryRouter>,
  )
  // Nothing renders until the first stats call decides onboarding is done.
  await screen.findByRole('navigation')
}

afterEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('App / the sidebar', () => {
  it('starts expanded, with a label on every destination', async () => {
    await setup()
    expect(screen.getByRole('link', { name: /Opportunities/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Resumes/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('collapses to icons, keeping every destination reachable', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))

    // The visible text goes, but the links must not — a collapsed sidebar that
    // drops its destinations is just a broken sidebar.
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
    for (const label of ['Opportunities', 'Applications', 'Resumes', 'Sources', 'Settings']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('keeps the label available to assistive technology when collapsed', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('link', { name: 'Resumes' })).toHaveAttribute('href', '/resumes')
  })

  it('attaches a hover label to each icon when collapsed', async () => {
    const user = userEvent.setup()
    await setup()
    expect(screen.queryAllByRole('tooltip')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))

    // A column of unlabelled glyphs is unusable, so every icon grows a
    // tooltip. It is CSS-driven, so what matters is that it is in the DOM.
    const labels = screen.getAllByRole('tooltip').map((tip) => tip.textContent)
    expect(labels).toEqual(expect.arrayContaining(['Opportunities', 'Resumes', 'Settings']))
  })

  it('expands again', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('remembers the choice across a reload', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))

    cleanup()
    await setup()
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('returns to the width it had, not the default, when expanded again', async () => {
    const user = userEvent.setup()
    await setup()
    const handle = screen.getByRole('separator', { name: 'Resize the sidebar' })
    fireEvent.pointerDown(handle, { clientX: 208, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 300, pointerId: 1 })
    fireEvent.pointerUp(handle, { clientX: 300, pointerId: 1 })
    expect(Number(handle.getAttribute('aria-valuenow'))).toBe(300)

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))

    expect(
      Number(screen.getByRole('separator', { name: 'Resize the sidebar' }).getAttribute('aria-valuenow')),
    ).toBe(300)
  })
})

describe('App / resizing the sidebar', () => {
  const handle = () => screen.getByRole('separator', { name: 'Resize the sidebar' })

  const dragTo = (x) => {
    fireEvent.pointerDown(handle(), { clientX: 208, pointerId: 1 })
    fireEvent.pointerMove(handle(), { clientX: x, pointerId: 1 })
    fireEvent.pointerUp(handle(), { clientX: x, pointerId: 1 })
  }

  it('can be dragged wider', async () => {
    await setup()
    dragTo(320)
    expect(Number(handle().getAttribute('aria-valuenow'))).toBe(320)
    expect(screen.getByRole('link', { name: /Opportunities/ })).toBeInTheDocument()
  })

  it('turns into icons once dragged narrow enough for a label not to fit', async () => {
    // The threshold, not the collapse button — dragging it small has to reach
    // the same state, or the two controls disagree about the mode.
    await setup()
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    dragTo(100)
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
    expect(screen.queryByText('12')).not.toBeInTheDocument()
    // Still every destination, just without its text.
    expect(screen.getByRole('link', { name: 'Resumes' })).toBeInTheDocument()
  })

  it('goes back to labels when dragged wide again', async () => {
    await setup()
    dragTo(100)
    fireEvent.pointerDown(handle(), { clientX: 100, pointerId: 1 })
    fireEvent.pointerMove(handle(), { clientX: 260, pointerId: 1 })
    fireEvent.pointerUp(handle(), { clientX: 260, pointerId: 1 })
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('cannot be dragged narrower than the icon rail', async () => {
    await setup()
    dragTo(-500)
    expect(Number(handle().getAttribute('aria-valuenow'))).toBe(56)
  })

  it('collapsing puts it at exactly the icon-rail width', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(Number(handle().getAttribute('aria-valuenow'))).toBe(56)
  })

  it('hides the count badges when collapsed, and shows them when not', async () => {
    const user = userEvent.setup()
    await setup()
    await waitFor(() => expect(screen.getByText('12')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.queryByText('12')).not.toBeInTheDocument()
  })

  it('shows a Resumes entry with its count', async () => {
    await setup()
    await waitFor(() => expect(screen.getByRole('link', { name: /Resumes/ })).toBeInTheDocument())
    expect(screen.getByText('4')).toBeInTheDocument()
  })
})


describe('App / reordering the sidebar', () => {
  const DEFAULT_ORDER = [
    '/opportunities',
    '/applications',
    '/resumes',
    '/insights',
    '/sources',
    '/settings',
  ]

  // The nav list, by destination. Reading hrefs rather than text so the test
  // says nothing about labels or badge counts.
  const order = () =>
    within(screen.getByRole('list'))
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'))

  const item = (name) => screen.getByRole('link', { name }).closest('li')

  // jsdom has no DragEvent and so no DataTransfer. The component only ever
  // sets data and an effect on it, so a stub with those is enough.
  const transfer = () => ({ setData: vi.fn(), getData: vi.fn(), dropEffect: '', effectAllowed: '' })

  const drag = (from, onto, { drop = true } = {}) => {
    const dataTransfer = transfer()
    fireEvent.dragStart(from, { dataTransfer })
    fireEvent.dragEnter(onto, { dataTransfer })
    fireEvent.dragOver(onto, { dataTransfer })
    if (drop) fireEvent.drop(onto, { dataTransfer })
    fireEvent.dragEnd(from, { dataTransfer })
  }

  it('lists the sections in the shipped order to begin with', async () => {
    await setup()
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('moves a section to where it was dropped', async () => {
    await setup()
    drag(item(/Settings/), item(/Opportunities/))
    expect(order()).toEqual([
      '/settings',
      '/opportunities',
      '/applications',
      '/resumes',
      '/insights',
      '/sources',
    ])
  })

  it('shuffles the list under the pointer before the drop', async () => {
    // The feedback during the drag is the whole affordance: without it there
    // is no sign that letting go will do anything.
    await setup()
    const dataTransfer = transfer()
    fireEvent.dragStart(item(/Settings/), { dataTransfer })
    fireEvent.dragEnter(item(/Resumes/), { dataTransfer })
    expect(order()[2]).toBe('/settings')
  })

  it('puts everything back when the drag is abandoned', async () => {
    // Escape, or a drop on something that did not want it. The list has been
    // rearranging all along, so stopping is not enough — it has to undo.
    await setup()
    drag(item(/Settings/), item(/Opportunities/), { drop: false })
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('remembers the arrangement across a reload', async () => {
    await setup()
    drag(item(/Sources/), item(/Opportunities/))
    const rearranged = order()

    cleanup()
    await setup()
    expect(order()).toEqual(rearranged)
    expect(order()[0]).toBe('/sources')
  })

  it('does not save an abandoned drag', async () => {
    await setup()
    drag(item(/Settings/), item(/Opportunities/), { drop: false })
    cleanup()
    await setup()
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('can be reordered from the keyboard, which a drag cannot be', async () => {
    await setup()
    const link = screen.getByRole('link', { name: /Resumes/ })
    link.focus()
    fireEvent.keyDown(link, { key: 'ArrowUp', altKey: true })
    expect(order()).toEqual([
      '/opportunities',
      '/resumes',
      '/applications',
      '/insights',
      '/sources',
      '/settings',
    ])
    // Focus follows the row it is on, so the next press keeps going rather
    // than starting over on whatever landed underneath.
    expect(document.activeElement).toBe(screen.getByRole('link', { name: /Resumes/ }))
  })

  it('saves a keyboard move too', async () => {
    await setup()
    fireEvent.keyDown(screen.getByRole('link', { name: /Settings/ }), { key: 'ArrowUp', altKey: true })
    cleanup()
    await setup()
    expect(order()[4]).toBe('/settings')
  })

  it('leaves the arrow keys alone without the modifier', async () => {
    // A bare arrow on a focused link already scrolls, and is how some screen
    // readers move between elements.
    await setup()
    fireEvent.keyDown(screen.getByRole('link', { name: /Resumes/ }), { key: 'ArrowUp' })
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('will not push the first section off the top, or the last off the bottom', async () => {
    await setup()
    fireEvent.keyDown(screen.getByRole('link', { name: /Opportunities/ }), {
      key: 'ArrowUp',
      altKey: true,
    })
    fireEvent.keyDown(screen.getByRole('link', { name: /Settings/ }), {
      key: 'ArrowDown',
      altKey: true,
    })
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('still shows every section when the saved order is from an older version', async () => {
    // A tab that has since been removed, and one that did not exist yet.
    localStorage.setItem(
      'opportunity-tracker.layout.nav-order',
      JSON.stringify(['/settings', '/gone', '/resumes']),
    )
    await setup()
    expect(order()).toHaveLength(DEFAULT_ORDER.length)
    expect(order().slice(0, 2)).toEqual(['/settings', '/resumes'])
    expect([...order()].sort()).toEqual([...DEFAULT_ORDER].sort())
  })

  it('ignores a stored value it cannot read', async () => {
    localStorage.setItem('opportunity-tracker.layout.nav-order', 'not json')
    await setup()
    expect(order()).toEqual(DEFAULT_ORDER)
  })

  it('keeps the agent pinned to the bottom, out of the reorderable list', async () => {
    await setup()
    expect(order()).not.toContain('/walten')
    expect(screen.getByRole('link', { name: /Walten/ })).toBeInTheDocument()
  })

  it('can still be reordered when collapsed to icons', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    drag(item('Settings'), item('Opportunities'))
    expect(order()[0]).toBe('/settings')
  })
})

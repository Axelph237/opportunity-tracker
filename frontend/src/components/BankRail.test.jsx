import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BankRail, { entryDates } from './BankRail'

const entry = (overrides) => ({
  id: 1,
  kind: 'experience',
  title: 'Research Assistant',
  organization: 'Fermilab',
  location: null,
  start_date: 'Jun 2026',
  end_date: 'Sep 2026',
  is_current: false,
  url: null,
  detail: null,
  bullets: [{ id: 11, text: 'Built the DAQ pipeline' }],
  ...overrides,
})

function setup(props = {}) {
  const handlers = {
    onImport: vi.fn(),
    onCreate: vi.fn(),
    onEdit: vi.fn(),
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
  }
  render(<BankRail entries={[entry()]} {...handlers} {...props} />)
  return handlers
}

describe('BankRail / an empty bank', () => {
  it('says it is empty rather than rendering a blank column', () => {
    setup({ entries: [] })
    expect(screen.getByText(/your experience bank is empty/i)).toBeInTheDocument()
  })

  it('points at the import button and makes it the obvious thing to press', () => {
    setup({ entries: [] })
    expect(screen.getByText(/import from your resume above/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import from my resume/i })).toHaveClass('btn-primary')
  })

  it('still offers the manual way in, for someone with no resume to import', async () => {
    const user = userEvent.setup()
    const { onCreate } = setup({ entries: [] })
    await user.click(screen.getByRole('button', { name: /add the first record/i }))
    expect(onCreate).toHaveBeenCalled()
  })

  it('says nothing about being empty while it is still loading', () => {
    setup({ entries: [], loading: true })
    expect(screen.queryByText(/your experience bank is empty/i)).not.toBeInTheDocument()
  })
})

describe('BankRail / the import', () => {
  it('marks it as a Claude call and says how long it may take', () => {
    setup()
    expect(screen.getByRole('button', { name: /import from my resume/i })).toHaveAttribute(
      'title',
      'Runs a Claude call',
    )
    expect(screen.getByText(/takes up to a minute/i)).toBeInTheDocument()
  })

  it('blocks a second import while the first is still reading', () => {
    setup({ importing: true })
    expect(screen.getByRole('button', { name: /reading your resume…/i })).toBeDisabled()
  })

  it('drops the primary treatment once there is something in the bank', () => {
    setup()
    expect(screen.getByRole('button', { name: /import from my resume/i })).not.toHaveClass('btn-primary')
  })
})

describe('BankRail / the records', () => {
  it('groups them by what they are', () => {
    setup({
      entries: [entry(), entry({ id: 2, kind: 'project', title: 'Delphi', organization: null })],
    })
    expect(screen.getByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Project' })).toBeInTheDocument()
  })

  it('leaves out a group with nothing in it', () => {
    setup()
    expect(screen.queryByRole('heading', { name: 'Education' })).not.toBeInTheDocument()
  })

  it('shows the employer, the dates and how many bullets are behind the record', () => {
    setup()
    const row = screen.getByText('Research Assistant').closest('li')
    expect(within(row).getByText('Fermilab · Jun 2026 -- Sep 2026')).toBeInTheDocument()
    expect(within(row).getByText('· 1')).toBeInTheDocument()
  })

  it('opens one for editing', async () => {
    const user = userEvent.setup()
    const { onEdit } = setup()
    await user.click(screen.getByRole('button', { name: 'Edit Research Assistant' }))
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })

  it('attaches drag data, which Firefox needs before it will start a drag at all', () => {
    const { onDragStart } = setup()
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), dropEffect: '', effectAllowed: '' }
    fireEvent.dragStart(screen.getByText('Research Assistant').closest('li'), { dataTransfer })
    expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', 'bank-entry:1')
    expect(onDragStart).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })

  it('fades the record being dragged so the pointer has something to follow', () => {
    setup({ draggingId: 1 })
    expect(screen.getByText('Research Assistant').closest('li')).toHaveClass('opacity-40')
  })

  it('says how to get a record onto the canvas, since nothing about a row announces it', () => {
    setup()
    expect(screen.getByText(/drag a record onto a section/i)).toBeInTheDocument()
  })
})

describe('entryDates', () => {
  it('joins the two halves the way a resume prints them', () => {
    expect(entryDates(entry())).toBe('Jun 2026 -- Sep 2026')
  })

  it('prints Present for a role that has not ended', () => {
    expect(entryDates(entry({ is_current: true, end_date: null }))).toBe('Jun 2026 -- Present')
  })

  it('does not leave a dangling dash when only one date is known', () => {
    expect(entryDates(entry({ end_date: null }))).toBe('Jun 2026')
    expect(entryDates(entry({ start_date: null }))).toBe('Sep 2026')
    expect(entryDates(entry({ start_date: null, end_date: null }))).toBe('')
  })
})

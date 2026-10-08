import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BankEntryForm from './BankEntryForm'

const ENTRY = {
  id: 5,
  kind: 'experience',
  title: 'Research Assistant',
  organization: 'Fermilab',
  location: 'Batavia, IL',
  start_date: 'Jun 2026',
  end_date: 'Sep 2026',
  is_current: false,
  url: null,
  detail: null,
  bullets: [
    { id: 11, text: 'Built the DAQ pipeline' },
    { id: 12, text: 'Cut calibration time by half' },
  ],
}

function setup(props = {}) {
  const handlers = { onSave: vi.fn(), onDelete: vi.fn(), onCancel: vi.fn() }
  render(<BankEntryForm {...handlers} {...props} />)
  return handlers
}

describe('BankEntryForm / what each kind asks for', () => {
  it('asks an experience for an employer and a location', () => {
    setup({ entry: ENTRY })
    expect(screen.getByRole('textbox', { name: /organization/i })).toHaveValue('Fermilab')
    expect(screen.getByRole('textbox', { name: /location/i })).toHaveValue('Batavia, IL')
  })

  it('asks a project for its stack instead of an employer', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: /kind/i }))
    await user.click(screen.getByRole('option', { name: 'Project' }))
    expect(screen.getByRole('textbox', { name: /detail/i })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /organization/i })).not.toBeInTheDocument()
  })

  it('asks a skill group for nothing but a label and its terms', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: /kind/i }))
    await user.click(screen.getByRole('option', { name: 'Skill group' }))
    expect(screen.getByRole('textbox', { name: /group/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add term/i })).toBeInTheDocument()
    for (const gone of [/organization/i, /location/i, /from/i, /link/i]) {
      expect(screen.queryByRole('textbox', { name: gone })).not.toBeInTheDocument()
    }
  })

  it('does not keep a value the new kind has nowhere to show', async () => {
    // Otherwise the record stores a location that no screen can edit or undo.
    const user = userEvent.setup()
    const { onSave } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('button', { name: /kind/i }))
    await user.click(screen.getByRole('option', { name: 'Skill group' }))
    await user.click(screen.getByRole('button', { name: /add to bank|save changes/i }))
    expect(onSave.mock.calls[0][0]).toMatchObject({ kind: 'skill_group', location: '', organization: '' })
  })
})

describe('BankEntryForm / dates', () => {
  it('takes the dates as free text, because a resume prints “Expected June 2027”', () => {
    setup({ entry: ENTRY })
    expect(screen.getByRole('textbox', { name: /^from/i })).toHaveValue('Jun 2026')
  })

  it('takes the end date away once the role is marked as still going', async () => {
    const user = userEvent.setup()
    const { onSave } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('textbox', { name: /^to/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    expect(onSave.mock.calls[0][0]).toMatchObject({ is_current: true, end_date: '' })
  })
})

describe('BankEntryForm / bullets', () => {
  it('hands the entry and its bullets back together, so one Save covers both', async () => {
    const user = userEvent.setup()
    const { onSave } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('button', { name: /add bullet/i }))
    await user.type(screen.getByRole('textbox', { name: 'Bullet 3' }), 'Presented at the group meeting')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    const [patch, bullets] = onSave.mock.calls[0]
    expect(patch.title).toBe('Research Assistant')
    expect(bullets).toEqual([
      { id: 11, text: 'Built the DAQ pipeline' },
      { id: 12, text: 'Cut calibration time by half' },
      { id: null, text: 'Presented at the group meeting' },
    ])
  })

  it('removes a bullet without disturbing the one below it', async () => {
    const user = userEvent.setup()
    const { onSave } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('button', { name: 'Remove bullet 1' }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    expect(onSave.mock.calls[0][1]).toEqual([{ id: 12, text: 'Cut calibration time by half' }])
  })

  it('drops a bullet row left empty rather than saving a blank one', async () => {
    const user = userEvent.setup()
    const { onSave } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('button', { name: /add bullet/i }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    expect(onSave.mock.calls[0][1]).toHaveLength(2)
  })

  it('says what a good bullet looks like, where it is being written', () => {
    setup({ entry: ENTRY })
    expect(screen.getByText(/start with a strong verb/i)).toBeInTheDocument()
  })
})

describe('BankEntryForm / saving and deleting', () => {
  it('will not save a record with no title', async () => {
    const user = userEvent.setup()
    const { onSave } = setup()
    const save = screen.getByRole('button', { name: /add to bank/i })
    expect(save).toBeDisabled()
    await user.click(save)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('offers no deletion for a record that does not exist yet', () => {
    setup()
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
  })

  it('offers deletion for one that does', async () => {
    const user = userEvent.setup()
    const { onDelete } = setup({ entry: ENTRY })
    await user.click(screen.getByRole('button', { name: /delete/i }))
    expect(onDelete).toHaveBeenCalled()
  })
})

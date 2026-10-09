import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProposalReview from './ProposalReview'

const BODY = {
  sections: [
    {
      ref: 's1',
      label: 'Experience',
      placements: [
        {
          ref: 'p1',
          title: 'Research Assistant',
          bullets: [{ ref: 'b1', text: 'Helped with the DAQ pipeline' }],
        },
      ],
    },
  ],
}

const BANK = [{ id: 7, title: 'Delphi' }]

// Operations as `ProposalOp` declares them, which has no id field.
const PROPOSAL = {
  id: 3,
  kind: 'tailor',
  status: 'pending',
  summary: 'Leads with the simulation work the ad asks for.',
  operations: [
    {
      op: 'RewriteBullet',
      placement_id: 'p1',
      bullet_ref: 'b1',
      text: 'Rebuilt the DAQ pipeline, cutting calibration time in half',
      rationale: 'The ad asks for a strong verb and a number.',
    },
    { op: 'AddEntry', entry_id: 7, section: 'Projects', position: 0 },
    { op: 'RenameSection', section_id: 's1', label: 'Research Experience' },
  ],
}

function setup(props = {}) {
  const handlers = { onApply: vi.fn(), onDismiss: vi.fn() }
  render(<ProposalReview proposal={PROPOSAL} body={BODY} bank={BANK} {...handlers} {...props} />)
  return handlers
}

describe('ProposalReview / what it lists', () => {
  it('says what the whole proposal is for before listing the parts', () => {
    setup()
    expect(screen.getByRole('heading', { name: /tailored for this ad/i })).toBeInTheDocument()
    expect(screen.getByText(/leads with the simulation work/i)).toBeInTheDocument()
  })

  it('calls a drifted bank out as a different kind of proposal', () => {
    setup({ proposal: { ...PROPOSAL, kind: 'sync' } })
    expect(screen.getByRole('heading', { name: /your bank has moved on/i })).toBeInTheDocument()
  })

  it('names the records a change touches, not the refs it names them by', () => {
    setup()
    expect(screen.getByText(/in Research Assistant/)).toBeInTheDocument()
    expect(screen.getByText(/Delphi to Projects/)).toBeInTheDocument()
    expect(screen.getByText(/Experience to “Research Experience”/)).toBeInTheDocument()
  })

  it('shows a reword as what it replaces and what it becomes', () => {
    setup()
    expect(screen.getByText('Helped with the DAQ pipeline')).toHaveClass('line-through')
    expect(
      screen.getByText('Rebuilt the DAQ pipeline, cutting calibration time in half'),
    ).toBeInTheDocument()
  })

  it('gives the reason the change was proposed', () => {
    setup()
    expect(screen.getByText(/strong verb and a number/i)).toBeInTheDocument()
  })

  it('promises the changes only move what the bank already holds', () => {
    setup()
    expect(screen.getByText(/already in your bank/i)).toBeInTheDocument()
  })

  it('still reads sensibly when an operation names a record that has since gone', () => {
    setup({ proposal: { ...PROPOSAL, operations: [{ op: 'DropEntry', placement_id: 'gone' }] } })
    expect(screen.getByText(/a record no longer there/i)).toBeInTheDocument()
  })

  it('does not blow up on an operation it has no wording for', () => {
    setup({ proposal: { ...PROPOSAL, operations: [{ op: 'Teleport' }] } })
    expect(screen.getByText('Teleport')).toBeInTheDocument()
  })
})

describe('ProposalReview / applying', () => {
  const accepts = (call) => call.map((op) => [op.op, op.accepted])

  it('hands back every operation that was offered, not just the ticked ones', async () => {
    const user = userEvent.setup()
    const { onApply } = setup()
    await user.click(screen.getByRole('button', { name: 'Apply 3 of 3' }))
    expect(accepts(onApply.mock.calls[0][0])).toEqual([
      ['RewriteBullet', true], ['AddEntry', true], ['RenameSection', true],
    ])
  })

  it('marks the ones the user unticked as not accepted', async () => {
    const user = userEvent.setup()
    const { onApply } = setup()
    await user.click(screen.getAllByRole('checkbox')[1])
    await user.click(screen.getByRole('button', { name: 'Apply 2 of 3' }))
    expect(accepts(onApply.mock.calls[0][0])).toEqual([
      ['RewriteBullet', true], ['AddEntry', false], ['RenameSection', true],
    ])
  })

  it('sends each operation back with the fields it was offered with', async () => {
    const user = userEvent.setup()
    const { onApply } = setup()
    await user.click(screen.getByRole('button', { name: 'Apply 3 of 3' }))
    expect(onApply.mock.calls[0][0][1]).toEqual({
      op: 'AddEntry', entry_id: 7, section: 'Projects', position: 0, accepted: true,
    })
  })

  it('puts one back when it is ticked again', async () => {
    const user = userEvent.setup()
    const { onApply } = setup()
    const box = screen.getAllByRole('checkbox')[0]
    await user.click(box)
    await user.click(box)
    await user.click(screen.getByRole('button', { name: 'Apply 3 of 3' }))
    expect(accepts(onApply.mock.calls[0][0])).toEqual([
      ['RewriteBullet', true], ['AddEntry', true], ['RenameSection', true],
    ])
  })

  it('has nothing to apply once every box is cleared', async () => {
    const user = userEvent.setup()
    const { onApply } = setup()
    for (const box of screen.getAllByRole('checkbox')) await user.click(box)
    expect(screen.getByRole('button', { name: /apply 0 of 3/i })).toBeDisabled()
    expect(onApply).not.toHaveBeenCalled()
  })

  it('discards the whole proposal without applying any of it', async () => {
    const user = userEvent.setup()
    const { onApply, onDismiss } = setup()
    await user.click(screen.getByRole('button', { name: /discard all/i }))
    expect(onDismiss).toHaveBeenCalled()
    expect(onApply).not.toHaveBeenCalled()
  })

  it('blocks a second apply while the first is in flight', () => {
    setup({ busy: true })
    expect(screen.getByRole('button', { name: /applying…/i })).toBeDisabled()
  })
})

describe('ProposalReview / nothing to change', () => {
  it('says so rather than offering an apply button with nothing behind it', () => {
    setup({ proposal: { ...PROPOSAL, operations: [], summary: 'This draft already covers the ad.' } })
    expect(screen.getByText('This draft already covers the ad.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^apply/i })).not.toBeInTheDocument()
  })
})

describe('ProposalReview / a document rather than a draft', () => {
  const SLOTS = [{
    key: 'experience', name: 'Experience',
    blocks: [{
      kind: 'entry', raw: '', heading: 'resumeSubheading',
      args: ['UChicago PME', 'Jun 2025', 'Research Assistant', 'Chicago, IL'],
      args_text: ['UChicago PME', 'Jun 2025', 'Research Assistant', 'Chicago, IL'],
      bullets: ['Helped with it'], bullets_text: ['Helped with it'],
    }],
  }]
  const slotProposal = (op) => ({
    id: 5, kind: 'tailor', status: 'pending', summary: 'x',
    operations: [{ slot: 'experience', block: 0, accepted: true, ...op }],
  })

  const show = (proposal) =>
    render(
      <ProposalReview proposal={proposal} slots={SLOTS} bank={[]} onApply={vi.fn()} onDismiss={vi.fn()} />,
    )

  it('names the block an operation points at, rather than calling it missing', () => {
    // Described with the draft vocabulary, every slot operation read "in a
    // record no longer there", because there was no ref for it to resolve.
    show(slotProposal({ op: 'RewriteBullet', bullet: 0, text: 'Built it' }))

    expect(screen.getByText(/Research Assistant/)).toBeInTheDocument()
    expect(screen.queryByText(/no longer there/i)).not.toBeInTheDocument()
  })

  it('shows the bullet being replaced, read from the block', () => {
    show(slotProposal({ op: 'RewriteBullet', bullet: 0, text: 'Built it' }))

    expect(screen.getByText(/Helped with it/)).toBeInTheDocument()
  })

  it('falls back to the position when the block is not where it was', () => {
    show(slotProposal({ op: 'DropEntry', block: 9 }))

    expect(screen.getByText(/block 10 of experience/i)).toBeInTheDocument()
  })
})

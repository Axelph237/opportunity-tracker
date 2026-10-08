import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Builder from './Builder'
import { ConfirmProvider } from '../components/ConfirmDialog'
import { api } from '../api'

// Never touch the network, and never the real ../data/opportunities.db.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: {
      ...actual.api,
      drafts: vi.fn(),
      draft: vi.fn(),
      createDraft: vi.fn(),
      updateDraft: vi.fn(),
      draftCoverage: vi.fn(),
      pushDraft: vi.fn(),
      tailorDraft: vi.fn(),
      resolveProposal: vi.fn(),
      bankEntries: vi.fn(),
      createBankEntry: vi.fn(),
      updateBankEntry: vi.fn(),
      deleteBankEntry: vi.fn(),
      createBankBullet: vi.fn(),
      updateBankBullet: vi.fn(),
      deleteBankBullet: vi.fn(),
      importBank: vi.fn(),
      jobPost: vi.fn(),
      createJobPost: vi.fn(),
      extractJobKeywords: vi.fn(),
    },
  }
})

const JOB_POST = { id: 4, title: 'Quantum Computing Intern', organization: 'ACME Labs' }

const BANK = [
  {
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
    bullets: [
      { id: 11, text: 'Built the DAQ pipeline' },
      { id: 12, text: 'Halved calibration time' },
    ],
  },
]

const BODY = {
  sections: [
    {
      ref: 's1',
      label: 'Experience',
      bullet_style: 'bullets',
      placements: [
        {
          ref: 'p1',
          entry_id: 1,
          kind: 'experience',
          title: 'Research Assistant',
          organization: 'Fermilab',
          dates: 'Jun 2026 -- Sep 2026',
          bullets: [
            { ref: 'b1', text: 'Built the DAQ pipeline', source_bullet_id: 11, source_text: 'Built the DAQ pipeline' },
            { ref: 'b2', text: 'Halved calibration time', source_bullet_id: 12, source_text: 'Halved calibration time' },
          ],
        },
      ],
    },
  ],
}

const DRAFT = { id: 9, name: 'ACME intern', job_post_id: 4, resume_instance_id: null, body: BODY, pushed_at: null }

// `CoverageReport` as models.py declares it. The terms ride on `keywords`:
// a fixture that invented a `coverage` field would agree with a page reading
// the same invented field and report 0 of 0 to the user forever.
const coverageOf = (covered) => ({
  draft_id: 9,
  job_post_id: 4,
  covered: covered ? 1 : 0,
  total: 2,
  keywords: [
    { term: 'Qiskit', bucket: 'technical', covered, hits: covered ? 1 : 0, where: covered ? ['p1'] : [] },
    { term: 'optimize', bucket: 'verb', covered: false, hits: 0, where: [] },
  ],
})

async function setup({ drafts = [DRAFT], draft = DRAFT, bank = BANK, jobPost = JOB_POST, coverage } = {}) {
  api.drafts.mockResolvedValue(drafts)
  api.bankEntries.mockResolvedValue(bank)
  api.draft.mockResolvedValue(draft)
  api.jobPost.mockResolvedValue(jobPost)
  api.draftCoverage.mockResolvedValue(coverage ?? coverageOf(false))
  api.updateDraft.mockImplementation(async (id, patch) => ({ ...draft, ...patch }))

  render(
    <ConfirmProvider>
      <Builder />
    </ConfirmProvider>,
  )
  if (drafts.length) await screen.findByRole('textbox', { name: /rename the experience section/i })
  else await screen.findByRole('button', { name: /start a resume/i })
}

const transfer = () => ({ setData: vi.fn(), getData: vi.fn(), dropEffect: '', effectAllowed: '' })

const drag = (from, onto, { drop = true } = {}) => {
  const dataTransfer = transfer()
  fireEvent.dragStart(from, { dataTransfer })
  fireEvent.dragEnter(onto, { dataTransfer })
  fireEvent.dragOver(onto, { dataTransfer })
  if (drop) fireEvent.drop(onto, { dataTransfer })
  fireEvent.dragEnd(from, { dataTransfer })
}

const row = (text) => screen.getByText(text).closest('li')

afterEach(() => {
  vi.clearAllMocks()
})

describe('Builder / the three panes', () => {
  it('puts the bank, the draft and the ad’s keywords side by side', async () => {
    await setup()
    expect(screen.getByText('Experience bank')).toBeInTheDocument()
    expect(screen.getByText('Research Assistant', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('Keyword coverage')).toBeInTheDocument()
  })

  it('gives each side pane a draggable divider', async () => {
    await setup()
    const labels = screen.getAllByRole('separator').map((handle) => handle.getAttribute('aria-label'))
    expect(labels).toEqual(
      expect.arrayContaining(['Resize the experience bank', 'Resize the coverage panel']),
    )
  })

  it('remembers a pane width across a remount', async () => {
    await setup()
    const handle = screen.getByRole('separator', { name: 'Resize the experience bank' })
    handle.focus()
    await userEvent.keyboard('{ArrowRight}')
    const widened = Number(handle.getAttribute('aria-valuenow'))
    expect(widened).toBeGreaterThan(240)

    cleanup()
    await setup()
    expect(
      Number(screen.getByRole('separator', { name: 'Resize the experience bank' }).getAttribute('aria-valuenow')),
    ).toBe(widened)
  })

  it('offers to start one when there is no draft at all', async () => {
    await setup({ drafts: [], draft: null })
    expect(screen.getByRole('button', { name: /start a resume/i })).toBeInTheDocument()
    expect(api.draft).not.toHaveBeenCalled()
  })

  it('does not ask for the ad before there is a draft to attach it to', async () => {
    // Otherwise the form is reachable with nothing behind it, and saving the
    // ad has no draft to point at.
    await setup({ drafts: [], draft: null })
    expect(screen.queryByRole('textbox', { name: /the ad/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Keyword coverage')).not.toBeInTheDocument()
  })
})

describe('Builder / an empty bank', () => {
  it('says so and points at the import, rather than rendering a blank column', async () => {
    await setup({ bank: [] })
    expect(screen.getByText(/your experience bank is empty/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import from my resume/i })).toHaveClass('btn-primary')
  })
})

describe('Builder / reordering bullets', () => {
  it('persists the new order to the server', async () => {
    await setup()
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'))

    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1))
    const [id, patch] = api.updateDraft.mock.calls[0]
    expect(id).toBe(9)
    expect(patch.body.sections[0].placements[0].bullets.map((b) => b.ref)).toEqual(['b2', 'b1'])
  })

  it('writes nothing when the drag is abandoned', async () => {
    await setup()
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'), { drop: false })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(api.updateDraft).not.toHaveBeenCalled()
  })
})

describe('Builder / the coverage feedback loop', () => {
  it('re-reads coverage after an edit, with no button to press', async () => {
    await setup()
    expect(screen.getByText('0/2')).toBeInTheDocument()

    // The whole reason the page exists: drag a bullet and watch the ad's
    // keyword go covered.
    api.draftCoverage.mockResolvedValue(coverageOf(true))
    drag(row('Halved calibration time'), row('Built the DAQ pipeline'))

    expect(await screen.findByText('1/2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Qiskit' })).toBeInTheDocument()
  })

  it('does not ask for coverage on a draft with no ad attached yet', async () => {
    await setup({ draft: { ...DRAFT, job_post_id: null }, jobPost: null })
    await waitFor(() => expect(api.jobPost).not.toHaveBeenCalled())
    expect(api.draftCoverage).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox', { name: /the ad/i })).toBeInTheDocument()
  })

  it('attaches a pasted ad to the draft', async () => {
    const user = userEvent.setup()
    api.createJobPost.mockResolvedValue(JOB_POST)
    await setup({ draft: { ...DRAFT, job_post_id: null }, jobPost: null })

    await user.type(screen.getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(screen.getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(screen.getByRole('button', { name: /save the ad/i }))

    await waitFor(() => expect(api.createJobPost).toHaveBeenCalled())
    expect(api.updateDraft).toHaveBeenCalledWith(9, { job_post_id: 4 })
  })
})

describe('Builder / the cold-start import', () => {
  const PREVIEW = {
    entries: [
      { kind: 'experience', title: 'Research Assistant', organization: 'Fermilab', bullets: [{ text: 'Built the DAQ pipeline' }] },
      { kind: 'project', title: 'Delphi', organization: null, bullets: [] },
    ],
  }

  it('writes nothing until the preview is confirmed', async () => {
    const user = userEvent.setup()
    api.importBank.mockResolvedValue(PREVIEW)
    await setup({ bank: [] })

    await user.click(screen.getByRole('button', { name: /import from my resume/i }))
    expect(await screen.findByText(/nothing is saved until you say so/i)).toBeInTheDocument()
    expect(api.createBankEntry).not.toHaveBeenCalled()
  })

  it('adds only the records left ticked, with their bullets', async () => {
    const user = userEvent.setup()
    api.importBank.mockResolvedValue(PREVIEW)
    api.createBankEntry.mockResolvedValue({ id: 50 })
    await setup({ bank: [] })

    await user.click(screen.getByRole('button', { name: /import from my resume/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getAllByRole('checkbox')[1])
    await user.click(within(panel).getByRole('button', { name: /add 1 to my bank/i }))

    await waitFor(() => expect(api.createBankEntry).toHaveBeenCalledTimes(1))
    expect(api.createBankEntry).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Research Assistant' }),
    )
    expect(api.createBankBullet).toHaveBeenCalledWith(50, { text: 'Built the DAQ pipeline' })
  })
})

describe('Builder / editing the bank', () => {
  it('opens a record in a panel and saves the entry and its bullets together', async () => {
    const user = userEvent.setup()
    api.updateBankEntry.mockResolvedValue({ id: 1 })
    await setup()

    await user.click(screen.getByRole('button', { name: 'Edit Research Assistant' }))
    const panel = await screen.findByRole('dialog')
    await user.clear(within(panel).getByRole('textbox', { name: 'Bullet 1' }))
    await user.type(within(panel).getByRole('textbox', { name: 'Bullet 1' }), 'Rebuilt the DAQ pipeline')
    await user.click(within(panel).getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(api.updateBankEntry).toHaveBeenCalledWith(1, expect.objectContaining({ title: 'Research Assistant' })))
    expect(api.updateBankBullet).toHaveBeenCalledWith(11, { text: 'Rebuilt the DAQ pipeline' })
    expect(api.updateBankBullet).toHaveBeenCalledTimes(1)
  })

  it('warns that the bullets go too before deleting a record', async () => {
    const user = userEvent.setup()
    await setup()
    await user.click(screen.getByRole('button', { name: 'Edit Research Assistant' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /delete/i }))

    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/keep their copy of the text/i)).toBeInTheDocument()
    expect(api.deleteBankEntry).not.toHaveBeenCalled()
  })
})

describe('Builder / tailoring', () => {
  const PROPOSAL = {
    id: 3,
    kind: 'tailor',
    summary: 'Leads with the simulation work.',
    operations: [
      { op: 'RewriteBullet', placement_id: 'p1', bullet_ref: 'b1', text: 'Rebuilt the DAQ pipeline' },
      { op: 'DropBullet', placement_id: 'p1', bullet_ref: 'b2' },
    ],
  }

  it('holds the button open for the call instead of polling for an answer', async () => {
    const user = userEvent.setup()
    let settle
    api.tailorDraft.mockReturnValue(new Promise((resolve) => (settle = resolve)))
    await setup({ coverage: coverageOf(false) })

    await user.click(screen.getByRole('button', { name: /tailor to this ad/i }))
    expect(screen.getByRole('button', { name: /tailoring…/i })).toBeDisabled()

    settle(PROPOSAL)
    expect(await screen.findByText('Leads with the simulation work.')).toBeInTheDocument()
    expect(api.tailorDraft).toHaveBeenCalledTimes(1)
  })

  it('applies only the operations left ticked', async () => {
    const user = userEvent.setup()
    api.tailorDraft.mockResolvedValue(PROPOSAL)
    api.resolveProposal.mockResolvedValue({ ...DRAFT })
    await setup()

    await user.click(screen.getByRole('button', { name: /tailor to this ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getAllByRole('checkbox')[1])
    await user.click(within(panel).getByRole('button', { name: /apply 1 of 2/i }))

    // `ProposalResolve` is {action, operations}. The whole reviewed set goes
    // back, because the server treats an operation left out as one the user
    // did not accept.
    await waitFor(() =>
      expect(api.resolveProposal).toHaveBeenCalledWith(3, {
        action: 'apply',
        operations: [
          { ...PROPOSAL.operations[0], accepted: true },
          { ...PROPOSAL.operations[1], accepted: false },
        ],
      }),
    )
  })

  it('discards the whole proposal without applying any of it', async () => {
    const user = userEvent.setup()
    api.tailorDraft.mockResolvedValue(PROPOSAL)
    api.resolveProposal.mockResolvedValue({ ...DRAFT })
    await setup()

    await user.click(screen.getByRole('button', { name: /tailor to this ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getByRole('button', { name: /discard all/i }))

    await waitFor(() =>
      expect(api.resolveProposal).toHaveBeenCalledWith(3, { action: 'dismiss' }),
    )
  })
})

describe('Builder / pushing to a resume', () => {
  it('writes the draft out when nothing has diverged', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockResolvedValue({ diverged: false, pushed_at: '2026-10-07T12:00:00Z' })
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))
    await waitFor(() => expect(api.pushDraft).toHaveBeenCalledWith(9))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('shows the hand-edit before overwriting it', async () => {
    // The LaTeX editor stays the escape hatch, so a push must never silently
    // replace work done there.
    const user = userEvent.setup()
    api.pushDraft.mockResolvedValue({ diverged: true })
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/edited by hand/i)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /replace it/i }))
    await waitFor(() => expect(api.pushDraft).toHaveBeenCalledWith(9, true))
  })

  it('leaves the resume alone when the overwrite is refused', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockResolvedValue({ diverged: true })
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: /cancel/i }))
    expect(api.pushDraft).toHaveBeenCalledTimes(1)
  })
})

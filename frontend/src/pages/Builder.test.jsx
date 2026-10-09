import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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
      placeDraftEntry: vi.fn(),
      pushDraft: vi.fn(),
      tailorDraft: vi.fn(),
      draftProposals: vi.fn(),
      resolveProposal: vi.fn(),
      bankEntries: vi.fn(),
      createBankEntry: vi.fn(),
      updateBankEntry: vi.fn(),
      deleteBankEntry: vi.fn(),
      createBankBullet: vi.fn(),
      updateBankBullet: vi.fn(),
      deleteBankBullet: vi.fn(),
      importBank: vi.fn(),
      resumeContact: vi.fn(),
      resumeLibrary: vi.fn(),
      resumeSlots: vi.fn(),
      writeResumeSlot: vi.fn(),
      placeInResumeSlot: vi.fn(),
      resumeCoverage: vi.fn(),
      resumeInstance: vi.fn(),
      tailorResume: vi.fn(),
      resumeProposals: vi.fn(),
      resolveResumeProposal: vi.fn(),
      updateResumeInstance: vi.fn(),
      compileResumeInstance: vi.fn(),
      saveResumeContact: vi.fn(),
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

const CONTACT = { name: '', location: '', email: '', phone: '', links: [] }

async function setup({
  drafts = [DRAFT], draft = DRAFT, bank = BANK, jobPost = JOB_POST, coverage, proposals = [],
  contact = CONTACT, route = '/builder', library, slots, slotsError,
} = {}) {
  api.resumeContact.mockResolvedValue(contact)
  if (slotsError) api.resumeSlots.mockRejectedValue(slotsError)
  else api.resumeSlots.mockResolvedValue(slots ?? [])
  api.resumeLibrary.mockResolvedValue(
    library ?? drafts.map((row) => ({
      key: `draft:${row.id}`, draft_id: row.id, instance_id: null, name: row.name,
      composed: true, pushed: false, has_pdf: false, is_default: false,
      compile_ok: false, linked_count: 0, updated_at: null,
    })),
  )
  api.drafts.mockResolvedValue(drafts)
  api.bankEntries.mockResolvedValue(bank)
  api.draft.mockResolvedValue(draft)
  api.jobPost.mockResolvedValue(jobPost)
  api.draftCoverage.mockResolvedValue(coverage ?? coverageOf(false))
  api.draftProposals.mockResolvedValue(proposals)
  api.updateDraft.mockImplementation(async (id, patch) => ({ ...draft, ...patch }))

  render(
    <MemoryRouter initialEntries={[route]}>
      <ConfirmProvider>
        <Builder />
      </ConfirmProvider>
    </MemoryRouter>,
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

describe('Builder / placing a record from the bank', () => {
  it('asks the server to cut the snapshot, and shows what it sent back', async () => {
    const placed = {
      ...DRAFT,
      body: {
        sections: [
          {
            ...BODY.sections[0],
            placements: [
              ...BODY.sections[0].placements,
              { ref: 'p9', entry_id: 1, kind: 'project', title: 'Delphi', bullets: [] },
            ],
          },
        ],
      },
    }
    api.placeDraftEntry.mockResolvedValue(placed)
    await setup()

    const dataTransfer = transfer()
    fireEvent.dragStart(
      screen.getByRole('button', { name: 'Edit Research Assistant' }).closest('li'),
      { dataTransfer },
    )
    fireEvent.drop(screen.getByDisplayValue('Experience').closest('section'), { dataTransfer })

    await waitFor(() =>
      expect(api.placeDraftEntry).toHaveBeenCalledWith(9, { entry_id: 1, section_ref: 's1' }),
    )
    expect(api.updateDraft).not.toHaveBeenCalled()
    expect(await screen.findByText('Delphi')).toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: /paste the job ad/i })).toBeInTheDocument()
  })

  it('attaches a pasted ad to the draft', async () => {
    const user = userEvent.setup()
    api.createJobPost.mockResolvedValue(JOB_POST)
    await setup({ draft: { ...DRAFT, job_post_id: null }, jobPost: null })

    await user.click(screen.getByRole('button', { name: /paste the job ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(within(panel).getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(within(panel).getByRole('button', { name: /save the ad/i }))

    await waitFor(() => expect(api.createJobPost).toHaveBeenCalled())
    expect(api.updateDraft).toHaveBeenCalledWith(9, { job_post_id: 4 })
    // The panel closes itself once the ad is stored.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

describe('Builder / the cold-start import', () => {
  const PREVIEW = {
    entries: [
      { kind: 'experience', title: 'Research Assistant', organization: 'Fermilab', bullets: ['Built the DAQ pipeline'] },
      { kind: 'project', title: 'Delphi', organization: null, bullets: [] },
    ],
  }

  it('writes nothing until the preview is confirmed', async () => {
    const user = userEvent.setup()
    api.importBank.mockResolvedValue(PREVIEW)
    await setup({ bank: [] })

    await user.click(screen.getByRole('button', { name: /import from my resume/i }))
    expect(await screen.findByText(/nothing is saved until you say so/i)).toBeInTheDocument()
    expect(screen.getByText('Built the DAQ pipeline', { selector: 'li' })).toBeInTheDocument()
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
    expect(api.createBankEntry).toHaveBeenCalledWith(PREVIEW.entries[0])
    expect(api.createBankBullet).not.toHaveBeenCalled()
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

describe('Builder / drift waiting on a decision', () => {
  const SYNC = {
    id: 12,
    kind: 'sync',
    status: 'pending',
    summary: '1 bullet changed in the bank since this draft was composed.',
    operations: [
      {
        op: 'RewriteBullet',
        accepted: true,
        placement_id: 'p1',
        bullet_ref: 'b1',
        bullet_id: 11,
        text: 'Rebuilt the DAQ pipeline',
      },
    ],
  }

  it('offers the standing proposal the server is holding', async () => {
    await setup({ proposals: [SYNC] })
    expect(api.draftProposals).toHaveBeenCalledWith(9)
    expect(screen.getByRole('button', { name: 'Review 1 change' })).toBeInTheDocument()
  })

  it('says nothing when the draft is up to date with the bank', async () => {
    await setup()
    expect(screen.queryByRole('button', { name: /review \d+ change/i })).not.toBeInTheDocument()
  })

  it('opens it for review and applies the id the list handed out', async () => {
    const user = userEvent.setup()
    api.resolveProposal.mockResolvedValue({ ...DRAFT })
    await setup({ proposals: [SYNC] })

    await user.click(screen.getByRole('button', { name: 'Review 1 change' }))
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/your bank has moved on/i)).toBeInTheDocument()
    api.draftProposals.mockResolvedValue([])
    await user.click(within(panel).getByRole('button', { name: /apply 1 of 1/i }))

    await waitFor(() =>
      expect(api.resolveProposal).toHaveBeenCalledWith(12, {
        action: 'apply',
        operations: [{ ...SYNC.operations[0], accepted: true }],
      }),
    )
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /review \d+ change/i })).not.toBeInTheDocument(),
    )
  })
})

describe('Builder / pushing to a resume', () => {
  // The shape src/api.test.js pins: a 409 reaches a caller as a throw
  // carrying the status and the parsed detail.
  const refused = () =>
    Object.assign(new Error('edited by hand'), {
      status: 409,
      detail: { diverged: true, current_latex: '% by hand' },
    })

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
    api.pushDraft.mockRejectedValueOnce(refused()).mockResolvedValue({ diverged: false })
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))
    const dialog = await screen.findByRole('alertdialog')
    // The work about to be lost, not a description of it.
    expect(within(dialog).getByText('% by hand')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /replace it/i }))
    await waitFor(() => expect(api.pushDraft).toHaveBeenCalledWith(9, true))
  })

  it('reports a push that failed for any other reason', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockRejectedValue(
      Object.assign(new Error('The resume template has no %%RESUME-BODY%% marker'), { status: 400 }),
    )
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))

    expect(await screen.findByText(/no %%RESUME-BODY%% marker/)).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('leaves the resume alone when the overwrite is refused', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockRejectedValue(refused())
    await setup()

    await user.click(screen.getByRole('button', { name: /push to resume/i }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: /cancel/i }))
    expect(api.pushDraft).toHaveBeenCalledTimes(1)
  })
})

describe('Builder / adding into a group', () => {
  const PROJECT = { id: 2, kind: 'project', title: 'Delphi', bullets: [] }

  it('opens the editor on the kind of the group whose plus was pressed', async () => {
    const user = userEvent.setup()
    api.createBankEntry.mockResolvedValue({ id: 9 })
    await setup({ bank: [BANK[0], PROJECT] })

    await user.click(screen.getByRole('button', { name: 'Add a record to Project' }))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /project/i }), 'SHEQ')
    await user.click(within(panel).getByRole('button', { name: /save/i }))

    await waitFor(() =>
      expect(api.createBankEntry).toHaveBeenCalledWith(expect.objectContaining({ kind: 'project' })),
    )
  })

  it('switches kind when a second group is pressed with the panel still open', async () => {
    // The rail stays reachable behind the panel, so this is a real path. The
    // form is keyed, and a key that did not move with the kind left the open
    // form on whichever group was pressed first.
    const user = userEvent.setup()
    api.createBankEntry.mockResolvedValue({ id: 9 })
    await setup({ bank: [BANK[0], PROJECT] })

    await user.click(screen.getByRole('button', { name: 'Add a record to Project' }))
    await screen.findByRole('dialog')
    await user.click(screen.getByRole('button', { name: 'Add a record to Experience' }))

    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /role/i }), 'Intern')
    await user.click(within(panel).getByRole('button', { name: /save/i }))

    await waitFor(() =>
      expect(api.createBankEntry).toHaveBeenCalledWith(expect.objectContaining({ kind: 'experience' })),
    )
  })
})

describe('Builder / naming the resume', () => {
  const openRename = async (user) => {
    await user.click(screen.getByRole('button', { name: 'Rename this resume' }))
    return screen.getByRole('textbox', { name: 'Resume name' })
  }

  it('shows a switcher and a rename control, not two fields holding the name', async () => {
    await setup()

    expect(screen.getByRole('button', { name: /switch resume/i })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Resume name' })).not.toBeInTheDocument()
  })

  it('renames the open draft', async () => {
    const user = userEvent.setup()
    api.updateDraft.mockResolvedValue({ ...DRAFT, name: 'ML Engineer, Argonne' })
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    await user.type(field, 'ML Engineer, Argonne')
    fireEvent.blur(field)

    await waitFor(() =>
      expect(api.updateDraft).toHaveBeenCalledWith(DRAFT.id, { name: 'ML Engineer, Argonne' }),
    )
  })

  it('writes nothing when the field is left at the name it already had', async () => {
    const user = userEvent.setup()
    await setup()

    fireEvent.blur(await openRename(user))

    expect(api.updateDraft).not.toHaveBeenCalled()
  })

  it('writes nothing when the name is cleared, rather than storing an empty one', async () => {
    const user = userEvent.setup()
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    fireEvent.blur(field)

    expect(api.updateDraft).not.toHaveBeenCalled()
  })

  it('discards an edit abandoned with escape', async () => {
    const user = userEvent.setup()
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    await user.type(field, 'Half typed')
    fireEvent.keyDown(field, { key: 'Escape' })
    fireEvent.blur(field)

    expect(api.updateDraft).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /switch resume/i })).toBeInTheDocument()
  })
})

describe('Builder / the contact details', () => {
  const FILLED = {
    name: 'Jordan Reyes',
    location: 'Chicago, IL',
    email: 'morgan@example.edu',
    phone: '',
    links: [{ label: 'github.com/me', url: 'https://github.com/me' }],
  }

  it('prints the stored details at the top of the canvas, where they land', async () => {
    await setup({ contact: FILLED })

    expect(await screen.findByText('Jordan Reyes')).toBeInTheDocument()
    expect(screen.getByText('Chicago, IL · morgan@example.edu')).toBeInTheDocument()
    expect(screen.getByText('github.com/me')).toBeInTheDocument()
  })

  it('says so when there are none, rather than printing an empty heading', async () => {
    await setup()

    expect(await screen.findByText(/add your name and contact details/i)).toBeInTheDocument()
  })

  it('saves what the form collects', async () => {
    const user = userEvent.setup()
    api.saveResumeContact.mockResolvedValue({ ...CONTACT, name: 'Jordan Reyes' })
    api.draft.mockResolvedValue(DRAFT)
    await setup()

    await user.click(await screen.findByText(/add your name and contact details/i))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: 'Name' }), 'Jordan Reyes')
    await user.click(within(panel).getByRole('button', { name: /save contact details/i }))

    await waitFor(() =>
      expect(api.saveResumeContact).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Jordan Reyes' }),
      ),
    )
  })

  it('drops a link row left with no address', async () => {
    const user = userEvent.setup()
    api.saveResumeContact.mockResolvedValue(CONTACT)
    api.draft.mockResolvedValue(DRAFT)
    await setup({ contact: FILLED })

    await user.click(screen.getByRole('button', { name: /edit your contact details/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getByRole('button', { name: /add a link/i }))
    await user.click(within(panel).getByRole('button', { name: /save contact details/i }))

    await waitFor(() => expect(api.saveResumeContact).toHaveBeenCalled())
    expect(api.saveResumeContact.mock.calls[0][0].links).toEqual([
      { label: 'github.com/me', url: 'https://github.com/me' },
    ])
  })
})

describe('Builder / the way through to Resumes', () => {
  const PUSHED = { ...DRAFT, resume_instance_id: 12 }

  it('offers the resume a pushed draft became, beside the page it rendered', async () => {
    // In the preview pane rather than the toolbar: it is what you want next
    // after looking at the page, and the toolbar had five controls already.
    const user = userEvent.setup()
    await setup({ draft: PUSHED })

    await user.click(screen.getByRole('tab', { name: /preview/i }))

    expect(screen.getByRole('link', { name: /open in resumes/i })).toHaveAttribute(
      'href',
      '/resumes?instance=12',
    )
  })

  it('offers nothing to open before the draft has been pushed', async () => {
    const user = userEvent.setup()
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))

    expect(screen.queryByRole('link', { name: /open in resumes/i })).not.toBeInTheDocument()
  })

  it('opens the draft named in the url rather than the newest one', async () => {
    const second = { ...DRAFT, id: 77, name: 'Second resume' }
    api.draft.mockResolvedValue(second)
    await setup({ drafts: [DRAFT, second], draft: second, route: '/builder?draft=77' })

    await waitFor(() => expect(api.draft).toHaveBeenCalledWith(77))
  })

  it('falls back to the newest when the url names a draft that is gone', async () => {
    await setup({ route: '/builder?draft=4040' })

    await waitFor(() => expect(api.draft).toHaveBeenCalledWith(DRAFT.id))
  })
})

describe('Builder / seeing the page without leaving', () => {
  it('pushes, compiles and shows the pdf from the right rail', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockResolvedValue({ ...DRAFT, resume_instance_id: 12, pushed: true })
    api.compileResumeInstance.mockResolvedValue({
      id: 12, has_pdf: true, compiled_at: '2026-10-08T10:00:00', compile_errors: [],
    })
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))
    await user.click(screen.getByRole('button', { name: /push and render/i }))

    await waitFor(() => expect(api.compileResumeInstance).toHaveBeenCalledWith(12))
  })

  it('says what went wrong rather than showing a blank frame', async () => {
    const user = userEvent.setup()
    api.pushDraft.mockResolvedValue({ ...DRAFT, resume_instance_id: 12, pushed: true })
    api.compileResumeInstance.mockResolvedValue({
      id: 12, has_pdf: false, compile_errors: [{ line: 4, message: 'Undefined control sequence' }],
    })
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))
    await user.click(screen.getByRole('button', { name: /push and render/i }))

    expect(await screen.findByText(/undefined control sequence/i)).toBeInTheDocument()
  })

  it('sends someone whose resume was hand-edited back to the push button', async () => {
    const user = userEvent.setup()
    const conflict = Object.assign(new Error('conflict'), { status: 409 })
    api.pushDraft.mockRejectedValue(conflict)
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))
    await user.click(screen.getByRole('button', { name: /push and render/i }))

    expect(await screen.findByText(/edited by hand/i)).toBeInTheDocument()
    expect(api.compileResumeInstance).not.toHaveBeenCalled()
  })
})

describe('Builder / one surface with two sides', () => {
  it('offers both sides, with this one selected', async () => {
    await setup({ draft: { ...DRAFT, resume_instance_id: 12 } })

    const tabs = screen.getAllByRole('tab').filter((tab) => /compose|source/i.test(tab.textContent))
    expect(tabs.map((tab) => [tab.textContent.trim(), tab.getAttribute('aria-selected')])).toEqual([
      ['Compose', 'true'],
      ['Source', 'false'],
    ])
  })

  it('disables the side that has nothing behind it, rather than hiding it', async () => {
    // A control that comes and goes as you move down the list is harder to
    // find than one that is there and says why it cannot be used.
    await setup()

    const source = screen.getAllByRole('tab').find((tab) => /source/i.test(tab.textContent))
    expect(source).toBeDisabled()
    expect(source).toHaveAttribute('title', expect.stringMatching(/push it/i))
  })

  it('offers every resume in the switcher, not only the composable ones', async () => {
    await setup({
      library: [
        { key: 'draft:9', draft_id: 9, instance_id: null, name: 'On the canvas', composed: true, pushed: false },
        { key: 'instance:4', draft_id: null, instance_id: 4, name: 'Written by hand', composed: false, pushed: true },
      ],
    })

    const switcher = screen.getByRole('button', { name: /switch resume/i })
    await userEvent.setup().click(switcher)

    expect(screen.getByRole('option', { name: 'Written by hand' })).toBeInTheDocument()
  })
})

describe('Builder / composing a document that has slots', () => {
  const PUSHED = { ...DRAFT, resume_instance_id: 12 }
  const SLOTS = [
    {
      key: 'experience',
      name: 'Experience',
      blocks: [
        {
          kind: 'entry', raw: '', heading: 'resumeSubheading',
          args: ['Fermilab', '2026', 'Intern', 'Batavia, IL'],
          bullets: ['Calibrated the readout'],
        },
        { kind: 'opaque', raw: '\\hrule', heading: null, args: [], bullets: [] },
      ],
    },
  ]

  it('lays the document out by its own regions once it has them', async () => {
    await setup({ draft: PUSHED, slots: SLOTS })

    expect(await screen.findByText('Intern')).toBeInTheDocument()
    expect(screen.getByText('Calibrated the readout')).toBeInTheDocument()
  })

  it('shows a block it could not read as the source it is, rather than hiding it', async () => {
    await setup({ draft: PUSHED, slots: SLOTS })

    expect(await screen.findByText(/your own latex/i)).toBeInTheDocument()
    expect(screen.getByText('\\hrule')).toBeInTheDocument()
  })

  it('offers no way to rename or remove a region, because the document owns those', async () => {
    await setup({ draft: PUSHED, slots: SLOTS })

    await screen.findByText('Intern')
    expect(screen.queryByRole('textbox', { name: /rename the/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove the .* section/i })).not.toBeInTheDocument()
  })

  it('writes a removal back into the document', async () => {
    const user = userEvent.setup()
    api.writeResumeSlot.mockResolvedValue(SLOTS)
    await setup({ draft: PUSHED, slots: SLOTS })

    await user.click(await screen.findByRole('button', { name: /remove intern/i }))

    await waitFor(() => expect(api.writeResumeSlot).toHaveBeenCalledWith(12, 'experience', [
      SLOTS[0].blocks[1],
    ]))
  })

  it('says so when the markers do not pair up, rather than looking empty', async () => {
    await setup({
      draft: PUSHED,
      slotsError: Object.assign(new Error('Slot x is never closed.'), { status: 409 }),
    })

    expect(await screen.findByText(/never closed/i)).toBeInTheDocument()
  })

  it('leaves a draft with no document on the old canvas', async () => {
    await setup()

    expect(await screen.findByRole('textbox', { name: /rename the experience section/i })).toBeInTheDocument()
  })
})

describe('Builder / tailoring a document rather than a draft', () => {
  const PUSHED = { ...DRAFT, resume_instance_id: 12 }
  const SLOTS = [{
    key: 'experience', name: 'Experience',
    blocks: [{
      kind: 'entry', raw: '', heading: 'resumeSubheading',
      args: ['Fermilab', '2026', 'Intern', 'Batavia, IL'],
      args_text: ['Fermilab', '2026', 'Intern', 'Batavia, IL'],
      bullets: ['Calibrated the readout'], bullets_text: ['Calibrated the readout'],
    }],
  }]
  const PROPOSAL = {
    id: 5, resume_instance_id: 12, status: 'pending', summary: 'Leads with the build',
    operations: [{ op: 'RewriteBullet', slot: 'experience', block: 0, bullet: 0,
                   text: 'Rebuilt the readout', accepted: true, rationale: 'mirrors the ad' }],
  }

  it('asks the document for a plan, not the draft behind it', async () => {
    const user = userEvent.setup()
    api.tailorResume.mockResolvedValue(PROPOSAL)
    await setup({ draft: PUSHED, slots: SLOTS, jobPost: JOB_POST, coverage: coverageOf(true) })

    await user.click(await screen.findByRole('button', { name: /tailor to this ad/i }))

    await waitFor(() => expect(api.tailorResume).toHaveBeenCalledWith(12))
    expect(api.tailorDraft).not.toHaveBeenCalled()
  })

  it('resolves against the document and re-reads its slots', async () => {
    const user = userEvent.setup()
    api.tailorResume.mockResolvedValue(PROPOSAL)
    api.resolveResumeProposal.mockResolvedValue({ ...PROPOSAL, status: 'applied' })
    await setup({ draft: PUSHED, slots: SLOTS, jobPost: JOB_POST, coverage: coverageOf(true) })

    await user.click(await screen.findByRole('button', { name: /tailor to this ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getByRole('button', { name: /apply/i }))

    await waitFor(() => expect(api.resolveResumeProposal).toHaveBeenCalled())
    expect(api.resolveProposal).not.toHaveBeenCalled()
    expect(api.resumeSlots).toHaveBeenCalledWith(12)
  })

  it('attaches a pasted ad to the document, which is what measures against it', async () => {
    const user = userEvent.setup()
    api.createJobPost.mockResolvedValue(JOB_POST)
    api.updateResumeInstance.mockResolvedValue({ id: 12 })
    await setup({ draft: { ...PUSHED, job_post_id: null }, slots: SLOTS, jobPost: null })

    await user.click(await screen.findByRole('button', { name: /paste the job ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(within(panel).getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(within(panel).getByRole('button', { name: /save the ad/i }))

    await waitFor(() =>
      expect(api.updateResumeInstance).toHaveBeenCalledWith(12, { job_post_id: 4 }))
    expect(api.updateDraft).not.toHaveBeenCalledWith(9, { job_post_id: 4 })
  })
})

describe('Builder / a document that failed to load its panel', () => {
  it('still lays out the slots it did load', async () => {
    // A coverage call that fell over is not a reason to blank the canvas.
    api.resumeCoverage.mockRejectedValue(new Error('coverage is down'))
    await setup({
      draft: { ...DRAFT, resume_instance_id: 12 },
      slots: [{
        key: 'experience', name: 'Experience',
        blocks: [{ kind: 'entry', raw: '', heading: 'resumeSubheading',
                   args_text: ['Fermilab', '2026', 'Intern', 'Batavia, IL'],
                   args: [], bullets: [], bullets_text: [] }],
      }],
    })

    expect(await screen.findByText('Intern')).toBeInTheDocument()
  })
})

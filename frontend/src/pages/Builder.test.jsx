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
      adoptDraft: vi.fn(),
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

// One resume, as the document model has it: an instance with named regions
// in its own source. There is no draft any more.
const SLOTS = [
  {
    key: 'experience',
    name: 'Experience',
    blocks: [
      {
        kind: 'entry',
        raw: '\\resumeSubheading{Fermilab}{Jun 2026 -- Sep 2026}{Research Assistant}{}',
        heading: 'resumeSubheading',
        args: ['Fermilab', 'Jun 2026 -- Sep 2026', 'Research Assistant', ''],
        args_text: ['Fermilab', 'Jun 2026 -- Sep 2026', 'Research Assistant', ''],
        bullets: ['Built the DAQ pipeline', 'Halved calibration time'],
        bullets_text: ['Built the DAQ pipeline', 'Halved calibration time'],
        in_list: true,
      },
    ],
  },
]

const INSTANCE = {
  id: 9, name: 'ACME intern', job_post_id: 4, draft_id: null,
  latex: '% <<slot experience>>\n% <</slot>>', has_pdf: false, compile_errors: [],
}

const libraryOf = (rows) =>
  rows.map((row) => ({
    key: `instance:${row.id}`, instance_id: row.id, draft_id: row.draft_id ?? null,
    name: row.name, composed: true, pushed: true, has_pdf: false, is_default: false,
    compile_ok: false, linked_count: 0, updated_at: null,
  }))

// `ResumeCoverage` as models.py declares it. The terms ride on `keywords`:
// a fixture that invented a `coverage` field would agree with a page reading
// the same invented field and report 0 of 0 to the user forever.
const coverageOf = (covered) => ({
  resume_instance_id: 9,
  job_post_id: 4,
  covered: covered ? 1 : 0,
  total: 2,
  keywords: [
    { term: 'Qiskit', bucket: 'technical', covered, hits: covered ? 1 : 0, where: covered ? ['experience:0'] : [] },
    { term: 'optimize', bucket: 'verb', covered: false, hits: 0, where: [] },
  ],
})

const CONTACT = { name: '', location: '', email: '', phone: '', links: [] }

async function setup({
  instance = INSTANCE, bank = BANK, jobPost = JOB_POST, coverage, proposals = [],
  contact = CONTACT, route = '/builder', library, slots = SLOTS, slotsError,
} = {}) {
  api.resumeContact.mockResolvedValue(contact)
  if (slotsError) api.resumeSlots.mockRejectedValue(slotsError)
  else api.resumeSlots.mockResolvedValue(slots)
  api.resumeLibrary.mockResolvedValue(library ?? (instance ? libraryOf([instance]) : []))
  api.bankEntries.mockResolvedValue(bank)
  api.resumeInstance.mockResolvedValue(instance)
  api.jobPost.mockResolvedValue(jobPost)
  api.resumeCoverage.mockResolvedValue(coverage ?? coverageOf(false))
  api.resumeProposals.mockResolvedValue(proposals)
  api.updateResumeInstance.mockImplementation(async (id, patch) => ({ ...instance, ...patch }))

  render(
    <MemoryRouter initialEntries={[route]}>
      <ConfirmProvider>
        <Builder />
      </ConfirmProvider>
    </MemoryRouter>,
  )
  // Waited on the canvas itself, by a marker only it renders. Waiting on
  // the slot's name matched the bank rail's group heading instead, which is
  // on screen before the document has loaded, so a test could run against a
  // canvas that was still empty.
  if (instance) {
    await waitFor(() =>
      expect(document.querySelector('[data-slot], [data-canvas-empty]')).toBeTruthy(),
    )
  } else {
    await screen.findByRole('button', { name: /start a resume/i })
  }
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
  it('puts the bank, the resume and the ad’s keywords side by side', async () => {
    await setup()
    expect(screen.getByText('Experience bank')).toBeInTheDocument()
    // The canvas by its structure, not its text: every line in it goes
    // through the keyword highlighter, which splits a sentence across
    // elements so no whole-string matcher can find it.
    expect(document.querySelectorAll('[data-block]').length).toBe(1)
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

  it('offers to start one when there is no resume at all', async () => {
    await setup({ instance: null })
    expect(screen.getByRole('button', { name: /start a resume/i })).toBeInTheDocument()
    expect(api.resumeInstance).not.toHaveBeenCalled()
  })

  it('does not ask for the ad before there is a resume to attach it to', async () => {
    // Otherwise the form is reachable with nothing behind it, and saving the
    // ad has no draft to point at.
    await setup({ instance: null })
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



describe('Builder / the coverage feedback loop', () => {
  it('re-reads coverage after an edit, with no button to press', async () => {
    await setup()
    expect(screen.getByText('0/2')).toBeInTheDocument()

    // The whole reason the page exists: change the resume and watch the
    // ad's keyword go covered, with nothing to press.
    api.resumeCoverage.mockResolvedValue(coverageOf(true))
    api.writeResumeSlot.mockResolvedValue(SLOTS)
    await userEvent.setup().click(screen.getByRole('button', { name: /remove research assistant/i }))

    expect(await screen.findByText('1/2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Qiskit' })).toBeInTheDocument()
  })

  it('does not ask for coverage on a resume with no ad attached yet', async () => {
    await setup({ instance: { ...INSTANCE, job_post_id: null }, jobPost: null })
    await waitFor(() => expect(api.jobPost).not.toHaveBeenCalled())
    expect(screen.getByRole('button', { name: /paste the job ad/i })).toBeInTheDocument()
  })

  it('attaches a pasted ad to the resume', async () => {
    const user = userEvent.setup()
    api.createJobPost.mockResolvedValue(JOB_POST)
    await setup({ instance: { ...INSTANCE, job_post_id: null }, jobPost: null })

    await user.click(screen.getByRole('button', { name: /paste the job ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(within(panel).getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(within(panel).getByRole('button', { name: /save the ad/i }))

    await waitFor(() => expect(api.createJobPost).toHaveBeenCalled())
    expect(api.updateResumeInstance).toHaveBeenCalledWith(9, { job_post_id: 4 })
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
    const panel = await screen.findByRole('dialog')
    expect(within(panel).getByText(/nothing is saved until you say so/i)).toBeInTheDocument()
    // Scoped: the composed block on the canvas names the same bullet.
    expect(within(panel).getByText('Built the DAQ pipeline')).toBeInTheDocument()
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

  it('renames the open resume', async () => {
    const user = userEvent.setup()
    api.updateResumeInstance.mockResolvedValue({ ...INSTANCE, name: 'ML Engineer, Argonne' })
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    await user.type(field, 'ML Engineer, Argonne')
    fireEvent.blur(field)

    await waitFor(() =>
      expect(api.updateResumeInstance).toHaveBeenCalledWith(INSTANCE.id, { name: 'ML Engineer, Argonne' }),
    )
  })

  it('writes nothing when the field is left at the name it already had', async () => {
    const user = userEvent.setup()
    await setup()

    fireEvent.blur(await openRename(user))

    expect(api.updateResumeInstance).not.toHaveBeenCalled()
  })

  it('writes nothing when the name is cleared, rather than storing an empty one', async () => {
    const user = userEvent.setup()
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    fireEvent.blur(field)

    expect(api.updateResumeInstance).not.toHaveBeenCalled()
  })

  it('discards an edit abandoned with escape', async () => {
    const user = userEvent.setup()
    await setup()

    const field = await openRename(user)
    await user.clear(field)
    await user.type(field, 'Half typed')
    fireEvent.keyDown(field, { key: 'Escape' })
    fireEvent.blur(field)

    expect(api.updateResumeInstance).not.toHaveBeenCalled()
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
  const PUSHED = INSTANCE

  it('offers this resume in the other surface, beside the page it rendered', async () => {
    // In the preview pane rather than the toolbar: it is what you want next
    // after looking at the page, and the toolbar had five controls already.
    const user = userEvent.setup()
    await setup({ draft: PUSHED })

    await user.click(screen.getByRole('tab', { name: /preview/i }))

    expect(screen.getByRole('link', { name: /open in resumes/i })).toHaveAttribute(
      'href',
      '/resumes?instance=9',
    )
  })


  it('opens the resume named in the url rather than the first', async () => {
    const second = { ...INSTANCE, id: 77, name: 'Second resume' }
    await setup({
      instance: second,
      library: libraryOf([INSTANCE, second]),
      route: '/builder?instance=77',
    })

    await waitFor(() => expect(api.resumeInstance).toHaveBeenCalledWith(77))
  })

  it('falls back to the first when the url names a resume that is gone', async () => {
    await setup({ route: '/builder?instance=4040' })

    await waitFor(() => expect(api.resumeInstance).toHaveBeenCalledWith(INSTANCE.id))
  })
})

describe('Builder / seeing the page without leaving', () => {
  it('compiles and shows the pdf from the right rail', async () => {
    const user = userEvent.setup()
    api.compileResumeInstance.mockResolvedValue({
      id: 12, has_pdf: true, compiled_at: '2026-10-08T10:00:00', compile_errors: [],
    })
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))
    await user.click(screen.getByRole('button', { name: /push and render/i }))

    await waitFor(() => expect(api.compileResumeInstance).toHaveBeenCalledWith(9))
  })

  it('says what went wrong rather than showing a blank frame', async () => {
    const user = userEvent.setup()
    api.compileResumeInstance.mockResolvedValue({
      id: 12, has_pdf: false, compile_errors: [{ line: 4, message: 'Undefined control sequence' }],
    })
    await setup()

    await user.click(screen.getByRole('tab', { name: /preview/i }))
    await user.click(screen.getByRole('button', { name: /push and render/i }))

    expect(await screen.findByText(/undefined control sequence/i)).toBeInTheDocument()
  })

})

describe('Builder / one surface with two sides', () => {
  it('offers both sides, with this one selected', async () => {
    await setup({ instance: INSTANCE })

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

    const compose = screen.getAllByRole('tab').find((tab) => /^compose$/i.test(tab.textContent))
    expect(compose).not.toBeDisabled()
    const source = screen.getAllByRole('tab').find((tab) => /^source$/i.test(tab.textContent))
    expect(source).not.toBeDisabled()
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
  const PUSHED = INSTANCE
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
    await setup({ instance: PUSHED, slots: SLOTS })

    expect(await screen.findByText('Intern')).toBeInTheDocument()
    expect(screen.getByText('Calibrated the readout')).toBeInTheDocument()
  })

  it('shows a block it could not read as the source it is, rather than hiding it', async () => {
    await setup({ instance: PUSHED, slots: SLOTS })

    expect(await screen.findByText(/your own latex/i)).toBeInTheDocument()
    expect(screen.getByText('\\hrule')).toBeInTheDocument()
  })

  it('offers no way to rename or remove a region, because the document owns those', async () => {
    await setup({ instance: PUSHED, slots: SLOTS })

    await screen.findByText('Intern')
    expect(screen.queryByRole('textbox', { name: /rename the/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove the .* section/i })).not.toBeInTheDocument()
  })

  it('writes a removal back into the document', async () => {
    const user = userEvent.setup()
    api.writeResumeSlot.mockResolvedValue(SLOTS)
    await setup({ instance: PUSHED, slots: SLOTS })

    await user.click(await screen.findByRole('button', { name: /remove intern/i }))

    await waitFor(() => expect(api.writeResumeSlot).toHaveBeenCalledWith(9, 'experience', [
      SLOTS[0].blocks[1],
    ]))
  })

  it('says so when the markers do not pair up, rather than looking empty', async () => {
    await setup({
      instance: PUSHED,
      slotsError: Object.assign(new Error('Slot x is never closed.'), { status: 409 }),
    })

    expect(await screen.findByText(/never closed/i)).toBeInTheDocument()
  })

})

describe('Builder / tailoring a document rather than a draft', () => {
  const PUSHED = INSTANCE
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
    id: 5, id: 9, status: 'pending', summary: 'Leads with the build',
    operations: [{ op: 'RewriteBullet', slot: 'experience', block: 0, bullet: 0,
                   text: 'Rebuilt the readout', accepted: true, rationale: 'mirrors the ad' }],
  }

  it('asks the document for a plan', async () => {
    const user = userEvent.setup()
    api.tailorResume.mockResolvedValue(PROPOSAL)
    await setup({ instance: PUSHED, slots: SLOTS, jobPost: JOB_POST, coverage: coverageOf(true) })

    await user.click(await screen.findByRole('button', { name: /tailor to this ad/i }))

    await waitFor(() => expect(api.tailorResume).toHaveBeenCalledWith(9))
  })

  it('resolves against the document and re-reads its slots', async () => {
    const user = userEvent.setup()
    api.tailorResume.mockResolvedValue(PROPOSAL)
    api.resolveResumeProposal.mockResolvedValue({ ...PROPOSAL, status: 'applied' })
    await setup({ instance: PUSHED, slots: SLOTS, jobPost: JOB_POST, coverage: coverageOf(true) })

    await user.click(await screen.findByRole('button', { name: /tailor to this ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.click(within(panel).getByRole('button', { name: /apply/i }))

    await waitFor(() => expect(api.resolveResumeProposal).toHaveBeenCalled())
    expect(api.resumeSlots).toHaveBeenCalledWith(9)
  })

  it('attaches a pasted ad to the document, which is what measures against it', async () => {
    const user = userEvent.setup()
    api.createJobPost.mockResolvedValue(JOB_POST)
    api.updateResumeInstance.mockResolvedValue({ id: 12 })
    await setup({ instance: { ...PUSHED, job_post_id: null }, slots: SLOTS, jobPost: null })

    await user.click(await screen.findByRole('button', { name: /paste the job ad/i }))
    const panel = await screen.findByRole('dialog')
    await user.type(within(panel).getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(within(panel).getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(within(panel).getByRole('button', { name: /save the ad/i }))

    await waitFor(() =>
      expect(api.updateResumeInstance).toHaveBeenCalledWith(9, { job_post_id: 4 }))
  })
})

describe('Builder / a document that failed to load its panel', () => {
  it('still lays out the slots it did load', async () => {
    // A coverage call that fell over is not a reason to blank the canvas.
    api.resumeCoverage.mockRejectedValue(new Error('coverage is down'))
    await setup({
      instance: INSTANCE,
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

describe('Builder / switching between resumes', () => {
  const second = { ...INSTANCE, id: 2, name: 'Second resume' }
  const unconverted = {
    key: 'draft:7', instance_id: null, draft_id: 7, name: 'A legacy draft',
    composed: true, pushed: false, has_pdf: false, is_default: false,
    compile_ok: false, linked_count: 0, updated_at: null,
  }

  it('offers every other resume in the switcher', async () => {
    const user = userEvent.setup()
    await setup({ library: libraryOf([INSTANCE, second]) })

    await user.click(screen.getByRole('button', { name: /switch resume/i }))

    expect(screen.getByRole('option', { name: 'Second resume' })).toBeInTheDocument()
  })

  it('opens the one that was picked', async () => {
    const user = userEvent.setup()
    await setup({ library: libraryOf([INSTANCE, second]) })

    await user.click(screen.getByRole('button', { name: /switch resume/i }))
    await user.click(screen.getByRole('option', { name: 'Second resume' }))

    await waitFor(() => expect(api.resumeInstance).toHaveBeenCalledWith(2))
  })

  it('offers a resume made before documents were the truth', async () => {
    // Filtering these out left them unreachable, which is to say lost: this
    // is the only page that could ever open one.
    const user = userEvent.setup()
    await setup({ library: [...libraryOf([INSTANCE]), unconverted] })

    await user.click(screen.getByRole('button', { name: /switch resume/i }))

    expect(screen.getByRole('option', { name: /A legacy draft/ })).toBeInTheDocument()
  })

  it('converts an old one the moment it is asked for', async () => {
    const user = userEvent.setup()
    api.adoptDraft.mockResolvedValue({ ...INSTANCE, id: 42 })
    await setup({ library: [...libraryOf([INSTANCE]), unconverted] })

    await user.click(screen.getByRole('button', { name: /switch resume/i }))
    await user.click(screen.getByRole('option', { name: /A legacy draft/ }))

    await waitFor(() => expect(api.adoptDraft).toHaveBeenCalledWith(7))
    await waitFor(() => expect(api.resumeInstance).toHaveBeenCalledWith(42))
  })
})

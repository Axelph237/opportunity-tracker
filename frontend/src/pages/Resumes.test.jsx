import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Resumes from './Resumes'
import { ConfirmProvider } from '../components/ConfirmDialog'
import { api } from '../api'

// Never touch the network, and never the real ../data/opportunities.db.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: {
      ...actual.api,
      resumes: vi.fn(),
      resumeInstance: vi.fn(),
      resumeLinks: vi.fn(),
      createResumeInstance: vi.fn(),
      updateResumeInstance: vi.fn(),
      deleteResumeInstance: vi.fn(),
      compileResumeInstance: vi.fn(),
      makeResumeDefault: vi.fn(),
      fixResumeInstance: vi.fn(),
      latexStatus: vi.fn(),
      resumeAdvice: vi.fn(),
      generateResumeAdvice: vi.fn(),
      resumeAssets: vi.fn(),
      uploadResumeAsset: vi.fn(),
      deleteResumeAsset: vi.fn(),
    },
  }
})

// CodeMirror needs layout APIs jsdom does not implement. The editor has its own
// contract — value in, onChange out, goToLine/insertAtCursor on the ref — so a
// textarea honouring that contract exercises everything this page cares about.
vi.mock('../components/LatexEditor', () => ({
  default: ({ value, onChange, errorLines, editorRef }) => {
    if (editorRef) {
      editorRef.current = { goToLine: vi.fn(), insertAtCursor: vi.fn() }
    }
    return (
      <div>
        <textarea aria-label="LaTeX source" value={value} onChange={(e) => onChange(e.target.value)} />
        <span data-testid="error-lines">{(errorLines || []).join(',')}</span>
      </div>
    )
  },
}))

const ENGINE = { available: true, path: '/opt/homebrew/bin/tectonic', engine: 'tectonic', version: 'Tectonic 0.15' }
const NO_ENGINE = { available: false, path: null, engine: null, version: null, candidates: ['tectonic'] }

function summary(overrides) {
  return {
    id: 1,
    name: 'Base',
    description: null,
    has_pdf: true,
    pdf_filename: 'resume-1.pdf',
    compiled_at: '2026-09-22T10:00:00Z',
    compile_ok: true,
    compile_errors: [],
    is_default: true,
    linked_count: 0,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-22T10:00:00Z',
    ...overrides,
  }
}

function detail(overrides) {
  return {
    ...summary(),
    latex: '\\documentclass{article}',
    compile_log: '',
    issues: [],
    ...overrides,
  }
}

const PDFLATEX_ISSUE = {
  id: 'glyphtounicode-input',
  title: 'pdflatex-only glyph map',
  detail: 'Tectonic runs XeTeX, which has no such table.',
  line: 24,
  snippet: '\\input{glyphtounicode}',
}

/**
 * Render the page and wait for its opening loads to land.
 *
 * Both the version list and the selected version resolve asynchronously, and
 * returning before they settle leaves React updating state after the test has
 * finished — which is exactly the `act(...)` warning. Awaiting the first
 * rendered content here keeps every test below free of that.
 */
async function setup({ list, instance, links = [], assets = [], engine = ENGINE } = {}) {
  const rows = list ?? [summary()]
  api.resumes.mockResolvedValue(rows)
  api.latexStatus.mockResolvedValue(engine)
  api.resumeInstance.mockResolvedValue(instance ?? detail())
  api.resumeLinks.mockResolvedValue(links)
  api.resumeAssets.mockResolvedValue(assets)
  const rendered = render(
    <MemoryRouter>
      <ConfirmProvider>
        <Resumes onMutate={() => {}} />
      </ConfirmProvider>
    </MemoryRouter>,
  )
  if (rows.length) await screen.findByLabelText('LaTeX source')
  else await screen.findByRole('button', { name: /new resume/i })
  return rendered
}

/**
 * Wait until no save or render is still in flight.
 *
 * The debounced save and the render that follows it both resolve well after the
 * call they were asserted on, and a test that ends in between leaves React
 * writing state into a torn-down tree.
 */
const settled = () =>
  waitFor(() => {
    expect(screen.queryByText('Saving…')).not.toBeInTheDocument()
    expect(screen.queryByText('Unsaved')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /rendering…/i })).not.toBeInTheDocument()
  })

/*
 * Real timers, deliberately.
 *
 * The page debounces a save at 700ms and a render at 1400ms. Fake timers look
 * like the obvious tool, but neither setting works here: frozen, RTL's
 * `findBy*` never resolves, and with `shouldAdvanceTime` the clock keeps
 * running through every `await`, so a debounce fires mid-assertion outside
 * act(). Waiting out the real delays costs a few seconds across this file and
 * tests the timing the user actually gets.
 */
const DEBOUNCE = { timeout: 4000 }

afterEach(() => {
  vi.clearAllMocks()
})

describe('Resumes / loading and selection', () => {
  it('opens on the version marked default rather than the first row', async () => {
    await setup({
      list: [summary({ id: 7, name: 'Tailored', is_default: false }), summary({ id: 9, name: 'Base' })],
      instance: detail({ id: 9, name: 'Base' }),
    })
    await waitFor(() => expect(api.resumeInstance).toHaveBeenCalledWith(9))
  })

  it('offers to create one when there are none', async () => {
    await setup({ list: [] })
    expect(await screen.findByRole('button', { name: /new resume/i })).toBeInTheDocument()
    expect(api.resumeInstance).not.toHaveBeenCalled()
  })

  it('marks the scored version and offers to switch on the others', async () => {
    await setup({ instance: detail({ is_default: false }) })
    expect(await screen.findByRole('button', { name: /use for scoring/i })).toBeInTheDocument()
  })
})

describe('Resumes / autosave and render', () => {
  it('saves once after typing stops, not once per keystroke', async () => {
    const user = userEvent.setup()
    api.updateResumeInstance.mockResolvedValue(detail({ latex: 'x' }))
    api.compileResumeInstance.mockResolvedValue(detail())
    await setup()

    const editor = await screen.findByLabelText('LaTeX source')
    await user.type(editor, 'abc')
    expect(api.updateResumeInstance).not.toHaveBeenCalled()

    await waitFor(() => expect(api.updateResumeInstance).toHaveBeenCalledTimes(1), DEBOUNCE)
    await settled()
  })

  it('renders only after the save has settled', async () => {
    const user = userEvent.setup()
    api.updateResumeInstance.mockResolvedValue(detail())
    api.compileResumeInstance.mockResolvedValue(detail())
    await setup()

    await user.type(await screen.findByLabelText('LaTeX source'), 'x')
    await waitFor(() => expect(api.updateResumeInstance).toHaveBeenCalled(), DEBOUNCE)
    // The render waits another beat after the save, so it cannot have run yet.
    expect(api.compileResumeInstance).not.toHaveBeenCalled()

    await waitFor(() => expect(api.compileResumeInstance).toHaveBeenCalledWith(1), DEBOUNCE)
    await settled()
  })

  it('does not try to render when no engine is installed', async () => {
    const user = userEvent.setup()
    api.updateResumeInstance.mockResolvedValue(detail())
    await setup({ engine: NO_ENGINE })

    await user.type(await screen.findByLabelText('LaTeX source'), 'x')
    await waitFor(() => expect(api.updateResumeInstance).toHaveBeenCalled(), DEBOUNCE)
    // Well past the point a render would have been triggered.
    await new Promise((resolve) => setTimeout(resolve, 2000))
    expect(api.compileResumeInstance).not.toHaveBeenCalled()
    await settled()
  })

  it('explains what to install when there is no engine', async () => {
    await setup({ engine: NO_ENGINE })
    expect(await screen.findByText(/brew install tectonic/)).toBeInTheDocument()
  })

  it('disables the download until something has been rendered', async () => {
    await setup({ instance: detail({ has_pdf: false, compiled_at: null }) })
    const download = await screen.findByTitle(/render it first/i)
    expect(download).toHaveAttribute('aria-disabled', 'true')
  })
})

describe('Resumes / compile errors', () => {
  const broken = detail({
    compile_ok: false,
    compile_errors: [{ line: 12, message: 'Undefined control sequence.' }],
    compile_log: '! Undefined control sequence.',
  })

  it('lists the errors and hands their lines to the editor', async () => {
    await setup({ instance: broken })
    expect(await screen.findByText(/line 12: Undefined control sequence/)).toBeInTheDocument()
    expect(screen.getByTestId('error-lines')).toHaveTextContent('12')
  })

  it('keeps the full log behind a toggle', async () => {
    const user = userEvent.setup()
    await setup({ instance: broken })
    await user.click(await screen.findByRole('button', { name: /full log/i }))
    expect(screen.getByText('! Undefined control sequence.')).toBeInTheDocument()
  })

  it('shows no error strip once a version compiles', async () => {
    await setup()
    await screen.findByLabelText('LaTeX source')
    expect(screen.queryByText(/compile error/i)).not.toBeInTheDocument()
  })
})

describe('Resumes / the recommendations rail', () => {
  const LINK = {
    id: 3,
    title: 'Quantum Intern',
    organization: 'ACME',
    url: 'https://example.com/job',
    deadline: null,
    relevance_score: 8.2,
    advice_generated_at: '2026-09-20T10:00:00Z',
  }

  it('says how to link a listing when none are', async () => {
    await setup()
    expect(await screen.findByText(/no listings use this resume yet/i)).toBeInTheDocument()
  })

  it('lists the linked listings and counts them on the toggle', async () => {
    await setup({ links: [LINK] })
    expect(await screen.findByText('Quantum Intern')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /advice \(1\)/i })).toBeInTheDocument()
  })

  it('collapses out of the way', async () => {
    const user = userEvent.setup()
    await setup({ links: [LINK] })
    await user.click(await screen.findByRole('button', { name: /advice \(1\)/i }))
    expect(screen.queryByText('Quantum Intern')).not.toBeInTheDocument()
  })

  it('fetches a listing’s advice only once its section is opened', async () => {
    const user = userEvent.setup()
    api.resumeAdvice.mockResolvedValue({
      fit_summary: 'Strong overlap on simulation work.',
      fit_score: 7.5,
      requirements: [{ requirement: 'C++', importance: 'required', status: 'met', evidence: null }],
      adjustments: [
        { section: 'Experience', current: null, suggested: 'Lead with the qubit count.', rationale: null, priority: 'high' },
      ],
      keywords: ['Qiskit'],
      talking_points: [],
      generated_at: '2026-09-20T10:00:00Z',
      resume_filename: 'resume.pdf',
      stale: false,
    })
    await setup({ links: [LINK] })

    await screen.findByText('Quantum Intern')
    expect(api.resumeAdvice).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /Quantum Intern/ }))
    await waitFor(() => expect(api.resumeAdvice).toHaveBeenCalledWith(3))
    expect(await screen.findByText('Lead with the qubit count.')).toBeInTheDocument()
  })
})

describe('Resumes / managing versions', () => {
  it('duplicates the open version by id', async () => {
    const user = userEvent.setup()
    api.createResumeInstance.mockResolvedValue(detail({ id: 2, name: 'Base copy' }))
    await setup()

    await user.click(await screen.findByRole('button', { name: /duplicate/i }))
    await waitFor(() =>
      expect(api.createResumeInstance).toHaveBeenCalledWith({ name: 'Base copy', copy_from: 1 }),
    )
    await settled()
  })

  it('warns how many listings a deletion will unlink', async () => {
    const user = userEvent.setup()
    await setup({ instance: detail({ linked_count: 2 }), list: [summary({ linked_count: 2 })] })

    await user.click(await screen.findByRole('button', { name: /^delete$/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/2 listings will be unlinked/i)).toBeInTheDocument()
  })

  it('renames on blur, and not while still typing', async () => {
    const user = userEvent.setup()
    api.updateResumeInstance.mockResolvedValue(detail({ name: 'Quantum labs' }))
    await setup()

    const field = await screen.findByLabelText('Resume name')
    await user.clear(field)
    await user.type(field, 'Quantum labs')
    expect(api.updateResumeInstance).not.toHaveBeenCalled()

    await user.tab()
    await waitFor(() =>
      expect(api.updateResumeInstance).toHaveBeenCalledWith(1, { name: 'Quantum labs' }),
    )
    await settled()
  })
})


describe('Resumes / adjustable layout', () => {
  it('offers a draggable divider for each pane', async () => {
    await setup({ links: [] })
    const labels = screen
      .getAllByRole('separator')
      .map((handle) => handle.getAttribute('aria-label'))
    expect(labels).toEqual(
      expect.arrayContaining([
        'Resize the versions rail',
        'Resize the assets panel',
        'Resize the editor',
        'Resize the recommendations rail',
      ]),
    )
  })

  it('remembers a width across a remount', async () => {
    await setup()
    const handle = screen.getByRole('separator', { name: 'Resize the versions rail' })
    handle.focus()
    await userEvent.keyboard('{ArrowRight}')
    const widened = Number(handle.getAttribute('aria-valuenow'))
    expect(widened).toBeGreaterThan(224)

    cleanup()
    await setup()
    expect(
      Number(screen.getByRole('separator', { name: 'Resize the versions rail' }).getAttribute('aria-valuenow')),
    ).toBe(widened)
  })

  it('shows the assets panel with the versions rail', async () => {
    await setup({ assets: [{ name: 'seal.png', size: 2048, updated_at: '2026-09-23T10:00:00Z' }] })
    expect(await screen.findByText('seal.png')).toBeInTheDocument()
  })
})

describe('Resumes / templates written for pdflatex', () => {
  it('says so, rather than letting the render fail with no explanation', async () => {
    await setup({ instance: detail({ issues: [PDFLATEX_ISSUE] }) })
    expect(await screen.findByText(/only pdflatex\s+understands/)).toBeInTheDocument()
  })

  it('stays out of the way for a document that is fine', async () => {
    await setup()
    expect(screen.queryByRole('button', { name: /Fix it/ })).not.toBeInTheDocument()
  })

  it('applies the fix and shows the rewritten source in the editor', async () => {
    // The whole reason this is a visible edit and not a compile-time rewrite:
    // what the editor shows has to be what gets rendered.
    const user = userEvent.setup()
    await setup({ instance: detail({ issues: [PDFLATEX_ISSUE] }) })
    api.fixResumeInstance.mockResolvedValue(
      detail({ latex: '\\ifdefined\\pdfgentounicode\\input{glyphtounicode}\\fi', issues: [] }),
    )

    await user.click(screen.getByRole('button', { name: 'Fix it' }))

    await waitFor(() => expect(api.fixResumeInstance).toHaveBeenCalledWith(1))
    expect(await screen.findByLabelText('LaTeX source')).toHaveValue(
      '\\ifdefined\\pdfgentounicode\\input{glyphtounicode}\\fi',
    )
    expect(screen.queryByRole('button', { name: 'Fix it' })).not.toBeInTheDocument()
    await settled()
  })

  it('does not leave the rewrite looking like an unsaved edit', async () => {
    const user = userEvent.setup()
    await setup({ instance: detail({ issues: [PDFLATEX_ISSUE] }) })
    api.fixResumeInstance.mockResolvedValue(detail({ latex: 'fixed', issues: [] }))

    await user.click(screen.getByRole('button', { name: 'Fix it' }))

    await waitFor(() => expect(api.fixResumeInstance).toHaveBeenCalled())
    expect(screen.queryByText('Unsaved')).not.toBeInTheDocument()
    // And it must not trigger the autosave path all over again.
    await new Promise((resolve) => setTimeout(resolve, 1200))
    expect(api.updateResumeInstance).not.toHaveBeenCalled()
  })
})

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CoveragePanel from './CoveragePanel'

const JOB = { id: 4, title: 'Quantum Computing Intern', organization: 'ACME Labs' }

const term = (overrides) => ({
  term: 'Qiskit',
  bucket: 'technical',
  covered: false,
  hits: 0,
  where: [],
  ...overrides,
})

function setup(props = {}) {
  const handlers = {
    onSaveJobPost: vi.fn(),
    onExtract: vi.fn(),
    onLocate: vi.fn(),
    onTailor: vi.fn(),
  }
  render(<CoveragePanel jobPost={JOB} coverage={[]} {...handlers} {...props} />)
  return handlers
}

describe('CoveragePanel / no job ad yet', () => {
  it('asks for the ad itself, and says why the listing summary will not do', () => {
    setup({ jobPost: null })
    expect(screen.getByText(/two-sentence summary/i)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /the ad/i })).toBeInTheDocument()
  })

  it('will not save an ad with no text in it', async () => {
    const user = userEvent.setup()
    const { onSaveJobPost } = setup({ jobPost: null })
    await user.type(screen.getByRole('textbox', { name: /role/i }), 'Intern')
    expect(screen.getByRole('button', { name: /save the ad/i })).toBeDisabled()
    expect(onSaveJobPost).not.toHaveBeenCalled()
  })

  it('saves the pasted ad', async () => {
    const user = userEvent.setup()
    const { onSaveJobPost } = setup({ jobPost: null })
    await user.type(screen.getByRole('textbox', { name: /role/i }), 'Intern')
    await user.type(screen.getByRole('textbox', { name: /the ad/i }), 'We need Qiskit.')
    await user.click(screen.getByRole('button', { name: /save the ad/i }))
    expect(onSaveJobPost).toHaveBeenCalledWith({
      title: 'Intern',
      organization: null,
      url: null,
      raw_text: 'We need Qiskit.',
    })
  })
})

describe('CoveragePanel / no keywords extracted yet', () => {
  it('marks the extraction as a Claude call and says how long it may take', () => {
    setup()
    const button = screen.getByRole('button', { name: /pull out the keywords/i })
    expect(button).toHaveAttribute('title', 'Runs a Claude call')
    expect(screen.getByText(/takes up to a minute/i)).toBeInTheDocument()
  })

  it('blocks a second extraction while the first is in flight', () => {
    setup({ extracting: true })
    expect(screen.getByRole('button', { name: /reading the ad…/i })).toBeDisabled()
  })

  it('offers nothing to tailor before there are keywords to tailor against', () => {
    setup()
    expect(screen.queryByRole('button', { name: /tailor to this ad/i })).not.toBeInTheDocument()
  })
})

describe('CoveragePanel / the terms', () => {
  const COVERAGE = [
    term({ term: 'Qiskit', covered: true, hits: 2, where: ['p1'] }),
    term({ term: 'Kubernetes' }),
    term({ term: 'optimized', bucket: 'verb', covered: true, hits: 1, where: ['p2'] }),
    term({ term: 'mentoring', bucket: 'professional' }),
  ]

  it('counts what is covered, overall and per bucket', () => {
    setup({ coverage: COVERAGE })
    expect(screen.getByText('2/4')).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument() // technical
  })

  it('separates the three buckets the ad is read into', () => {
    setup({ coverage: COVERAGE })
    for (const label of ['Technical terms', 'Action verbs', 'Professional skills']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('leaves out a bucket the ad produced nothing for', () => {
    setup({ coverage: [term({ term: 'Qiskit' })] })
    expect(screen.getByText('Technical terms')).toBeInTheDocument()
    expect(screen.queryByText('Action verbs')).not.toBeInTheDocument()
  })

  it('makes a covered term a control that points at where it was used', async () => {
    const user = userEvent.setup()
    const { onLocate } = setup({ coverage: COVERAGE })
    await user.click(screen.getByRole('button', { name: 'Qiskit' }))
    expect(onLocate).toHaveBeenCalledWith('p1')
  })

  it('leaves a missing term as a label, with nowhere to click to', () => {
    setup({ coverage: COVERAGE })
    expect(screen.queryByRole('button', { name: 'Kubernetes' })).not.toBeInTheDocument()
    expect(screen.getByText('Kubernetes')).toBeInTheDocument()
  })

  it('tells covered from missing by tone, not only by position', () => {
    setup({ coverage: COVERAGE })
    expect(screen.getByRole('button', { name: 'Qiskit' })).toHaveClass('text-primary')
    expect(screen.getByText('Kubernetes')).toHaveClass('text-on-surface-variant')
  })

  it('does not offer to jump to a covered term with no traced placement', () => {
    setup({ coverage: [term({ term: 'Qiskit', covered: true, hits: 1, where: [] })] })
    expect(screen.queryByRole('button', { name: 'Qiskit' })).not.toBeInTheDocument()
  })
})

describe('CoveragePanel / tailoring', () => {
  const COVERAGE = [term({ term: 'Qiskit' })]

  it('marks tailoring as a Claude call and promises it cannot invent experience', () => {
    setup({ coverage: COVERAGE })
    const button = screen.getByRole('button', { name: /tailor to this ad/i })
    expect(button).toHaveAttribute('title', 'Runs a Claude call')
    expect(screen.getByText(/cannot add experience you do not have/i)).toBeInTheDocument()
  })

  it('disables itself while the call is out, rather than queueing a second one', async () => {
    const user = userEvent.setup()
    const { onTailor } = setup({ coverage: COVERAGE, generating: true })
    const button = screen.getByRole('button', { name: /tailoring…/i })
    expect(button).toBeDisabled()
    await user.click(button)
    expect(onTailor).not.toHaveBeenCalled()
  })
})

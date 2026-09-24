import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LatexIssues from './LatexIssues'

const ISSUE = {
  id: 'glyphtounicode-input',
  title: 'pdflatex-only glyph map',
  detail: 'Tectonic runs XeTeX, which has no such table.',
  line: 24,
  snippet: '\\input{glyphtounicode}',
}

const SECOND = { ...ISSUE, id: 'pdfgentounicode', title: 'pdflatex-only Unicode mapping', line: 64 }

describe('LatexIssues', () => {
  it('renders nothing when the document is fine', () => {
    const { container } = render(<LatexIssues issues={[]} onFix={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when issues are absent entirely', () => {
    const { container } = render(<LatexIssues onFix={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('counts the problems in the singular', () => {
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} />)
    expect(screen.getByText(/1 command that only pdflatex/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fix it' })).toBeInTheDocument()
  })

  it('counts them in the plural', () => {
    render(<LatexIssues issues={[ISSUE, SECOND]} onFix={vi.fn()} />)
    expect(screen.getByText(/2 commands that only pdflatex/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fix them' })).toBeInTheDocument()
  })

  it('keeps the detail collapsed until asked', async () => {
    const user = userEvent.setup()
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} />)
    expect(screen.queryByText(ISSUE.detail)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /What changes/ }))
    expect(screen.getByText(ISSUE.detail)).toBeInTheDocument()
    expect(screen.getByText(ISSUE.snippet)).toBeInTheDocument()
  })

  it('says the fix is a guard rather than a deletion', async () => {
    // The reassurance that matters: applying this does not break the file
    // anywhere the user compiles it with pdflatex.
    const user = userEvent.setup()
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /What changes/ }))
    expect(screen.getByText(/rather than\s+deleted/)).toBeInTheDocument()
  })

  it('applies the fix on request', async () => {
    const user = userEvent.setup()
    const onFix = vi.fn()
    render(<LatexIssues issues={[ISSUE]} onFix={onFix} />)
    await user.click(screen.getByRole('button', { name: 'Fix it' }))
    expect(onFix).toHaveBeenCalled()
  })

  it('cannot be fired twice while it is working', () => {
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} busy />)
    expect(screen.getByRole('button', { name: 'Fixing…' })).toBeDisabled()
  })

  it('jumps to the offending line when the editor can take it', async () => {
    const user = userEvent.setup()
    const onGoToLine = vi.fn()
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} onGoToLine={onGoToLine} />)
    await user.click(screen.getByRole('button', { name: /What changes/ }))
    await user.click(screen.getByRole('button', { name: 'line 24' }))
    expect(onGoToLine).toHaveBeenCalledWith(24)
  })

  it('still shows the line number where there is no editor to jump to', async () => {
    const user = userEvent.setup()
    render(<LatexIssues issues={[ISSUE]} onFix={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /What changes/ }))
    expect(screen.getByText('line 24')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'line 24' })).not.toBeInTheDocument()
  })
})

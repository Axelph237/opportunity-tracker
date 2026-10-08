import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import HighlightedText from './HighlightedText'

const marks = (container) => [...container.querySelectorAll('mark')].map((node) => node.textContent)

describe('HighlightedText', () => {
  it('marks every occurrence of a term and leaves the rest of the sentence alone', () => {
    const { container } = render(
      <p>
        <HighlightedText text="Built a PyTorch model, then shipped the PyTorch service." terms={['PyTorch']} />
      </p>,
    )
    expect(marks(container)).toEqual(['PyTorch', 'PyTorch'])
    expect(container.textContent).toBe('Built a PyTorch model, then shipped the PyTorch service.')
  })

  it('renders the text untouched when no term appears in it', () => {
    const { container } = render(<p><HighlightedText text="Ran the beamline." terms={['Kubernetes']} /></p>)
    expect(marks(container)).toEqual([])
    expect(container.textContent).toBe('Ran the beamline.')
  })

  it('renders the text untouched when there are no terms at all', () => {
    const { container } = render(<p><HighlightedText text="Ran the beamline." terms={[]} /></p>)
    expect(container.textContent).toBe('Ran the beamline.')
  })

  it('never turns the text into markup', () => {
    // The point of building nodes rather than an HTML string. This text comes
    // out of a scraped ad, so a term either side of a tag must not let the tag
    // through as an element.
    const { container } = render(
      <p><HighlightedText text="Used <b>Rust</b> and <script>alert(1)</script>" terms={['Rust']} /></p>,
    )
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toBe('Used <b>Rust</b> and <script>alert(1)</script>')
    expect(marks(container)).toEqual(['Rust'])
  })

  it('matches whatever case the resume happens to use, and keeps that case on screen', () => {
    const { container } = render(<p><HighlightedText text="python and Python" terms={['PYTHON']} /></p>)
    expect(marks(container)).toEqual(['python', 'Python'])
  })

  it('does not mark a term that is only part of a longer word', () => {
    const { container } = render(
      <p><HighlightedText text="JavaScript is not Java." terms={['Java']} /></p>,
    )
    expect(marks(container)).toEqual(['Java'])
  })

  it('marks terms that end in punctuation, which a word boundary would miss', () => {
    // `\b` puts a boundary inside "C++" and refuses one after it, so the terms
    // most worth marking are the ones it gets wrong.
    const { container } = render(
      <p><HighlightedText text="Wrote C++ and C# for the DAQ." terms={['C++', 'C#']} /></p>,
    )
    expect(marks(container)).toEqual(['C++', 'C#'])
  })

  it('prefers the longer term where two overlap', () => {
    const { container } = render(
      <p>
        <HighlightedText text="Applied machine learning to the data." terms={['learning', 'machine learning']} />
      </p>,
    )
    expect(marks(container)).toEqual(['machine learning'])
  })

  it('matches a multi-word term across the line break the resume wrapped it on', () => {
    const { container } = render(
      <p><HighlightedText text={'Applied machine\nlearning here.'} terms={['machine learning']} /></p>,
    )
    expect(marks(container)).toEqual(['machine\nlearning'])
  })

  it('carries the covered-keyword tone so a mark reads as a chip, not a browser highlight', () => {
    render(<p><HighlightedText text="Ran Qiskit jobs." terms={['Qiskit']} /></p>)
    expect(screen.getByText('Qiskit')).toHaveClass('bg-primary/10', 'text-primary')
  })
})

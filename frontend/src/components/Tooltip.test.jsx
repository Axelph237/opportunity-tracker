import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import Tooltip from './Tooltip'

describe('Tooltip', () => {
  it('renders the label as a tooltip element alongside the children', () => {
    render(
      <Tooltip label="Runs a Claude call">
        <button type="button">Scrape</button>
      </Tooltip>,
    )
    expect(screen.getByRole('button', { name: 'Scrape' })).toBeInTheDocument()
    expect(screen.getByRole('tooltip')).toHaveTextContent('Runs a Claude call')
  })

  it('returns children untouched, with no wrapper, when label is falsy', () => {
    const { container } = render(
      <div data-testid="wrapper">
        <Tooltip label="">
          <button type="button">Scrape</button>
        </Tooltip>
      </div>,
    )
    // No tooltip node at all, and the button is the wrapper's only child --
    // i.e. Tooltip did not add its `<span className="group/tip ...">` shell.
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    const wrapper = container.querySelector('[data-testid="wrapper"]')
    expect(wrapper.children).toHaveLength(1)
    expect(wrapper.firstElementChild.tagName).toBe('BUTTON')
  })

  it('also passes through untouched for null/undefined label', () => {
    render(
      <Tooltip label={null}>
        <span>Plain</span>
      </Tooltip>,
    )
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    expect(screen.getByText('Plain')).toBeInTheDocument()
  })

  it.each([
    ['top', 'bottom-full'],
    ['top-end', 'bottom-full'],
    ['bottom', 'top-full'],
    ['left', 'right-full'],
    ['right', 'left-full'],
  ])('applies the %s placement classes', (placement, expectedClassFragment) => {
    render(
      <Tooltip label="hint" placement={placement}>
        <span>anchor</span>
      </Tooltip>,
    )
    expect(screen.getByRole('tooltip').className).toContain(expectedClassFragment)
  })

  it('falls back to the top placement for an unrecognized value', () => {
    render(
      <Tooltip label="hint" placement="nowhere">
        <span>anchor</span>
      </Tooltip>,
    )
    expect(screen.getByRole('tooltip').className).toContain('bottom-full')
  })

  it('defaults to the top placement when none is given', () => {
    render(
      <Tooltip label="hint">
        <span>anchor</span>
      </Tooltip>,
    )
    expect(screen.getByRole('tooltip').className).toContain('bottom-full')
  })
})

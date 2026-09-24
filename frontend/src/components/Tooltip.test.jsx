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

describe('Tooltip / when it is visible', () => {
  const bubble = () => screen.getByRole('tooltip')

  function renderOne() {
    render(
      <Tooltip label="Opportunities">
        <a href="/opportunities">link</a>
      </Tooltip>,
    )
  }

  // These assert on class names, which is normally a poor test — but here the
  // class *is* the behaviour. Visibility is pure CSS, so jsdom cannot observe
  // it any other way, and the bug being guarded against was exactly one of
  // these variants being the wrong one.
  it('appears on hover', () => {
    renderOne()
    expect(bubble().className).toContain('group-hover/tip:opacity-100')
  })

  it('appears for keyboard focus', () => {
    renderOne()
    expect(bubble().className).toContain('group-has-focus-visible/tip:opacity-100')
  })

  it('does not stay up after a click', () => {
    // `:focus-within` matches a link the user clicked and kept focus on, so
    // the bubble hung around after the pointer left, until something else was
    // clicked. `:focus-visible` does not match a mouse click.
    renderOne()
    expect(bubble().className).not.toContain('focus-within')
  })

  it('starts hidden and cannot swallow a click meant for the page', () => {
    renderOne()
    expect(bubble().className).toContain('opacity-0')
    expect(bubble().className).toContain('pointer-events-none')
  })
})

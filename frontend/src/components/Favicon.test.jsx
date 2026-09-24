import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import Favicon, { domainOf } from './Favicon'

describe('domainOf', () => {
  it.each([
    ['https://jobs.example.com/role/1', 'jobs.example.com'],
    ['http://Example.COM/x', 'example.com'],
    ['https://www.example.com/x', 'example.com'],
    ['https://example.com:8443/x', 'example.com'],
  ])('reduces %s to %s', (url, expected) => {
    expect(domainOf(url)).toBe(expected)
  })

  it.each([['not a url'], [''], [null], [undefined]])('returns null for %s', (url) => {
    expect(domainOf(url)).toBeNull()
  })

  it('strips www so one site is one icon, matching the server', () => {
    expect(domainOf('https://www.ibm.com/a')).toBe(domainOf('https://ibm.com/b'))
  })
})

describe('Favicon', () => {
  it('points at the cache endpoint for the row’s domain', () => {
    render(<Favicon url="https://jobs.example.com/role" />)
    expect(screen.getByRole('presentation', { hidden: true })).toHaveAttribute(
      'src',
      '/api/favicons/jobs.example.com',
    )
  })

  it('falls back to a glyph when the URL is not usable', () => {
    const { container } = render(<Favicon url="nonsense" />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it('falls back to a glyph when the site has no icon', () => {
    // A row must never be left showing a broken-image box where its
    // identity should be.
    const { container } = render(<Favicon url="https://jobs.example.com/role" />)
    fireEvent.error(container.querySelector('img'))
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it('is decorative, since the row already names the organisation', () => {
    const { container } = render(<Favicon url="https://jobs.example.com/role" />)
    const img = container.querySelector('img')
    expect(img).toHaveAttribute('aria-hidden', 'true')
    expect(img).toHaveAttribute('alt', '')
  })

  it('loads lazily so a page of rows is not a page of requests up front', () => {
    const { container } = render(<Favicon url="https://jobs.example.com/role" />)
    expect(container.querySelector('img')).toHaveAttribute('loading', 'lazy')
  })

  it('encodes the domain into the URL', () => {
    const { container } = render(<Favicon url="https://sub.dom-ain.co.uk/x" />)
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/favicons/sub.dom-ain.co.uk')
  })
})
